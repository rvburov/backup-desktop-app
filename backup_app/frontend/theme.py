"""Оформление интерфейса: цвета (токены макета), шрифты, палитра и таблица стилей (QSS).

Все размеры и цвета взяты из CSS макета Main.dc.html. Правила для будущих правок — docs/UI_DESIGN.md.

Порядок запуска (см. app.py):
    enable_hidpi()            # до создания QApplication
    app = QApplication(argv)
    apply(app)                # стиль Fusion + шрифты + палитра + QSS

Варианты элементов задаются динамическими свойствами и подхватываются QSS:
    button.setProperty("variant", "primary")      # или set_props(button, variant="primary")
    frame.setProperty("kind", "card")
После смены свойства у уже показанного виджета нужен repolish(widget) — set_props делает это сам.

Рамка фокуса — только с клавиатуры: apply() ставит FocusTracker, он ведет свойство kbfocus="true"
(в QSS — [kbfocus="true"] вместо :focus, в paintEvent — has_keyboard_focus()).
"""
import os
from typing import Dict, Optional, Tuple

from PyQt5.QtCore import QEvent, QObject, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPainter, QPainterPath, QPalette, QPen
from PyQt5.QtWidgets import QAbstractButton, QApplication, QProxyStyle, QStyle, QStyleFactory, QWidget

from .resources import resource_path


class C:
    """Цветовые токены макета. Менять здесь — меняется во всем окне (QSS строится из них)."""

    WIN = "#F5F7FA"            # фон окна и рабочей области
    SIDE = "#ECEFF4"           # фон боковой панели
    CARD = "#FFFFFF"           # фон карточек, полей, строки состояния
    BORDER = "#DDE2E9"         # рамка карточек, верхняя граница панелей
    DIVIDER = "#EEF1F5"        # разделители внутри карточек, фон «сегментов»
    SIDE_DIVIDER = "#D6DCE4"   # разделитель в боковой панели
    RING = "#D3DAE3"           # обводка выбранной вкладки/сегмента, линия разделителя панелей
    INPUT = "#C9D0DA"          # рамка полей и обычных кнопок
    INPUT_HOVER = "#B7C0CC"    # рамка кнопки при наведении
    CHIP_HOVER = "#9FAAB8"     # рамка «дня недели» при наведении, рамка флажка
    TEXT = "#18202B"           # основной текст
    TEXT2 = "#3A4552"          # вторичный текст, иконки
    MUTED = "#5A6573"          # подсказки, подписи
    FAINT = "#8A94A3"          # совсем бледный текст, иконка карандаша, точка «выключено»
    ACCENT = "#1F5FD1"         # акцент: основная кнопка, переключатели, фокус
    ACCENT_HOVER = "#174FB3"
    ACCENT_SOFT = "#E8EFFC"    # фон «таблеток»
    ACCENT_SOFT_TEXT = "#1F4FA8"
    OK = "#17803D"             # зеленый: расписание запущено, успешный результат
    WARN = "#9A5A06"           # текст предупреждения
    WARN_ICON = "#B26A00"      # значок предупреждения
    DANGER = "#B42318"         # ошибка, кнопки удаления
    DANGER_HOVER = "#971D14"   # сплошная красная кнопка при наведении
    DANGER_BORDER = "#E9B8B2"
    DANGER_BORDER_HOVER = "#DC9A92"
    DANGER_SOFT = "#FDF1EF"    # фон красной кнопки при наведении, фон плашки ошибки
    NOTICE_TEXT = "#8E1C12"    # текст плашки ошибки
    FOLDER = "#A86A12"         # иконка папки в списке
    FILE = "#3F679F"           # иконка файла в списке
    SWITCH_OFF = "#B4BDC9"     # переключатель выключен
    HOVER = "#F1F4F8"          # фон обычной кнопки/пункта меню при наведении
    GHOST_HOVER = "#E6EAF0"    # фон «прозрачной» кнопки при наведении
    SIDE_HOVER = "#DFE4EB"     # строка вкладки при наведении
    SEG_HOVER = "#E3E8EF"      # сегмент при наведении; дорожка индикатора хода
    ROW_HOVER = "#F7F9FB"      # строка списка источников при наведении
    OPT_HOVER = "#F4F6F9"      # строка флажка при наведении; фон серых плашек-пояснений
    NOTE_BG = "#F4F6F9"        # серая плашка «Расписание остановлено…», пояснения
    FOOTER_BG = "#FAFBFC"      # подвал карточки «Так будет выглядеть копия»
    READONLY_BG = "#F8FAFC"    # поле только для чтения (папка назначения)
    SCROLL = "#AEB7C3"         # ползунок полосы прокрутки
    SCROLL_HOVER = "#8E99A7"
    SPLIT_GRIP = "#B9C1CC"     # «таблетка» на разделителе панелей
    TOAST_BG = "#1F2733"       # тост и подсказки
    TOAST_TEXT = "#D5DBE4"
    TOAST_INFO = "#7FB0FF"
    TOAST_WARN = "#F4B740"
    TOAST_OK = "#6FD08C"
    WHITE = "#FFFFFF"
    DIM = "rgba(16, 24, 40, 0.38)"  # затемнение под модальным окном


# Прозрачность недоступных элементов в макете (.btn:disabled{opacity:.45}).
DISABLED_OPACITY = 0.45

