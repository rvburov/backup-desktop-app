"""Готовые элементы интерфейса в стиле макета. Окно собирается из них (см. docs/UI_DESIGN.md).

Виджеты не знают о бэкенде: получают тексты и состояния, сообщают о действиях сигналами.
Цвета и шрифты — из theme.py, иконки — из icons.py.
"""
import html
import math
import struct
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

from PyQt5.QtCore import (QElapsedTimer, QEasingCurve, QEvent, QEventLoop, QModelIndex, QPoint, QPointF,
                          QPropertyAnimation, QRect, QRectF, QSize, QSortFilterProxyModel, Qt, QTimer,
                          pyqtProperty, pyqtSignal)
from PyQt5.QtGui import (QColor, QFont, QFontMetrics, QFontMetricsF, QIcon, QPainter, QPainterPath, QPalette, QPen,
                         QRadialGradient, QRawFont, QStandardItem, QStandardItemModel, QTextCharFormat, QTextLayout,
                         QTextOption)
from PyQt5 import sip
from PyQt5.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QFrame,
                             QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLayout, QLineEdit, QListView,
                             QProgressBar, QPushButton, QSizePolicy, QSpacerItem, QSplitter, QSplitterHandle, QStyle,
                             QStyledItemDelegate, QStyleOptionButton, QStyleOptionFrame, QStylePainter, QVBoxLayout,
                             QWidget, QWidgetItem)

from . import icons
from .theme import (BUTTON_HEIGHT, BUTTON_HEIGHT_SMALL, C, exact, faded, font, font_exact, has_keyboard_focus,
                    keyboard_focus_reason, mix, px_to_pt, set_props)

DAY_SHORT = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
DAY_FULL = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")

# Ширина списка вкладок (как в макете: SIDE_MIN, SIDE_MAX, SIDE_DEFAULT) и минимум рабочей области.
SIDE_MIN, SIDE_MAX, SIDE_DEFAULT = 180, 440, 240
MAIN_MIN = 380

# Цвет иконки кнопки = цвет ее текста (currentColor в макете).
_VARIANT_ICON = {
    None: C.TEXT, "default": C.TEXT, "primary": C.WHITE, "ghost": C.TEXT2, "link": C.ACCENT,
    "danger": C.DANGER, "danger-solid": C.WHITE, "nav": C.TEXT2, "stepper": C.TEXT2,
    "toast-close": C.TOAST_TEXT, "notice-close": C.NOTICE_TEXT,
}


# =========================================================================== мелкие помощники
def label(text: str = "", kind: Optional[str] = None, wrap: bool = False, parent=None) -> QLabel:
    """QLabel с видом из QSS (kind: h1, h2, h3, medium, muted, secondary, warn, ok, mono, note, ...).

    Текст всегда обычный (PlainText): имена вкладок и пути не должны разбираться как HTML.
    """
    w = _Label(text, parent)
    w.setTextFormat(Qt.PlainText)
    if kind:
        w.setProperty("kind", kind)
    if wrap:
        w.setWordWrap(True)
    return w


def elided(metrics, text: str, width: float) -> str:
    """Текст, сокращенный справа до width px с «…», как text-overflow: ellipsis в макете.

    Qt оставляет пробел перед «…» («Очень длинное название …»), макет — нет: пробелы в конце
    обрезанной части убираются («Очень длинное название…»). metrics — QFontMetrics или QFontMetricsF.
    """
    shown = metrics.elidedText(text, Qt.ElideRight, width)
    if shown != text and shown.endswith("…"):
        shown = shown[:-1].rstrip() + "…"
    return shown


def half_leading(line_height: float, font_height: float) -> int:
    """Отступ текста от верха строки высотой line_height, как в Chromium (LayoutNG): половина разницы
    высоты строки и шрифта, округленная ВНИЗ до целых px (у 12px: (16.8 − 15) / 2 = 0.9 → 0)."""
    return max(0, math.floor((line_height - font_height) / 2 + 1e-6))


def exact_width_delta(f: QFont, text: str) -> int:
    """На сколько px текст шрифта f (дробный размер, Qt5 рисует его целым) шире, чем в макете.

    Стиль приложения рисует такой текст шрифтом exact(f) (AppStyle.drawItemText); размеры виджетов
    Qt считает по округленному шрифту — их уменьшаем на эту разницу.
    """
    e = exact(f)
    if e is f or not text:
        return 0
    return max(0, QFontMetrics(f).horizontalAdvance(text) - math.ceil(QFontMetricsF(e).horizontalAdvance(text)))


class _Label(QLabel):
    """QLabel, ширина которого с дробным размером шрифта — как у текста в макете (см. exact_width_delta)."""

    def sizeHint(self):  # noqa: N802
        hint = super().sizeHint()
        if not self.wordWrap():
            hint.setWidth(hint.width() - exact_width_delta(self.font(), self.text()))
        return hint

    def minimumSizeHint(self):  # noqa: N802
        hint = super().minimumSizeHint()
        if not self.wordWrap():
            hint.setWidth(hint.width() - exact_width_delta(self.font(), self.text()))
        return hint


def hline(kind: str = "divider") -> QFrame:
    """Горизонтальный разделитель 1px (#EEF1F5; kind="side-divider" — #D6DCE4 для боковой панели)."""
    f = QFrame()
    f.setProperty("kind", kind)
    f.setFixedHeight(1)
    return f


def vline() -> QFrame:
    """Вертикальный разделитель 1px между колонками карточки."""
    f = QFrame()
    f.setProperty("kind", "vdivider")
    f.setFixedWidth(1)
    return f


class IconLabel(QLabel):
    """Иконка из icons.py в QLabel фиксированного размера."""

    def __init__(self, name: str, color: str = C.TEXT2, size: int = 16, stroke: Optional[float] = None,
                 parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.set_icon(name, color, stroke)

    def set_icon(self, name: str, color: str = C.TEXT2, stroke: Optional[float] = None) -> None:
        self.icon_name, self.icon_color = name, color
        self.setPixmap(icons.pix(name, color, self._size, stroke))


class CapsLabel(QLabel):
    """Подпись капителью: 11px/600, разрядка .06em, верхний регистр («ВКЛАДКИ»)."""

    def __init__(self, text: str = "", parent=None, letter_spacing_em: float = 0.06):
        super().__init__(parent)
        self.setTextFormat(Qt.PlainText)
        self.setProperty("kind", "caps")
        self._em = letter_spacing_em
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - имя из Qt
        super().setText(text.upper())

    def changeEvent(self, event):  # noqa: N802
        if event.type() == QEvent.FontChange:
            f = self.font()
            px = f.pixelSize() if f.pixelSize() > 0 else f.pointSizeF() / px_to_pt(1)
            spacing = px * self._em
            if abs(f.letterSpacing() - spacing) > 0.01:
                f.setLetterSpacing(f.AbsoluteSpacing, spacing)
                self.setFont(f)
        super().changeEvent(event)


class FlowLayout(QLayout):
    """Раскладка «в строку с переносом» (flex-wrap макета): элементы переносятся, когда не помещаются."""

    def __init__(self, parent=None, hspacing: int = 8, vspacing: int = 8):
        super().__init__(parent)
        self._items: List = []
        self._h, self._v = hspacing, vspacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def addWidget(self, widget):  # noqa: N802
        self.addChildWidget(widget)
        self.addItem(QWidgetItem(widget))

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = area.x(), area.y(), 0
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and line_h > 0:
                x, y = area.x(), y + line_h + self._v
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._h
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


class _FlexProps(NamedTuple):
    basis: Optional[int]       # None — по ширине содержимого (flex-basis: auto)
    grow: float
    shrink: float
    min_width: Optional[int]   # None — минимальная ширина виджета (min-width: auto)
    max_width: Optional[int]
    align: Optional[str]


class FlexRow(QLayout):
    """Строка с переносом по правилам CSS flex-wrap: у каждого элемента basis/grow/shrink/min-width.

    Элементы раскладываются по строкам: элемент, который не помещается, начинает новую строку;
    в каждой строке лишняя ширина делится по grow, нехватка — по shrink × basis (не меньше min-width).
    align: center (align-items: center), start или stretch — по высоте строки.

        row = FlexRow(widget, hgap=8, vgap=8)
        row.add(title_block, basis=280, grow=1, min_width=0)
        row.add_spacer()                  # <div style="flex: 1">
        row.add(button)
    """

    def __init__(self, parent=None, hgap: int = 8, vgap: int = 8, align: str = "center"):
        super().__init__(parent)
        self._items: List[Tuple[object, _FlexProps]] = []
        self._h, self._v, self._align = hgap, vgap, align
        self._cache: dict = {}
        self.setContentsMargins(0, 0, 0, 0)

    # --- наполнение
    def add(self, widget: QWidget, basis: Optional[int] = None, grow: float = 0, shrink: float = 1,
            min_width: Optional[int] = None, max_width: Optional[int] = None, align: Optional[str] = None) -> QWidget:
        self.addChildWidget(widget)
        self._items.append((QWidgetItem(widget), _FlexProps(basis, grow, shrink, min_width, max_width, align)))
        self.invalidate()
        return widget

    def add_spacer(self, grow: float = 1) -> None:
        """Растяжка flex: 1 (ширина 0, забирает свободное место строки)."""
        self._items.append((QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum),
                            _FlexProps(0, grow, 1, 0, None, None)))
        self.invalidate()

    def addItem(self, item):  # noqa: N802
        self._items.append((item, _FlexProps(None, 0, 1, None, None, None)))

    def addWidget(self, widget):  # noqa: N802
        self.add(widget)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        return self._items[index][0] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802
        if 0 <= index < len(self._items):
            item = self._items.pop(index)[0]
            self.invalidate()
            return item
        return None

    def invalidate(self):
        self._cache = {}
        super().invalidate()

    def expandingDirections(self):  # noqa: N802
        return Qt.Horizontal

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        m = self.contentsMargins()
        return self._solve(width - m.left() - m.right())[1] + m.top() + m.bottom()

    def sizeHint(self):  # noqa: N802
        m = self.contentsMargins()
        visible = self._visible()
        width = sum(self._hint_width(item, p) for item, p in visible) + self._h * max(0, len(visible) - 1)
        return QSize(width + m.left() + m.right(), self.heightForWidth(width + m.left() + m.right()))

    def minimumSize(self):  # noqa: N802
        m = self.contentsMargins()
        width, height = 0, 0
        for item, p in self._visible():
            width = max(width, self._min_width(item, p))
            height = max(height, item.minimumSize().height())
        return QSize(width + m.left() + m.right(), height + m.top() + m.bottom())

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        places, _height = self._solve(area.width())
        for item, (x, y, w, h) in places:
            item.setGeometry(QRect(area.x() + x, area.y() + y, w, h))

    # --- расчет
    def _visible(self):
        """Показанные элементы; растяжка (QSpacerItem) Qt считает пустой, но она участвует в раскладке."""
        return [(item, p) for item, p in self._items if isinstance(item, QSpacerItem) or not item.isEmpty()]

    @staticmethod
    def _min_width(item, p: _FlexProps) -> int:
        if p.min_width is not None:
            return p.min_width
        return item.minimumSize().width() if item.widget() is not None else 0

    def _hint_width(self, item, p: _FlexProps) -> int:
        base = p.basis if p.basis is not None else item.sizeHint().width()
        top = p.max_width if p.max_width is not None else item.maximumSize().width()
        return max(self._min_width(item, p), min(base, top))

    def _height(self, item, width: int) -> int:
        if item.hasHeightForWidth():
            h = item.heightForWidth(width)
        else:
            h = item.sizeHint().height()
        return max(item.minimumSize().height(), min(h, item.maximumSize().height()))

    def _solve(self, width: int):
        """Места элементов [(item, (x, y, w, h))] и общая высота для ширины width."""
        width = max(0, int(width))
        cached = self._cache.get(width)
        if cached is not None:
            return cached
        visible = self._visible()
        lines, line, used = [], [], 0
        for item, p in visible:
            size = self._hint_width(item, p)
            extra = size + (self._h if line else 0)
            if line and used + extra > width:
                lines.append(line)
                line, used, extra = [], 0, size
            line.append([item, p, size])
            used += extra
        if line:
            lines.append(line)
        places, y = [], 0
        for index, line in enumerate(lines):
            self._resolve(line, width)
            x, heights = 0, []
            for item, _p, size in line:
                heights.append(self._height(item, size))
            line_h = max(heights) if heights else 0
            for (item, p, size), h in zip(line, heights):
                align = p.align or self._align
                if align == "stretch":
                    h = max(h, min(line_h, item.maximumSize().height()))
                    top = 0
                elif align == "start":
                    top = 0
                else:
                    top = (line_h - h) // 2
                places.append((item, (x, y + top, size, h)))
                x += size + self._h
            y += line_h + (self._v if index < len(lines) - 1 else 0)
        result = (places, y)
        self._cache[width] = result
        return result

    def _resolve(self, line, width: int) -> None:
        """Ширины элементов строки: свободное место по grow, нехватка — по shrink × basis."""
        gaps = self._h * (len(line) - 1)
        for _ in range(3):  # повторы — когда элементы упираются в min/max
            free = width - gaps - sum(entry[2] for entry in line)
            if free > 0:
                growing = [e for e in line if e[1].grow > 0 and e[2] < self._max(e)]
                total = sum(e[1].grow for e in growing)
                if not growing or total <= 0:
                    return
                rest = free
                for e in growing:
                    add = int(free * e[1].grow / total) if e is not growing[-1] else rest
                    new = min(self._max(e), e[2] + add)
                    rest -= new - e[2]
                    e[2] = new
                if rest <= 0:
                    return
            elif free < 0:
                shrinking = [e for e in line if e[1].shrink > 0 and e[2] > self._min_width(e[0], e[1])]
                total = sum(e[1].shrink * max(1, e[2]) for e in shrinking)
                if not shrinking or total <= 0:
                    return
                need = -free
                for e in shrinking:
                    cut = math.ceil(need * e[1].shrink * max(1, e[2]) / total)
                    e[2] = max(self._min_width(e[0], e[1]), e[2] - cut)
                if width - gaps - sum(entry[2] for entry in line) >= 0:
                    return
            else:
                return

    @staticmethod
    def _max(entry) -> int:
        item, p, _size = entry
        top = item.maximumSize().width()
        return min(top, p.max_width) if p.max_width is not None else top


