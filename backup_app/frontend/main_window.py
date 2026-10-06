"""Главное окно. Только интерфейс: показывает состояние бэкенда и передает ему команды.

Расписание, копирование, проверки и сохранение настроек выполняет BackupService.
Окно вызывает его методы и получает события через ServiceBridge в своем потоке.

Поведение в фоне:
- закрытие и сворачивание окна прячут приложение в трей, если трей доступен;
- плановые запуски не открывают диалогов, о проблемах сообщают уведомления;
- о результате каждого копирования сообщает уведомление.

Внизу окна показывается история копирования из бэкенда. Служебные сообщения в окно
не попадают: они есть только в подробном журнале, который открывается кнопкой.
"""
import os
import platform
from datetime import datetime
from typing import List, Optional

from PyQt5.QtCore import QEvent, QSize, Qt, QTime, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QIcon, QTextCursor
from PyQt5.QtWidgets import (QAction, QApplication, QCheckBox, QComboBox, QFrame, QGridLayout,
                             QGroupBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                             QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QSpinBox,
                             QStackedWidget, QTabWidget, QTimeEdit, QToolBar,
                             QVBoxLayout, QWidget)

from ..backend import (ALREADY_RUNNING, MAX_PATH_LENGTH, PERIOD_MONTHLY, PERIOD_WEEKLY, PERIODS,
                       SECURITY_TAG, STATUS_CANCELLED, STATUS_OK, STATUS_PARTIAL, WEEKDAYS,
                       AppConfig, AppProblem, BackupFinished, BackupProgress, BackupResult, BackupService,
                       BackupStarted, ConfigChanged, HistoryAdded, HistoryEntry, RunSkipped, ScheduleChanged,
                       TabConfig, format_run_time, get_logger)
from .bridge import ServiceBridge
from .constants import APP_TITLE, SECURITY_HINT, TAB_TITLE_LIMIT
from .resources import resource_path
from .tab_page import TabPage
from .tray import TrayIcon

# Как показывать результат копирования: заголовок уведомления, вид, строка состояния.
RESULT_VIEW = {
    STATUS_OK: ("Копирование завершено", "info", "Копирование завершено успешно"),
    STATUS_PARTIAL: ("Копирование завершено с ошибками", "warning", "Копирование завершено с ошибками"),
    STATUS_CANCELLED: ("Копирование отменено", "warning", "Копирование отменено"),
}
FAILED_VIEW = ("Ошибка копирования", "error", "Ошибка копирования")
NO_DATA_TEXT = "Выберите исходные файлы/папки и папку назначения!"
HISTORY_TITLE = "История копирования"
HISTORY_EMPTY_TEXT = "Копирований пока не было"
HISTORY_VIEW_LIMIT = 10000  # строк истории в окне; файл истории хранит записи за год


def truncate_tab_title(title: str) -> str:
    return title[:11] + " ..." if len(title) > TAB_TITLE_LIMIT else title