# Размеры (px) — общие для QSS и виджетов.
FIELD_HEIGHT = 32
FIELD_HEIGHT_SMALL = 30        # поле поиска вкладок (в макете height: 30px)
FIELD_HEIGHT_SEARCH = FIELD_HEIGHT_SMALL
BUTTON_HEIGHT = 32
BUTTON_HEIGHT_SMALL = 28
RADIUS_CARD = 8
RADIUS_FIELD = 6
BASE_FONT_PX = 13
LINE_HEIGHT = 1.4              # межстрочный интервал макета (body line-height)

# --------------------------------------------------------------------------- шрифты
# Начертания Golos Text из Google Fonts регистрируются как отдельные семейства (и в Windows, и в Linux),
# поэтому жирность задается именем семейства, а не font-weight (Qt5 к тому же сдвигает 500→63, 600→75).
FONT_FILES = ("GolosText-Regular.ttf", "GolosText-Medium.ttf", "GolosText-SemiBold.ttf", "JetBrainsMono-Regular.ttf")
_BUNDLED = {
    "regular": ("Golos Text", 400),
    "medium": ("Golos Text Medium", 400),
    "semibold": ("Golos Text SemiBold", 400),
    "mono": ("JetBrains Mono", 400),
}
# Текущие (семейство, font-weight для QSS) по ролям; load_fonts() заменяет на системные, если файлов нет.
_fonts: Dict[str, Tuple[str, int]] = dict(_BUNDLED)
_fonts_ok = False


def fonts_dir() -> str:
    return resource_path("fonts")


def load_fonts(folder: Optional[str] = None) -> bool:
    """Регистрирует шрифты из папки fonts/. Нужен существующий QApplication.

    True — все четыре начертания доступны. Иначе роли, для которых шрифта нет, получают системный
    шрифт с подходящей жирностью (font-weight), и интерфейс остается рабочим.
    """
    global _fonts_ok
    folder = folder or fonts_dir()
    if os.path.isdir(folder):
        for name in FONT_FILES:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                QFontDatabase.addApplicationFont(path)
    families = set(QFontDatabase().families())
    system = QFontDatabase.systemFont(QFontDatabase.GeneralFont).family()
    fixed = QFontDatabase.systemFont(QFontDatabase.FixedFont).family()
    # Qt5 переводит font-weight из QSS делением на 8: 456 → 57 (Medium), 504 → 63 (DemiBold);
    # «честные» 500/600 дали бы 63/75, то есть полужирный и жирный.
    fallback = {"regular": (system, 400), "medium": (system, 456), "semibold": (system, 504), "mono": (fixed, 400)}
    ok = True
    for role, (family, weight) in _BUNDLED.items():
        if family in families:
            _fonts[role] = (family, weight)
        else:
            _fonts[role] = fallback[role]
            ok = False
    _fonts_ok = ok
    return ok


def fonts_loaded() -> bool:
    """Все ли фирменные шрифты зарегистрированы последним вызовом load_fonts()."""
    return _fonts_ok


def family(role: str = "regular") -> str:
    """Имя семейства шрифта для роли: regular, medium, semibold, mono."""
    return _fonts[role][0]


def _dpi() -> float:
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    return screen.logicalDotsPerInchY() if screen is not None else 96.0


def px_to_pt(px: float) -> float:
    """Пиксели макета → пункты Qt с учетом логического DPI (нужно для дробных 12.5px, 13.5px)."""
    return px * 72.0 / _dpi()


def font(role: str = "regular", px: float = BASE_FONT_PX, letter_spacing: float = 0.0) -> QFont:
    """QFont для рисования вручную (делегаты, paintEvent). px может быть дробным."""
    name, weight = _fonts[role]
    f = QFont(name)
    f.setPointSizeF(px_to_pt(px))
    if weight != 400:
        f.setWeight(min(99, round(weight / 8)))  # так же, как Qt5 понимает font-weight в QSS
    if letter_spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, letter_spacing)
    return f


def font_exact(role: str = "regular", px: float = BASE_FONT_PX) -> QFont:
    """QFont для рисования с шириной текста как у дробного размера макета (11.5px, 12.5px).

    Qt5 округляет размер шрифта до целого пикселя (12.5 → 13), и текст выходит шире, чем в макете.
    Здесь берется меньший целый размер, а ширина знаков растягивается до дробного (PercentageSpacing).
    """
    whole = int(px)
    if whole == px or whole <= 0:
        return font(role, px)
    f = font(role, whole)
    f.setLetterSpacing(QFont.PercentageSpacing, px / whole * 100.0)
    return f


def font_px(f: QFont) -> float:
    """Размер шрифта в пикселях макета (дробный, как задан в QSS или font())."""
    return f.pixelSize() if f.pixelSize() > 0 else f.pointSizeF() / px_to_pt(1)


def exact(f: QFont) -> QFont:
    """Тот же шрифт с шириной текста как у дробного размера (см. font_exact); целый размер — без изменений."""
    px = font_px(f)
    whole = int(px + 0.01)
    if abs(px - whole) < 0.01 or whole <= 0:
        return f
    result = QFont(f)
    result.setPointSizeF(px_to_pt(whole))
    result.setLetterSpacing(QFont.PercentageSpacing, px / whole * 100.0)
    return result