# =========================================================================== текст
class ElidedLabel(QLabel):
    """Однострочная надпись с «…», если не помещается (text-overflow: ellipsis)."""

    def __init__(self, text: str = "", kind: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.PlainText)
        if kind:
            self.setProperty("kind", kind)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        self.updateGeometry()
        self.update()

    def _metrics(self) -> QFontMetrics:
        # Qt5 округляет дробный размер шрифта (12.5px → 13px): ширина текста — как у дробного размера макета
        return QFontMetrics(exact(self.font()))

    def is_elided(self) -> bool:
        width = self.contentsRect().width()
        return self._metrics().horizontalAdvance(self.text()) > width

    def elided_text(self) -> str:
        return elided(self._metrics(), self.text(), max(0, self.contentsRect().width()))

    def sizeHint(self):  # noqa: N802
        # ширина — текст (как у дробного размера макета) плюс поля QSS, без запаса, который добавляет QLabel
        self.ensurePolished()
        hint = super().sizeHint()
        if not self.text():
            return hint
        frame = self.width() - self.contentsRect().width()
        return QSize(frame + math.ceil(QFontMetricsF(exact(self.font())).horizontalAdvance(self.text())) + 1,
                     hint.height())

    def minimumSizeHint(self):  # noqa: N802
        hint = super().minimumSizeHint()
        margins = self.width() - self.contentsRect().width() if self.width() else 0
        return QSize(min(hint.width(), self._metrics().horizontalAdvance("…") + margins + 8), hint.height())

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        self.drawFrame(painter)
        painter.setFont(exact(self.font()))
        rect = self.contentsRect()
        self.style().drawItemText(painter, rect, int(self.alignment()) | Qt.TextSingleLine, self.palette(),
                                  self.isEnabled(), self.elided_text(), self.foregroundRole())


class Badge(ElidedLabel):
    """«Таблетка»: kind="badge" (11.5px/500, «действуют только для …») или "pill" (12px, строка состояния)."""

    def __init__(self, text: str = "", kind: str = "badge", max_width: Optional[int] = None, parent=None):
        super().__init__(text, kind, parent)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setMaximumWidth(max_width or (260 if kind == "badge" else 360))


Pill = Badge


class WrapAnywhereLabel(QFrame):
    """Многострочный текст с переносом где угодно (overflow-wrap: anywhere) и межстрочным 1.4, как в макете.

    QLabel переносит только по словам, и длинный путь без пробелов обрезается. bold_prefix рисуется
    полужирным в начале (так в плашке ошибки: «Заголовок. текст»).
    """

    def __init__(self, text: str = "", kind: Optional[str] = None, parent=None, line_height: float = 1.4,
                 bold_prefix: str = ""):
        super().__init__(parent)
        if kind:
            self.setProperty("kind", kind)
        self._text, self._bold = "", ""
        self._align = Qt.AlignLeft
        self._line_height = line_height
        policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.set_text(text, bold_prefix)

    def text(self) -> str:
        return self._bold + self._text

    def setText(self, text: str) -> None:  # noqa: N802
        self.set_text(text)

    def set_alignment(self, alignment) -> None:
        """Выравнивание строк: Qt.AlignLeft (по умолчанию) или Qt.AlignHCenter (text-align: center)."""
        self._align = alignment
        self.update()

    def set_text(self, text: str, bold_prefix: str = "") -> None:
        self._text, self._bold = text, bold_prefix
        self.updateGeometry()
        self.update()

    def _margins(self) -> Tuple[int, int]:
        r = self.contentsRect()
        return self.width() - r.width(), self.height() - r.height()

    def _layout(self, width: float) -> Tuple[QTextLayout, float]:
        full = self._bold + self._text
        layout = QTextLayout(full, exact(self.font()))
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        option.setAlignment(self._align)
        layout.setTextOption(option)
        if self._bold:
            fmt = QTextCharFormat()
            bold = font("semibold")
            fmt.setFontFamily(bold.family())
            fmt.setFontWeight(bold.weight())
            rng = QTextLayout.FormatRange()
            rng.start, rng.length, rng.format = 0, len(self._bold), fmt
            layout.setFormats([rng])
        metrics = QFontMetricsF(exact(self.font()))
        step = metrics.height()
        px = self.font().pixelSize() if self.font().pixelSize() > 0 else self.font().pointSizeF() / px_to_pt(1)
        if self._line_height:
            step = max(step, px * self._line_height)
        lead = half_leading(step, metrics.height())
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
        return layout, y

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        mw, mh = self._margins()
        height = self._layout(width - mw)[1]
        # с межстрочным 1.4 строки уже с запасом: округляем, как CSS (18.2 + 16.8 = 35, а не 19 + 17)
        return (int(height + 0.5) if self._line_height else math.ceil(height)) + mh

    def sizeHint(self):  # noqa: N802
        mw, _ = self._margins()
        text_w = QFontMetrics(exact(self.font())).horizontalAdvance(self._bold + self._text) + 2
        w = min(text_w, 600) + mw
        return QSize(w, self.heightForWidth(w))

    def minimumSizeHint(self):  # noqa: N802
        mw, mh = self._margins()
        return QSize(40 + mw, math.ceil(QFontMetricsF(self.font()).height()) + mh)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        self.drawFrame(painter)
        rect = self.contentsRect()
        painter.setPen(self.palette().color(self.foregroundRole()))
        self._layout(rect.width())[0].draw(painter, QPointF(rect.x(), rect.y()))


class EmptyNote(WrapAnywhereLabel):
    """Пустой список («Список пуст. Добавьте…»): текст по центру в рамке border: 1.5px dashed, радиус 8.

    Рамку QSS (dashed) Qt рисует точками и бледно, а у скругленной рамки нижний край выходит двойным,
    поэтому штриховую рамку рисуем сами, как Chromium: толщина 1.5px, округленная вниз до целых
    пикселей экрана (при 100 % — 1px полного цвета), штрих 3 толщины, промежуток около 2 толщин,
    подобранный так, чтобы каждая сторона начиналась и кончалась штрихом; скругления — сплошные.
    QSS оставляет прозрачную рамку 1px (ее место) и поля.
    """

    BORDER_PX = 1.5
    RADIUS = 8.0

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, "empty", parent)
        self.set_alignment(Qt.AlignHCenter)

    def border_width(self) -> float:
        """Толщина рамки в px окна: 1.5px макета, округленные вниз до пикселей экрана (не меньше одного)."""
        ratio = max(1.0, self.devicePixelRatioF())
        return max(1, math.floor(self.BORDER_PX * ratio + 1e-6)) / ratio

    @staticmethod
    def _dashes(length: float, dash: float, gap: float) -> List[Tuple[float, float]]:
        """Штрихи (начало, длина) на отрезке length: первый и последний — у концов, промежутки равные."""
        if length <= dash:
            return [(0.0, max(0.0, length))]
        count = max(2, round((length + gap) / (dash + gap)))
        step = (length - dash) / (count - 1)
        return [(i * step, dash) for i in range(count)]

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        w = self.border_width()
        rect = QRectF(self.rect()).adjusted(w / 2, w / 2, -w / 2, -w / 2)
        radius = max(0.0, min(self.RADIUS - w / 2, rect.width() / 2, rect.height() / 2))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(C.INPUT), w)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        d = 2 * radius
        left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
        for x, y, start in ((left, top, 90), (right - d, top, 0), (right - d, bottom - d, 270),
                            (left, bottom - d, 180)):
            painter.drawArc(QRectF(x, y, d, d), start * 16, 90 * 16)
        dash, gap = 3 * w, 2 * w
        for x0, y0, dx, dy, length in ((left + radius, top, 1, 0, rect.width() - d),
                                       (left + radius, bottom, 1, 0, rect.width() - d),
                                       (left, top + radius, 0, 1, rect.height() - d),
                                       (right, top + radius, 0, 1, rect.height() - d)):
            for start, size in self._dashes(length, dash, gap):
                a = QPointF(x0 + dx * start, y0 + dy * start)
                painter.drawLine(a, QPointF(a.x() + dx * size, a.y() + dy * size))


