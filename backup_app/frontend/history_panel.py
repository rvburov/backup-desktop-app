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
RELAYOUT_MS = 120   # пауза после изменения ширины, после которой строки истории перекладываются


def split_icon(text: str) -> Tuple[str, str]:
    """«✓ Успешно…» → («✓», «Успешно…»); без значка — («», текст)."""
    for icon in ICON_COLORS:
        if text.startswith(icon + " "):
            return icon, text[len(icon) + 1:]
        if text == icon:
            return icon, ""
    return "", text


class HistoryModel(QAbstractListModel):
    """Записи истории. revision растет при каждом изменении набора строк (ключ кэша высот строк)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: List[HistoryEntry] = []
        self.revision = 0

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
        self.revision += 1
        self.endResetModel()

    def append(self, entry: HistoryEntry) -> None:
        row = len(self.entries)
        self.beginInsertRows(QModelIndex(), row, row)
        self.entries.append(entry)
        self.revision += 1
        self.endInsertRows()

    def drop_first(self, count: int) -> None:
        if count <= 0:
            return
        self.beginRemoveRows(QModelIndex(), 0, count - 1)
        del self.entries[:count]
        self.revision += 1
        self.endRemoveRows()


class HistoryDelegate(QStyledItemDelegate):
    """Рисует запись: поля 3px 14px, время 116 px, значок 14 px, текст и подробности с переносом.

    Высоты строк дробные, как в браузере (однострочная — 3 + 12.5 × 1.4 + 3 = 23.5 px): края строк —
    округленные точные края строк макета от начала списка (как у списка вкладок), строки по 23 и 24 px.
    Прокрутка в браузере целая, поэтому и у прокрученного к концу списка строки стоят как в макете.

    Кэши ключуются самой записью (HistoryEntry неизменяема и сравнивается по значению), а не id():
    после удаления старых записей id может достаться новой записи. Высота строки, которая
    помещается без переноса, считается по ширине текста без раскладки: при изменении ширины окна
    раскладка (QTextLayout) нужна только длинным записям и видимым строкам.
    """

    PAD_X, PAD_Y = 14, 3
    TIME_W, ICON_W, GAP = 116, 14, 10
    TEXT_X = PAD_X + TIME_W + GAP + ICON_W + GAP      # 164: и текст, и подробности (margin-left 150)
    HEAD_PX, DETAIL_PX = 12.5, 12
    CACHE_LIMIT = 40000
    LAYOUT_LIMIT = 400

    def __init__(self, parent=None):
        super().__init__(parent)
        self._natural = {}   # запись → (значок, текст, ширина текста, ширины подробностей): от ширины не зависит
        self._heights = {}   # (запись, ширина) → точная (дробная) высота строки
        self._layouts = {}   # (запись, ширина) → раскладка для рисования (только видимые строки)
        self._steps = None
        self._tops = None    # ((ширина, ревизия модели, строк), округленные верхи строк)

    def clear_cache(self) -> None:
        """Забыть высоты и раскладки (ширина изменилась)."""
        self._heights = {}
        self._layouts = {}
        self._tops = None

    def forget(self) -> None:
        """Забыть все (новый набор записей)."""
        self.clear_cache()
        self._natural = {}

    def _line_steps(self) -> Tuple[float, float]:
        if self._steps is None:
            self._steps = tuple(max(QFontMetricsF(font("regular", px)).height(), px * 1.4)
                                for px in (self.HEAD_PX, self.DETAIL_PX))
        return self._steps

    @staticmethod
    def _layout(text: str, px: float, role: str, width: float) -> Tuple[QTextLayout, float]:
        f = font(role, px)
        layout = QTextLayout(text, f)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        metrics = QFontMetricsF(f)
        step = max(metrics.height(), px * 1.4)
        lead = W.half_leading(step, metrics.height())   # как в Chromium: целые px, округление вниз
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

    def _natural_widths(self, entry: HistoryEntry):
        cached = self._natural.get(entry)
        if cached is None:
            icon, text = split_icon(entry.text)
            head = QFontMetricsF(font("regular", self.HEAD_PX)).horizontalAdvance(text)
            detail = QFontMetricsF(font("regular", self.DETAIL_PX))
            cached = (icon, text, head, tuple(detail.horizontalAdvance(d) for d in entry.details))
            if len(self._natural) > self.CACHE_LIMIT:
                self._natural = {}
            self._natural[entry] = cached
        return cached

    def _text_width(self, width: int) -> int:
        return max(40, width - self.TEXT_X - self.PAD_X)

    def entry_height(self, entry: HistoryEntry, width: int) -> float:
        """Точная высота строки записи в макете (дробная: 23.5 px у однострочной)."""
        key = (entry, width)
        height = self._heights.get(key)
        if height is None:
            _icon, _text, head_w, detail_ws = self._natural_widths(entry)
            text_w = self._text_width(width) - 1
            if head_w <= text_w and all(w <= text_w for w in detail_ws):
                head_step, detail_step = self._line_steps()   # все в одну строку: раскладка не нужна
                height = self.PAD_Y * 2 + head_step + detail_step * len(detail_ws)
            else:
                height = self._parts(entry, width)[4]
            if len(self._heights) > self.CACHE_LIMIT:
                self._heights = {}
            self._heights[key] = height
        return height

    def tops(self, model: "HistoryModel", width: int) -> List[int]:
        """Верхи строк от начала списка: округленные суммы точных высот (длина — строк + 1, последний — низ)."""
        key = (width, model.revision, len(model.entries))
        if self._tops is None or self._tops[0] != key:
            tops, total = [0], 0.0
            for entry in model.entries:
                total += self.entry_height(entry, width)
                tops.append(int(total + 0.5))
            self._tops = (key, tops)
        return self._tops[1]

    def row_height(self, model: "HistoryModel", row: int, width: int) -> int:
        """Высота строки row в пикселях (23 или 24 у однострочных, см. tops)."""
        tops = self.tops(model, width)
        return tops[row + 1] - tops[row]

    def _parts(self, entry: HistoryEntry, width: int):
        key = (entry, width)
        cached = self._layouts.get(key)
        if cached is not None:
            return cached
        icon, text, _head_w, _detail_ws = self._natural_widths(entry)
        text_w = self._text_width(width)
        head, head_h = self._layout(text, self.HEAD_PX, "regular", text_w)
        details = [self._layout(detail, self.DETAIL_PX, "regular", text_w) for detail in entry.details]
        height = self.PAD_Y * 2 + head_h + sum(h for _l, h in details)
        result = (icon, head, head_h, details, height)
        if len(self._layouts) > self.LAYOUT_LIMIT:
            self._layouts = {}
        self._layouts[key] = result
        return result

    def sizeHint(self, option, index):  # noqa: N802
        width = option.rect.width() or 600
        model = index.model()
        if isinstance(model, HistoryModel) and 0 <= index.row() < len(model.entries):
            return QSize(width, self.row_height(model, index.row(), width))
        return QSize(width, int(self.entry_height(index.data(Qt.UserRole), width) + 0.5))

    def paint(self, p, option, index):
        entry = index.data(Qt.UserRole)
        r = option.rect
        icon, head, head_h, details, _height = self._parts(entry, r.width())
        color = QColor(ICON_COLORS.get(icon, C.TEXT2))
        p.save()
        p.setClipRect(r)  # пока ширина меняется, высота строки может отставать от раскладки
        top = r.top() + self.PAD_Y   # текст — от округленного верха строки (как и в браузере)
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
        self.setViewportMargins(0, 4, 0, 4)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.verticalScrollBar().setSingleStep(20)
        self._width = 0
        # пока ширину тянут мышью, строки не перекладываются на каждом шаге: высоты всех записей
        # пересчитываются один раз, когда ширина перестала меняться
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(RELAYOUT_MS)
        self._relayout_timer.timeout.connect(self._relayout)

    def content_height(self, limit: int = MAX_LIST_HEIGHT) -> int:
        """Высота записей (с конца), пока не превысит limit."""
        width = self.viewport().width() or self.width() or 600
        tops = self.delegate.tops(self.model_, width)
        bottom = tops[-1]
        for top in reversed(tops):
            if bottom - top >= limit:
                return bottom - top
        return bottom

    def fit_height(self) -> None:
        self.setFixedHeight(min(MAX_LIST_HEIGHT, self.content_height() + 8))

    def scroll_to_end(self) -> None:
        self.scrollToBottom()
        QTimer.singleShot(0, self.scrollToBottom)

    def _relayout(self) -> None:
        self.delegate.clear_cache()
        self.scheduleDelayedItemsLayout()
        self.fit_height()

    def resizeEvent(self, event):  # noqa: N802
        width = self.viewport().width()
        if width != self._width:
            first = self._width == 0
            self._width = width
            if first:
                self._relayout()
            else:
                self._relayout_timer.start()
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
        self.empty_label = W.label(HISTORY_EMPTY_TEXT, "secondary-muted")
        e_lay.addWidget(self.empty_label)
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
        self.view.delegate.forget()
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