def _fs(px: float) -> str:
    """font-size для QSS: целые px как есть, дробные — в pt (QSS не понимает дробные px)."""
    if float(px).is_integer():
        return f"font-size: {int(px)}px;"
    return f"font-size: {px_to_pt(px):.3f}pt;"


def qss_font(role: str = "regular", px: Optional[float] = None) -> str:
    """Фрагмент QSS: семейство, жирность и (если задан) размер."""
    name, weight = _fonts[role]
    text = f'font-family: "{name}"; font-weight: {weight};'
    if px is not None:
        text += " " + _fs(px)
    return text


# --------------------------------------------------------------------------- цвета
def mix(color: str, background: str, alpha: float) -> str:
    """Цвет color с прозрачностью alpha поверх background (как CSS opacity)."""
    a, b = QColor(color), QColor(background)
    return QColor(round(a.red() * alpha + b.red() * (1 - alpha)),
                  round(a.green() * alpha + b.green() * (1 - alpha)),
                  round(a.blue() * alpha + b.blue() * (1 - alpha))).name().upper()


def faded(color: str, background: str = C.CARD) -> str:
    """Цвет недоступного элемента (opacity .45 в макете)."""
    return mix(color, background, DISABLED_OPACITY)


def build_palette() -> QPalette:
    """Светлая палитра: окно не «темнеет» в темной теме Windows/KDE/macOS, QSS задает остальное."""
    pal = QPalette()
    roles = {
        QPalette.Window: C.WIN, QPalette.WindowText: C.TEXT, QPalette.Base: C.CARD,
        QPalette.AlternateBase: C.ROW_HOVER, QPalette.Text: C.TEXT, QPalette.Button: C.CARD,
        QPalette.ButtonText: C.TEXT, QPalette.BrightText: C.WHITE, QPalette.Highlight: C.ACCENT,
        QPalette.HighlightedText: C.WHITE, QPalette.ToolTipBase: C.TOAST_BG, QPalette.ToolTipText: C.WHITE,
        QPalette.Link: C.ACCENT, QPalette.LinkVisited: C.ACCENT_HOVER, QPalette.Light: C.WHITE,
        QPalette.Midlight: C.DIVIDER, QPalette.Mid: C.INPUT, QPalette.Dark: C.FAINT, QPalette.Shadow: C.TEXT2,
    }
    for role, value in roles.items():
        pal.setColor(role, QColor(value))
    pal.setColor(QPalette.PlaceholderText, QColor(C.FAINT))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(faded(C.TEXT)))
    pal.setColor(QPalette.Disabled, QPalette.Highlight, QColor(faded(C.ACCENT)))
    return pal


# --------------------------------------------------------------------------- QSS
# Размер шрифта (px) однострочных надписей QLabel[kind]: высота строки = px * LINE_HEIGHT.
_TEXT_KINDS = {
    "h1": 18, "h2": 13.5, "h3": 13, "medium": 13, "semibold": 13, "muted": 12, "muted-sm": 11.5,
    "secondary": 12.5, "secondary-muted": 12.5, "faint": 12, "caps": 11, "count": 11, "warn": 12, "danger": 11.5,
    "ok": 12.5, "detail": 12, "result": 12.5,
    "status": 12.5, "mono": 11, "mono-body": 12, "mono-time": 11.5,
}


def line_box(px: float) -> int:
    """Высота строки текста размером px (line-height 1.4 макета), округленная до пикселя."""
    return int(px * LINE_HEIGHT + 0.5)


def _line_boxes() -> str:
    return "\n".join(f'QLabel[kind="{kind}"] {{ min-height: {line_box(px)}px; }}' for kind, px in _TEXT_KINDS.items())