# =========================================================================== кнопки
class Button(QPushButton):
    """Кнопка макета. variant: None (обычная), primary, ghost, link, danger, danger-solid, nav.

    small=True — 28px (.btn-sm); icon — имя иконки из icons.py (цвет = цвет текста варианта);
    icon_only=True — квадратная кнопка 32×32 / 28×28; elide=True — текст с «…», если не помещается
    (полный текст — в text() и подсказке). Между иконкой и текстом 6px (у nav — 10px), как в макете.
    surface — фон под кнопкой (недоступная кнопка полупрозрачна поверх него): "card" или "side".
    Фокус только с клавиатуры (синяя рамка не «залипает» после щелчка мышью).
    """

    LEFT_ALIGNED = ("link", "nav")

    def __init__(self, text: str = "", variant: Optional[str] = None, small: bool = False,
                 icon: Optional[str] = None, icon_color: Optional[str] = None, icon_size: Optional[int] = None,
                 icon_only: bool = False, accessible_name: Optional[str] = None, elide: bool = False,
                 checkable: bool = False, surface: str = "card", parent=None):
        super().__init__(text, parent)
        self._surface = surface
        if surface != "card":
            self.setProperty("surface", surface)
        self._elide = elide
        self._icon_name, self._icon_color, self._icon_stroke = None, icon_color, None
        self._icon_size = icon_size or (15 if not icon_only else 16)
        self._variant = variant
        self._small = small
        self._icon_only = icon_only
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setCheckable(checkable)
        if variant:
            self.setProperty("variant", variant)
        if small:
            self.setProperty("small", True)
        if icon_only:
            self.setProperty("iconOnly", True)
        if accessible_name:
            self.setAccessibleName(accessible_name)  # имя для экранного диктора: у кнопки-иконки нет текста
        self._apply_size()
        if icon:
            self.set_icon(icon, icon_color)
        if elide:
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def _apply_size(self) -> None:
        h = BUTTON_HEIGHT_SMALL if self._small else BUTTON_HEIGHT
        if self._variant == "nav":
            h = 32  # .tab макета: 7 + 18.2 + 7
        if self._icon_only:
            self.setFixedSize(h, h)
        else:
            self.setFixedHeight(h)

    def icon_gap(self) -> int:
        return 10 if self._variant == "nav" else 6

    def set_variant(self, variant: Optional[str]) -> None:
        """Сменить вариант на лету (например, primary → обычная)."""
        self._variant = variant
        set_props(self, variant=variant)
        if self._icon_name:
            self.set_icon(self._icon_name, None, self._icon_stroke)

    def variant(self) -> Optional[str]:
        return self._variant

    def icon_name(self) -> Optional[str]:
        return self._icon_name

    def set_icon(self, name: Optional[str], color: Optional[str] = None, stroke: Optional[float] = None) -> None:
        """Иконка слева от текста; color по умолчанию — цвет текста варианта."""
        self._icon_name = name
        self._icon_stroke = stroke
        if color:
            self._icon_color = color
        if not name:
            self.setIcon(QIcon())
            return
        base = self._icon_color or _VARIANT_ICON.get(self._variant, C.TEXT)
        behind = C.SIDE if self._surface == "side" else C.CARD
        disabled = mix(C.WHITE, C.WIN, 0.45) if self._variant in ("primary", "danger-solid") else faded(base, behind)
        self.setIcon(icons.icon(name, base, self._icon_size, stroke, disabled_color=disabled))
        self.setIconSize(QSize(self._icon_size, self._icon_size))
        self.updateGeometry()

    def full_text(self) -> str:
        return self.text()

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        self.updateGeometry()
        self.update()

    # --- размеры: Qt ставит между иконкой и текстом 4px, у нас 6 (10 у nav)
    def sizeHint(self):  # noqa: N802
        hint = super().sizeHint()
        if not self.icon().isNull() and self.text() and not self._icon_only:
            hint.setWidth(hint.width() + self.icon_gap() - 4)
        if self.text() and not self._icon_only:
            # 12.5px (.btn-sm, .seg): ширина текста как в макете, а не как у округленных 13px
            hint.setWidth(hint.width() - exact_width_delta(self.font(), self.text()))
        return hint

    def minimumSizeHint(self):  # noqa: N802
        if not self._elide:
            return super().minimumSizeHint()
        return QSize(48, super().minimumSizeHint().height())

    def is_elided(self) -> bool:
        return self._shown_text() != self.text()

    def _content_rect(self, option) -> QRect:
        return self.style().subElementRect(QStyle.SE_PushButtonContents, option, self)

    def _shown_text(self, rect: Optional[QRect] = None) -> str:
        if not self._elide or not self.text():
            return self.text()
        if rect is None:
            option = QStyleOptionButton()
            self.initStyleOption(option)
            rect = self._content_rect(option)
        width = rect.width()
        if not self.icon().isNull():
            width -= self.iconSize().width() + self.icon_gap()
        return elided(QFontMetrics(exact(self.font())), self.text(), max(10, width))

    def paintEvent(self, event):  # noqa: N802
        if self._elide and self.icon().isNull() and not self._icon_only and self.text():
            # без иконки: обычная отрисовка стилем, но с текстом «…» (QSS задает выравнивание и поля)
            painter = QStylePainter(self)
            option = QStyleOptionButton()
            self.initStyleOption(option)
            option.text = self._shown_text(self._content_rect(option))
            painter.drawControl(QStyle.CE_PushButton, option)
            return
        if self.icon().isNull() or self._icon_only or not self.text():
            super().paintEvent(event)
            return
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter.drawControl(QStyle.CE_PushButtonBevel, option)
        rect = self._content_rect(option)
        text = self._shown_text(rect)
        text_font = exact(self.font())
        painter.setFont(text_font)
        fm = QFontMetrics(text_font)
        size = self.iconSize()
        total = size.width() + self.icon_gap() + fm.horizontalAdvance(text)
        if self._variant in self.LEFT_ALIGNED:
            x = rect.left()
        else:
            x = max(rect.left(), rect.left() + (rect.width() - total) // 2)
        mode = QIcon.Normal if self.isEnabled() else QIcon.Disabled
        icon_rect = QRect(x, rect.top() + (rect.height() - size.height()) // 2, size.width(), size.height())
        self.icon().paint(painter, icon_rect, Qt.AlignCenter, mode)
        group = QPalette.Active if self.isEnabled() else QPalette.Disabled
        painter.setPen(self.palette().color(group, QPalette.ButtonText))
        text_rect = QRect(icon_rect.right() + 1 + self.icon_gap(), rect.top(),
                          rect.right() - icon_rect.right() - self.icon_gap(), rect.height())
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine, text)


# =========================================================================== переключатели
class ToggleSwitch(QAbstractButton):
    """Переключатель 38×22 (role=switch в макете) с плавным ходом «ползунка».

    Сигнал toggled(bool) — как у любой QAbstractButton. set_checked_silent() — без сигнала и анимации.
    """

    WIDTH, HEIGHT, KNOB = 38, 22, 16

    def __init__(self, checked: bool = False, parent=None, accessible_name: str = ""):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setProperty("kind", "switch")
        if accessible_name:
            self.setAccessibleName(accessible_name)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, value: float) -> None:
        self._pos = value
        self.update()

    knob = pyqtProperty(float, _get_knob, _set_knob)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        if not self.isVisible():
            self._set_knob(1.0 if on else 0.0)
            return
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def set_checked_silent(self, on: bool) -> None:
        self._anim.stop()
        blocked = self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(blocked)
        self._set_knob(1.0 if on else 0.0)

    def sizeHint(self):  # noqa: N802
        return QSize(self.WIDTH, self.HEIGHT)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        off, on, t = QColor(C.SWITCH_OFF), QColor(C.ACCENT), self._pos
        track = QColor(round(off.red() + (on.red() - off.red()) * t),
                       round(off.green() + (on.green() - off.green()) * t),
                       round(off.blue() + (on.blue() - off.blue()) * t))
        if not self.isEnabled():
            track = QColor(mix(track.name(), C.CARD, 0.45))
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, self.WIDTH, self.HEIGHT), self.HEIGHT / 2, self.HEIGHT / 2)
        x = 3 + (self.WIDTH - self.KNOB - 6) * t
        # тень ползунка: 0 1px 2px rgba(0,0,0,.25)
        for spread, alpha in ((1.2, 22), (0.6, 38)):
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawEllipse(QRectF(x - spread / 2, 3 + 1 - spread / 2, self.KNOB + spread, self.KNOB + spread))
        p.setBrush(QColor(C.WHITE))
        p.drawEllipse(QRectF(x, 3, self.KNOB, self.KNOB))
        if has_keyboard_focus(self):
            p.setPen(QPen(QColor("#0B2F75" if self.isChecked() else C.ACCENT), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(0.75, 0.75, self.WIDTH - 1.5, self.HEIGHT - 1.5), 10.25, 10.25)


class Segmented(QFrame):
    """Сегменты «Ежедневно | Еженедельно | Ежемесячно»: фон #EEF1F5, выбранный — белый с обводкой.

    options — [(ключ, подпись), ...]. Сигнал changed(str) — только от пользователя.
    Ширина сегмента — по тексту плюс равная доля свободного места (flex: 1 1 auto в макете);
    в узкой колонке подписи сокращаются с «…».
    """

    changed = pyqtSignal(str)
    PAD, GAP, MIN_SEGMENT = 2, 2, 40

    def __init__(self, options: Sequence[Tuple[str, str]], value: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setProperty("kind", "segmented")
        self.setFixedHeight(32)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = {}
        self._keys: List[str] = []
        for key, text in options:
            b = Button(text, elide=True, checkable=True, parent=self)
            b.setProperty("kind", "seg")
            b.setFixedHeight(28)
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            self._group.addButton(b)
            self._buttons[key] = b
            self._keys.append(key)
        self._group.buttonToggled.connect(lambda *_: self.update())  # обводка — за выбранным сегментом
        self._value = None
        self.set_value(value if value is not None else self._keys[0])

    def _hints(self) -> List[int]:
        return [self._buttons[key].sizeHint().width() for key in self._keys]

    def _frame(self) -> int:
        return self.PAD * 2 + self.GAP * (len(self._keys) - 1)

    def sizeHint(self):  # noqa: N802
        return QSize(sum(self._hints()) + self._frame(), 32)

    def minimumSizeHint(self):  # noqa: N802
        return QSize(self.MIN_SEGMENT * len(self._keys) + self._frame(), 32)

    def segment_widths(self, width: int) -> List[float]:
        """Ширины сегментов при ширине width: как flex: 1 1 auto (лишнее — поровну, нехватка — по ширине)."""
        hints = self._hints()
        free = width - self._frame() - sum(hints)
        if free >= 0:
            return [h + free / len(hints) for h in hints]
        total = sum(hints) or 1
        return [max(self.MIN_SEGMENT, h + free * h / total) for h in hints]

    def _place(self) -> None:
        x = float(self.PAD)
        for key, w in zip(self._keys, self.segment_widths(self.width())):
            left, right = round(x), round(x + w)
            self._buttons[key].setGeometry(left, self.PAD, right - left, 28)
            x += w + self.GAP

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._place()

    def event(self, event):
        if event.type() in (QEvent.LayoutRequest, QEvent.Polish, QEvent.StyleChange):
            self._place()
        return super().event(event)

    # тень выбранного сегмента (0 1px 2px rgba(20,32,52,.12)): размытие ~ полосы с прозрачностью
    # гауссова края (sigma 1px) — (расширение рамки, альфа)
    SHADOW_LAYERS = ((1.0, 0.029), (0.0, 0.046), (-1.0, 0.037))

    def paintEvent(self, event):  # noqa: N802
        """Фон из QSS, затем выбранный сегмент: обводка 1px СНАРУЖИ его 28px, тень и белая заливка, как в макете
        (box-shadow: 0 0 0 1px #D3DAE3, 0 1px 2px rgba(20,32,52,.12)). Заливку рисуем здесь, а не QSS кнопки:
        QSS со скруглением заливает крайний ряд пикселей наполовину, и сквозь него видна обводка."""
        super().paintEvent(event)
        button = self._buttons.get(self._value)
        if button is None or not button.isChecked() or not button.isVisible():
            return
        box = QRectF(button.geometry())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(C.RING))
        painter.drawRoundedRect(box.adjusted(-1, -1, 1, 1), 6, 6)
        outside = QPainterPath()
        outside.addRect(QRectF(self.rect()))
        inside = QPainterPath()
        inside.addRoundedRect(box, 5, 5)
        painter.setClipPath(outside.subtracted(inside))
        for grow, alpha in self.SHADOW_LAYERS:
            painter.setBrush(QColor(20, 32, 52, round(255 * alpha)))
            painter.drawRoundedRect(box.translated(0, 1).adjusted(-grow, -grow, grow, grow), 5 + grow, 5 + grow)
        painter.setClipping(False)
        painter.setBrush(QColor(C.CARD))
        painter.drawRoundedRect(box, 5, 5)

    def _pick(self, key: str) -> None:
        if key != self._value:
            self._value = key
            self._buttons[key].setChecked(True)
            self.changed.emit(key)
        else:
            self._buttons[key].setChecked(True)

    def value(self) -> str:
        return self._value

    def set_value(self, key: str, emit: bool = False) -> None:
        if key not in self._buttons:
            raise KeyError(key)
        old = self._value
        self._value = key
        self._buttons[key].setChecked(True)
        if emit and key != old:
            self.changed.emit(key)

    def button(self, key: str) -> QPushButton:
        return self._buttons[key]

    def keys(self) -> List[str]:
        return list(self._keys)

    def keyPressEvent(self, event):  # noqa: N802
        step = {Qt.Key_Left: -1, Qt.Key_Right: 1}.get(event.key())
        if step:
            index = (self._keys.index(self._value) + step) % len(self._keys)
            self._pick(self._keys[index])
            self._buttons[self._keys[index]].setFocus(Qt.TabFocusReason)
            return
        super().keyPressEvent(event)


class DayChips(QWidget):
    """Дни недели «Пн … Вс»: кнопки 34×28, выбран один день (0 = понедельник). Переносятся, если тесно."""

    changed = pyqtSignal(int)

    def __init__(self, value: int = 0, labels: Sequence[str] = DAY_SHORT, full_names: Sequence[str] = DAY_FULL,
                 parent=None):
        super().__init__(parent)
        lay = FlowLayout(self, 4, 4)
        self._buttons: List[QPushButton] = []
        self._group = QButtonGroup(self)
        for index, text in enumerate(labels):
            b = QPushButton(text)
            b.setProperty("kind", "chip")
            b.setCheckable(True)
            b.setFixedSize(34, 28)
            b.setFocusPolicy(Qt.TabFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.setAccessibleName(full_names[index])
            b.clicked.connect(lambda _=False, i=index: self._pick(i))
            self._group.addButton(b)
            lay.addWidget(b)
            self._buttons.append(b)
        self._value = -1
        self.set_value(value)
        policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def _pick(self, index: int) -> None:
        self._buttons[index].setChecked(True)
        if index != self._value:
            self._value = index
            self.changed.emit(index)

    def value(self) -> int:
        return self._value

    def set_value(self, index: int, emit: bool = False) -> None:
        old = self._value
        self._value = index
        self._buttons[index].setChecked(True)
        if emit and index != old:
            self.changed.emit(index)

    def button(self, index: int) -> QPushButton:
        return self._buttons[index]

    def sizeHint(self):  # noqa: N802
        n = len(self._buttons)
        return QSize(n * 34 + (n - 1) * 4, 28)


class MonthdayStepper(QFrame):
    """Число месяца «− N +» в рамке. По кругу: после 31 идет 1, перед 1 — 31."""

    changed = pyqtSignal(int)
    MIN, MAX = 1, 31

    def __init__(self, value: int = 1, parent=None):
        super().__init__(parent)
        self.setProperty("kind", "stepper")
        self.setFixedHeight(30)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        self.down_button = Button(variant="stepper", icon="minus", icon_only=True, small=True,
                                  accessible_name="Раньше на день", icon_size=13)
        self.up_button = Button(variant="stepper", icon="plus", icon_only=True, small=True,
                                accessible_name="Позже на день", icon_size=13)
        self.value_label = QLabel()
        self.value_label.setProperty("kind", "semibold")
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setMinimumWidth(30)
        lay.addWidget(self.down_button)
        lay.addWidget(self.value_label)
        lay.addWidget(self.up_button)
        self.down_button.clicked.connect(lambda: self.step(-1))
        self.up_button.clicked.connect(lambda: self.step(1))
        # стрелки обрабатывают сами кнопки (переход фокуса), поэтому клавиши перехватываются фильтром
        self.down_button.installEventFilter(self)
        self.up_button.installEventFilter(self)
        self._value = self.MIN
        self.set_value(value)

    def value(self) -> int:
        return self._value

    def set_value(self, value: int, emit: bool = False) -> None:
        value = max(self.MIN, min(self.MAX, int(value)))
        old = self._value
        self._value = value
        self.value_label.setText(str(value))
        if emit and value != old:
            self.changed.emit(value)

    def step(self, delta: int) -> None:
        """Шаг с переносом по кругу; всегда сообщает changed."""
        span = self.MAX - self.MIN + 1
        self.set_value((self._value - self.MIN + delta) % span + self.MIN, emit=True)

    _KEY_STEPS = {Qt.Key_Up: 1, Qt.Key_Right: 1, Qt.Key_Plus: 1,
                  Qt.Key_Down: -1, Qt.Key_Left: -1, Qt.Key_Minus: -1}

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.KeyPress and obj in (self.down_button, self.up_button):
            delta = self._KEY_STEPS.get(event.key())
            if delta:
                self.step(delta)
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):  # noqa: N802
        delta = self._KEY_STEPS.get(event.key())
        if delta:
            self.step(delta)
        else:
            super().keyPressEvent(event)


class SwitchRow(QFrame):
    """Строка «заголовок + подсказка … переключатель» (Настройки, «Копировать по расписанию»).

    title_kind: "medium" (строки страницы «Настройки») или "h3" (13px/600 в карточке вкладки).
    top_border=True — линия #EEF1F5 сверху, как между строками карточки.
    """

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, hint: str = "", checked: bool = False, title_kind: str = "medium",
                 top_border: bool = False, margins: Tuple[int, int, int, int] = (14, 10, 14, 10), parent=None):
        super().__init__(parent)
        self.setProperty("kind", "row-plain" if top_border else "")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(*margins)
        lay.setSpacing(12)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        # строки по 1.4 высоты шрифта, как в макете; растяжки держат текст по центру строки (align-items: center)
        self.title_label = WrapAnywhereLabel(title, title_kind)
        self.hint_label = WrapAnywhereLabel(hint, "muted")
        text.addStretch(1)
        text.addWidget(self.title_label)
        text.addWidget(self.hint_label)
        text.addStretch(1)
        lay.addLayout(text, 1)
        # скрывать/показывать только после того, как у надписи есть родитель: setVisible(True) у виджета
        # без родителя открывает его отдельным окном
        self.hint_label.setVisible(bool(hint))
        self.switch = ToggleSwitch(checked, accessible_name=title)
        lay.addWidget(self.switch, 0, Qt.AlignVCenter)
        self.switch.toggled.connect(self.toggled)

    def is_checked(self) -> bool:
        return self.switch.isChecked()

    def set_checked(self, on: bool, silent: bool = True) -> None:
        if silent:
            self.switch.set_checked_silent(on)
        else:
            self.switch.setChecked(on)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)
        self.switch.setAccessibleName(text)

    def set_hint(self, text: str) -> None:
        self.hint_label.setText(text)
        self.hint_label.setVisible(bool(text))