class MainWindow(QMainWindow):
    def __init__(self, service: BackupService, bridge: ServiceBridge, parent=None):
        super().__init__(parent)
        self.service = service
        self.tray: Optional[TrayIcon] = None
        self._quitting = False
        self._loading = False
        self._tray_hint_shown = False
        self._running = False
        self._schedule_active = False
        self.log = get_logger()

        self.setWindowTitle(APP_TITLE)
        self.setGeometry(100, 100, 900, 700)
        icon_path = resource_path("icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            self.setWindowIcon(self.style().standardIcon(self.style().SP_ComputerIcon))

        self.init_ui()
        bridge.event_received.connect(self.on_backend_event)
        self.setup_tray()
        self.apply_config(service.config)
        self.render_schedule(service.schedule_active, service.next_run)
        self.render_running(service.is_running)
        self.render_history(service.history())

    # ================================================================ UI
    def init_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 16, 10, 10)
        layout.setSpacing(6)

        self.create_toolbar()

        self.stacked_widget = QStackedWidget()
        layout.addWidget(self.stacked_widget)

        self.files_widget = QWidget()
        files_layout = QVBoxLayout(self.files_widget)
        files_layout.setAlignment(Qt.AlignTop)
        files_layout.setContentsMargins(0, 0, 0, 0)
        files_layout.setSpacing(5)

        self.settings_widget = QWidget()
        settings_layout = QVBoxLayout(self.settings_widget)
        settings_layout.setAlignment(Qt.AlignTop)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(5)

        self.stacked_widget.addWidget(self.files_widget)
        self.stacked_widget.addWidget(self.settings_widget)
        self.init_files_section()
        self.init_settings_section()
        self.stacked_widget.setCurrentIndex(0)

        buttons = QHBoxLayout()
        self.start_btn = QPushButton("Запустить")
        self.start_btn.clicked.connect(self.start_schedule)
        self.start_btn.setStyleSheet("background-color: #4CAF50; color: white;")
        self.stop_btn = QPushButton("Остановить")
        self.stop_btn.clicked.connect(self.stop_schedule)
        self.stop_btn.setStyleSheet("background-color: #f44336; color: white;")
        self.stop_btn.setEnabled(False)
        self.manual_btn = QPushButton("Копировать")
        self.manual_btn.clicked.connect(self.manual_backup)
        self.manual_btn.setStyleSheet("background-color: #2196F3; color: white;")
        self.cancel_btn = QPushButton("Отменить")
        self.cancel_btn.clicked.connect(self.cancel_backup)
        self.cancel_btn.setStyleSheet("background-color: #FF9800; color: white;")
        self.cancel_btn.setVisible(False)
        for button in (self.start_btn, self.stop_btn, self.manual_btn, self.cancel_btn):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.next_backup_label = QLabel("Следующее копирование: остановлено")
        self.next_backup_label.setStyleSheet(
            "background-color: #e3f2fd; padding: 5px; border: 1px solid #bbdefb;")
        layout.addWidget(self.next_backup_label)

        history_group = QGroupBox()
        history_layout = QVBoxLayout(history_group)
        header = QHBoxLayout()
        header.addWidget(QLabel(HISTORY_TITLE))
        header.addStretch()
        self.journal_btn = QPushButton("Открыть подробный журнал")
        self.journal_btn.clicked.connect(self.open_journal)
        header.addWidget(self.journal_btn)
        history_layout.addLayout(header)
        self.history_text = QPlainTextEdit()
        self.history_text.setReadOnly(True)
        self.history_text.setMaximumBlockCount(HISTORY_VIEW_LIMIT)
        self.history_text.setPlaceholderText(HISTORY_EMPTY_TEXT)
        history_layout.addWidget(self.history_text)
        layout.addWidget(history_group)

        self.hide_period_widgets()
        self.setup_statusbar(layout)

    def create_toolbar(self) -> None:
        toolbar = QToolBar("Main Toolbar", self)
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setOrientation(Qt.Vertical)
        self.addToolBar(Qt.RightToolBarArea, toolbar)

        toolbar.addSeparator()
        files_action = QAction(QIcon(resource_path("icons", "files_icon.png")), "Выбор файлов", self)
        files_action.triggered.connect(self.show_files_section)
        toolbar.addAction(files_action)
        settings_action = QAction(QIcon(resource_path("icons", "settings_icon.png")), "Настройки", self)
        settings_action.triggered.connect(self.show_settings_section)
        toolbar.addAction(settings_action)
        toolbar.addSeparator()

    @staticmethod
    def _section_title(text: str, layout: QVBoxLayout) -> None:
        title = QLabel(text)
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: #666; font-size: 11px;")
        return label

    def init_files_section(self) -> None:
        files_layout = self.files_widget.layout()
        self._section_title("Выбор файлов и папок", files_layout)

        self.tabs_widget = QTabWidget()
        self.tabs_widget.setTabsClosable(True)
        self.tabs_widget.tabCloseRequested.connect(self.close_tab)
        self.tabs_widget.currentChanged.connect(self.on_settings_changed)
        tab_width = 140
        self.tabs_widget.setStyleSheet(
            f"QTabBar::tab {{ width: {tab_width}px; min-width: {tab_width}px; max-width: {tab_width}px; }}")

        self.add_tab_btn = QPushButton("+ Добавить вкладку")
        self.add_tab_btn.clicked.connect(self.add_new_tab)
        self.add_tab_btn.setStyleSheet("font-weight: bold;")
        self.add_tab_btn.setFixedHeight(40)

        files_layout.addWidget(self.tabs_widget)
        files_layout.addWidget(self.add_tab_btn)

    def init_settings_section(self) -> None:
        settings_layout = self.settings_widget.layout()
        self._section_title("Настройки", settings_layout)

        planning_group = QGroupBox("Планирование")
        planning_layout = QGridLayout(planning_group)
        planning_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        planning_layout.addWidget(QLabel("Тип периода:"), 0, 0)
        self.period_type_combo = QComboBox()
        self.period_type_combo.addItems(list(PERIODS))
        self.period_type_combo.currentTextChanged.connect(self.on_period_changed)
        planning_layout.addWidget(self.period_type_combo, 0, 1)

        planning_layout.addWidget(QLabel("Время копирования:"), 1, 0)
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setTime(QTime(0, 0))
        self.time_edit.timeChanged.connect(self.on_settings_changed)
        planning_layout.addWidget(self.time_edit, 1, 1)

        self.weekday_label = QLabel("День недели:")
        self.weekday_combo = QComboBox()
        self.weekday_combo.addItems(list(WEEKDAYS))
        self.weekday_combo.currentIndexChanged.connect(self.on_settings_changed)
        planning_layout.addWidget(self.weekday_label, 2, 0)
        planning_layout.addWidget(self.weekday_combo, 2, 1)

        self.monthday_label = QLabel("День месяца:")
        self.monthday_spin = QSpinBox()
        self.monthday_spin.setRange(1, 31)
        self.monthday_spin.setValue(1)
        self.monthday_spin.valueChanged.connect(self.on_settings_changed)
        planning_layout.addWidget(self.monthday_label, 3, 0)
        planning_layout.addWidget(self.monthday_spin, 3, 1)
        settings_layout.addWidget(planning_group)

        additional_group = QGroupBox("Дополнительные настройки")
        additional_layout = QGridLayout(additional_group)
        additional_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        self.copy_all_tabs_cb = QCheckBox("Копировать данные всех вкладок")
        self.copy_folder_contents_cb = QCheckBox("Копировать только содержимое папок, без самих папок")
        self.keep_history_cb = QCheckBox("Добавить дату к имени сохраненной копии файла")
        self.create_backup_folder_cb = QCheckBox(
            'Создавать отдельную папку с названием «Резервное копирование дд-мм-гггг» при каждом копировании')
        self.auto_start_cb = QCheckBox("Автозапуск при входе в систему")
        self.minimize_to_tray_cb = QCheckBox("Фоновый режим работы")
        self.show_notifications_cb = QCheckBox("Уведомления о начале и результате копирования")
        self.run_missed_cb = QCheckBox("Выполнять пропущенное копирование при следующем запуске")

        for row, checkbox in enumerate((
                self.copy_all_tabs_cb, self.copy_folder_contents_cb, self.keep_history_cb,
                self.create_backup_folder_cb, self.auto_start_cb, self.minimize_to_tray_cb,
                self.show_notifications_cb, self.run_missed_cb)):
            additional_layout.addWidget(checkbox, row, 0, 1, 2)
            if checkbox is self.auto_start_cb:
                checkbox.toggled.connect(self.toggle_auto_start)
            else:
                checkbox.toggled.connect(self.on_settings_changed)
        settings_layout.addWidget(additional_group)

        security_group = QGroupBox("Безопасность")
        security_layout = QGridLayout(security_group)
        security_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        security_layout.addWidget(QLabel("Максимальный размер файла, ГБ (0 — без ограничения):"), 0, 0)
        self.max_size_spin = QSpinBox()
        self.max_size_spin.setRange(0, 100_000)
        self.max_size_spin.valueChanged.connect(self.on_settings_changed)
        security_layout.addWidget(self.max_size_spin, 0, 1)
        security_layout.addWidget(self._hint(SECURITY_HINT.format(max_path=MAX_PATH_LENGTH, tag=SECURITY_TAG)),
                                  1, 0, 1, 2)
        settings_layout.addWidget(security_group)

        reset_group = QGroupBox("Сброс настроек")
        reset_layout = QVBoxLayout(reset_group)
        reset_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.reset_btn = QPushButton("Сбросить все настройки по умолчанию")
        self.reset_btn.setStyleSheet("background-color: #FF9800; color: white;")
        self.reset_btn.clicked.connect(self.reset_settings_to_default)
        reset_layout.addWidget(self.reset_btn)
        reset_layout.addWidget(self._hint("Эта функция очистит все настройки и восстановит значения по умолчанию. "
                                          "Полезно при возникновении проблем в работе приложения."))
        settings_layout.addWidget(reset_group)
        settings_layout.addStretch()

    def setup_statusbar(self, layout: QVBoxLayout) -> None:
        status_widget = QWidget()
        status_layout = QVBoxLayout(status_widget)
        status_layout.setContentsMargins(10, 5, 10, 5)
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignCenter)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(20)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        if platform.system() == "Darwin":
            self.progress_bar.setMaximumHeight(25)
            self.progress_bar.setStyleSheet("""
                QProgressBar { border: 1px solid #C0C0C0; border-radius: 5px;
                               background-color: #F0F0F0; text-align: center; }
                QProgressBar::chunk { background-color: #007AFF; border-radius: 4px; }
            """)
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.progress_bar)
        layout.addWidget(status_widget)

    def show_files_section(self) -> None:
        self.stacked_widget.setCurrentIndex(0)

    def show_settings_section(self) -> None:
        self.stacked_widget.setCurrentIndex(1)

    def hide_period_widgets(self) -> None:
        for widget in (self.weekday_label, self.weekday_combo, self.monthday_label, self.monthday_spin):
            widget.setVisible(False)

    def update_ui_for_period(self, period: str) -> None:
        self.hide_period_widgets()
        if period == PERIOD_WEEKLY:
            self.weekday_label.setVisible(True)
            self.weekday_combo.setVisible(True)
        elif period == PERIOD_MONTHLY:
            self.monthday_label.setVisible(True)
            self.monthday_spin.setVisible(True)

    def show_problem(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)

    def show_app_problem(self, title: str, text: str) -> None:
        """Сбой приложения: на открытом окне диалог, при работе в трее уведомление.

        Уведомление показывается, даже если уведомления о копировании выключены.
        """
        if self.isVisible() or self.tray is None:
            QMessageBox.warning(self, title, text)
        else:
            self.tray.notify(title, text, "warning")

    # ============================================================== вкладки
    def add_tab(self, config: Optional[TabConfig] = None, make_current: bool = True) -> TabPage:
        page = TabPage(config or TabConfig(), self.service, self.tabs_widget)
        page.changed.connect(self.on_settings_changed)
        page.title_changed.connect(lambda title, page=page: self.set_tab_title(page, title))
        page.problem.connect(self.show_problem)
        index = self.tabs_widget.addTab(page, truncate_tab_title(page.title))
        if make_current:
            self.tabs_widget.setCurrentIndex(index)
        return page

    def add_new_tab(self) -> None:
        self.add_tab()
        self.on_settings_changed()

    def set_tab_title(self, page: TabPage, title: str) -> None:
        index = self.tabs_widget.indexOf(page)
        if index >= 0:
            self.tabs_widget.setTabText(index, truncate_tab_title(title))

    def close_tab(self, index: int) -> None:
        if self.tabs_widget.count() <= 1:
            return
        page = self.tabs_widget.widget(index)
        self.tabs_widget.removeTab(index)
        page.deleteLater()
        self.on_settings_changed()

    def pages(self) -> List[TabPage]:
        return [self.tabs_widget.widget(index) for index in range(self.tabs_widget.count())]

    def current_page(self) -> Optional[TabPage]:
        return self.tabs_widget.currentWidget()

    # ============================================================ настройки
    def apply_config(self, config: AppConfig) -> None:
        """Показывает настройки бэкенда в виджетах."""
        self._loading = True
        try:
            while self.tabs_widget.count():
                page = self.tabs_widget.widget(0)
                self.tabs_widget.removeTab(0)
                page.deleteLater()
            for tab in (config.tabs or [TabConfig()]):
                self.add_tab(tab, make_current=False)
            active = config.active_tab if 0 <= config.active_tab < self.tabs_widget.count() else 0
            self.tabs_widget.setCurrentIndex(active)

            self.period_type_combo.setCurrentText(
                config.period_type if config.period_type in PERIODS else PERIODS[0])
            moment = QTime.fromString(config.backup_time, "hh:mm")
            self.time_edit.setTime(moment if moment.isValid() else QTime(0, 0))
            self.weekday_combo.setCurrentIndex(config.weekday if 0 <= config.weekday < len(WEEKDAYS) else 0)
            self.monthday_spin.setValue(config.monthday if 1 <= config.monthday <= 31 else 1)

            self.copy_all_tabs_cb.setChecked(config.copy_all_tabs)
            self.copy_folder_contents_cb.setChecked(config.copy_folder_contents)
            self.keep_history_cb.setChecked(config.keep_history)
            self.create_backup_folder_cb.setChecked(config.create_backup_folder)
            self.auto_start_cb.setChecked(config.auto_start)
            self.minimize_to_tray_cb.setChecked(config.minimize_to_tray)
            self.show_notifications_cb.setChecked(config.show_notifications)
            self.run_missed_cb.setChecked(config.run_missed)
            self.max_size_spin.setValue(max(0, config.max_file_size_gb))
            self.update_ui_for_period(self.period_type_combo.currentText())
        finally:
            self._loading = False

    def collect_config(self) -> AppConfig:
        """Настройки из виджетов. Сервис берет из них только то, что меняет пользователь."""
        return AppConfig(
            period_type=self.period_type_combo.currentText(),
            backup_time=self.time_edit.time().toString("hh:mm"),
            weekday=self.weekday_combo.currentIndex(),
            monthday=self.monthday_spin.value(),
            keep_history=self.keep_history_cb.isChecked(),
            create_backup_folder=self.create_backup_folder_cb.isChecked(),
            copy_folder_contents=self.copy_folder_contents_cb.isChecked(),
            copy_all_tabs=self.copy_all_tabs_cb.isChecked(),
            minimize_to_tray=self.minimize_to_tray_cb.isChecked(),
            show_notifications=self.show_notifications_cb.isChecked(),
            run_missed=self.run_missed_cb.isChecked(),
            max_file_size_gb=self.max_size_spin.value(),
            active_tab=max(0, self.tabs_widget.currentIndex()),
            tabs=[page.to_config() for page in self.pages()],
        )

    def on_settings_changed(self, *_args) -> None:
        if self._loading:
            return
        self.service.update_config(self.collect_config())

    def on_period_changed(self, period: str) -> None:
        self.update_ui_for_period(period)
        self.on_settings_changed()

    def toggle_auto_start(self, checked: bool) -> None:
        if self._loading:
            return
        try:
            self.service.set_autostart(checked)
        except Exception as error:
            QMessageBox.critical(self, "Ошибка", f"Не удалось изменить автозапуск:\n{error}")
            self.auto_start_cb.blockSignals(True)
            self.auto_start_cb.setChecked(not checked)
            self.auto_start_cb.blockSignals(False)

    def reset_settings_to_default(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Подтверждение сброса")
        box.setText("Вы уверены, что хотите сбросить все настройки к значениям по умолчанию?")
        box.setIcon(QMessageBox.Warning)
        yes_button = box.addButton("Да", QMessageBox.YesRole)
        no_button = box.addButton("Нет", QMessageBox.NoRole)
        box.setDefaultButton(no_button)
        box.exec_()
        if box.clickedButton() != yes_button:
            return
        self.perform_reset()
        QMessageBox.information(self, "Сброс завершен",
                                "Все настройки успешно сброшены к значениям по умолчанию.")

    def perform_reset(self) -> None:
        self.service.reset()

    # ============================================================ команды
    def start_schedule(self) -> None:
        problems = self.service.start_schedule()
        if problems:
            QMessageBox.warning(self, "Ошибка", NO_DATA_TEXT + "\n" + "; ".join(problems))

    def stop_schedule(self) -> None:
        self.service.stop_schedule()

    def manual_backup(self) -> None:
        problems = self.service.run_now()
        if not problems:
            return
        if problems == [ALREADY_RUNNING]:
            QMessageBox.information(self, "Копирование", ALREADY_RUNNING)
        else:
            QMessageBox.warning(self, "Ошибка", NO_DATA_TEXT + "\n" + "; ".join(problems))

    def cancel_backup(self) -> None:
        if self._running:
            self.service.cancel()
            self.status_label.setText("Отмена копирования...")

    # ============================================================ события
    def on_backend_event(self, event) -> None:
        if isinstance(event, BackupProgress):
            self.update_progress(event.percent, event.text)
        elif isinstance(event, BackupStarted):
            self.render_running(True)
            self.status_label.setText("Подготовка к копированию...")
            if event.scheduled:
                self.notify("Резервное копирование", "Начато плановое копирование: " + ", ".join(event.tab_names))
        elif isinstance(event, BackupFinished):
            self.render_running(False)
            self.show_result(event.result)
        elif isinstance(event, ScheduleChanged):
            self.render_schedule(event.active, event.next_run)
        elif isinstance(event, RunSkipped):
            if event.scheduled:
                self.notify("Копирование не выполнено", event.reason, "warning")
        elif isinstance(event, ConfigChanged):
            self.apply_config(event.config)
        elif isinstance(event, HistoryAdded):
            self.add_history_entry(event.entry)
        elif isinstance(event, AppProblem):
            self.show_app_problem(event.title, event.text)

    def show_result(self, result: BackupResult) -> None:
        title, kind, status = RESULT_VIEW.get(result.status, FAILED_VIEW)
        self.status_label.setText(status)
        self.notify(title, result.message, kind)

    def notify(self, title: str, message: str, kind: str = "info") -> None:
        if self.tray is not None and self.show_notifications_cb.isChecked():
            self.tray.notify(title, message, kind)

    def render_schedule(self, active: bool, next_run: Optional[datetime]) -> None:
        self._schedule_active = active
        if active and next_run is not None:
            text = f"Следующее копирование: {format_run_time(next_run)}"
        else:
            text = "Следующее копирование: остановлено"
        self.next_backup_label.setText(text)
        if self.tray is not None:
            self.tray.set_next_backup(text)
        self.update_buttons()

    def render_running(self, running: bool) -> None:
        self._running = running
        self.update_buttons()
        if running:
            self.show_progress_bar()
        else:
            self.hide_progress_bar()

    def update_buttons(self) -> None:
        running, scheduled = self._running, self._schedule_active
        self.start_btn.setEnabled(not running and not scheduled)
        self.stop_btn.setEnabled(not running and scheduled)
        self.manual_btn.setEnabled(not running)
        self.cancel_btn.setVisible(running)
        if self.tray is not None:
            self.tray.set_backup_enabled(not running)

    # ============================================================= история
    def render_history(self, entries: List[HistoryEntry]) -> None:
        self.history_text.setPlainText("\n".join(line for entry in entries for line in entry.lines()))
        self.history_text.moveCursor(QTextCursor.End)

    def add_history_entry(self, entry: HistoryEntry) -> None:
        for line in entry.lines():
            self.history_text.appendPlainText(line)

    def open_journal(self) -> None:
        path = self.service.log_path
        if not path or not os.path.exists(path):
            QMessageBox.information(self, "Подробный журнал", "Журнал пока пуст.")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            self.show_problem("Не удалось открыть журнал", f"Откройте файл вручную:\n{path}")

    # ============================================================ прогресс
    def show_progress_bar(self) -> None:
        self.progress_bar.setRange(0, 0)  # «занято», пока бэкенд считает объем
        self.progress_bar.setVisible(True)

    def update_progress(self, percent: int, text: str) -> None:
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(percent)
        self.status_label.setText(text)

    def hide_progress_bar(self) -> None:
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        QTimer.singleShot(4000, self._clear_status_if_idle)

    def _clear_status_if_idle(self) -> None:
        if not self._running:
            self.status_label.setText("")

    # ========================================================= трей и выход
    def setup_tray(self) -> None:
        if not TrayIcon.available():
            self.log.warning("Системный трей недоступен: при закрытии окна приложение завершится")
            return
        self.tray = TrayIcon(self.windowIcon(), self)
        self.tray.show_requested.connect(self.show_from_tray)
        self.tray.backup_requested.connect(self.manual_backup)
        self.tray.quit_requested.connect(self.quit_app)
        self.tray.show()

    def tray_mode_enabled(self) -> bool:
        return self.tray is not None and self.minimize_to_tray_cb.isChecked()

    def show_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def hide_to_tray(self) -> None:
        if not self.tray_mode_enabled():
            return
        self.hide()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self.notify("Приложение работает в фоне",
                        "Копирование по расписанию продолжится. Окно открывается щелчком по иконке в трее.")
        self.log.info("Окно свернуто в трей, приложение продолжает работать")

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and self.isMinimized() and self.tray_mode_enabled():
            QTimer.singleShot(0, self.hide_to_tray)

    def closeEvent(self, event) -> None:
        if not self._quitting and self.tray_mode_enabled():
            event.ignore()
            self.hide_to_tray()
            return
        self._quitting = True
        if self.tray is not None:
            self.tray.hide()
        event.accept()
        QApplication.instance().quit()

    def quit_app(self) -> None:
        self._quitting = True
        self.close()
