"""Главное окно. Только интерфейс: показывает состояние бэкенда и передает ему команды.

Расписание, копирование, проверки и сохранение настроек выполняет BackupService.
Окно вызывает его методы и получает события через ServiceBridge в своем потоке.

Окно (макет Main.dc.html): слева список вкладок с поиском, «Добавить вкладку», «Копировать все
вкладки» и «Настройки»; справа вкладка или страница «Настройки»; внизу история копирования и
строка состояния (ход копирования, итог, ближайшее копирование по расписанию).

Поведение в фоне:
- закрытие и сворачивание окна прячут приложение в трей, если трей доступен;
- плановые запуски не открывают диалогов, о проблемах сообщают уведомления;
- о результате каждого копирования сообщает уведомление.

Короткие сообщения окна (отказ запуска, сброс выполнен, журнал) — тост внутри окна,
подтверждения удаления вкладки и сброса — модальное окно внутри окна.
"""
import copy
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import QEvent, QSize, Qt, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QGuiApplication, QIcon
from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLineEdit, QMainWindow, QMessageBox, QScrollArea,
                             QStackedWidget, QVBoxLayout, QWidget)

from ..backend import (ALREADY_RUNNING, STATUS_CANCELLED, STATUS_OK, STATUS_PARTIAL, AppConfig, AppProblem,
                       BackupFinished, BackupProgress, BackupResult, BackupService, BackupStarted, ConfigChanged,
                       HistoryAdded, RunSkipped, ScheduleChanged, TabConfig, count_tabs_genitive, get_logger)
from . import icons
from . import widgets as W
from .bridge import ServiceBridge
from .constants import (ALREADY_RUNNING_TITLE, APP_TITLE, CANCELLING_TEXT, DELETE_CANCEL, DELETE_OK, DELETE_TEXT,
                        DELETE_TITLE, HISTORY_COLLAPSE, HISTORY_EMPTY_TEXT, HISTORY_EXPAND, HISTORY_VIEW_LIMIT,
                        JOURNAL_EMPTY_TEXT, JOURNAL_OPEN_FAILED_TITLE, JOURNAL_TITLE, NEXT_RUN_PILL,
                        NEXT_RUN_STOPPED, NO_DATA_TEXT, PREPARING_TEXT, RESET_CANCEL, RESET_DONE_TEXT,
                        RESET_DONE_TITLE, RESET_OK, RESET_TEXT, RESET_TITLE, RESULT_FLASH_MS, RUN_REFUSED_TITLE,
                        RUN_SKIPPED_TITLE, RUNNING_PERCENT_TEXT, SCHEDULE_REFUSED_TITLE, SCHEDULED_START_TEXT,
                        SCHEDULED_START_TITLE, TITLE_COMMIT_MS, TRAY_HINT_TEXT, TRAY_HINT_TITLE)
from .history_panel import HistoryPanel
from .resources import resource_path
from .settings_page import SettingsPage
from .tab_page import TabPage, fmt_when, sched_short, tab_name, tab_problem
from .theme import C
from .tray import TrayIcon

# Как показывать результат копирования: заголовок уведомления, вид уведомления, строка состояния,
# значок и тон строки состояния.
RESULT_VIEW = {
    STATUS_OK: ("Копирование завершено", "info", "Копирование завершено успешно", "✓", "ok"),
    STATUS_PARTIAL: ("Копирование завершено с ошибками", "warning", "Копирование завершено с ошибками", "⚠", "warn"),
    STATUS_CANCELLED: ("Копирование отменено", "warning", "Копирование отменено", "✗", "warn"),
}
FAILED_VIEW = ("Ошибка копирования", "error", "Ошибка копирования", "✗", "danger")
TAB_STATUS_PREFIX = "Копирование вкладки"
SEARCH_THRESHOLD = 6          # поиск по вкладкам — когда их больше
DEFAULT_CLIENT = QSize(1180, 868)
MINIMUM_CLIENT = QSize(760, 560)
CLOCK_MS = 30_000             # «сегодня/завтра в …» и отметка времени в примере копии

