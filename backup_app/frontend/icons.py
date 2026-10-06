"""Набор иконок интерфейса: SVG-контуры из макета (viewBox 24×24) → QPixmap/QIcon нужного цвета.

Иконки рисуются из векторных путей под нужный размер с учетом масштаба экрана (100/125/150/200 %),
поэтому остаются четкими. Готовые изображения кэшируются.

    pix("folder", "#A86A12", 18)          # QPixmap для QLabel
    icon("trash", C.TEXT2, 16)            # QIcon для кнопки (серый вариант для disabled — сам)
"""
import math
from typing import Dict, Optional, Tuple

from PyQt5.QtCore import QByteArray, QRect, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QGuiApplication, QIcon, QIconEngine, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer

# Контурные иконки: (пути, толщина линии по умолчанию — как в макете).
_STROKE: Dict[str, Tuple[str, float]] = {
    # щит с галочкой: значок приложения, тосты и уведомления
    "shield": ('<path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-0.7-8-4.5-8-9V6z"/>'
               '<path d="M8.5 12l2.5 2.5 4.5-5"/>', 2.0),
    # щит без галочки: карточка «Безопасность»
    "shield-plain": ('<path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-0.7-8-4.5-8-9V6z"/>', 1.8),
    "folder": ('<path d="M3 7.5A1.5 1.5 0 0 1 4.5 6H9l2 2h8.5A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5'
               'h-15A1.5 1.5 0 0 1 3 17.5z"/>', 1.8),
    "file": ('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>', 1.8),
    "folder-plus": ('<path d="M3 7.5A1.5 1.5 0 0 1 4.5 6H9l2 2h8.5A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5'
                    'h-15A1.5 1.5 0 0 1 3 17.5z"/><path d="M12 11v5"/><path d="M9.5 13.5h5"/>', 1.8),
    "file-plus": ('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'
                  '<path d="M12 12v5"/><path d="M9.5 14.5h5"/>', 1.8),
    "plus": ('<path d="M12 5v14"/><path d="M5 12h14"/>', 2.0),
    "minus": ('<path d="M5 12h14"/>', 2.2),
    "x": ('<path d="M6 6l12 12"/><path d="M18 6L6 18"/>', 2.0),
    "layers": ('<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>', 2.0),
    "gear": ('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 0.3 1.8l0.1 0.1a2 2 0 1 1-2.8 2.8'
             'l-0.1-0.1a1.7 1.7 0 0 0-1.8-0.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-0.1a1.7 1.7 0 0 0-1.1-1.5'
             ' 1.7 1.7 0 0 0-1.8 0.3l-0.1 0.1a2 2 0 1 1-2.8-2.8l0.1-0.1a1.7 1.7 0 0 0 0.3-1.8 1.7 1.7 0 0 0-1.5-1'
             'H3a2 2 0 1 1 0-4h0.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-0.3-1.8l-0.1-0.1a2 2 0 1 1 2.8-2.8l0.1 0.1'
             'a1.7 1.7 0 0 0 1.8 0.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v0.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0'
             ' 1.8-0.3l0.1-0.1a2 2 0 1 1 2.8 2.8l-0.1 0.1a1.7 1.7 0 0 0-0.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1'
             ' 0 4h-0.1a1.7 1.7 0 0 0-1.5 1z"/>', 1.8),
    "pencil": ('<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>', 1.8),
    "clock": ('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', 2.0),
    # круг с чертой: «расписание остановлено»
    "off": ('<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>', 2.0),
    "drive": ('<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M5 13l2.5-8h9L19 13"/>'
              '<path d="M16.5 16.5h0.01"/>', 1.8),
    "alert": ('<path d="M12 3.5l9 16H3z"/><path d="M12 10v4"/><path d="M12 17h0.01"/>', 2.0),
    "calendar": ('<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18"/><path d="M8 3v4"/>'
                 '<path d="M16 3v4"/>', 2.0),
    "sliders": ('<path d="M4 6h9"/><path d="M17 6h3"/><circle cx="15" cy="6" r="2"/><path d="M4 12h3"/>'
                '<path d="M11 12h9"/><circle cx="9" cy="12" r="2"/><path d="M4 18h11"/><circle cx="17" cy="18" r="2"/>',
                1.8),
    "list": ('<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3.5 6h0.01"/>'
             '<path d="M3.5 12h0.01"/><path d="M3.5 18h0.01"/>', 1.8),
    "trash": ('<path d="M4 7h16"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M6 7l1 13h10l1-13"/>'
              '<path d="M9 7V4h6v3"/>', 1.8),
    "monitor": ('<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8"/><path d="M12 17v4"/>', 1.8),
    "logout": ('<path d="M9 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
               1.8),
    # окно: пункт меню трея «Открыть окно»
    "window": ('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/>', 1.8),
    "search": ('<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>', 1.8),
    "check": ('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 2.2),
    # дуга индикатора «идет копирование» (статичная; анимированная — widgets.Spinner)
    "spinner": ('<path d="M21 12a9 9 0 1 1-6.2-8.6"/>', 2.4),
}

# Залитые иконки.
_FILL: Dict[str, str] = {
    "play": '<path d="M7 4.5l12.5 7.5L7 19.5z"/>',
}

# Синонимы: в коде удобно писать и через подчеркивание.
_ALIASES = {
    "folder_plus": "folder-plus",
    "file_plus": "file-plus",
    "shield_plain": "shield-plain",
    "minus-circle": "off",
    "minus_circle": "off",
    "warning": "alert",
    "settings": "gear",
    "close": "x",
}

NAMES = tuple(sorted(set(_STROKE) | set(_FILL)))

_pix_cache: Dict[tuple, QPixmap] = {}
_renderer_cache: Dict[tuple, QSvgRenderer] = {}


def _canonical(name: str) -> str:
    name = _ALIASES.get(name, name)
    if name not in _STROKE and name not in _FILL:
        raise KeyError(f"Нет иконки «{name}». Есть: {', '.join(NAMES)}")
    return name


def svg_text(name: str, color: str, stroke: Optional[float] = None) -> str:
    """Полный SVG-документ иконки заданного цвета."""
    name = _canonical(name)
    color = QColor(color).name(QColor.HexArgb) if QColor(color).alpha() < 255 else QColor(color).name()
    if name in _FILL:
        attrs, body = f'fill="{color}" stroke="none"', _FILL[name]
    else:
        body, default_stroke = _STROKE[name]
        width = default_stroke if stroke is None else stroke
        attrs = (f'fill="none" stroke="{color}" stroke-width="{width}" '
                 f'stroke-linecap="round" stroke-linejoin="round"')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {attrs}>{body}</svg>'


def _renderer(name: str, color: str, stroke: Optional[float]) -> QSvgRenderer:
    key = (name, color, stroke)
    renderer = _renderer_cache.get(key)
    if renderer is None:
        renderer = QSvgRenderer(QByteArray(svg_text(name, color, stroke).encode("utf-8")))
        _renderer_cache[key] = renderer
    return renderer


def _app_dpr() -> float:
    app = QGuiApplication.instance()
    if app is None:
        return 1.0
    screens = QGuiApplication.screens()
    ratios = [screen.devicePixelRatio() for screen in screens] or [app.devicePixelRatio()]
    return max(ratios)


def pix(name: str, color: str, size: int = 16, stroke: Optional[float] = None,
        dpr: Optional[float] = None) -> QPixmap:
    """QPixmap иконки: логический размер size×size, физический — с учетом масштаба экрана.

    dpr — масштаб экрана; по умолчанию наибольший среди подключенных экранов (дробный тоже).
    """
    name = _canonical(name)
    ratio = float(dpr) if dpr else _app_dpr()
    key = (name, QColor(color).rgba(), size, stroke, round(ratio, 3))
    cached = _pix_cache.get(key)
    if cached is not None:
        return cached
    side = max(1, math.ceil(size * ratio))
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    _renderer(name, color, stroke).render(painter, QRectF(0, 0, side, side))
    painter.end()
    pixmap.setDevicePixelRatio(side / size)
    _pix_cache[key] = pixmap
    return pixmap


def paint(painter: QPainter, rect, name: str, color: str, stroke: Optional[float] = None) -> None:
    """Нарисовать иконку прямо в painter (вектор, четко при любом масштабе) — для делегатов и paintEvent."""
    _renderer(_canonical(name), color, stroke).render(painter, QRectF(rect))


class SvgIconEngine(QIconEngine):
    """Движок QIcon: иконка рисуется под запрошенный размер; для disabled/active — свой цвет."""

    def __init__(self, name: str, color: str, stroke: Optional[float] = None,
                 disabled_color: Optional[str] = None, active_color: Optional[str] = None):
        super().__init__()
        self.name = _canonical(name)
        self.color = color
        self.stroke = stroke
        self.disabled_color = disabled_color or _faded(color)
        self.active_color = active_color or color

    def _color(self, mode) -> str:
        if mode == QIcon.Disabled:
            return self.disabled_color
        if mode == QIcon.Active:
            return self.active_color
        return self.color

    def paint(self, painter, rect, mode, state):
        _renderer(self.name, self._color(mode), self.stroke).render(painter, QRectF(rect))

    def pixmap(self, size, mode, state):
        # Qt5 передает сюда уже физический размер (логический × масштаб экрана).
        key = ("engine", self.name, QColor(self._color(mode)).rgba(), size.width(), size.height(), self.stroke)
        cached = _pix_cache.get(key)
        if cached is not None:
            return cached
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        _pix_cache[key] = pixmap
        return pixmap

    def actualSize(self, size, mode, state):
        side = min(size.width(), size.height())
        return QSize(side, side)

    def clone(self):
        return SvgIconEngine(self.name, self.color, self.stroke, self.disabled_color, self.active_color)

    def key(self):
        return "BackupAppSvgIcon"


def _faded(color: str, alpha: float = 0.45) -> str:
    """Цвет «как при opacity .45» на белом фоне — так в макете выглядят недоступные кнопки."""
    c = QColor(color)
    r = round(c.red() * alpha + 255 * (1 - alpha))
    g = round(c.green() * alpha + 255 * (1 - alpha))
    b = round(c.blue() * alpha + 255 * (1 - alpha))
    return QColor(r, g, b).name()


def icon(name: str, color: str = "#3A4552", size: int = 16, stroke: Optional[float] = None,
         disabled_color: Optional[str] = None, active_color: Optional[str] = None) -> QIcon:
    """QIcon, рисуемый под любой размер и масштаб.

    size оставлен для совместимости: размер выбирает тот, кто рисует (setIconSize, меню и т. п.).
    """
    return QIcon(SvgIconEngine(name, color, stroke, disabled_color, active_color))


def clear_cache() -> None:
    """Сбросить кэш (например, после смены масштаба экрана)."""
    _pix_cache.clear()
    _renderer_cache.clear()