def build_stylesheet() -> str:
    """Полная таблица стилей приложения. Вызывать после load_fonts()."""
    reg, med, semi, mono = (qss_font(r) for r in ("regular", "medium", "semibold", "mono"))
    dis_text = faded(C.TEXT)
    dis_border = faded(C.INPUT)
    dis_primary = mix(C.ACCENT, C.WIN, DISABLED_OPACITY)
    dis_primary_text = mix(C.WHITE, C.WIN, DISABLED_OPACITY)
    dis_ghost = faded(C.TEXT2)
    dis_danger = faded(C.DANGER)
    dis_danger_border = faded(C.DANGER_BORDER)
    return f"""
/* ---------- основа ---------- */
QWidget {{ {reg} {_fs(13)} color: {C.TEXT}; }}
QMainWindow, QDialog {{ background: {C.WIN}; }}
QWidget[kind="page"], QStackedWidget[kind="page"] {{ background: {C.WIN}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QLabel {{ background: transparent; }}

/* ---------- текст: QLabel[kind=...] ---------- */
QLabel[kind="h1"] {{ {semi} {_fs(18)} }}
QLabel[kind="h2"] {{ {semi} {_fs(13.5)} }}
QLabel[kind="h3"], QWidget[kind="h3"] {{ {semi} {_fs(13)} }}
QLabel[kind="medium"], QWidget[kind="medium"] {{ {med} }}
QLabel[kind="semibold"], QWidget[kind="semibold"] {{ {semi} }}
QLabel[kind="muted"], QWidget[kind="muted"] {{ {_fs(12)} color: {C.MUTED}; }}
QLabel[kind="muted-sm"] {{ {_fs(11.5)} color: {C.MUTED}; }}
QLabel[kind="secondary"], QWidget[kind="secondary"] {{ {_fs(12.5)} color: {C.TEXT2}; }}
QLabel[kind="secondary-muted"], QWidget[kind="secondary-muted"] {{ {_fs(12.5)} color: {C.MUTED}; }}
QLabel[kind="faint"] {{ {_fs(12)} color: {C.FAINT}; }}
QLabel[kind="caps"] {{ {semi} {_fs(11)} color: {C.MUTED}; }}
QLabel[kind="count"] {{ {_fs(11)} color: {C.MUTED}; }}
QLabel[kind="warn"], QWidget[kind="warn"] {{ {_fs(12)} color: {C.WARN}; }}
QLabel[kind="danger"], QWidget[kind="danger"] {{ {_fs(11.5)} color: {C.DANGER}; }}
QLabel[kind="ok"] {{ {med} {_fs(12.5)} color: {C.OK}; }}
QLabel[kind="mono"], QWidget[kind="mono"] {{ {mono} {_fs(11)} color: {C.MUTED}; }}
QLabel[kind="mono-body"], QWidget[kind="mono-body"] {{ {mono} {_fs(12)} color: {C.TEXT}; }}
QLabel[kind="mono-time"] {{ {mono} {_fs(11.5)} color: {C.MUTED}; }}
QLabel[kind="detail"] {{ {_fs(12)} color: {C.TEXT2}; }}
QLabel[kind="result"] {{ {semi} {_fs(12.5)} color: {C.OK}; }}
QLabel[kind="result"][tone="warn"] {{ color: {C.WARN}; }}
QLabel[kind="result"][tone="danger"] {{ color: {C.DANGER}; }}
QLabel[kind="result-icon"] {{ {semi} {_fs(13)} color: {C.OK}; }}
QLabel[kind="result-icon"][tone="warn"] {{ color: {C.WARN}; }}
QLabel[kind="result-icon"][tone="danger"] {{ color: {C.DANGER}; }}
QLabel[kind="status"] {{ {_fs(12.5)} color: {C.MUTED}; }}
QLabel[kind="status"][tone="run"] {{ color: {C.ACCENT}; }}
QLabel[kind="status"][tone="warn"] {{ color: {C.WARN}; }}
QLabel[kind="status"][tone="ok"] {{ color: {C.OK}; }}
QLabel[kind="status"][tone="danger"] {{ color: {C.DANGER}; }}
QWidget[kind="toast-title"] {{ {semi} {_fs(13)} color: {C.WHITE}; }}
QWidget[kind="toast-text"] {{ {_fs(12.5)} color: {C.TOAST_TEXT}; }}
QWidget[kind="dialog-title"] {{ {semi} {_fs(15)} color: {C.TEXT}; }}
QWidget[kind="dialog-text"] {{ {_fs(13)} color: {C.TEXT2}; }}
QLabel[kind="badge"] {{ {med} {_fs(11.5)} color: {C.ACCENT_SOFT_TEXT}; background: {C.ACCENT_SOFT};
    border-radius: 9px; padding: 2px 8px; }}
QLabel[kind="pill"] {{ {_fs(12)} color: {C.ACCENT_SOFT_TEXT}; background: {C.ACCENT_SOFT};
    border-radius: 9px; padding: 2px 9px; }}
QLabel[kind="note"], QWidget[kind="note"] {{ {_fs(12.5)} color: {C.MUTED}; background: {C.NOTE_BG};
    border-radius: 6px; padding: 10px 12px; }}
QLabel[kind="note-sm"], QWidget[kind="note-sm"] {{ {_fs(12)} color: {C.MUTED}; background: {C.NOTE_BG};
    border-radius: 6px; padding: 9px 11px; }}
QLabel[kind="empty"], QWidget[kind="empty"] {{ {_fs(12.5)} color: {C.MUTED}; border: 1px dashed {C.INPUT};
    border-radius: 8px; padding: 18px 12px; }}
/* строка текста высотой line-height 1.4, как в макете (текст по центру строки) */
{_line_boxes()}

/* ---------- поверхности: QFrame[kind=...] ---------- */
QFrame[kind="sidebar"] {{ background: {C.SIDE}; }}
QFrame[kind="card"] {{ background: {C.CARD}; border: 1px solid {C.BORDER}; border-radius: {RADIUS_CARD}px; }}
QFrame[kind="card"] QFrame[kind="card-section"] {{ background: transparent; border: none; }}
QFrame[kind="card-footer"] {{ background: {C.FOOTER_BG}; border: none; border-top: 1px solid {C.DIVIDER};
    border-bottom-left-radius: 7px; border-bottom-right-radius: 7px; }}
QFrame[kind="divider"] {{ background: {C.DIVIDER}; border: none; min-height: 1px; max-height: 1px; }}
QFrame[kind="vdivider"] {{ background: {C.DIVIDER}; border: none; min-width: 1px; max-width: 1px; }}
QFrame[kind="side-divider"] {{ background: {C.SIDE_DIVIDER}; border: none; min-height: 1px; max-height: 1px; }}
QFrame[kind="col-left"] {{ background: transparent; border: none; border-right: 1px solid {C.DIVIDER}; }}
QFrame[kind="panel"] {{ background: {C.CARD}; border: none; border-top: 1px solid {C.BORDER}; }}
QFrame[kind="row"] {{ background: transparent; border: none; border-top: 1px solid {C.DIVIDER}; }}
QFrame[kind="row"]:hover {{ background: {C.ROW_HOVER}; }}
QFrame[kind="row-plain"] {{ background: transparent; border: none; border-top: 1px solid {C.DIVIDER}; }}
QFrame[kind="notice"] {{ background: {C.DANGER_SOFT}; border: none; border-radius: 6px; }}
QFrame[kind="notice"] QWidget {{ color: {C.NOTICE_TEXT}; {_fs(12.5)} }}
QFrame[kind="note"] {{ background: {C.NOTE_BG}; border: none; border-radius: 6px; }}
QFrame[kind="stepper"] {{ background: {C.CARD}; border: 1px solid {C.INPUT}; border-radius: 6px; }}
QFrame[kind="toast"] {{ background: {C.TOAST_BG}; border: none; border-radius: 10px; }}
QFrame[kind="toast"] QLabel {{ color: {C.WHITE}; }}
QFrame[kind="dialog"] {{ background: {C.CARD}; border: none; border-radius: 10px; }}
QWidget[kind="option"] {{ background: transparent; border-radius: 6px; }}
QWidget[kind="option"]:hover {{ background: {C.OPT_HOVER}; }}

/* ---------- кнопки ---------- */
QPushButton, QToolButton {{ {med} {_fs(13)} color: {C.TEXT}; background: {C.CARD}; border: 1px solid {C.INPUT};
    border-radius: 6px; padding: 0 12px; min-height: {BUTTON_HEIGHT - 2}px; }}
QPushButton:hover, QToolButton:hover {{ background: {C.HOVER}; border-color: {C.INPUT_HOVER}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {C.GHOST_HOVER}; }}
QPushButton[kbfocus="true"], QToolButton[kbfocus="true"] {{ border-color: {C.ACCENT}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {dis_text}; background: {C.CARD}; border-color: {dis_border}; }}
QPushButton[small="true"], QToolButton[small="true"] {{ {_fs(12.5)} padding: 0 9px;
    min-height: {BUTTON_HEIGHT_SMALL - 2}px; }}
QPushButton[iconOnly="true"], QToolButton[iconOnly="true"] {{ padding: 0; }}
QPushButton::menu-indicator, QToolButton::menu-indicator {{ image: none; width: 0; }}

QPushButton[variant="primary"] {{ background: {C.ACCENT}; border-color: {C.ACCENT}; color: {C.WHITE}; }}
QPushButton[variant="primary"]:hover {{ background: {C.ACCENT_HOVER}; border-color: {C.ACCENT_HOVER}; }}
QPushButton[variant="primary"][kbfocus="true"] {{ border-color: #0B2F75; }}
QPushButton[variant="primary"]:disabled {{ background: {dis_primary}; border-color: {dis_primary};
    color: {dis_primary_text}; }}

QPushButton[variant="ghost"], QToolButton[variant="ghost"] {{ background: transparent; border-color: transparent;
    color: {C.TEXT2}; }}
QPushButton[variant="ghost"]:hover, QToolButton[variant="ghost"]:hover {{ background: {C.GHOST_HOVER};
    border-color: transparent; }}
QPushButton[variant="ghost"]:pressed, QToolButton[variant="ghost"]:pressed {{ background: {C.SEG_HOVER}; }}
QPushButton[variant="ghost"][kbfocus="true"], QToolButton[variant="ghost"][kbfocus="true"] {{ border-color: {C.ACCENT}; }}
QPushButton[variant="ghost"]:disabled, QToolButton[variant="ghost"]:disabled {{ background: transparent;
    border-color: transparent; color: {dis_ghost}; }}

QPushButton[variant="link"] {{ background: transparent; border-color: transparent; color: {C.ACCENT};
    text-align: left; padding-left: 9px; }}
QPushButton[variant="link"]:hover {{ background: {C.SIDE_HOVER}; border-color: transparent; }}
QPushButton[variant="link"][kbfocus="true"] {{ border-color: {C.ACCENT}; }}
QPushButton[variant="link"]:disabled {{ background: transparent; color: {faded(C.ACCENT)}; }}

QPushButton[variant="danger"] {{ color: {C.DANGER}; border-color: {C.DANGER_BORDER}; }}
QPushButton[variant="danger"]:hover {{ background: {C.DANGER_SOFT}; border-color: {C.DANGER_BORDER_HOVER}; }}
QPushButton[variant="danger"][kbfocus="true"] {{ border-color: {C.DANGER}; }}
QPushButton[variant="danger"]:disabled {{ background: {C.CARD}; color: {dis_danger}; border-color: {dis_danger_border}; }}

QPushButton[variant="danger-solid"] {{ background: {C.DANGER}; border-color: {C.DANGER}; color: {C.WHITE}; }}
QPushButton[variant="danger-solid"]:hover {{ background: {C.DANGER_HOVER}; border-color: {C.DANGER_HOVER}; }}
QPushButton[variant="danger-solid"][kbfocus="true"] {{ border-color: #5C0F09; }}

QPushButton[variant="toast-close"] {{ background: transparent; border-color: transparent; min-height: 22px;
    max-height: 22px; }}
QPushButton[variant="toast-close"]:hover {{ background: rgba(255, 255, 255, 0.12); }}
QPushButton[variant="toast-close"][kbfocus="true"] {{ border-color: {C.TOAST_INFO}; }}
QPushButton[variant="notice-close"] {{ background: transparent; border-color: transparent; min-height: 20px;
    max-height: 20px; }}
QPushButton[variant="notice-close"]:hover {{ background: rgba(142, 28, 18, 0.08); }}
QPushButton[variant="notice-close"][kbfocus="true"] {{ border-color: {C.NOTICE_TEXT}; }}
QPushButton[variant="stepper"] {{ background: transparent; border: 1px solid transparent; border-radius: 0;
    color: {C.TEXT2}; padding: 0; }}
QPushButton[variant="stepper"]:hover {{ background: {C.GHOST_HOVER}; }}
QPushButton[variant="stepper"][kbfocus="true"] {{ border-color: {C.ACCENT}; }}

/* пункт боковой панели («Настройки»): как строка вкладки */
QPushButton[variant="nav"] {{ background: transparent; border: 1px solid transparent; border-radius: 6px;
    text-align: left; padding: 0 9px; min-height: 30px; }}
QPushButton[variant="nav"]:hover {{ background: {C.SIDE_HOVER}; }}
QPushButton[variant="nav"]:checked {{ background: {C.CARD}; border-color: {C.RING}; }}
QPushButton[variant="nav"][kbfocus="true"] {{ border-color: {C.ACCENT}; }}

/* ---------- переключатель периодов и дни недели ---------- */
QFrame[kind="segmented"] {{ background: {C.DIVIDER}; border: none; border-radius: 7px; }}
QPushButton[kind="seg"] {{ {med} {_fs(12.5)} background: transparent; border: 1px solid transparent;
    border-radius: 5px; padding: 0 10px; min-height: 26px; max-height: 26px; color: {C.TEXT2}; }}
QPushButton[kind="seg"]:hover {{ background: {C.SEG_HOVER}; }}
QPushButton[kind="seg"]:checked {{ background: {C.CARD}; color: {C.TEXT}; border-color: {C.RING};
    border-bottom-color: #C5CDD8; }}
QPushButton[kind="seg"][kbfocus="true"] {{ border-color: {C.ACCENT}; }}
QPushButton[kind="chip"] {{ {med} {_fs(12)} background: {C.CARD}; border: 1px solid {C.INPUT}; border-radius: 5px;
    padding: 0; min-height: 26px; max-height: 26px; min-width: 32px; max-width: 32px; color: {C.TEXT2}; }}
QPushButton[kind="chip"]:hover {{ border-color: {C.CHIP_HOVER}; }}
QPushButton[kind="chip"]:checked {{ background: {C.ACCENT}; border-color: {C.ACCENT}; color: {C.WHITE}; }}
QPushButton[kind="chip"][kbfocus="true"] {{ border-color: {C.ACCENT_HOVER}; }}
QPushButton[kind="chip"][kbfocus="true"]:checked {{ border-color: #0B2F75; }}

/* ---------- поля ввода ---------- */
QLineEdit, QAbstractSpinBox {{ {reg} {_fs(13)} background: {C.CARD}; border: 1px solid {C.INPUT};
    border-radius: 6px; padding: 0 8px; min-height: {FIELD_HEIGHT - 2}px; max-height: {FIELD_HEIGHT - 2}px;
    color: {C.TEXT};
    selection-background-color: {C.ACCENT}; selection-color: {C.WHITE}; }}
QLineEdit:focus, QAbstractSpinBox:focus {{ border-color: {C.ACCENT}; }}
QLineEdit:disabled, QAbstractSpinBox:disabled {{ color: {dis_text}; background: {C.READONLY_BG};
    border-color: {dis_border}; }}
QLineEdit[readOnly="true"] {{ background: {C.READONLY_BG}; }}
QLineEdit[mono="true"] {{ {mono} {_fs(12)} }}
QLineEdit[small="true"] {{ {_fs(12.5)} min-height: {FIELD_HEIGHT_SMALL - 2}px;
    max-height: {FIELD_HEIGHT_SMALL - 2}px; }}
QLineEdit[kind="title"] {{ {semi} {_fs(18)} background: transparent; border: 1px solid transparent;
    padding: 2px 6px; min-height: 27px; max-height: 32px; }}
QLineEdit[kind="title"]:hover {{ background: {C.CARD}; border-color: {C.INPUT}; }}
QLineEdit[kind="title"]:focus {{ background: {C.CARD}; border-color: {C.ACCENT}; }}
/* у счетчиков нет стрелок, как у полей макета: значение вводится с клавиатуры, стрелками или колесом */
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0; border: none; background: transparent; }}

/* ---------- флажки ---------- */
QCheckBox {{ spacing: 9px; background: transparent; color: {C.TEXT}; }}
QCheckBox:disabled {{ color: {dis_text}; }}
QCheckBox[kind="filter"] {{ {_fs(12.5)} color: {C.TEXT2}; spacing: 6px; }}
QRadioButton {{ spacing: 8px; background: transparent; }}

/* ---------- полосы прокрутки: тонкие, как в боковой панели макета ---------- */
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; border: none; }}
QScrollBar::handle:vertical {{ background: {C.SCROLL}; border-radius: 2px; min-height: 28px; margin: 2px; }}
QScrollBar::handle:vertical:hover, QScrollBar::handle:vertical:pressed {{ background: {C.SCROLL_HOVER}; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; border: none; }}
QScrollBar::handle:horizontal {{ background: {C.SCROLL}; border-radius: 2px; min-width: 28px; margin: 2px; }}
QScrollBar::handle:horizontal:hover, QScrollBar::handle:horizontal:pressed {{ background: {C.SCROLL_HOVER}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: transparent; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- списки ---------- */
QListView, QTreeView, QListWidget, QTreeWidget {{ background: transparent; border: none; outline: 0; }}
QListView[kind="tabs"] {{ background: {C.SIDE}; }}

/* ---------- меню (трей) ---------- */
QMenu {{ background: {C.CARD}; border: 1px solid {C.RING}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ {_fs(13)} color: {C.TEXT}; background: transparent; padding: 0 14px 0 10px; min-height: 32px;
    border-radius: 5px; }}
QMenu::item:selected {{ background: {C.HOVER}; }}
QMenu::item:disabled {{ color: {C.FAINT}; background: transparent; }}
QMenu::icon {{ padding-left: 10px; }}
QMenu::separator {{ height: 1px; background: {C.DIVIDER}; margin: 4px 6px; }}

/* ---------- подсказки и системные окна ---------- */
QToolTip {{ {reg} {_fs(12)} color: {C.WHITE}; background: {C.TOAST_BG}; border: 1px solid {C.TOAST_BG};
    padding: 4px 7px; }}
QMessageBox {{ background: {C.CARD}; }}
QMessageBox QLabel {{ {_fs(13)} color: {C.TEXT2}; }}
QMessageBox QLabel#qt_msgbox_label {{ {med} color: {C.TEXT}; }}
QMessageBox QPushButton {{ min-width: 72px; }}
QDialogButtonBox QPushButton {{ min-width: 72px; }}

/* ---------- ход копирования (если используется обычный QProgressBar) ---------- */
QProgressBar {{ background: {C.SEG_HOVER}; border: none; border-radius: 3px; min-height: 6px; max-height: 6px;
    color: transparent; }}
QProgressBar::chunk {{ background: {C.ACCENT}; border-radius: 3px; }}
"""