__all__ = ["MainWindow", "RESULT_VIEW", "FAILED_VIEW", "NO_DATA_TEXT", "HISTORY_EMPTY_TEXT", "HISTORY_VIEW_LIMIT"]


# =========================================================================== боковая панель
class Sidebar(QFrame):
    """«ВКЛАДКИ» + число, поиск, список вкладок, «Добавить вкладку», «Копировать все вкладки», «Настройки»."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("kind", "sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 10)
        root.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(16, 0, 16, 6)
        head.setSpacing(8)
        head.addWidget(W.CapsLabel("Вкладки"))
        head.addStretch(1)
        self.count_label = W.label("", "count")
        head.addWidget(self.count_label)
        root.addLayout(head)
        self.search_box = QWidget()
        s_lay = QVBoxLayout(self.search_box)
        s_lay.setContentsMargins(10, 0, 10, 8)
        self.search = QLineEdit()
        self.search.setProperty("small", True)
        self.search.setPlaceholderText("Найти вкладку…")
        self.search.setAccessibleName("Поиск по вкладкам")
        self.search.setClearButtonEnabled(True)
        s_lay.addWidget(self.search)
        root.addWidget(self.search_box)
        self.tab_list = W.SidebarTabList()
        self.tab_list.setAccessibleName("Вкладки копирования")
        # строка списка рисуется на 1 px ниже своего места (зазор между строками), поэтому поле сверху 1, а не 2
        self.tab_list.setViewportMargins(0, 1, 0, 4)
        root.addWidget(self.tab_list, 1)
        add_box = QHBoxLayout()
        add_box.setContentsMargins(10, 6, 10, 0)
        self.add_button = W.Button("Добавить вкладку", "link", small=True, icon="plus")
        add_box.addWidget(self.add_button)
        root.addLayout(add_box)
        foot = QVBoxLayout()
        foot.setContentsMargins(10, 8, 10, 0)
        foot.setSpacing(0)
        foot.addWidget(W.hline("side-divider"))
        foot.addSpacing(10)
        self.copy_all_button = W.Button("Копировать все вкладки", icon="layers", elide=True,
                                        tooltip="Копировать все вкладки")
        foot.addWidget(self.copy_all_button)
        foot.addSpacing(6)
        self.settings_button = W.Button("Настройки", "nav", icon="gear", icon_size=16, elide=True, checkable=True)
        foot.addWidget(self.settings_button)
        root.addLayout(foot)
        self.search_box.hide()


# =========================================================================== строка состояния
class StatusBar(QFrame):
    """Ход копирования («Отменить»), итог на 4 с, ближайшее копирование и кнопка истории."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("kind", "panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumHeight(41)
        row = W.FlexRow(self, hgap=12, vgap=8)
        row.setContentsMargins(14, 6, 14, 6)

        self.run_box = QWidget()
        run = W.FlexRow(self.run_box, hgap=10, vgap=4)
        self.spinner = W.Spinner(15)
        run.add(self.spinner)
        self.run_label = W.ElidedLabel("", "medium")
        run.add(self.run_label, min_width=0)
        self.progress = W.ProgressBar(indeterminate=True)
        run.add(self.progress, basis=120, grow=1, min_width=80)
        self.detail_label = W.label("", "detail")
        run.add(self.detail_label)
        row.add(self.run_box, basis=360, grow=1, min_width=0)
        self.cancel_button = W.Button("Отменить", small=True)
        row.add(self.cancel_button)

        self.result_box = QWidget()
        res = QHBoxLayout(self.result_box)
        res.setContentsMargins(0, 0, 0, 0)
        res.setSpacing(8)
        self.result_icon = W.label("", "result-icon")
        self.result_icon.setFixedWidth(15)
        self.result_icon.setAlignment(Qt.AlignCenter)
        self.result_label = W.ElidedLabel("", "result")
        res.addWidget(self.result_icon)
        res.addWidget(self.result_label, 1)
        row.add(self.result_box, basis=260, grow=1, min_width=0)
        self.idle_box = QWidget()
        self.idle_box.setFixedHeight(1)
        row.add(self.idle_box, basis=260, grow=1, min_width=0)

        self.pill = W.Badge("", "pill", max_width=360)
        self.pill.setFixedHeight(20)
        row.add(self.pill, min_width=0)
        self.history_button = W.Button("", "ghost", small=True, icon="list")
        row.add(self.history_button)
        self.show_idle()

    def show_running(self, label: str, percent: Optional[int], detail: str) -> None:
        self.result_box.hide()
        self.idle_box.hide()
        self.run_box.show()
        self.cancel_button.show()
        self.run_label.setText(label)
        if percent is None:
            self.progress.set_indeterminate(True)
        else:
            self.progress.set_indeterminate(False)
            self.progress.setValue(max(0, min(100, int(percent))))
        self.detail_label.setText(detail)
        self.detail_label.setVisible(bool(detail) and percent is not None)
        self._relayout()

    def show_result(self, icon: str, text: str, tone: str) -> None:
        self.run_box.hide()
        self.cancel_button.hide()
        self.idle_box.hide()
        W.set_props(self.result_icon, tone=tone)
        W.set_props(self.result_label, tone=tone)
        self.result_icon.setText(icon)
        self.result_label.setText(text)
        self.result_box.show()
        self._relayout()

    def show_idle(self) -> None:
        self.run_box.hide()
        self.cancel_button.hide()
        self.result_box.hide()
        self.idle_box.show()
        self._relayout()

    def is_running_shown(self) -> bool:
        return self.run_box.isVisibleTo(self)

    def is_result_shown(self) -> bool:
        return self.result_box.isVisibleTo(self)

    def _relayout(self) -> None:
        self.run_box.layout().invalidate()
        self.layout().invalidate()
        self.updateGeometry()