class OptionCheck(QWidget):
    """Флажок с полужирной (500) подписью и серой подсказкой; щелчок по всей строке переключает флажок.

    Подсветка строки выступает на INSET px за колонку (margin: 0 -8px в макете): отступ колонки делайте
    на INSET меньше, чтобы флажок стоял по линии заголовка.
    """

    INSET = 8

    toggled = pyqtSignal(bool)

    def __init__(self, text: str, hint: str = "", checked: bool = False, parent=None):
        super().__init__(parent)
        self.setProperty("kind", "option")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(9)
        self.checkbox = QCheckBox()
        self.checkbox.setFocusPolicy(Qt.TabFocus)
        self.checkbox.setChecked(checked)
        self.checkbox.setAccessibleName(text)
        box = QVBoxLayout()
        box.setContentsMargins(0, 2, 0, 0)
        box.addWidget(self.checkbox)
        box.addStretch(1)
        lay.addLayout(box)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.text_label = WrapAnywhereLabel(text, "medium")
        self.hint_label = WrapAnywhereLabel(hint, "muted")
        col.addWidget(self.text_label)
        col.addWidget(self.hint_label)
        col.addStretch(1)  # лишняя высота — под текстом (align-items: flex-start)
        lay.addLayout(col, 1)
        self.hint_label.setVisible(bool(hint))  # после addLayout: у надписи уже есть родитель
        self.checkbox.toggled.connect(self.toggled)

    def isChecked(self) -> bool:  # noqa: N802
        return self.checkbox.isChecked()

    def setChecked(self, on: bool, silent: bool = False) -> None:  # noqa: N802
        blocked = self.checkbox.blockSignals(silent) if silent else None
        self.checkbox.setChecked(on)
        if silent:
            self.checkbox.blockSignals(blocked)

    def set_text(self, text: str) -> None:
        self.text_label.setText(text)
        self.checkbox.setAccessibleName(text)

    def set_hint(self, text: str) -> None:
        self.hint_label.setText(text)
        self.hint_label.setVisible(bool(text))

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()) and self.isEnabled():
            self.checkbox.toggle()
        super().mouseReleaseEvent(event)


