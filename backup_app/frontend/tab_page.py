"""Страница вкладки: название и состояние, «Что копировать», «Папка сохранения», «Настройки вкладки».

Одна страница на все вкладки: окно привязывает ее к выбранной вкладке (bind), поэтому
переключение мгновенное даже при сотнях вкладок. Страница меняет переданный ей TabConfig
и сообщает об этом сигналами; в сервис изменения передает окно.

Проверки путей выполняет бэкенд: страница получает объект validator с методами
source_problem, destination_problem и path_problem. Сама страница диск не читает.
"""
import os
from datetime import datetime
from typing import Iterable, List, Optional, Sequence, Tuple

from PyQt5.QtCore import QEvent, QRect, QRectF, QSize, Qt, QTime, pyqtSignal
from PyQt5.QtGui import QColor, QFontMetrics, QPainter, QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import (QAbstractItemView, QAbstractSpinBox, QFileDialog, QFrame, QHBoxLayout, QLineEdit,
                             QListView, QSizePolicy, QStyle, QStyledItemDelegate, QTimeEdit, QToolTip, QVBoxLayout,
                             QWidget)

from ..backend import (DEFAULT_TAB_TITLE, PATH_SYSTEM, PERIOD_DAILY, PERIOD_MONTHLY, PERIOD_WEEKLY,
                       PERIODS, TabConfig, backup_folder_name, folder_copy_name, plural)
from . import icons
from . import widgets as W
from .constants import (DESTINATION_REFUSED, FILES_REFUSED, FOLDER_REFUSED, NEXT_RUN_OFF_TAB, NEXT_RUN_TEXT,
                        SCHEDULE_OFF_SHORT, TAB_RUNNING_TEXT)
from .theme import C, font_exact as font

DAY_DATIVE = ("понедельникам", "вторникам", "средам", "четвергам", "пятницам", "субботам", "воскресеньям")
# Отметка времени в имени копии при совпадении имен — как COPY_STAMP_FORMAT в copier.
COPY_STAMP_FORMAT = "%d.%m.%Y_%H-%M-%S"
SAMPLE_FILE_NAME = "Отчет.docx"

SCHEDULE_TITLE = "Копировать по расписанию"
SCHEDULE_HINT = "включено — расписание запущено; работает и в фоне, из трея"
SCHEDULE_OFF_NOTE = ("Расписание остановлено. Вкладка копируется только кнопкой «Копировать сейчас» "
                     "или «Копировать все вкладки».")
MONTH_HINT = "В месяцах, где столько дней нет, — в последний день месяца."
EMPTY_SOURCES = "Список пуст. Добавьте папки или файлы кнопками выше."
NO_DESTINATION_HINT = "Без папки назначения вкладку нельзя скопировать."
DESTINATION_PLACEHOLDER = "Папка назначения не выбрана"
OPTION_CONTENTS = ("Копировать только содержимое папок, без самих папок",
                   "выбранные папки не создаются в месте назначения")
OPTION_DATE_FOLDER = "Создавать отдельную папку с названием «Резервное копирование дд-мм-гггг» при каждом копировании"
OPTION_DATE_NAME = ("Добавить дату к имени сохраненной копии файла",
                    "только при совпадении имен, иначе номер: файл_(1).txt")
PREVIEW_NO_DESTINATION = ("Сначала выберите папку назначения", "Существующие файлы никогда не перезаписываются.")


# =========================================================================== тексты
def tab_name(tab: TabConfig) -> str:
    """Имя вкладки для показа: без пробелов по краям, пустое — «Без названия»."""
    return (tab.title or "").strip() or DEFAULT_TAB_TITLE


def fmt_when(moment: datetime, now: datetime) -> str:
    """«сегодня в 09:00», «завтра в 09:00», «вс, 12.10 в 22:00»."""
    days = (moment.date() - now.date()).days
    if days == 0:
        return f"сегодня в {moment:%H:%M}"
    if days == 1:
        return f"завтра в {moment:%H:%M}"
    return f"{W.DAY_SHORT[moment.weekday()].lower()}, {moment:%d.%m} в {moment:%H:%M}"


def sched_short(tab: TabConfig, on: bool) -> str:
    """Подпись расписания в списке вкладок: «Каждый день · 09:00», «По воскресеньям · 22:00»."""
    if not on:
        return SCHEDULE_OFF_SHORT
    if tab.period_type == PERIOD_WEEKLY:
        return f"По {DAY_DATIVE[max(0, min(6, tab.weekday))]} · {tab.backup_time}"
    if tab.period_type == PERIOD_MONTHLY:
        return f"{tab.monthday}-го числа · {tab.backup_time}"
    return f"Каждый день · {tab.backup_time}"