# --------------------------------------------------------------------------- фокус с клавиатуры
KBFOCUS = "kbfocus"
KEYBOARD_REASONS = (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)
_MOUSE_EVENTS = frozenset((QEvent.MouseButtonPress, QEvent.MouseButtonDblClick, QEvent.TouchBegin))


class FocusTracker(QObject):
    """Рамка фокуса только при работе с клавиатуры (button:focus-visible макета).

    Фильтр событий приложения (ставит apply()). Виджет, получивший фокус клавишей (Tab, Shift+Tab,
    сочетание, стрелки), получает свойство kbfocus="true"; уход фокуса или щелчок мышью его снимают.
    QSS рисует рамку по [kbfocus="true"], нарисованные вручную элементы спрашивают has_keyboard_focus().
    Причины фокуса мало: Qt сам переводит фокус «по Tab», когда скрывается виджет с фокусом (например,
    при смене страницы щелчком), поэтому учитывается и то, чем пользователь действовал последним.
    """

    def __init__(self):
        super().__init__()
        self.mouse_mode = False

    def is_keyboard(self, reason) -> bool:
        return reason in KEYBOARD_REASONS and not self.mouse_mode

    def eventFilter(self, obj, event):  # noqa: N802
        kind = event.type()
        if kind in _MOUSE_EVENTS:
            self.mouse_mode = True
            focused = QApplication.focusWidget()
            if focused is not None:
                _set_kbfocus(focused, False)
        elif kind == QEvent.KeyPress:
            self.mouse_mode = False
        elif kind == QEvent.FocusIn:
            if obj.isWidgetType():
                _set_kbfocus(obj, self.is_keyboard(event.reason()))
        elif kind == QEvent.FocusOut:
            if obj.isWidgetType():
                _set_kbfocus(obj, False)
        return False