# =========================================================================== карточки и плашки
class Card(QFrame):
    """Белая карточка: рамка #DDE2E9, скругление 8. Необязательная шапка: иконка + заголовок 13.5/600 +
    свои виджеты справа (add_header_widget) и линия под шапкой (header_divider).

    body / body_layout — содержимое; add_footer() — серый подвал (#FAFBFC) с линией сверху.
    """

    def __init__(self, title: str = "", icon_name: Optional[str] = None, header_divider: bool = False,
                 header_margins: Tuple[int, int, int, int] = (12, 9, 12, 9),
                 body_margins: Tuple[int, int, int, int] = (12, 0, 12, 12), spacing: int = 8, parent=None):
        super().__init__(parent)
        self.setProperty("kind", "card")
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        self._root = root
        self.header: Optional[QWidget] = None
        self.header_layout: Optional[QHBoxLayout] = None
        self.title_label: Optional[QLabel] = None
        self.icon_label: Optional[IconLabel] = None
        self.footer: Optional[QFrame] = None
        if title or icon_name:
            self.header = QWidget()
            self.header_layout = QHBoxLayout(self.header)
            self.header_layout.setContentsMargins(*header_margins)
            self.header_layout.setSpacing(8)
            if icon_name:
                self.icon_label = IconLabel(icon_name, C.TEXT2, 16)
                self.header_layout.addWidget(self.icon_label)
            self.title_label = label(title, "h2")
            self.header_layout.addWidget(self.title_label)
            root.addWidget(self.header)
            if header_divider:
                root.addWidget(hline())
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(*body_margins)
        self.body_layout.setSpacing(spacing)
        root.addWidget(self.body, 1)

    def set_title(self, text: str) -> None:
        if self.title_label is not None:
            self.title_label.setText(text)

    def add_header_widget(self, widget: QWidget, stretch: int = 0) -> QWidget:
        """Добавить виджет в шапку (после заголовка). Возвращает widget."""
        self.header_layout.addWidget(widget, stretch)
        return widget

    def add_header_stretch(self) -> None:
        self.header_layout.addStretch(1)

    def add_footer(self, margins: Tuple[int, int, int, int] = (14, 10, 14, 10), spacing: int = 3) -> QVBoxLayout:
        """Серый подвал карточки (как «Так будет выглядеть копия»). Возвращает его раскладку."""
        self.footer = QFrame()
        self.footer.setProperty("kind", "card-footer")
        lay = QVBoxLayout(self.footer)
        lay.setContentsMargins(*margins)
        lay.setSpacing(spacing)
        self._root.addWidget(self.footer)
        return lay


class NoticeBanner(QFrame):
    """Красная плашка внутри карточки: «⚠ <b>Заголовок.</b> текст  ×». Скрывается крестиком (closed)."""

    closed = pyqtSignal()

    def __init__(self, title: str = "", text: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("kind", "notice")
        self.setAccessibleName("Сообщение")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 6, 8)
        lay.setSpacing(8)
        self.icon_label = IconLabel("alert", C.NOTICE_TEXT, 15)
        icon_box = QVBoxLayout()
        icon_box.setContentsMargins(0, 2, 0, 0)
        icon_box.addWidget(self.icon_label)
        icon_box.addStretch(1)
        lay.addLayout(icon_box)
        self.text_label = WrapAnywhereLabel()
        lay.addWidget(self.text_label, 1)
        self.close_button = Button(variant="notice-close", icon="x", icon_only=True, small=True,
                                   accessible_name="Скрыть сообщение", icon_size=12)
        self.close_button.setFixedSize(22, 22)
        self.close_button.set_icon("x", C.NOTICE_TEXT, 2.4)
        close_box = QVBoxLayout()
        close_box.setContentsMargins(0, 0, 0, 0)
        close_box.addWidget(self.close_button)
        close_box.addStretch(1)
        lay.addLayout(close_box)
        self.close_button.clicked.connect(self.dismiss)
        self._title, self._text = "", ""
        self.set_message(title, text)

    def set_message(self, title: str, text: str) -> None:
        self._title, self._text = title, text
        self.text_label.set_text(text, f"{title}. " if title else "")

    def show_message(self, title: str, text: str) -> None:
        self.set_message(title, text)
        self.show()

    def title(self) -> str:
        return self._title

    def text(self) -> str:
        return self._text

    def dismiss(self) -> None:
        self.hide()
        self.closed.emit()


# =========================================================================== индикаторы
class Spinner(QWidget):
    """Крутящаяся дуга «идет копирование» (14–15px). Анимируется только пока виден."""

    def __init__(self, size: int = 15, color: str = C.ACCENT, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._color = color
        self.angle = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self.advance)

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def is_spinning(self) -> bool:
        return self._timer.isActive()

    def advance(self) -> None:
        self.angle = (self.angle + 12.0) % 360.0  # один оборот за 0.9 с
        self.update()

    def showEvent(self, event):  # noqa: N802
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        draw_spinner(p, QRectF(self.rect()), self._color, self.angle)


def draw_spinner(painter: QPainter, rect: QRectF, color: str, angle: float) -> None:
    """Дуга спиннера макета (path «M21 12a9 9 0 1 1-6.2-8.6», ~288°) в rect, повернутая на angle."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    side = min(rect.width(), rect.height())
    painter.translate(rect.center())
    painter.rotate(angle)
    painter.scale(side / 24.0, side / 24.0)
    painter.setPen(QPen(QColor(color), 2.4, Qt.SolidLine, Qt.RoundCap))
    painter.setBrush(Qt.NoBrush)
    painter.drawArc(QRectF(-9, -9, 18, 18), 0, -288 * 16)
    painter.restore()


class ProgressBar(QProgressBar):
    """Полоска хода 6px: дорожка #E3E8EF, заполнение — акцент. Диапазон (0, 0) — «бегущий» отрезок."""

    PERIOD_MS = 1100

    def __init__(self, parent=None, indeterminate: bool = False):
        super().__init__(parent)
        self.setTextVisible(False)
        self.setFixedHeight(6)
        self.setMinimumWidth(80)
        self.setRange(0, 0 if indeterminate else 100)
        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.update)
        self._sync_timer()

    def is_indeterminate(self) -> bool:
        return self.minimum() == 0 and self.maximum() == 0

    def set_indeterminate(self, on: bool) -> None:
        self.setRange(0, 0 if on else 100)
        self._sync_timer()

    def setRange(self, minimum, maximum):  # noqa: N802
        super().setRange(minimum, maximum)
        if hasattr(self, "_timer"):
            self._sync_timer()

    def _sync_timer(self) -> None:
        if self.is_indeterminate() and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()

    def is_animating(self) -> bool:
        return self._timer.isActive()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event):  # noqa: N802
        super().hideEvent(event)
        self._timer.stop()

    def block_rect(self, phase: Optional[float] = None) -> QRectF:
        """Где сейчас «бегущий» отрезок (35% ширины, от −110% до +300% своей длины, ease-in-out)."""
        w, h = self.width(), self.height()
        if phase is None:
            phase = (self._clock.elapsed() % self.PERIOD_MS) / self.PERIOD_MS
        eased = QEasingCurve(QEasingCurve.InOutSine).valueForProgress(phase)
        bw = w * 0.35
        x = bw * (-1.1 + 4.1 * eased)
        return QRectF(x, 0, bw, h)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        radius = r.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C.SEG_HOVER))
        p.drawRoundedRect(r, radius, radius)
        p.setClipRect(r)
        p.setBrush(QColor(C.ACCENT if self.isEnabled() else faded(C.ACCENT)))
        if self.is_indeterminate():
            p.drawRoundedRect(self.block_rect(), radius, radius)
            return
        span = self.maximum() - self.minimum()
        ratio = (self.value() - self.minimum()) / span if span > 0 else 0.0
        ratio = max(0.0, min(1.0, ratio))
        if ratio > 0:
            p.drawRoundedRect(QRectF(0, 0, max(r.height(), r.width() * ratio), r.height()), radius, radius)


class IndeterminateBar(ProgressBar):
    """«Подготовка к копированию»: полоска 6px с бегущим отрезком."""

    def __init__(self, parent=None):
        super().__init__(parent, indeterminate=True)


class StatusLine(QWidget):
    """Строка состояния вкладки под заголовком: значок 14px + текст 12.5px цвета состояния.

    tone: run (спиннер, синий), warn (⚠, коричневый), ok (часы, зеленый), off (круг с чертой, серый).
    """

    TONES = {
        "run": (None, C.ACCENT),
        "warn": ("alert", C.WARN),
        "ok": ("clock", C.OK),
        "off": ("off", C.MUTED),
    }

    def __init__(self, tone: str = "off", text: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.spinner = Spinner(14)
        self.icon_label = IconLabel("off", C.MUTED, 14)
        self.text_label = ElidedLabel(kind="status")
        lay.addWidget(self.spinner)
        lay.addWidget(self.icon_label)
        lay.addWidget(self.text_label, 1)
        self.tone = ""
        self.set_status(tone, text)

    def set_status(self, tone: str, text: str) -> None:
        icon_name, color = self.TONES.get(tone, self.TONES["off"])
        self.tone = tone
        self.spinner.setVisible(icon_name is None)
        self.spinner.set_color(color)
        self.icon_label.setVisible(icon_name is not None)
        if icon_name:
            self.icon_label.set_icon(icon_name, color)
        set_props(self.text_label, tone=tone)
        self.text_label.setText(text)

    def text(self) -> str:
        return self.text_label.text()


# =========================================================================== разделитель панелей
class GripHandle(QSplitterHandle):
    """Ручка 8px: линия 1px #D3DAE3 + «таблетка» 4×36 #B9C1CC; при наведении/перетаскивании — акцент.
    Двойной щелчок и Enter — ширина по умолчанию, стрелки — шаг 16px (с Shift — 48px)."""

    def __init__(self, orientation, splitter):
        super().__init__(orientation, splitter)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAccessibleName("Ширина списка вкладок")
        self.setCursor(Qt.SplitHCursor)
        self.hovered = self.pressed = False

    def enterEvent(self, event):  # noqa: N802
        self.hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self.hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        self.pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self.pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        self.splitter().reset_side_width()

    def keyPressEvent(self, event):  # noqa: N802
        step = 48 if event.modifiers() & Qt.ShiftModifier else 16
        splitter = self.splitter()
        if event.key() == Qt.Key_Left:
            splitter.set_side_width(splitter.side_width() - step)
        elif event.key() == Qt.Key_Right:
            splitter.set_side_width(splitter.side_width() + step)
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            splitter.reset_side_width()
        else:
            super().keyPressEvent(event)

    def is_active(self) -> bool:
        return self.hovered or self.pressed or has_keyboard_focus(self)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(C.WIN))
        active = self.is_active()
        p.fillRect(0, 0, 2 if active else 1, self.height(), QColor(C.ACCENT if active else C.RING))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C.ACCENT if active else C.SPLIT_GRIP))
        p.drawRoundedRect(QRectF(2, self.height() / 2 - 18, 4, 36), 2, 2)


class GripSplitter(QSplitter):
    """Боковая панель | рабочая область. Ширина панели 180…440 (по умолчанию 240), рабочая — от 380.

    Сигнал side_width_changed(int) — после перетаскивания, клавиш или сброса (для сохранения ширины).
    """

    side_width_changed = pyqtSignal(int)

    def __init__(self, side: QWidget, main: QWidget, parent=None, side_min: int = SIDE_MIN,
                 side_max: int = SIDE_MAX, side_default: int = SIDE_DEFAULT, main_min: int = MAIN_MIN):
        super().__init__(Qt.Horizontal, parent)
        self.side_min, self.side_max, self.side_default = side_min, side_max, side_default
        self.setHandleWidth(8)
        self.setChildrenCollapsible(False)
        self.setOpaqueResize(True)
        side.setMinimumWidth(side_min)
        side.setMaximumWidth(side_max)
        main.setMinimumWidth(main_min)
        self.addWidget(side)
        self.addWidget(main)
        self.setStretchFactor(0, 0)
        self.setStretchFactor(1, 1)
        self._wanted = side_default
        self.set_side_width(side_default, emit=False)
        self.splitterMoved.connect(self._moved)

    def createHandle(self):  # noqa: N802
        return GripHandle(self.orientation(), self)

    def handle_widget(self) -> GripHandle:
        return self.handle(1)

    def clamp(self, width: int) -> int:
        return max(self.side_min, min(self.side_max, int(round(width))))

    def side_width(self) -> int:
        sizes = self.sizes()
        return sizes[0] if sizes and sum(sizes) > 0 else self._wanted

    def set_side_width(self, width: int, emit: bool = True) -> int:
        """Задать ширину панели (с ограничением 180…440). Возвращает итоговую ширину."""
        width = self.clamp(width)
        self._wanted = width
        total = sum(self.sizes())
        if total <= 0:
            total = max(self.width() - self.handleWidth(), width + self.widget(1).minimumWidth())
        self.setSizes([width, max(total - width, 1)])
        actual = self.side_width()
        if emit:
            self.side_width_changed.emit(actual)
        return actual

    def reset_side_width(self) -> int:
        return self.set_side_width(self.side_default)

    def _moved(self, pos: int, index: int) -> None:
        self._wanted = self.side_width()
        self.side_width_changed.emit(self._wanted)