def tab_problem(tab: TabConfig) -> str:
    """Первая причина, по которой вкладку нельзя скопировать, или пустая строка."""
    problems = tab.problems()
    return problems[0] if problems else ""


def _base_name(path: str) -> str:
    stripped = path.rstrip("/\\")
    for sep in ("/", "\\"):
        stripped = stripped.split(sep)[-1] if sep in stripped else stripped
    return stripped or path


def _dir_name(path: str) -> str:
    stripped = path.rstrip("/\\")
    index = max(stripped.rfind("/"), stripped.rfind("\\"))
    return stripped[:index] if index > 0 else path


def preview_texts(tab: TabConfig, now: datetime, usable: Sequence[Tuple[str, str]]) -> Tuple[str, str]:
    """«Так будет выглядеть копия»: путь копии и что будет при совпадении имен.

    usable — доступные источники [(вид, путь)] в порядке копирования (сначала папки, затем файлы).
    Правила — как в copier: папка «Резервное копирование дд-мм-гггг» (backup_folder_name), имя папки
    в копии (folder_copy_name), при совпадении имя_дд.мм.гггг_чч-мм-сс или имя_(1) (safe_destination_path).
    """
    if not tab.destination:
        return PREVIEW_NO_DESTINATION
    destination = tab.destination.rstrip("/\\") or tab.destination
    sep = "\\" if "\\" in destination and "/" not in destination else "/"
    parts = [destination]
    if tab.create_backup_folder:
        parts.append(backup_folder_name(now))
    kind, source = usable[0] if usable else ("", "")
    file_name = SAMPLE_FILE_NAME
    whole_folder = kind == "folder" and not tab.copy_folder_contents
    if kind == "folder":
        if whole_folder:
            parts.append(folder_copy_name(source))
    elif kind == "file":
        file_name = _base_name(source)
    parts.append(file_name)
    clash = folder_copy_name(source) if whole_folder else file_name
    stem, ext = os.path.splitext(clash)
    renamed = f"{stem}_{now.strftime(COPY_STAMP_FORMAT)}{ext}" if tab.keep_history else f"{stem}_(1){ext}"
    what = f"папка «{clash}»" if whole_folder else f"файл «{clash}»"
    conflict = f"Ничего не перезаписывается: если {what} уже есть, копия получит имя {renamed}"
    if tab.create_backup_folder:
        conflict += ". Папка с датой одна на день: повторные копирования в тот же день попадают в нее."
    return sep.join(parts), conflict


# =========================================================================== список источников
ROLE_PATH = Qt.UserRole + 1
ROLE_KIND = Qt.UserRole + 2
ROLE_PROBLEM = Qt.UserRole + 3   # полный текст проблемы пути (PATH_UNAVAILABLE / PATH_SYSTEM) или ""


def problem_line(path: str, problem: str) -> str:
    """Вторая строка строки списка для пути с проблемой."""
    if problem == PATH_SYSTEM:
        return f"{path} — системный путь, будет пропущен"
    return f"{path} — недоступен, будет пропущен"


