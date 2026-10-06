"""Панель «История копирования» внизу окна: записи истории бэкенда, новые внизу.

Строка: время (моноширинный), значок итога (✓ ⚠ ✗) и текст цвета итога; подробности (ошибки по
файлам) — ниже с отступом. Фильтр «Только «<Имя>»» оставляет записи выбранной вкладки (по
идентификаторам вкладок в записи). В окне держится не больше HISTORY_VIEW_LIMIT строк.
"""
from typing import List, Optional, Sequence, Tuple

from PyQt5.QtCore import QAbstractListModel, QModelIndex, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFontMetricsF, QTextLayout, QTextOption
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QFrame, QHBoxLayout, QListView, QSizePolicy,
                             QStyledItemDelegate, QVBoxLayout, QWidget)

from ..backend import ICON_ERROR, ICON_OK, ICON_WARNING, HistoryEntry
from . import widgets as W
from .constants import HISTORY_EMPTY_TEXT, HISTORY_FILTER, HISTORY_TITLE, HISTORY_VIEW_LIMIT
from .theme import C, font_exact as font

ICON_COLORS = {ICON_OK: C.OK, ICON_WARNING: C.WARN, ICON_ERROR: C.DANGER}
TIME_FORMAT = "%d.%m.%Y %H:%M"
MAX_LIST_HEIGHT = 150


def split_icon(text: str) -> Tuple[str, str]:
    """«✓ Успешно…» → («✓», «Успешно…»); без значка — («», текст)."""
    for icon in ICON_COLORS:
        if text.startswith(icon + " "):
            return icon, text[len(icon) + 1:]
        if text == icon:
            return icon, ""
    return "", text


class HistoryModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: List[HistoryEntry] = []

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.entries)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        entry = self.entries[index.row()]
        if role in (Qt.DisplayRole, Qt.AccessibleTextRole):
            return "\n".join(entry.lines())
        if role == Qt.UserRole:
            return entry
        return None

    def set_entries(self, entries: Sequence[HistoryEntry]) -> None:
        self.beginResetModel()
        self.entries = list(entries)
        self.endResetModel()

    def append(self, entry: HistoryEntry) -> None:
        row = len(self.entries)
        self.beginInsertRows(QModelIndex(), row, row)
        self.entries.append(entry)
        self.endInsertRows()

    def drop_first(self, count: int) -> None:
        if count <= 0:
            return
        self.beginRemoveRows(QModelIndex(), 0, count - 1)
        del self.entries[:count]
        self.endRemoveRows()


class HistoryDelegate(QStyledItemDelegate):
    """Рисует запись: поля 3px 14px, время 116 px, значок 14 px, текст и подробности с переносом."""

    PAD_X, PAD_Y = 14, 3
    TIME_W, ICON_W, GAP = 116, 14, 10
    TEXT_X = PAD_X + TIME_W + GAP + ICON_W + GAP      # 164: и текст, и подробности (margin-left 150)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = {}

    def clear_cache(self) -> None:
        self._cache = {}

    @staticmethod
    def _layout(text: str, px: float, role: str, width: float) -> Tuple[QTextLayout, float]:
        f = font(role, px)
        layout = QTextLayout(text, f)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        metrics = QFontMetricsF(f)
        step = max(metrics.height(), px * 1.4)
        lead = (step - metrics.height()) / 2
        layout.beginLayout()
        y = 0.0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1.0, width))
            line.setPosition(QPointF(0, y + lead))
            y += step
        layout.endLayout()
        return layout, max(y, step)

    def _parts(self, entry: HistoryEntry, width: int):
        key = (id(entry), width)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        icon, text = split_icon(entry.text)
        text_w = max(40, width - self.TEXT_X - self.PAD_X)
        head, head_h = self._layout(text, 12.5, "regular", text_w)
        details = [self._layout(detail, 12, "regular", text_w) for detail in entry.details]
        height = self.PAD_Y * 2 + head_h + sum(h for _l, h in details)
        result = (icon, head, head_h, details, int(height + 0.5))
        if len(self._cache) > 20000:
            self._cache = {}
        self._cache[key] = result
        return result

    def sizeHint(self, option, index):  # noqa: N802
        entry = index.data(Qt.UserRole)
        width = option.rect.width() or 600
        return QSize(width, self._parts(entry, width)[4])

    def paint(self, p, option, index):
        entry = index.data(Qt.UserRole)
        r = option.rect
        icon, head, head_h, details, _height = self._parts(entry, r.width())
        color = QColor(ICON_COLORS.get(icon, C.TEXT2))
        p.save()
        top = r.top() + self.PAD_Y
        line_h = 12.5 * 1.4
        p.setFont(font("mono", 11.5))
        p.setPen(QColor(C.MUTED))
        p.drawText(QRectF(r.left() + self.PAD_X, top + 0.5, self.TIME_W, line_h), Qt.AlignLeft | Qt.AlignVCenter,
                   entry.time.strftime(TIME_FORMAT))
        if icon:
            p.setFont(font("semibold", 12.5))
            p.setPen(color)
            p.drawText(QRectF(r.left() + self.PAD_X + self.TIME_W + self.GAP, top, self.ICON_W, line_h),
                       Qt.AlignCenter, icon)
        p.setPen(color)
        head.draw(p, QPointF(r.left() + self.TEXT_X, top))
        y = top + head_h
        p.setPen(QColor(C.MUTED))
        for layout, height in details:
            layout.draw(p, QPointF(r.left() + self.TEXT_X, y))
            y += height
        p.restore()