# =========================================================================== список вкладок
class TabEntry(NamedTuple):
    """Строка списка вкладок. status: running | warn | on | off. sub_color по умолчанию — по статусу."""

    uid: str
    name: str
    sub: str = ""
    status: str = "off"
    sub_color: Optional[str] = None


ROLE_UID = Qt.UserRole + 1
ROLE_SUB = Qt.UserRole + 2
ROLE_SUB_COLOR = Qt.UserRole + 3
ROLE_STATUS = Qt.UserRole + 4

STATUS_RUNNING, STATUS_WARN, STATUS_ON, STATUS_OFF = "running", "warn", "on", "off"


def _sub_color(entry: TabEntry) -> str:
    if entry.sub_color:
        return entry.sub_color
    return C.WARN if entry.status == STATUS_WARN else C.MUTED


class EdgeShadow(QWidget):
    """Мягкая тень у края списка, когда за краем есть еще строки (radial-gradient макета, 8px)."""

    HEIGHT = 8

    def __init__(self, parent, top: bool):
        super().__init__(parent)
        self.top = top
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, event):  # noqa: N802
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # эллиптический градиент «farthest-side»: круг радиуса 1, растянутый на (w/2, h)
        p.translate(w / 2, 0 if self.top else h)
        p.scale(w / 2, h)
        g = QRadialGradient(QPointF(0, 0), 1.0)
        g.setColorAt(0, QColor(20, 32, 52, 46))
        g.setColorAt(1, QColor(20, 32, 52, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRect(QRectF(-1, 0 if self.top else -1, 2, 1))


class TabDelegate(QStyledItemDelegate):
    """Рисует строку вкладки: статус (точка/⚠/спиннер), имя 13/600 и подпись 11.5px с «…»."""

    # .tab макета: 7 + 18.2 (имя 13px × 1.4) + 16.1 (подпись 11.5px × 1.4) + 7 = 48.3, между строками 2 px.
    # Строки дробные, как в браузере: высоты строк 50/51 px, края плашек — округленные края строк макета.
    BOX = 48.3
    PITCH = BOX + 2
    OFFSET = 1.4             # дробная часть верха первой строки в макете (список начинается не с целого px)
    NAME_H, SUB_H, PAD_TOP = 18.2, 16.1, 7
    ROW_HEIGHT = 50          # высота строки без дробной части (строки по 50 и 51 px)
    PAD_LEFT, PAD_RIGHT = 10, 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.spin_angle = 0.0

    @classmethod
    def row_top(cls, row: int) -> int:
        """Верх строки row в списке (строка 0 — с 0)."""
        return round(cls.OFFSET + row * cls.PITCH) - round(cls.OFFSET)

    @classmethod
    def row_height(cls, row: int) -> int:
        return cls.row_top(row + 1) - cls.row_top(row)

    def sizeHint(self, option, index):  # noqa: N802
        return QSize(max(0, option.rect.width()), self.row_height(max(0, index.row())))

    def item_rect(self, rect, row: int = 0) -> QRectF:
        """Плашка строки: с 1 px от верха строки до округленного края 48.3 px (как в браузере)."""
        exact = self.OFFSET + row * self.PITCH
        height = round(exact + self.BOX) - round(exact)
        return QRectF(rect.left() + self.PAD_LEFT, rect.top() + 1, rect.width() - self.PAD_LEFT - self.PAD_RIGHT,
                      height)

    def _text_top(self, rect, row: int) -> float:
        """Верх имени: точный верх плашки макета + 7 px."""
        exact = self.OFFSET + row * self.PITCH
        return rect.top() + 1 + (exact - round(exact)) + self.PAD_TOP

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        row = max(0, index.row())
        r = self.item_rect(option.rect, row)
        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 32, 52, 15))
            p.drawRoundedRect(r.translated(0, 1), 6, 6)
            p.setBrush(QColor(C.CARD))
            p.setPen(QPen(QColor(C.RING), 1))
            p.drawRoundedRect(r.adjusted(-0.5, -0.5, 0.5, 0.5), 6.5, 6.5)
        elif option.state & QStyle.State_MouseOver:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(C.SIDE_HOVER))
            p.drawRoundedRect(r, 6, 6)
        view = option.widget
        if (option.state & QStyle.State_HasFocus and view is not None and view.hasFocus()
                and getattr(view, "keyboard_focus", False)):
            p.setPen(QPen(QColor(C.ACCENT), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 5.5, 5.5)

        status = index.data(ROLE_STATUS)
        text_top = self._text_top(option.rect, row)
        gx, cy = r.left() + 10, text_top - self.PAD_TOP + self.BOX / 2
        glyph = QRectF(gx, cy - 8, 16, 16)
        if status == STATUS_RUNNING:
            draw_spinner(p, glyph.adjusted(0.5, 0.5, -0.5, -0.5), C.ACCENT, self.spin_angle)
        elif status == STATUS_WARN:
            icons.paint(p, glyph.adjusted(0.5, 0.5, -0.5, -0.5), "alert", C.WARN_ICON, 2.0)
        else:
            on = status == STATUS_ON
            p.setPen(QPen(QColor(C.OK if on else C.FAINT), 2))
            p.setBrush(QColor(C.OK) if on else Qt.NoBrush)
            p.drawEllipse(QRectF(glyph.center().x() - 3.5, glyph.center().y() - 3.5, 7, 7))

        tx = r.left() + 36
        tw = max(0, int(r.right() - 10 - tx))
        name_font = font("semibold", 13)
        sub_font = font_exact("regular", 11.5)
        p.setFont(name_font)
        p.setPen(QColor(C.TEXT))
        name = elided(QFontMetrics(name_font), index.data(Qt.DisplayRole) or "", tw)
        p.drawText(QRectF(tx, text_top, tw, self.NAME_H), Qt.AlignLeft | Qt.AlignVCenter, name)
        p.setFont(sub_font)
        p.setPen(QColor(index.data(ROLE_SUB_COLOR) or C.MUTED))
        sub = elided(QFontMetrics(sub_font), index.data(ROLE_SUB) or "", tw)
        p.drawText(QRectF(tx, text_top + self.NAME_H, tw, self.SUB_H), Qt.AlignLeft | Qt.AlignVCenter, sub)
        p.restore()


class SidebarTabList(QListView):
    """Список вкладок боковой панели: модель + фильтр по названию + делегат + тени у краев.

    set_entries([TabEntry, ...]) — показать вкладки; set_current(uid) — выделить (без сигнала);
    set_query(text) — фильтр по названию без учета регистра. Сигнал tab_selected(uid) — выбор пользователя.
    Если по фильтру ничего не найдено, в списке пишется empty_text (set_empty_text).
    """

    tab_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("kind", "tabs")
        self.model_ = QStandardItemModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model_)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterRole(Qt.DisplayRole)
        self.setModel(self.proxy)
        self.delegate = TabDelegate(self)
        self.setItemDelegate(self.delegate)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WA_Hover, True)
        self.setFrameShape(QFrame.NoFrame)
        self.setViewportMargins(0, 2, 0, 4)
        self.setFocusPolicy(Qt.StrongFocus)
        self.verticalScrollBar().setSingleStep(25)
        self.keyboard_focus = False
        self._selected: Optional[str] = None
        self._query = ""
        self._empty_text = ""
        self._silent = False
        self._items: Dict[str, QStandardItem] = {}   # uid → строка модели (поиск без перебора)
        self._order: List[str] = []
        self._top, self._bottom = EdgeShadow(self, True), EdgeShadow(self, False)
        bar = self.verticalScrollBar()
        bar.valueChanged.connect(self._update_shadows)
        bar.rangeChanged.connect(self._update_shadows)
        self.selectionModel().currentChanged.connect(self._current_changed)
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(30)
        self._spin_timer.timeout.connect(self._spin)

    # --- данные
    def set_entries(self, entries: Iterable[TabEntry]) -> None:
        """Заменить список. Выделение сохраняется по uid, если вкладка осталась."""
        entries = list(entries)
        same_order = self._order == [e.uid for e in entries]
        self._silent = True
        try:
            if same_order:
                for row, entry in enumerate(entries):
                    self._fill(self.model_.item(row), entry)
            else:
                self.model_.clear()
                self._items = {}
                for entry in entries:
                    item = QStandardItem()
                    item.setEditable(False)
                    self._fill(item, entry)
                    self.model_.appendRow(item)
                    self._items[entry.uid] = item
                self._order = [e.uid for e in entries]
        finally:
            self._silent = False
        if self._selected is not None and self._item(self._selected) is None:
            self._selected = None
        self._sync_selection()
        self._sync_spinner()
        self._update_shadows()

    def update_entry(self, entry: TabEntry) -> bool:
        """Обновить одну вкладку по uid. False — такой нет."""
        return self.update_entries([entry]) > 0

    def update_entries(self, entries: Iterable[TabEntry]) -> int:
        """Обновить несколько вкладок по uid (одним проходом). Возвращает число обновленных.

        Выделение не меняется: если вкладка перестала подходить под фильтр (переименована),
        она просто пропадает из списка, а выбранной остается она же (без сигнала tab_selected).
        """
        count, renamed = 0, False
        self._silent = True
        try:
            for entry in entries:
                item = self._items.get(entry.uid)
                if item is None:
                    continue
                if self._entry(item) == entry:
                    count += 1
                    continue
                renamed = renamed or item.data(Qt.DisplayRole) != entry.name
                self._fill(item, entry)
                count += 1
        finally:
            self._silent = False
        if renamed:
            self._sync_selection()
            self._update_shadows()
        self._sync_spinner()
        return count

    def entries(self) -> List[TabEntry]:
        return [self._entry(self.model_.item(row)) for row in range(self.model_.rowCount())]

    def entry(self, uid: str) -> Optional[TabEntry]:
        item = self._item(uid)
        return self._entry(item) if item is not None else None

    @staticmethod
    def _fill(item: QStandardItem, entry: TabEntry) -> None:
        item.setData(entry.name, Qt.DisplayRole)
        item.setData(entry.uid, ROLE_UID)
        item.setData(entry.sub, ROLE_SUB)
        item.setData(entry.status, ROLE_STATUS)
        item.setData(_sub_color(entry), ROLE_SUB_COLOR)
        item.setData(entry.sub_color, Qt.UserRole + 9)

    @staticmethod
    def _entry(item: QStandardItem) -> TabEntry:
        return TabEntry(item.data(ROLE_UID), item.data(Qt.DisplayRole), item.data(ROLE_SUB) or "",
                        item.data(ROLE_STATUS) or STATUS_OFF, item.data(Qt.UserRole + 9))

    def _item(self, uid: Optional[str]) -> Optional[QStandardItem]:
        return self._items.get(uid) if uid is not None else None

    # --- выделение
    def current_uid(self) -> Optional[str]:
        """Выбранная вкладка (остается выбранной, даже если скрыта фильтром)."""
        return self._selected

    def set_current(self, uid: Optional[str]) -> None:
        """Выделить вкладку (None — снять выделение, например на странице «Настройки»). Без сигнала."""
        self._selected = uid if uid is not None and self._item(uid) is not None else None
        self._sync_selection()

    def _sync_selection(self) -> None:
        """Показать self._selected в представлении, не посылая сигналов."""
        self._silent = True
        try:
            item = self._item(self._selected) if self._selected is not None else None
            index = self.proxy.mapFromSource(item.index()) if item is not None else QModelIndex()
            selection = self.selectionModel()
            if index.isValid():
                selection.setCurrentIndex(index, selection.ClearAndSelect)
                self.scrollTo(index)
            else:
                selection.clearSelection()
                selection.setCurrentIndex(QModelIndex(), selection.Clear)
        finally:
            self._silent = False
        self.viewport().update()

    def _current_changed(self, current, previous) -> None:
        if self._silent or not current.isValid():
            return
        uid = current.data(ROLE_UID)
        if uid is not None and uid != self._selected:
            self._selected = uid
            self.tab_selected.emit(uid)

    def select_row(self, row: int) -> None:
        """Выбрать видимую строку как пользователь (с сигналом) — для клавиатуры и тестов."""
        index = self.proxy.index(row, 0)
        if index.isValid():
            self.selectionModel().setCurrentIndex(index, self.selectionModel().ClearAndSelect)

    # --- фильтр
    def set_query(self, text: str) -> None:
        self._query = text.strip()
        self._silent = True
        try:
            self.proxy.setFilterFixedString(self._query)
        finally:
            self._silent = False
        self._sync_selection()
        self._update_shadows()
        self.viewport().update()

    def query(self) -> str:
        return self._query

    def visible_count(self) -> int:
        return self.proxy.rowCount()

    def visible_uids(self) -> List[str]:
        return [self.proxy.index(row, 0).data(ROLE_UID) for row in range(self.proxy.rowCount())]

    def set_empty_text(self, text: str) -> None:
        self._empty_text = text
        self.viewport().update()

    # --- анимация спиннера
    def _sync_spinner(self) -> None:
        running = any(item.data(ROLE_STATUS) == STATUS_RUNNING for item in self._items.values())
        if running and not self._spin_timer.isActive():
            self._spin_timer.start()
        elif not running:
            self._spin_timer.stop()

    def _spin(self) -> None:
        self.delegate.spin_angle = (self.delegate.spin_angle + 12.0) % 360.0
        self.viewport().update()

    # --- тени и фокус
    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        vr = self.viewport().geometry()
        self._top.setGeometry(vr.x(), vr.y(), vr.width(), EdgeShadow.HEIGHT)
        self._bottom.setGeometry(vr.x(), vr.bottom() + 1 - EdgeShadow.HEIGHT, vr.width(), EdgeShadow.HEIGHT)
        self._update_shadows()

    def _update_shadows(self, *_):
        bar = self.verticalScrollBar()
        self._top.setVisible(bar.value() > bar.minimum())
        self._bottom.setVisible(bar.value() < bar.maximum())
        self._top.raise_()
        self._bottom.raise_()

    def shadows_visible(self) -> Tuple[bool, bool]:
        return self._top.isVisibleTo(self), self._bottom.isVisibleTo(self)

    def focusInEvent(self, event):  # noqa: N802
        self.keyboard_focus = keyboard_focus_reason(event.reason())
        super().focusInEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        self.keyboard_focus = False
        super().mousePressEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        self.keyboard_focus = True
        super().keyPressEvent(event)

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        if self.proxy.rowCount() == 0 and self._empty_text:
            p = QPainter(self.viewport())
            p.setFont(font("regular", 12.5))
            p.setPen(QColor(C.MUTED))
            rect = self.viewport().rect().adjusted(16, 10, -12, -4)
            p.drawText(rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWrapAnywhere, self._empty_text)