_tracker: Optional[FocusTracker] = None


def focus_tracker() -> FocusTracker:
    """Общий FocusTracker приложения (создается при первом обращении)."""
    global _tracker
    if _tracker is None:
        _tracker = FocusTracker()
    return _tracker


def _set_kbfocus(widget: QWidget, on: bool) -> None:
    value = "true" if on else None
    if widget.property(KBFOCUS) == value:
        return
    widget.setProperty(KBFOCUS, value)
    if isinstance(widget, QAbstractButton):
        repolish(widget)
    else:
        widget.update()


def has_keyboard_focus(widget: Optional[QWidget]) -> bool:
    """Есть ли у виджета фокус, полученный с клавиатуры (тогда рисуется рамка фокуса)."""
    return widget is not None and widget.hasFocus() and widget.property(KBFOCUS) == "true"


def keyboard_focus_reason(reason) -> bool:
    """Пришел ли фокус с такой причиной от клавиатуры (для focusInEvent своих виджетов)."""
    return focus_tracker().is_keyboard(reason)


# --------------------------------------------------------------------------- стиль Qt
class AppStyle(QProxyStyle):
    """Fusion + флажок и стрелки счетчика как в макете (рисуются вектором, без файлов-картинок)."""

    INDICATOR = 15

    def __init__(self):
        super().__init__(QStyleFactory.create("Fusion"))

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (QStyle.PM_IndicatorWidth, QStyle.PM_IndicatorHeight):
            return self.INDICATOR
        return super().pixelMetric(metric, option, widget)

    def styleHint(self, hint, option=None, widget=None, data=None):
        if hint == QStyle.SH_ToolTip_WakeUpDelay:
            return 500
        return super().styleHint(hint, option, widget, data)

    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PE_IndicatorCheckBox:
            self._draw_checkbox(option, painter, widget)
            return
        if element in (QStyle.PE_IndicatorSpinUp, QStyle.PE_IndicatorSpinDown,
                       QStyle.PE_IndicatorArrowUp, QStyle.PE_IndicatorArrowDown):
            up = element in (QStyle.PE_IndicatorSpinUp, QStyle.PE_IndicatorArrowUp)
            self._draw_chevron(option, painter, up)
            return
        super().drawPrimitive(element, option, painter, widget)

    @staticmethod
    def _draw_checkbox(option, painter, widget=None):
        enabled = bool(option.state & QStyle.State_Enabled)
        checked = bool(option.state & (QStyle.State_On | QStyle.State_NoChange))
        hover = bool(option.state & QStyle.State_MouseOver)
        # рамка фокуса — только при работе с клавиатуры (у флажка-виджета; без виджета — по состоянию)
        focus = bool(option.state & QStyle.State_HasFocus) and (
            not isinstance(widget, QWidget) or widget.property(KBFOCUS) == "true")
        side = min(option.rect.width(), option.rect.height(), AppStyle.INDICATOR)
        rect = QRectF(option.rect.x() + (option.rect.width() - side) / 2,
                      option.rect.y() + (option.rect.height() - side) / 2, side, side)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if checked:
            fill = C.ACCENT_HOVER if hover else C.ACCENT
            if not enabled:
                fill = faded(C.ACCENT)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(fill))
            painter.drawRoundedRect(rect, 3, 3)
            pen = QPen(QColor(C.WHITE), max(1.6, side / 8.0), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            path = QPainterPath()
            if option.state & QStyle.State_NoChange:
                path.moveTo(rect.left() + side * 0.27, rect.center().y())
                path.lineTo(rect.right() - side * 0.27, rect.center().y())
            else:
                path.moveTo(rect.left() + side * 0.24, rect.top() + side * 0.53)
                path.lineTo(rect.left() + side * 0.43, rect.top() + side * 0.71)
                path.lineTo(rect.left() + side * 0.77, rect.top() + side * 0.31)
            painter.drawPath(path)
        else:
            border = C.ACCENT if (hover or focus) and enabled else ("#767F8C" if enabled else faded("#767F8C"))
            painter.setPen(QPen(QColor(border), 1))
            painter.setBrush(QColor(C.CARD))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 2.5, 2.5)
        if focus and enabled:
            painter.setPen(QPen(QColor(C.ACCENT), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 4.5, 4.5)
        painter.restore()

    @staticmethod
    def _draw_chevron(option, painter, up):
        enabled = bool(option.state & QStyle.State_Enabled)
        color = QColor(C.TEXT2 if enabled else faded(C.TEXT2))
        r = QRectF(option.rect)
        cx, cy = r.center().x(), r.center().y()
        w, h = 3.5, 2.0
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        path = QPainterPath()
        if up:
            path.moveTo(cx - w, cy + h / 2)
            path.lineTo(cx, cy - h / 2 - 0.5)
            path.lineTo(cx + w, cy + h / 2)
        else:
            path.moveTo(cx - w, cy - h / 2)
            path.lineTo(cx, cy + h / 2 + 0.5)
            path.lineTo(cx + w, cy - h / 2)
        painter.drawPath(path)
        painter.restore()


# --------------------------------------------------------------------------- применение
def enable_hidpi() -> None:
    """Масштабирование под HiDPI (в т. ч. дробные 125/150 %). Только до создания QApplication."""
    if QApplication.instance() is not None:
        return
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


def apply(app: QApplication, fonts_folder: Optional[str] = None) -> bool:
    """Стиль, шрифты, палитра и QSS для всего приложения. Возвращает load_fonts()."""
    app.setStyle(AppStyle())
    app.installEventFilter(focus_tracker())  # повторная установка не дублирует фильтр
    ok = load_fonts(fonts_folder)
    base = font("regular", BASE_FONT_PX)
    app.setFont(base)
    app.setPalette(build_palette())
    app.setStyleSheet(build_stylesheet())
    return ok


def repolish(widget: QWidget) -> None:
    """Пересчитать QSS виджета после смены динамического свойства."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_props(widget: QWidget, **props) -> QWidget:
    """Задать динамические свойства (variant, kind, small, ...) и сразу обновить вид. Возвращает widget.

    None удаляет свойство. Пример: set_props(button, variant="danger", small=True).
    """
    changed = False
    for name, value in props.items():
        if value is None:
            if widget.property(name) is not None:
                widget.setProperty(name, None)
                changed = True
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        if widget.property(name) != value:
            widget.setProperty(name, value)
            changed = True
    if changed:
        repolish(widget)
    return widget