class SourceDelegate(QStyledItemDelegate):
    """Строка «Что копировать»: иконка, имя (500) и папка моноширинным или проблема красным, кнопка «×»."""

    ROW_HEIGHT = 47   # 1 линия сверху + 6 + 18 + 15 + 6, как .srow в макете
    BUTTON = 28

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hover_button_row = -1

    def sizeHint(self, option, index):  # noqa: N802
        return QSize(max(0, option.rect.width()), self.ROW_HEIGHT)

    def button_rect(self, rect: QRect) -> QRect:
        body = rect.adjusted(0, 1, 0, 0)
        return QRect(body.right() - 8 - self.BUTTON + 1, body.top() + (body.height() - self.BUTTON) // 2,
                     self.BUTTON, self.BUTTON)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        p.fillRect(QRect(r.x(), r.y(), r.width(), 1), QColor(C.DIVIDER))
        body = r.adjusted(0, 1, 0, 0)
        if option.state & QStyle.State_MouseOver:
            p.fillRect(body, QColor(C.ROW_HOVER))
        path = index.data(ROLE_PATH) or ""
        kind = index.data(ROLE_KIND)
        problem = index.data(ROLE_PROBLEM) or ""
        icon_color = C.DANGER if problem else (C.FOLDER if kind == "folder" else C.FILE)
        cy = body.top() + body.height() / 2
        icons.paint(p, QRectF(12, cy - 9, 18, 18).translated(r.x(), 0), "folder" if kind == "folder" else "file",
                    icon_color)
        button = self.button_rect(r)
        tx = r.x() + 40
        tw = max(0, button.left() - 10 - tx)
        top = body.top() + (body.height() - 33.6) / 2
        name_font = font("medium", 13)
        p.setFont(name_font)
        p.setPen(QColor(C.DANGER if problem else C.TEXT))
        name = QFontMetrics(name_font).elidedText(_base_name(path), Qt.ElideRight, tw)
        p.drawText(QRectF(tx, top, tw, 18.2), Qt.AlignLeft | Qt.AlignVCenter, name)
        if problem:
            sub_font, sub, color, height = font("regular", 11.5), problem_line(path, problem), C.DANGER, 16.1
        else:
            sub_font, sub, color, height = font("mono", 11), _dir_name(path), C.MUTED, 15.4
        p.setFont(sub_font)
        p.setPen(QColor(color))
        p.drawText(QRectF(tx, top + 18.2, tw, height), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(sub_font).elidedText(sub, Qt.ElideRight, tw))
        if self.hover_button_row == index.row():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(C.GHOST_HOVER))
            p.drawRoundedRect(QRectF(button), 6, 6)
        icons.paint(p, QRectF(button.center().x() - 6.5, button.center().y() - 6.5, 14, 14), "x", C.TEXT2, 2.0)
        p.restore()

    def editorEvent(self, event, model, option, index):  # noqa: N802
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if self.button_rect(option.rect).contains(event.pos()):
                view = self.parent()
                if view is not None:
                    view.remove_requested.emit(index.data(ROLE_PATH))
                return True
        return super().editorEvent(event, model, option, index)

    def helpEvent(self, event, view, option, index):  # noqa: N802
        if event.type() == QEvent.ToolTip and index.isValid():
            path = index.data(ROLE_PATH) or ""
            problem = index.data(ROLE_PROBLEM) or ""
            if self.button_rect(option.rect).contains(event.pos()):
                text = "Убрать из списка"
            else:
                text = f"{path}\n{problem}" if problem else path
            QToolTip.showText(event.globalPos(), text, view)
            return True
        return super().helpEvent(event, view, option, index)


class SourceList(QListView):
    """Папки и файлы вкладки: строки с линией сверху, высота по содержимому, не больше 188 px."""

    remove_requested = pyqtSignal(str)
    MAX_HEIGHT = 188

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_ = QStandardItemModel(self)
        self.setModel(self.model_)
        self.delegate = SourceDelegate(self)
        self.setItemDelegate(self.delegate)
        self.setFrameShape(QFrame.NoFrame)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.TabFocus)
        self.verticalScrollBar().setSingleStep(24)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_sources(self, rows: Iterable[Tuple[str, str, str]]) -> None:
        """rows — [(вид folder/file, путь, проблема)]."""
        self.model_.clear()
        for kind, path, problem in rows:
            item = QStandardItem()
            item.setEditable(False)
            item.setData(path, ROLE_PATH)
            item.setData(kind, ROLE_KIND)
            item.setData(problem, ROLE_PROBLEM)
            item.setData(path, Qt.AccessibleTextRole)
            self.model_.appendRow(item)
        # строка в макете 46.6 px (1 + 6 + 18.2 + 15.4 + 6): высота списка — как у суммы строк макета
        self.setFixedHeight(min(int(self.model_.rowCount() * 46.6 + 0.5), self.MAX_HEIGHT))

    def rows(self) -> List[Tuple[str, str, str]]:
        return [(self.model_.item(r).data(ROLE_KIND), self.model_.item(r).data(ROLE_PATH),
                 self.model_.item(r).data(ROLE_PROBLEM) or "") for r in range(self.model_.rowCount())]

    def tooltip(self, row: int) -> str:
        item = self.model_.item(row)
        problem = item.data(ROLE_PROBLEM)
        return f"{item.data(ROLE_PATH)}\n{problem}" if problem else item.data(ROLE_PATH)

    def mouseMoveEvent(self, event):  # noqa: N802
        index = self.indexAt(event.pos())
        row = -1
        if index.isValid() and self.delegate.button_rect(self.visualRect(index)).contains(event.pos()):
            row = index.row()
        if row != self.delegate.hover_button_row:
            self.delegate.hover_button_row = row
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self.delegate.hover_button_row = -1
        self.viewport().update()
        super().leaveEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            index = self.currentIndex()
            if index.isValid():
                self.remove_requested.emit(index.data(ROLE_PATH))
                return
        super().keyPressEvent(event)

    def focusInEvent(self, event):  # noqa: N802
        super().focusInEvent(event)
        if not self.currentIndex().isValid() and self.model_.rowCount():
            self.setCurrentIndex(self.model_.index(0, 0))