# =========================================================================== тост и модальное окно
class Toast(QFrame):
    """Всплывающее сообщение внутри окна: темное, 340px, в правом нижнем углу родителя, само скрывается
    через 5 с. kind: info (синяя иконка), warn (желтая), ok (зеленая).

    toast = Toast(window); toast.show_message("Расписание не запущено", "Выберите …", kind="warn")
    """

    closed = pyqtSignal()
    WIDTH = 340
    TIMEOUT_MS = 5000
    COLORS = {"info": C.TOAST_INFO, "warn": C.TOAST_WARN, "ok": C.TOAST_OK}

    def __init__(self, parent: QWidget, right: int = 16, bottom: int = 56):
        super().__init__(parent)
        self.setProperty("kind", "toast")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._right, self._bottom = right, bottom
        self.kind = "info"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 12, 12)
        lay.setSpacing(10)
        self.icon_label = IconLabel("shield", C.TOAST_INFO, 18)
        icon_box = QVBoxLayout()
        icon_box.setContentsMargins(0, 1, 0, 0)
        icon_box.addWidget(self.icon_label)
        icon_box.addStretch(1)
        lay.addLayout(icon_box)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.title_label = WrapAnywhereLabel(kind="toast-title")
        self.text_label = WrapAnywhereLabel(kind="toast-text")
        col.addWidget(self.title_label)
        col.addWidget(self.text_label)
        lay.addLayout(col, 1)
        self.close_button = Button(variant="toast-close", icon="x", icon_only=True, small=True,
                                   accessible_name="Закрыть уведомление", icon_size=12)
        self.close_button.setFixedSize(24, 24)
        self.close_button.set_icon("x", C.TOAST_TEXT, 2.4)
        close_box = QVBoxLayout()
        close_box.setContentsMargins(0, 0, 0, 0)
        close_box.addWidget(self.close_button)
        close_box.addStretch(1)
        lay.addLayout(close_box)
        self.close_button.clicked.connect(self.dismiss)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 14)
        shadow.setColor(QColor(16, 24, 40, 80))
        self.setGraphicsEffect(shadow)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        parent.installEventFilter(self)
        self.hide()

    def set_offsets(self, right: int, bottom: int) -> None:
        """Отступы от правого и нижнего края родителя (в макете 16 и 56 — над строкой состояния)."""
        self._right, self._bottom = right, bottom
        self.reposition()

    def show_message(self, title: str, text: str = "", kind: str = "info", timeout: int = TIMEOUT_MS) -> None:
        self.kind = kind
        self.icon_label.set_icon("shield", self.COLORS.get(kind, C.TOAST_INFO))
        self.title_label.set_text(title)
        self.text_label.set_text(text)
        self.text_label.setVisible(bool(text))
        self.show()
        self.raise_()
        self.reposition()
        if timeout and timeout > 0:
            self.timer.start(timeout)
        else:
            self.timer.stop()

    def title(self) -> str:
        return self.title_label.text()

    def text(self) -> str:
        return self.text_label.text()

    def dismiss(self) -> None:
        self.timer.stop()
        if self.isVisible():
            self.hide()
            self.closed.emit()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        width = max(160, min(self.WIDTH, parent.width() - 32))
        self.setFixedWidth(width)
        lay = self.layout()
        lay.activate()
        height = lay.totalHeightForWidth(width) if lay.hasHeightForWidth() else lay.sizeHint().height()
        self.setFixedHeight(max(height, 44))
        self.move(parent.width() - width - self._right, parent.height() - self.height() - self._bottom)

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.parentWidget() and event.type() == QEvent.Resize and self.isVisible():
            self.reposition()
        return False


class OverlayDialog(QWidget):
    """Модальное окно внутри окна: затемнение rgba(16,24,40,.38) и белая карточка 400px по центру.

    ok = OverlayDialog(window, "Удалить вкладку «Фото»?", "Удаляются только …",
                       ok_text="Удалить вкладку", cancel_text="Отмена").exec_()
    exec_() ждет ответа (вложенный цикл событий) и возвращает True/False; open() — без ожидания,
    ответ придет сигналом finished(bool).

    Для тестов: OverlayDialog.preset_answer = True/False — exec_() сразу возвращает этот ответ, окно не
    показывается; заголовок и текст записываются в OverlayDialog.asked [(title, text), ...].
    """

    finished = pyqtSignal(bool)
    preset_answer: Optional[bool] = None
    asked: List[Tuple[str, str]] = []
    WIDTH = 400

    def __init__(self, parent: QWidget, title: str, text: str = "", ok_text: str = "Да", cancel_text: str = "Нет",
                 ok_variant: str = "danger-solid"):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.result_: Optional[bool] = None
        self._loop: Optional[QEventLoop] = None
        self._return_focus: Optional[QWidget] = None
        self._return_keyboard = False
        self.title_text, self.body_text = title, text
        self.card = QFrame(self)
        self.card.setProperty("kind", "dialog")
        self.card.setAccessibleName(title)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(8)
        self.title_label = WrapAnywhereLabel(title, kind="dialog-title")
        self.text_label = WrapAnywhereLabel(text, kind="dialog-text")
        lay.addWidget(self.title_label)
        lay.addWidget(self.text_label)
        self.text_label.setVisible(bool(text))  # после addWidget: без родителя надпись открылась бы окном
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 8, 0, 0)
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.cancel_button = Button(cancel_text)
        self.ok_button = Button(ok_text, variant=ok_variant)
        for b in (self.cancel_button, self.ok_button):
            b.setFocusPolicy(Qt.StrongFocus)
            buttons.addWidget(b)
        lay.addLayout(buttons)
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button.clicked.connect(self.accept)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(50)
        shadow.setOffset(0, 20)
        shadow.setColor(QColor(16, 24, 40, 77))
        self.card.setGraphicsEffect(shadow)
        self.parentWidget().installEventFilter(self)
        self.hide()

    # --- показ
    def open(self) -> None:  # noqa: A003 - как QDialog.open
        parent = self.parentWidget()
        focused = QApplication.focusWidget()
        if focused is not None and focused is not self and not self.isAncestorOf(focused):
            # после ответа фокус вернется сюда (как у QDialog), иначе он пропадает
            self._return_focus, self._return_keyboard = focused, has_keyboard_focus(focused)
        self.setGeometry(parent.rect())
        self._place_card()
        self.show()
        self.raise_()
        self.cancel_button.setFocus(Qt.OtherFocusReason)

    def exec_(self) -> bool:  # noqa: N802
        """Показать и дождаться ответа. True — подтверждено."""
        if OverlayDialog.preset_answer is not None:
            OverlayDialog.asked.append((self.title_text, self.body_text))
            self.result_ = bool(OverlayDialog.preset_answer)
            self.finished.emit(self.result_)
            return self.result_
        self.open()
        self._loop = QEventLoop(self)
        self._loop.exec_()
        self._loop = None
        return bool(self.result_)

    exec = exec_

    def accept(self) -> None:
        self._finish(True)

    def reject(self) -> None:
        self._finish(False)

    def _finish(self, result: bool) -> None:
        if self.result_ is not None and not self.isVisible():
            return
        self.result_ = result
        self._restore_focus()  # до hide(): иначе Qt сам переведет фокус на следующий виджет окна
        self.hide()
        self.finished.emit(result)
        if self._loop is not None:
            self._loop.quit()

    def _restore_focus(self) -> None:
        widget, self._return_focus = self._return_focus, None
        if widget is None or sip.isdeleted(widget) or not widget.isVisible() or not widget.isEnabled():
            return
        widget.setFocus(Qt.TabFocusReason if self._return_keyboard else Qt.OtherFocusReason)

    # --- раскладка и клавиатура
    def _place_card(self) -> None:
        width = max(200, min(self.WIDTH, self.width() - 32))
        self.card.setFixedWidth(width)
        lay = self.card.layout()
        lay.activate()
        height = lay.totalHeightForWidth(width) if lay.hasHeightForWidth() else lay.sizeHint().height()
        self.card.setFixedHeight(height)
        self.card.move((self.width() - width) // 2, max(16, (self.height() - height) // 2))

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._place_card()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.parentWidget():
            if event.type() == QEvent.Resize and self.isVisible():
                self.setGeometry(obj.rect())
            elif event.type() == QEvent.Hide and self.isVisible() and self._loop is not None:
                self.reject()
        return False

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(16, 24, 40, 97))

    def mousePressEvent(self, event):  # noqa: N802
        event.accept()  # щелчки мимо карточки не доходят до окна

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.reject()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            focused = self.focusWidget()
            (focused if isinstance(focused, QPushButton) else self.ok_button).click()
        else:
            event.accept()

    def focusNextPrevChild(self, forward: bool) -> bool:  # noqa: N802
        """Tab ходит только между кнопками окна, не уходя в окно под затемнением."""
        order = [self.cancel_button, self.ok_button]
        current = self.focusWidget()
        index = order.index(current) if current in order else -1
        order[(index + (1 if forward else -1)) % len(order)].setFocus(Qt.TabFocusReason)
        return True