class HistoryView(QListView):
    """Список записей: высота по содержимому, не больше 150 px, прокрутка к последней записи."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_ = HistoryModel(self)
        self.setModel(self.model_)
        self.delegate = HistoryDelegate(self)
        self.setItemDelegate(self.delegate)
        self.setFrameShape(QFrame.NoFrame)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setResizeMode(QListView.Adjust)
        self.setViewportMargins(0, 4, 0, 4)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.verticalScrollBar().setSingleStep(20)
        self._width = 0

    def content_height(self, limit: int = MAX_LIST_HEIGHT) -> int:
        """Высота записей (с конца), пока не превысит limit."""
        width = self.viewport().width() or self.width() or 600
        total = 0
        for entry in reversed(self.model_.entries):
            total += self.delegate._parts(entry, width)[4]
            if total >= limit:
                break
        return total

    def fit_height(self) -> None:
        self.setFixedHeight(min(MAX_LIST_HEIGHT, self.content_height() + 8))

    def scroll_to_end(self) -> None:
        self.scrollToBottom()
        QTimer.singleShot(0, self.scrollToBottom)

    def resizeEvent(self, event):  # noqa: N802
        if self.viewport().width() != self._width:
            self._width = self.viewport().width()
            self.delegate.clear_cache()
            self.scheduleDelayedItemsLayout()
        super().resizeEvent(event)
        self.fit_height()


class FilterCheck(QWidget):
    """Флажок фильтра с подписью, обрезаемой «…» (max-width 280 px), как в макете."""

    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.checkbox = QCheckBox()
        self.checkbox.setFocusPolicy(Qt.TabFocus)
        self.checkbox.setProperty("kind", "filter")
        self.text_label = W.ElidedLabel("", "secondary")
        self.text_label.setMaximumWidth(280)
        self.text_label.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.checkbox)
        lay.addWidget(self.text_label, 1)
        self.checkbox.toggled.connect(self.toggled)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def setText(self, text: str) -> None:  # noqa: N802
        self.text_label.setText(text)
        self.checkbox.setAccessibleName(text)

    def text(self) -> str:
        return self.text_label.text()

    def isChecked(self) -> bool:  # noqa: N802
        return self.checkbox.isChecked()

    def setChecked(self, on: bool) -> None:  # noqa: N802
        self.checkbox.setChecked(on)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self.text_label.geometry().contains(event.pos()):
            self.checkbox.toggle()
        super().mouseReleaseEvent(event)


class HistoryPanel(QFrame):
    """Панель истории. journal_requested — кнопка «Открыть подробный журнал»."""

    journal_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("kind", "panel")
        self._all: List[HistoryEntry] = []
        self._tab_uid: Optional[str] = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = QWidget()
        row = W.FlexRow(header, hgap=10, vgap=8)
        row.setContentsMargins(14, 8, 14, 8)
        row.add(W.label(HISTORY_TITLE, "h3"))
        self.filter_check = FilterCheck()
        self.filter_check.toggled.connect(self._refilter)
        row.add(self.filter_check, min_width=0)
        row.add_spacer()
        self.journal_button = W.Button("Открыть подробный журнал", "ghost", small=True)
        self.journal_button.clicked.connect(self.journal_requested)
        row.add(self.journal_button)
        root.addWidget(header)
        root.addWidget(W.hline())
        self.view = HistoryView()
        root.addWidget(self.view)
        empty = QWidget()
        e_lay = QVBoxLayout(empty)
        e_lay.setContentsMargins(14, 10, 14, 10)
        e_lay.addWidget(W.label(HISTORY_EMPTY_TEXT, "secondary-muted"))
        self.empty_box = empty
        root.addWidget(empty)
        self._update_empty()

    # ------------------------------------------------------------ данные
    def set_entries(self, entries: Sequence[HistoryEntry]) -> None:
        """Вся история (от старых записей к новым)."""
        self._all = list(entries)
        self._refilter()

    def add_entry(self, entry: HistoryEntry) -> None:
        self._all.append(entry)
        if self._matches(entry):
            self.view.model_.append(entry)
            self._trim()
            self._update_empty()
            self.view.scroll_to_end()
        self._trim_all()

    def set_tab(self, uid: Optional[str], name: str) -> None:
        """Вкладка фильтра «Только «Имя»»."""
        self.filter_check.setText(HISTORY_FILTER.format(name=name))
        if uid != self._tab_uid:
            self._tab_uid = uid
            if self.filter_check.isChecked():
                self._refilter()

    def total_count(self) -> int:
        return len(self._all)

    def visible_entries(self) -> List[HistoryEntry]:
        return list(self.view.model_.entries)

    def plain_text(self) -> str:
        """Показанные строки, как в файле истории (без вкладок)."""
        return "\n".join(line for entry in self.view.model_.entries for line in entry.lines())

    def only_tab(self) -> bool:
        return self.filter_check.isChecked()

    def set_only_tab(self, on: bool) -> None:
        self.filter_check.setChecked(on)

    # ------------------------------------------------------------ внутреннее
    def _matches(self, entry: HistoryEntry) -> bool:
        return not self.filter_check.isChecked() or (self._tab_uid is not None and self._tab_uid in entry.tab_ids)

    def _refilter(self, *_args) -> None:
        shown = [entry for entry in self._all if self._matches(entry)]
        self.view.delegate.clear_cache()
        self.view.model_.set_entries(self._limited(shown))
        self._update_empty()
        self.view.scroll_to_end()

    @staticmethod
    def _limited(entries: List[HistoryEntry]) -> List[HistoryEntry]:
        total, start = 0, len(entries)
        while start > 0:
            lines = 1 + len(entries[start - 1].details)
            if total + lines > HISTORY_VIEW_LIMIT:
                break
            total += lines
            start -= 1
        return entries[start:]

    def _trim(self) -> None:
        entries = self.view.model_.entries
        total = sum(1 + len(entry.details) for entry in entries)
        drop = 0
        while total > HISTORY_VIEW_LIMIT and drop < len(entries) - 1:
            total -= 1 + len(entries[drop].details)
            drop += 1
        self.view.model_.drop_first(drop)

    def _trim_all(self) -> None:
        # полная история в памяти тоже ограничена: старые записи не нужны ни фильтру, ни окну
        if len(self._all) > HISTORY_VIEW_LIMIT * 2:
            del self._all[:len(self._all) - HISTORY_VIEW_LIMIT]

    def _update_empty(self) -> None:
        has = bool(self.view.model_.entries)
        self.view.setVisible(has)
        self.empty_box.setVisible(not has)
        if has:
            self.view.fit_height()