class PageScroll(QScrollArea):
    """Прокрутка страницы. Полоса прокрутки занимает половину правого поля (16 → 8 px), поэтому
    карточки не сдвигаются, когда она появляется."""

    def __init__(self, page: QWidget, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(page)
        self.verticalScrollBar().setSingleStep(24)
        self.verticalScrollBar().rangeChanged.connect(self._sync_margin)
        self._sync_margin()

    def _sync_margin(self, *_args) -> None:
        layout = self.widget().layout()
        bar = self.verticalScrollBar()
        right = 16 - bar.sizeHint().width() if bar.maximum() > 0 else 16
        m = layout.contentsMargins()
        if m.right() != right:
            layout.setContentsMargins(m.left(), m.top(), max(0, right), m.bottom())


# =========================================================================== окно
class MainWindow(QMainWindow):
    def __init__(self, service: BackupService, bridge: ServiceBridge, parent=None):
        super().__init__(parent)
        self.service = service
        self.tray: Optional[TrayIcon] = None
        self.log = get_logger()
        self._quitting = False
        self._tray_hint_shown = False
        self._loading = False
        self._config: AppConfig = service.config
        self._current_uid: str = self._config.current_tab().uid
        self._view = "tab"
        self._next_runs: Dict[str, datetime] = dict(service.next_runs())
        self._running: Tuple[str, ...] = tuple(service.running_tabs)
        self._run_names: Tuple[str, ...] = tuple(tab_name(t) for t in self._config.tabs if t.uid in self._running)
        self._progress: Optional[Tuple[int, str]] = None
        self._tab_text = ""
        self._detail = ""
        self._cancelling = False
        self._history_open = True

        self.setWindowTitle(APP_TITLE)
        icon_path = resource_path("icon.ico")
        self.setWindowIcon(QIcon(icon_path) if os.path.exists(icon_path) else icons.icon("shield", C.ACCENT))
        self._init_ui()
        self._init_size()

        self._title_timer = QTimer(self)
        self._title_timer.setSingleShot(True)
        self._title_timer.setInterval(TITLE_COMMIT_MS)
        self._title_timer.timeout.connect(self.save_settings)
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._end_flash)
        self._clock = QTimer(self)
        self._clock.setInterval(CLOCK_MS)
        self._clock.timeout.connect(self.refresh)
        self._clock.start()

        bridge.event_received.connect(self.on_backend_event)
        self.setup_tray()
        self.apply_config(self._config)
        self.history_panel.set_entries(service.history())
        self.refresh()

    # ================================================================ UI
    def _init_ui(self) -> None:
        central = QWidget()
        central.setProperty("kind", "page")
        central.setAttribute(Qt.WA_StyledBackground, True)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar()
        self.tab_list = self.sidebar.tab_list
        self.page = TabPage(self.service)
        self.settings_page = SettingsPage()
        self.tab_scroll = PageScroll(self.page)
        self.settings_scroll = PageScroll(self.settings_page)
        self.stack = QStackedWidget()
        self.stack.setProperty("kind", "page")
        self.stack.addWidget(self.tab_scroll)
        self.stack.addWidget(self.settings_scroll)
        self.splitter = W.GripSplitter(self.sidebar, self.stack)
        layout.addWidget(self.splitter, 1)
        self.history_panel = HistoryPanel()
        layout.addWidget(self.history_panel)
        self.status_bar = StatusBar()
        layout.addWidget(self.status_bar)
        self.toast = W.Toast(central, right=16, bottom=56)

        self.tab_list.tab_selected.connect(self.select_tab)
        self.sidebar.search.textChanged.connect(self._on_search)
        self.sidebar.add_button.clicked.connect(self.add_new_tab)
        self.sidebar.copy_all_button.clicked.connect(self.copy_all_tabs)
        self.sidebar.settings_button.clicked.connect(self.show_settings_section)

        self.page.changed.connect(self._on_tab_changed)
        self.page.title_edited.connect(self._on_title_edited)
        self.page.title_committed.connect(self._on_title_committed)
        self.page.run_requested.connect(self.manual_backup)
        self.page.delete_requested.connect(self.ask_delete_tab)
        self.page.schedule_toggled.connect(self.set_schedule)

        self.settings_page.changed.connect(self.save_settings)
        self.settings_page.autostart_toggled.connect(self.toggle_auto_start)
        self.settings_page.reset_requested.connect(self.reset_settings_to_default)

        self.history_panel.journal_requested.connect(self.open_journal)
        self.status_bar.cancel_button.clicked.connect(self.cancel_backup)
        self.status_bar.history_button.clicked.connect(self.toggle_history)

    def _init_size(self) -> None:
        self.setMinimumSize(MINIMUM_CLIENT)
        size = QSize(DEFAULT_CLIENT)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            size = size.boundedTo(QSize(int(area.width() * 0.9), int(area.height() * 0.9)))
            size = size.expandedTo(MINIMUM_CLIENT)
            self.resize(size)
            self.move(area.center().x() - size.width() // 2, area.center().y() - size.height() // 2)
        else:
            self.resize(size)

    # ================================================================ вкладки
    def tabs(self) -> List[TabConfig]:
        return self._config.tabs

    def tab(self, uid: Optional[str]) -> Optional[TabConfig]:
        return self._config.tab(uid) if uid else None

    def current_tab(self) -> TabConfig:
        return self.tab(self._current_uid) or self._config.tabs[0]

    def current_uid(self) -> str:
        return self._current_uid

    def current_page(self) -> TabPage:
        return self.page

    def _index_of(self, uid: str) -> int:
        for index, tab in enumerate(self._config.tabs):
            if tab.uid == uid:
                return index
        return 0

    def select_tab(self, uid: str) -> None:
        """Показать вкладку uid (щелчок в списке)."""
        tab = self.tab(uid)
        if tab is None:
            return
        self._flush_title()
        changed = uid != self._current_uid
        self._current_uid = uid
        self._show_view("tab")
        self.tab_list.set_current(uid)
        if changed or self.page.tab is not tab:
            self.page.bind(tab)
        self.page.hide_notice()
        self._render_page()
        self.history_panel.set_tab(uid, tab_name(tab))
        if changed:
            self.save_settings()

    def add_new_tab(self) -> None:
        self._flush_title()
        tab = TabConfig()
        self._config.tabs.append(tab)
        self.sidebar.search.clear()
        self._current_uid = tab.uid
        self._show_view("tab")
        self._render_sidebar(rebuild=True)
        self.page.bind(tab)
        self._render_page()
        self.history_panel.set_tab(tab.uid, tab_name(tab))
        self.save_settings()

    def can_delete(self, uid: Optional[str] = None) -> bool:
        uid = uid or self._current_uid
        return len(self._config.tabs) > 1 and uid not in self._running and self.tab(uid) is not None

    def ask_delete_tab(self, uid: Optional[str] = None) -> bool:
        """Удалить вкладку после подтверждения. True — удалена."""
        uid = uid or self._current_uid
        if not self.can_delete(uid):
            return False
        self._flush_title()
        name = tab_name(self.tab(uid))
        if not W.confirm(self.centralWidget(), DELETE_TITLE.format(name=name), DELETE_TEXT, DELETE_OK,
                         DELETE_CANCEL):
            return False
        if not self.can_delete(uid):  # пока окно было открыто, вкладка могла начать копироваться
            return False
        self.delete_tab(uid)
        return True

    def delete_tab(self, uid: str) -> None:
        """Удалить вкладку без вопросов (последнюю — нельзя)."""
        if len(self._config.tabs) <= 1 or self.tab(uid) is None:
            return
        index = self._index_of(uid)
        del self._config.tabs[index]
        if uid == self._current_uid:
            self._current_uid = self._config.tabs[max(0, index - 1)].uid
            self.page.bind(self.current_tab())
        self._render_sidebar(rebuild=True)
        self._render_page()
        self.history_panel.set_tab(self._current_uid, tab_name(self.current_tab()))
        self.save_settings()

    def _on_search(self, text: str) -> None:
        self.tab_list.set_query(text)
        query = text.strip()
        self.tab_list.set_empty_text(f"Нет вкладок с «{query}»" if query else "")
        self._render_counts()

    def _render_counts(self) -> None:
        total = len(self._config.tabs)
        query = self.sidebar.search.text().strip()
        self.sidebar.count_label.setText(f"{self.tab_list.visible_count()} из {total}" if query else str(total))
        show = total > SEARCH_THRESHOLD or bool(self.sidebar.search.text())
        if self.sidebar.search_box.isVisibleTo(self.sidebar) != show:
            self.sidebar.search_box.setVisible(show)

    # ================================================================ страницы
    def _show_view(self, view: str) -> None:
        self._view = view
        self.stack.setCurrentIndex(0 if view == "tab" else 1)
        self.sidebar.settings_button.setChecked(view == "settings")
        if view == "settings":
            self.tab_list.set_current(None)
            self.page.hide_notice()
        else:
            self.tab_list.set_current(self._current_uid)

    def show_settings_section(self) -> None:
        self._flush_title()
        self._show_view("settings")

    def show_files_section(self) -> None:
        self._show_view("tab")

    def current_view(self) -> str:
        return self._view

    # ================================================================ настройки
    def apply_config(self, config: AppConfig) -> None:
        """Показать настройки бэкенда (запуск, сброс, синхронизация автозапуска)."""
        self._loading = True
        try:
            self._config = config
            if not config.tabs:
                config.tabs.append(TabConfig())
            if self.tab(self._current_uid) is None:
                self._current_uid = config.current_tab().uid
            self.settings_page.apply_config(config)
            self._render_sidebar(rebuild=True)
            self.page.bind(self.current_tab())
            if self._view == "tab":
                self.tab_list.set_current(self._current_uid)
            self.history_panel.set_tab(self._current_uid, tab_name(self.current_tab()))
            self._render_page()
        finally:
            self._loading = False

    def collect_config(self) -> AppConfig:
        """Настройки из окна. Сервис берет из них только то, что меняет пользователь."""
        return AppConfig(
            auto_start=self.settings_page.value("auto_start"),
            minimize_to_tray=self.settings_page.value("minimize_to_tray"),
            show_notifications=self.settings_page.value("show_notifications"),
            run_missed=self.settings_page.value("run_missed"),
            max_file_size_gb=self.settings_page.max_file_size(),
            active_tab=self._index_of(self._current_uid),
            tabs=copy.deepcopy(self._config.tabs),
        )

    def save_settings(self, *_args) -> None:
        """Отправить настройки окна в сервис (он сохраняет их в файл)."""
        if self._loading:
            return
        self._title_timer.stop()
        self.service.update_config(self.collect_config())

    def _flush_title(self) -> None:
        if self._title_timer.isActive():
            self.save_settings()

    def _on_tab_changed(self) -> None:
        self._title_timer.stop()
        self._render_entry(self.current_tab())
        self._render_page()
        self._render_status()  # ближайшее копирование учитывает только вкладки с данными
        self.save_settings()

    def _on_title_edited(self, name: str) -> None:
        self._render_entry(self.current_tab())
        self.history_panel.set_tab(self._current_uid, name)
        self._title_timer.start()

    def _on_title_committed(self, _title: str) -> None:
        self._render_entry(self.current_tab())
        self.history_panel.set_tab(self._current_uid, tab_name(self.current_tab()))
        self.save_settings()

    def toggle_auto_start(self, checked: bool) -> None:
        try:
            self.service.set_autostart(checked)
        except Exception as error:
            QMessageBox.critical(self, "Ошибка", f"Не удалось изменить автозапуск:\n{error}")
            self.settings_page.set_autostart_silent(not checked)

    def reset_settings_to_default(self) -> None:
        if not W.confirm(self.centralWidget(), RESET_TITLE, RESET_TEXT, RESET_OK, RESET_CANCEL):
            return
        self.perform_reset()
        self.show_toast(RESET_DONE_TITLE, RESET_DONE_TEXT)

    def perform_reset(self) -> None:
        self._title_timer.stop()
        self.service.reset()

    # ================================================================ команды
    def set_schedule(self, on: bool, uid: Optional[str] = None) -> bool:
        """Включить или выключить расписание вкладки. False — сервис отказал (переключатель остается выключенным)."""
        uid = uid or self._current_uid
        self._flush_title()
        problems = self.service.set_tab_schedule(uid, on)
        self._render_page()
        if problems:
            self.show_toast(SCHEDULE_REFUSED_TITLE, f"{NO_DATA_TEXT} {'; '.join(problems)}", "warn")
            return False
        return True

    def manual_backup(self) -> List[str]:
        """«Копировать сейчас»: копирование выбранной вкладки."""
        return self._run([self._current_uid])

    def copy_all_tabs(self) -> List[str]:
        """«Копировать все вкладки» (боковая панель и меню трея)."""
        return self._run(None)

    def _run(self, tab_ids) -> List[str]:
        self._flush_title()
        problems = self.service.run_now(tab_ids)
        if problems == [ALREADY_RUNNING]:
            self.show_toast(ALREADY_RUNNING_TITLE, ALREADY_RUNNING, "info")
        elif problems:
            self.show_toast(RUN_REFUSED_TITLE, f"{NO_DATA_TEXT} {'; '.join(problems)}", "warn")
        return problems

    def cancel_backup(self) -> None:
        if self._running:
            self.service.cancel()
            self._cancelling = True
            self._render_status()

    def show_toast(self, title: str, text: str = "", kind: str = "info") -> None:
        """Сообщение в окне; если окно спрятано в трей — уведомлением у значка."""
        if not self.isVisible() and self.tray is not None:
            self.tray.notify(title, text, "warning" if kind == "warn" else "info")
            return
        self.toast.show_message(title, text, kind)

    def show_app_problem(self, title: str, text: str) -> None:
        """Сбой приложения: на открытом окне диалог, при работе в трее уведомление.

        Уведомление показывается, даже если уведомления о копировании выключены.
        """
        if self.isVisible() or self.tray is None:
            QMessageBox.warning(self, title, text)
        else:
            self.tray.notify(title, text, "warning")

    # ================================================================ события
    def on_backend_event(self, event) -> None:
        if isinstance(event, BackupProgress):
            self._on_progress(event.percent, event.text)
        elif isinstance(event, BackupStarted):
            self._on_started(event)
        elif isinstance(event, BackupFinished):
            self._on_finished(event)
        elif isinstance(event, ScheduleChanged):
            self._next_runs = dict(event.next_runs)
            self.refresh()
        elif isinstance(event, RunSkipped):
            if event.scheduled:
                self.notify(RUN_SKIPPED_TITLE, event.reason, "warning")
        elif isinstance(event, ConfigChanged):
            self.apply_config(event.config)
            self.refresh()
        elif isinstance(event, HistoryAdded):
            self.history_panel.add_entry(event.entry)
            self._render_history_button()
        elif isinstance(event, AppProblem):
            self.show_app_problem(event.title, event.text)

    def _on_started(self, event: BackupStarted) -> None:
        self._running = tuple(event.tab_ids)
        self._run_names = tuple(event.tab_names)
        self._progress = None
        self._tab_text, self._detail = "", ""
        self._cancelling = False
        self._flash_timer.stop()
        self.refresh()
        if event.scheduled:
            self.notify(SCHEDULED_START_TITLE, SCHEDULED_START_TEXT.format(names=", ".join(event.tab_names)))

    def _on_progress(self, percent: int, text: str) -> None:
        if not self._running:
            return
        first = self._progress is None
        self._progress = (percent, text)
        if text.startswith(TAB_STATUS_PREFIX):
            self._tab_text = text
        elif text:
            self._detail = text
        for uid in self._running:
            tab = self.tab(uid)
            if tab is not None:
                self._render_entry(tab)
        self._render_status()
        if first:
            self._render_page()

    def _on_finished(self, event: BackupFinished) -> None:
        self._running = ()
        self._progress = None
        self._cancelling = False
        title, kind, status, icon, tone = RESULT_VIEW.get(event.result.status, FAILED_VIEW)
        self._flash = (icon, status, tone)
        self._flash_timer.start(RESULT_FLASH_MS)
        self.refresh()
        self.notify(title, event.result.message, kind)

    def _end_flash(self) -> None:
        self._flash = None
        self._render_status()

    def show_result(self, result: BackupResult) -> None:
        """Итог копирования в строке состояния (на RESULT_FLASH_MS)."""
        _title, _kind, status, icon, tone = RESULT_VIEW.get(result.status, FAILED_VIEW)
        self._flash = (icon, status, tone)
        self._flash_timer.start(RESULT_FLASH_MS)
        self._render_status()

    def notify(self, title: str, message: str, kind: str = "info") -> None:
        if self.tray is not None and self.settings_page.value("show_notifications"):
            self.tray.notify(title, message, kind)

    # ================================================================ отрисовка
    _flash: Optional[Tuple[str, str, str]] = None

    def refresh(self) -> None:
        """Обновить все, что зависит от вкладок, расписания и копирования."""
        self._render_sidebar()
        self._render_page()
        self._render_status()
        self._render_history_button()
        self.settings_page.set_busy(bool(self._running))
        self.sidebar.copy_all_button.setEnabled(not self._running)
        if self.tray is not None:
            self.tray.set_backup_enabled(not self._running)

    def _entry(self, tab: TabConfig) -> W.TabEntry:
        uid, name = tab.uid, tab_name(tab)
        if uid in self._running:
            if self._progress is None:
                sub = PREPARING_TEXT
            else:
                sub = RUNNING_PERCENT_TEXT.format(percent=int(self._progress[0]))
            return W.TabEntry(uid, name, sub, W.STATUS_RUNNING)
        problem = tab_problem(tab)
        if problem:
            return W.TabEntry(uid, name, problem, W.STATUS_WARN)
        on = uid in self._next_runs
        return W.TabEntry(uid, name, sched_short(tab, on), W.STATUS_ON if on else W.STATUS_OFF)

    def _render_sidebar(self, rebuild: bool = False) -> None:
        self.tab_list.set_entries([self._entry(tab) for tab in self._config.tabs])
        if self._view == "tab":
            self.tab_list.set_current(self._current_uid)
        self._render_counts()

    def _render_entry(self, tab: TabConfig) -> None:
        self.tab_list.update_entry(self._entry(tab))

    def _render_page(self) -> None:
        tab = self.current_tab()
        if self.page.tab is not tab:
            self.page.bind(tab)
        uid = tab.uid
        self.page.set_state(uid in self._next_runs, self._next_runs.get(uid), uid in self._running,
                            bool(self._running), self.can_delete(uid))

    def _nearest(self) -> Optional[Tuple[datetime, TabConfig]]:
        """Ближайшее копирование по расписанию среди вкладок, которые можно скопировать."""
        best = None
        for uid, moment in self._next_runs.items():
            tab = self.tab(uid)
            if tab is None or tab.problems():
                continue
            if best is None or moment < best[0]:
                best = (moment, tab)
        return best

    def next_run_text(self, now: Optional[datetime] = None) -> str:
        nearest = self._nearest()
        if nearest is None:
            return NEXT_RUN_STOPPED
        return NEXT_RUN_PILL.format(when=fmt_when(nearest[0], now or datetime.now()), name=tab_name(nearest[1]))

    def tray_text(self) -> str:
        nearest = self._nearest()
        if nearest is None:
            return NEXT_RUN_STOPPED
        return NEXT_RUN_PILL.format(when=f"{nearest[0]:%d.%m.%Y %H:%M}", name=tab_name(nearest[1]))

    def run_label_text(self) -> str:
        if self._cancelling:
            return CANCELLING_TEXT
        if self._progress is None:
            return PREPARING_TEXT
        if self._tab_text:
            return self._tab_text
        if len(self._run_names) == 1:
            return f"Копирование «{self._run_names[0]}»"
        return f"Копирование {count_tabs_genitive(len(self._run_names))}"

    def _render_status(self) -> None:
        bar = self.status_bar
        if self._running:
            percent = None if self._progress is None else self._progress[0]
            bar.show_running(self.run_label_text(), percent, self._detail)
        elif self._flash is not None:
            icon, status, tone = self._flash
            bar.show_result(icon, status, tone)
        else:
            bar.show_idle()
        bar.pill.setText(self.next_run_text())
        if self.tray is not None:
            self.tray.set_next_backup(self.tray_text())

    def _render_history_button(self) -> None:
        button = self.status_bar.history_button
        text = HISTORY_COLLAPSE if self._history_open else HISTORY_EXPAND.format(
            count=self.history_panel.total_count())
        if button.text() != text:
            button.setText(text)

    def toggle_history(self) -> None:
        self.set_history_open(not self._history_open)

    def set_history_open(self, on: bool) -> None:
        self._history_open = on
        self.history_panel.setVisible(on)
        if on:
            self.history_panel.view.scroll_to_end()
        self._render_history_button()

    def history_open(self) -> bool:
        return self._history_open

    # ================================================================ журнал
    def open_journal(self) -> None:
        path = self.service.log_path
        if not path or not os.path.exists(path):
            self.show_toast(JOURNAL_TITLE, JOURNAL_EMPTY_TEXT, "info")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            self.show_toast(JOURNAL_OPEN_FAILED_TITLE, f"Откройте файл вручную:\n{path}", "warn")

    # ================================================================ трей и выход
    def setup_tray(self) -> None:
        if not TrayIcon.available():
            self.log.warning("Системный трей недоступен: при закрытии окна приложение завершится")
            return
        self.tray = TrayIcon(self.windowIcon(), self)
        self.tray.show_requested.connect(self.show_from_tray)
        self.tray.backup_requested.connect(self.copy_all_tabs)
        self.tray.quit_requested.connect(self.quit_app)
        self.tray.show()

    def tray_mode_enabled(self) -> bool:
        return self.tray is not None and self.settings_page.value("minimize_to_tray")

    def show_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def hide_to_tray(self) -> None:
        if not self.tray_mode_enabled():
            return
        self._flush_title()
        self.hide()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self.notify(TRAY_HINT_TITLE, TRAY_HINT_TEXT)
        self.log.info("Окно свернуто в трей, приложение продолжает работать")

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and self.isMinimized() and self.tray_mode_enabled():
            QTimer.singleShot(0, self.hide_to_tray)

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._quitting and self.tray_mode_enabled():
            event.ignore()
            self.hide_to_tray()
            return
        self._flush_title()
        self._quitting = True
        if self.tray is not None:
            self.tray.hide()
        event.accept()
        QApplication.instance().quit()

    def quit_app(self) -> None:
        self._quitting = True
        self.close()