def confirm(parent: QWidget, title: str, text: str = "", ok_text: str = "Да", cancel_text: str = "Нет",
            ok_variant: str = "danger-solid") -> bool:
    """Спросить подтверждение модальным окном внутри parent. True — подтверждено."""
    dialog = OverlayDialog(parent, title, text, ok_text, cancel_text, ok_variant)
    try:
        return dialog.exec_()
    finally:
        dialog.deleteLater()


# =========================================================================== заголовок вкладки
_SIZE_EXTRA = {}


def size_attribute_extra(f: QFont) -> int:
    """Запас ширины поля <input size=N> в браузере сверх N средних знаков: наибольшая ширина знака
    (по рамке всех знаков шрифта, таблица head) минус средняя (OS/2 xAvgCharWidth, как averageCharWidth)."""
    key = f.key()
    extra = _SIZE_EXTRA.get(key)
    if extra is None:
        fm = QFontMetrics(f)
        widest = fm.maxWidth()
        raw = QRawFont.fromFont(f)
        head = bytes(raw.fontTable(b"head")) if raw.isValid() else b""
        if len(head) >= 42 and raw.unitsPerEm() > 0:
            x_min, x_max = struct.unpack(">h", head[36:38])[0], struct.unpack(">h", head[40:42])[0]
            widest = int((x_max - x_min) * raw.pixelSize() / raw.unitsPerEm())
        extra = _SIZE_EXTRA[key] = max(0, widest - fm.averageCharWidth())
    return extra


class FocusHalo(QWidget):
    """Мягкая обводка 3 px вокруг поля в фокусе (box-shadow: 0 0 0 3px rgba(31,95,209,.18) в макете).

    Рисуется поверх ближайшего предка, в который помещается (поле может стоять у самого края своего
    родителя), и следует за полем при изменении размеров и положения.
    """

    WIDTH = 3

    def __init__(self, field: QWidget, radius: float = 6.0):
        super().__init__(field.parentWidget())  # пока не показана — у родителя поля; при показе — у предка
        self.field = field
        self.radius = radius
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.hide()

    def sync(self) -> None:
        field = self.field
        if not field.hasFocus() or not field.isVisible():
            self.hide()
            return
        w = self.WIDTH
        host = field.parentWidget()
        rect = QRect(field.mapTo(host, QPoint(0, 0)), field.size()).adjusted(-w, -w, w, w)
        while host.parentWidget() is not None and not host.rect().contains(rect):
            rect.translate(host.pos())
            host = host.parentWidget()
        if self.parentWidget() is not host:
            self.setParent(host)
        self.setGeometry(rect)
        self.raise_()
        self.show()
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.WIDTH
        outer, inner = QPainterPath(), QPainterPath()
        outer.addRoundedRect(QRectF(self.rect()), self.radius + w, self.radius + w)
        inner.addRoundedRect(QRectF(self.rect()).adjusted(w, w, -w, -w), self.radius, self.radius)
        p.fillPath(outer.subtracted(inner), QColor(31, 95, 209, 46))


class _TitleLineEdit(QLineEdit):
    """Поле названия: без фокуса длинный текст обрезается с «…» с начала строки (text-overflow: ellipsis)."""

    hint_width = 0  # ширина по тексту (TitleEdit._fit): поле растет с названием, как size="len+2" в макете

    def sizeHint(self):  # noqa: N802
        hint = super().sizeHint()
        if self.hint_width:
            hint.setWidth(self.hint_width)
        return hint

    def focusOutEvent(self, event):  # noqa: N802
        super().focusOutEvent(event)
        self.setCursorPosition(0)

    def paintEvent(self, event):  # noqa: N802
        option = QStyleOptionFrame()
        self.initStyleOption(option)
        rect = self.style().subElementRect(QStyle.SE_LineEditContents, option, self)
        margins = self.textMargins()
        rect = rect.adjusted(margins.left() + 2, margins.top(), -margins.right() - 2, -margins.bottom())
        fm = self.fontMetrics()
        if self.hasFocus() or fm.horizontalAdvance(self.text()) <= rect.width():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_PanelLineEdit, option, painter, self)
        painter.setPen(self.palette().color(self.palette().Text))
        painter.setFont(self.font())
        painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter,
                         elided(fm, self.text(), rect.width()))


class TitleEdit(QWidget):
    """Название вкладки, редактируемое на месте: 18px/600, рамка только при наведении/фокусе, карандаш.

    Ширина поля — по тексту (как size="len+2" в макете, 6…48 знаков). Сигналы: text_edited(str) — каждое
    изменение; editing_finished(str) — один раз по Enter, Esc или уходу фокуса, если имя изменилось
    (Esc — всегда, с прежним именем); пустое имя заменяется на empty_text. Esc возвращает прежнее имя.

    Текст начинается на TEXT_INSET px правее левого края (рамка + поля): в макете поле сдвинуто влево
    (margin-left: -8px), чтобы текст стоял ровно над строкой состояния, — уменьшите левый отступ раскладки.
    В фокусе вокруг поля — мягкая синяя обводка 3 px (box-shadow макета), ее рисует FocusHalo.
    """

    TEXT_INSET = 8      # рамка 1 + поле 5 + внутренний отступ QLineEdit 2 (в макете: рамка 1 + поле 7)
    CHROME = 2 * TEXT_INSET
    text_edited = pyqtSignal(str)
    editing_finished = pyqtSignal(str)

    def __init__(self, text: str = "", empty_text: str = "Без названия", max_length: int = 0, parent=None):
        super().__init__(parent)
        self.empty_text = empty_text
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.line_edit = _TitleLineEdit()
        self.line_edit.setProperty("kind", "title")
        self.line_edit.setAccessibleName("Название вкладки")
        self.line_edit.setFixedHeight(33)  # 18px × 1.4 + поля 3 + рамка 1
        if max_length:
            self.line_edit.setMaxLength(max_length)
        self.pencil = IconLabel("pencil", C.FAINT, 15)
        lay.addWidget(self.line_edit)
        lay.addWidget(self.pencil)
        lay.addStretch(1)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._before = text
        self.line_edit.setText(text)
        self.line_edit.setCursorPosition(0)
        self.line_edit.textEdited.connect(self._edited)
        self.line_edit.editingFinished.connect(self._finished)
        self.line_edit.installEventFilter(self)
        self.halo = FocusHalo(self.line_edit)
        self._fit()

    def text(self) -> str:
        return self.line_edit.text()

    def set_text(self, text: str) -> None:
        """Задать имя извне (без сигналов)."""
        if text != self.line_edit.text():
            self.line_edit.setText(text)
            if not self.line_edit.hasFocus():
                self.line_edit.setCursorPosition(0)
        self._before = text
        self._fit()

    setText = set_text

    def _edited(self, text: str) -> None:
        self._fit()
        self.text_edited.emit(text)

    def _finished(self, force: bool = False) -> None:
        text = self.line_edit.text()
        if not text.strip():
            text = self.empty_text
            self.line_edit.setText(text)
            self._fit()
        elif not force and text == self._before:
            return  # уже сообщено (Enter, затем уход фокуса) или имя не менялось
        self._before = text
        self.editing_finished.emit(text)

    def chars(self) -> int:
        """Ширина поля в знаках, как атрибут size в макете."""
        return max(6, min(48, len(self.line_edit.text()) + 2))

    def _fit(self) -> None:
        fm = self.line_edit.fontMetrics()
        frame = self.CHROME
        # как ширина <input size=N> в браузере: N × средняя ширина знака + (наибольшая − средняя)
        extra = size_attribute_extra(self.line_edit.font())
        by_size = fm.averageCharWidth() * self.chars() + extra
        by_text = fm.horizontalAdvance(self.line_edit.text()) + 6
        self.line_edit.setMinimumWidth(min(by_size, fm.averageCharWidth() * 6 + extra) + frame)
        # как size="len+2" (не больше 48 знаков) в макете: длиннее — текст обрезается «…»
        self._wanted = (max(by_size, by_text) if self.chars() < 48 else by_size) + frame
        self.line_edit.setMaximumWidth(self._wanted)
        self.line_edit.hint_width = self._wanted
        self.line_edit.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.line_edit.updateGeometry()

    def wanted_width(self) -> int:
        return self._wanted

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.line_edit:
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self.line_edit.setText(self._before)
                self._fit()
                self.text_edited.emit(self._before)
                self._finished(force=True)
                self.line_edit.clearFocus()
                return True
            if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                # сообщаем сами и не отдаем Enter полю: иначе editingFinished придет дважды (Enter + уход фокуса)
                self._finished()
                self.line_edit.clearFocus()
                return True
            if event.type() in (QEvent.FontChange, QEvent.StyleChange, QEvent.Polish):
                QTimer.singleShot(0, self._fit)
            if event.type() in (QEvent.FocusIn, QEvent.FocusOut, QEvent.Resize, QEvent.Move, QEvent.Show,
                                QEvent.Hide):
                self.halo.sync()
        return False

    def moveEvent(self, event):  # noqa: N802
        super().moveEvent(event)
        self.halo.sync()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.halo.sync()


def style_menu(menu) -> None:
    """Скругленные углы меню (трей, контекстные): прозрачный фон окна, рамку и фон рисует QSS."""
    menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WA_TranslucentBackground, True)


def escape(text: str) -> str:
    """Экранировать пользовательский текст для QLabel с RichText."""
    return html.escape(text, quote=False)