# =========================================================================== поле времени
class TimeField(QTimeEdit):
    """Время «чч:мм» шириной 104 px с иконкой часов справа, как поле type=time в макете."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDisplayFormat("HH:mm")
        self.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.setFixedWidth(104)
        self.setFixedHeight(32)
        self.setAccessibleName("Время")
        self.setStyleSheet("QTimeEdit { padding-right: 30px; }")
        self.clock = W.IconLabel("clock", C.TEXT, 13, 2.0, parent=self)
        self.clock.setAttribute(Qt.WA_TransparentForMouseEvents)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.clock.move(self.width() - 13 - 11, (self.height() - 13) // 2)


# =========================================================================== страница
def _box(layout_cls, margins=(0, 0, 0, 0), spacing=0, parent=None):
    lay = layout_cls(parent)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return lay


class TabPage(QWidget):
    """Вид выбранной вкладки. Сигналы сообщают окну о действиях пользователя."""

    changed = pyqtSignal()                 # изменились данные вкладки: окно отправит их в сервис
    title_edited = pyqtSignal(str)         # название печатается (имя для показа)
    title_committed = pyqtSignal(str)      # название готово (Enter, уход фокуса)
    run_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    schedule_toggled = pyqtSignal(bool)

    def __init__(self, validator=None, parent=None):
        super().__init__(parent)
        self.validator = validator
        self.tab = TabConfig()
        self._loading = False
        self._now = datetime.now()
        self._next_run: Optional[datetime] = None
        self._schedule_on = False
        self._running = False
        self._problems_cache: dict = {}
        self.setProperty("kind", "page")
        self.setAttribute(Qt.WA_StyledBackground, True)

        root = _box(QVBoxLayout, (16 - W.TitleEdit.TEXT_INSET, 16, 16, 16), 12, self)
        root.addWidget(self._build_header())
        cards = _box(QVBoxLayout, (W.TitleEdit.TEXT_INSET, 0, 0, 0), 12)
        cards.addWidget(self._build_sources_card())
        cards.addWidget(self._build_destination_card())
        cards.addWidget(self._build_settings_card())
        root.addLayout(cards)
        root.addStretch(1)
        self.bind(self.tab)

    # ------------------------------------------------------------ сборка
    def _build_header(self) -> QWidget:
        header = QWidget()
        row = W.FlexRow(header, hgap=12, vgap=12)
        left = QWidget()
        col = _box(QVBoxLayout, spacing=2, parent=left)
        self.title_edit = W.TitleEdit(DEFAULT_TAB_TITLE, empty_text=DEFAULT_TAB_TITLE)
        self.title_edit.text_edited.connect(self._on_title_edited)
        self.title_edit.editing_finished.connect(self._on_title_finished)
        col.addWidget(self.title_edit)
        status_box = QWidget()
        status_lay = _box(QHBoxLayout, (W.TitleEdit.TEXT_INSET, 0, 0, 0), parent=status_box)
        self.status_line = W.StatusLine()
        status_lay.addWidget(self.status_line)
        col.addWidget(status_box)
        row.add(left, basis=280, grow=1, min_width=0)
        right = QWidget()
        buttons = _box(QHBoxLayout, spacing=8, parent=right)
        self.run_button = W.Button("Копировать сейчас", "primary", icon="play", icon_size=14)
        self.run_button.clicked.connect(self.run_requested)
        self.delete_button = W.Button(icon="trash", icon_only=True, tooltip="Удалить вкладку")
        self.delete_button.clicked.connect(self.delete_requested)
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.delete_button)
        row.add(right)
        return header

    def _build_sources_card(self) -> QFrame:
        card = QFrame()
        card.setProperty("kind", "card")
        lay = _box(QVBoxLayout, (0, 0, 0, 0), 0, card)
        head = QWidget()
        row = W.FlexRow(head, hgap=8, vgap=8)
        row.setContentsMargins(12, 9, 12, 9)
        row.add(W.IconLabel("folder", C.TEXT2, 16))
        row.add(W.label("Что копировать", "h2"))
        self.summary_label = W.label("", "muted")
        row.add(self.summary_label, min_width=0)
        row.add_spacer()
        self.add_folder_button = W.Button("Добавить папку", small=True, icon="folder-plus")
        self.add_folder_button.clicked.connect(self.add_folder)
        self.add_files_button = W.Button("Добавить файл", small=True, icon="file-plus")
        self.add_files_button.clicked.connect(self.add_files)
        self.clear_button = W.Button("Очистить список", "ghost", small=True)
        self.clear_button.clicked.connect(self.clear_sources)
        for button in (self.add_folder_button, self.add_files_button, self.clear_button):
            row.add(button)
        lay.addWidget(head)
        notice_box = QWidget()
        notice_lay = _box(QVBoxLayout, (12, 0, 12, 10), parent=notice_box)
        self.notice = W.NoticeBanner()
        self.notice.closed.connect(lambda: self.notice_box.hide())
        notice_lay.addWidget(self.notice)
        self.notice_box = notice_box
        lay.addWidget(notice_box)
        self.source_list = SourceList()
        self.source_list.remove_requested.connect(self.remove_path)
        lay.addWidget(self.source_list)
        empty_box = QWidget()
        empty_lay = _box(QVBoxLayout, (12, 0, 12, 12), parent=empty_box)
        self.empty_label = W.WrapAnywhereLabel(EMPTY_SOURCES, "empty")
        self.empty_label.set_alignment(Qt.AlignHCenter)
        empty_lay.addWidget(self.empty_label)
        self.empty_box = empty_box
        lay.addWidget(empty_box)
        notice_box.hide()
        return card

    def _build_destination_card(self) -> QFrame:
        card = QFrame()
        card.setProperty("kind", "card")
        lay = _box(QVBoxLayout, (12, 9, 12, 11), 8, card)
        head = _box(QHBoxLayout, spacing=8)
        head.addWidget(W.IconLabel("drive", C.TEXT2, 16))
        head.addWidget(W.label("Папка сохранения", "h2"))
        head.addStretch(1)
        lay.addLayout(head)
        row_widget = QWidget()
        row = W.FlexRow(row_widget, hgap=8, vgap=8)
        self.dest_edit = QLineEdit()
        self.dest_edit.setReadOnly(True)
        self.dest_edit.setProperty("mono", True)
        self.dest_edit.setPlaceholderText(DESTINATION_PLACEHOLDER)
        self.dest_edit.setAccessibleName("Папка назначения")
        self.dest_edit.setFocusPolicy(Qt.TabFocus)
        row.add(self.dest_edit, basis=260, grow=1, min_width=0)
        self.dest_button = W.Button("Выбрать папку")
        self.dest_button.clicked.connect(self.select_destination)
        row.add(self.dest_button)
        lay.addWidget(row_widget)
        self.no_dest_label = W.WrapAnywhereLabel(NO_DESTINATION_HINT, "warn")
        lay.addWidget(self.no_dest_label)
        return card

    def _build_settings_card(self) -> QFrame:
        card = QFrame()
        card.setProperty("kind", "card")
        lay = _box(QVBoxLayout, (0, 0, 0, 0), 0, card)
        head = QWidget()
        row = W.FlexRow(head, hgap=8, vgap=8)
        row.setContentsMargins(12, 9, 12, 9)
        row.add(W.IconLabel("sliders", C.TEXT2, 16))
        row.add(W.label("Настройки вкладки", "h2"))
        self.scope_badge = W.Badge("", "badge", max_width=260)
        self.scope_badge.setFixedHeight(20)
        row.add(self.scope_badge, min_width=0)
        row.add_spacer()
        lay.addWidget(head)
        lay.addWidget(W.hline())

        cols_widget = QWidget()
        cols = W.FlexRow(cols_widget, hgap=0, vgap=0, align="stretch")
        cols.add(self._build_schedule_column(), basis=300, grow=1, min_width=0)
        cols.add(self._build_options_column(), basis=300, grow=1, min_width=0)
        lay.addWidget(cols_widget)

        footer = QFrame()
        footer.setProperty("kind", "card-footer")
        f_lay = _box(QVBoxLayout, (14, 10, 14, 10), 3, footer)
        f_lay.addWidget(W.CapsLabel("Так будет выглядеть копия", letter_spacing_em=0.05))
        self.preview_path = W.WrapAnywhereLabel("", "mono-body")
        self.preview_note = W.WrapAnywhereLabel("", "muted")
        f_lay.addWidget(self.preview_path)
        f_lay.addWidget(self.preview_note)
        lay.addWidget(footer)
        return card

    def _build_schedule_column(self) -> QFrame:
        col = QFrame()
        col.setProperty("kind", "col-left")
        lay = _box(QVBoxLayout, (14, 12, 14, 12), 10, col)
        self.schedule_row = W.SwitchRow(SCHEDULE_TITLE, SCHEDULE_HINT, title_kind="h3", margins=(0, 0, 0, 0))
        self.schedule_switch = self.schedule_row.switch
        self.schedule_row.toggled.connect(self._on_schedule_toggled)
        lay.addWidget(self.schedule_row)

        self.schedule_box = QWidget()
        on = _box(QVBoxLayout, spacing=10, parent=self.schedule_box)
        self.period = W.Segmented([(p, p) for p in PERIODS], PERIOD_DAILY)
        self.period.changed.connect(self._on_period)
        on.addWidget(self.period)
        when = QWidget()
        when_row = W.FlexRow(when, hgap=14, vgap=8)
        time_box = QWidget()
        time_lay = _box(QHBoxLayout, spacing=8, parent=time_box)
        time_lay.addWidget(W.label("Время", "secondary"))
        self.time_edit = TimeField()
        self.time_edit.timeChanged.connect(self._on_time)
        time_lay.addWidget(self.time_edit)
        when_row.add(time_box)
        self.day_chips = W.DayChips(0)
        self.day_chips.changed.connect(self._on_weekday)
        when_row.add(self.day_chips, min_width=34)
        self.monthday_box = QWidget()
        md_lay = _box(QHBoxLayout, spacing=8, parent=self.monthday_box)
        md_lay.addWidget(W.label("Число", "secondary"))
        self.monthday = W.MonthdayStepper(1)
        self.monthday.changed.connect(self._on_monthday)
        md_lay.addWidget(self.monthday)
        when_row.add(self.monthday_box)
        on.addWidget(when)
        self.month_hint = W.WrapAnywhereLabel(MONTH_HINT, "muted")
        on.addWidget(self.month_hint)
        next_box = QWidget()
        next_lay = _box(QHBoxLayout, spacing=6, parent=next_box)
        next_lay.addWidget(W.IconLabel("calendar", C.OK, 14))
        self.next_label = W.ElidedLabel("", "ok")
        next_lay.addWidget(self.next_label, 1)
        on.addWidget(next_box)
        lay.addWidget(self.schedule_box)
        self.schedule_off_note = W.WrapAnywhereLabel(SCHEDULE_OFF_NOTE, "note")
        lay.addWidget(self.schedule_off_note)
        lay.addStretch(1)
        return col

    def _build_options_column(self) -> QWidget:
        col = QWidget()
        lay = _box(QVBoxLayout, (14 - W.OptionCheck.INSET, 12, 14 - W.OptionCheck.INSET, 12), 4, col)
        title = W.label("Параметры копирования", "h3")
        title.setContentsMargins(W.OptionCheck.INSET, 0, 0, 0)
        lay.addWidget(title)
        lay.addSpacing(4)
        self.contents_option = W.OptionCheck(*OPTION_CONTENTS)
        self.date_folder_option = W.OptionCheck(OPTION_DATE_FOLDER, "")
        self.date_name_option = W.OptionCheck(*OPTION_DATE_NAME)
        for option in (self.contents_option, self.date_folder_option, self.date_name_option):
            option.toggled.connect(self._on_option)
            lay.addWidget(option)
        lay.addStretch(1)
        return col

    # ------------------------------------------------------------ данные
    @property
    def title(self) -> str:
        return tab_name(self.tab)

    @property
    def destination(self) -> str:
        return self.tab.destination

    def bind(self, tab: TabConfig) -> None:
        """Показать вкладку tab (страница меняет этот объект)."""
        switched = tab is not self.tab and getattr(tab, "uid", None) != getattr(self.tab, "uid", None)
        self.tab = tab
        self._loading = True
        try:
            if self.title_edit.text() != tab.title or switched:
                self.title_edit.set_text(tab.title)
            self.period.set_value(tab.period_type if tab.period_type in PERIODS else PERIOD_DAILY)
            moment = QTime.fromString(tab.backup_time, "hh:mm")
            self.time_edit.setTime(moment if moment.isValid() else QTime(9, 0))
            self.day_chips.set_value(max(0, min(6, tab.weekday)))
            self.monthday.set_value(max(1, min(31, tab.monthday)))
            self.contents_option.setChecked(tab.copy_folder_contents, silent=True)
            self.date_folder_option.setChecked(tab.create_backup_folder, silent=True)
            self.date_name_option.setChecked(tab.keep_history, silent=True)
        finally:
            self._loading = False
        if switched:
            self.hide_notice()
        self.refresh_sources()
        self.refresh()

    def to_config(self) -> TabConfig:
        return self.tab

    def refresh_sources(self) -> None:
        """Список источников с подсветкой путей, которые будут пропущены (недоступные, системные)."""
        rows = [("folder", path, self._path_problem(path)) for path in self.tab.folders if path]
        rows += [("file", path, self._path_problem(path)) for path in self.tab.files if path]
        self.source_list.set_sources(rows)
        has = bool(rows)
        self.source_list.setVisible(has)
        self.empty_box.setVisible(not has)
        self.clear_button.setEnabled(has)
        folders = sum(1 for kind, _p, _x in rows if kind == "folder")
        files = len(rows) - folders
        bad = sum(1 for _k, _p, problem in rows if problem)
        if rows:
            parts = []
            if folders:
                parts.append(f"{folders} {plural(folders, 'папка', 'папки', 'папок')}")
            if files:
                parts.append(f"{files} {plural(files, 'файл', 'файла', 'файлов')}")
            summary = ", ".join(parts) + (f" · недоступно: {bad}" if bad else "")
        else:
            summary = "пока ничего не выбрано"
        self.summary_label.setText(summary)

    def _path_problem(self, path: str) -> str:
        if self.validator is None:
            return ""
        return self.validator.path_problem(path) or ""

    def _usable_sources(self) -> List[Tuple[str, str]]:
        rows = self.source_list.rows()
        return [(kind, path) for kind, path, problem in rows if not problem]

    # ------------------------------------------------------------ состояние
    def set_state(self, schedule_on: bool, next_run: Optional[datetime], running: bool, busy: bool,
                  can_delete: bool, now: Optional[datetime] = None) -> None:
        """Показать состояние вкладки: расписание (от сервиса), идет ли копирование."""
        self._schedule_on, self._next_run, self._running = schedule_on, next_run, running
        self._busy, self._can_delete = busy, can_delete
        self._now = now or datetime.now()
        self.refresh()

    def refresh(self) -> None:
        """Обновить все, что зависит от данных вкладки и состояния."""
        tab, now = self.tab, self._now
        name = tab_name(tab)
        problem = tab_problem(tab)
        if self._running:
            self.status_line.set_status("run", TAB_RUNNING_TEXT)
        elif problem:
            self.status_line.set_status("warn", problem)
        elif self._schedule_on and self._next_run is not None:
            self.status_line.set_status("ok", NEXT_RUN_TEXT.format(when=fmt_when(self._next_run, now)))
        else:
            self.status_line.set_status("off", NEXT_RUN_OFF_TAB)
        self.run_button.setEnabled(not getattr(self, "_busy", False) and not problem)
        self.delete_button.setEnabled(getattr(self, "_can_delete", False))
        self.dest_edit.setText(tab.destination)
        self.dest_edit.setToolTip(tab.destination)
        self.dest_edit.setCursorPosition(0)
        self.no_dest_label.setVisible(not tab.destination)
        self.scope_badge.setText(f"действуют только для «{name}»")
        self.schedule_switch.set_checked_silent(self._schedule_on)
        self.schedule_box.setVisible(self._schedule_on)
        self.schedule_off_note.setVisible(not self._schedule_on)
        period = self.period.value()
        self.day_chips.setVisible(period == PERIOD_WEEKLY)
        self.monthday_box.setVisible(period == PERIOD_MONTHLY)
        self.month_hint.setVisible(period == PERIOD_MONTHLY and self.monthday.value() > 28)
        self.next_label.setText(NEXT_RUN_TEXT.format(when=fmt_when(self._next_run, now)) if self._next_run else "")
        self.date_folder_option.set_hint(f"сегодня: «{backup_folder_name(now)}»")
        path, note = preview_texts(tab, now, self._usable_sources())
        self.preview_path.setText(path)
        self.preview_note.setText(note)

    def set_name_preview(self, name: str) -> None:
        """Пока название печатается: обновить надписи с именем вкладки."""
        self.scope_badge.setText(f"действуют только для «{name}»")

    # ------------------------------------------------------------ плашка ошибки
    def show_notice(self, title: str, text: str) -> None:
        self.notice.set_message(title, text)
        self.notice.show()
        self.notice_box.show()

    def hide_notice(self) -> None:
        self.notice_box.hide()

    def notice_visible(self) -> bool:
        return self.notice_box.isVisibleTo(self)

    # ------------------------------------------------------------ правки пользователя
    def _emit_changed(self) -> None:
        if not self._loading:
            self.refresh()
            self.changed.emit()

    def _on_title_edited(self, text: str) -> None:
        self.tab.title = text.strip() or DEFAULT_TAB_TITLE
        self.set_name_preview(tab_name(self.tab))
        self.title_edited.emit(tab_name(self.tab))

    def _on_title_finished(self, text: str) -> None:
        self.tab.title = text.strip() or DEFAULT_TAB_TITLE
        if self.title_edit.text() != self.tab.title and not self.title_edit.line_edit.hasFocus():
            self.title_edit.set_text(self.tab.title)
        self.refresh()
        self.title_committed.emit(self.tab.title)

    def rename(self, title: str) -> None:
        """Переименовать вкладку, как будто пользователь ввел название и нажал Enter."""
        self.title_edit.line_edit.setText(title)
        self.title_edit.line_edit.textEdited.emit(title)
        self.title_edit._finished()

    def _on_schedule_toggled(self, on: bool) -> None:
        # переключатель показывает состояние сервиса: окно включит расписание или вернет его назад
        self.schedule_switch.set_checked_silent(self._schedule_on)
        self.schedule_toggled.emit(on)

    def _on_period(self, period: str) -> None:
        self.tab.period_type = period
        self._emit_changed()

    def _on_time(self, moment: QTime) -> None:
        if self._loading:
            return
        self.tab.backup_time = moment.toString("HH:mm")
        self._emit_changed()

    def _on_weekday(self, index: int) -> None:
        self.tab.weekday = index
        self._emit_changed()

    def _on_monthday(self, value: int) -> None:
        self.tab.monthday = value
        self._emit_changed()

    def _on_option(self, _on: bool) -> None:
        if self._loading:
            return
        self.tab.copy_folder_contents = self.contents_option.isChecked()
        self.tab.create_backup_folder = self.date_folder_option.isChecked()
        self.tab.keep_history = self.date_name_option.isChecked()
        self._emit_changed()

    def _check(self, method: str, path: str) -> Optional[str]:
        if self.validator is None:
            return None
        return getattr(self.validator, method)(path)

    def add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Выберите папку для копирования")
        if path:
            self.add_folder_path(path)

    def add_folder_path(self, path: str) -> bool:
        if not path or path in self.tab.folders:
            return False
        problem = self._check("source_problem", path)
        if problem:
            self.show_notice(FOLDER_REFUSED, problem)
            return False
        self.hide_notice()
        self.tab.folders.append(path)
        self.refresh_sources()
        self._emit_changed()
        return True

    def add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Выберите файлы для копирования")
        if files:
            self.add_file_paths(files)

    def add_file_paths(self, paths: Iterable[str]) -> int:
        existing = set(self.tab.files)
        added, refused = 0, []
        for path in paths:
            if not path or path in existing:
                continue
            problem = self._check("source_problem", path)
            if problem:
                refused.append(problem)
                continue
            self.tab.files.append(path)
            existing.add(path)
            added += 1
        if refused:
            self.show_notice(FILES_REFUSED, "\n".join(refused))
        elif added:
            self.hide_notice()
        if added:
            self.refresh_sources()
            self._emit_changed()
        return added

    def remove_path(self, path: str) -> None:
        if path in self.tab.folders:
            self.tab.folders.remove(path)
        elif path in self.tab.files:
            self.tab.files.remove(path)
        else:
            return
        self.refresh_sources()
        self._emit_changed()

    def clear_sources(self) -> None:
        if not self.tab.folders and not self.tab.files:
            return
        self.tab.folders.clear()
        self.tab.files.clear()
        self.refresh_sources()
        self._emit_changed()

    # прежние имена (списки папок и файлов раньше очищались отдельно)
    def clear_folders(self) -> None:
        if self.tab.folders:
            self.tab.folders.clear()
            self.refresh_sources()
            self._emit_changed()

    def clear_files(self) -> None:
        if self.tab.files:
            self.tab.files.clear()
            self.refresh_sources()
            self._emit_changed()

    def select_destination(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Выберите папку для резервных копий")
        if path:
            self.set_destination(path)

    def set_destination(self, path: str) -> bool:
        problem = self._check("destination_problem", path)
        if problem:
            self.show_notice(DESTINATION_REFUSED, problem)
            return False
        self.hide_notice()
        self.tab.destination = path
        self._emit_changed()
        return True

    def source_tooltips(self) -> List[str]:
        return [self.source_list.tooltip(row) for row in range(self.source_list.model_.rowCount())]


