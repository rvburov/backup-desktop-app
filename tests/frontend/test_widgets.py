"""Оформление и готовые элементы интерфейса: собираются без экрана и ведут себя как в макете."""
import math

import pytest
from PyQt5.QtCore import QEvent, QObject, QPoint, Qt, QTimer, qInstallMessageHandler
from PyQt5.QtGui import QColor, QFont, QIcon
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QMenu, QStackedWidget, QStyle,
                             QStyleOptionButton, QVBoxLayout, QWidget)

from backup_app.frontend import icons, theme
from backup_app.frontend import widgets as W
from backup_app.frontend.theme import C
from helpers import wait_for


@pytest.fixture
def themed(qapp):
    theme.apply(qapp)
    return qapp


@pytest.fixture
def host(themed):
    """Окно-родитель для виджетов; закрывается после теста."""
    w = QWidget()
    w.resize(800, 600)
    yield w
    w.close()
    w.deleteLater()


def pump(_widget=None, n=5):
    for _ in range(n):
        QApplication.processEvents()


def show_in(host, widget, width=None):
    lay = host.layout() or QVBoxLayout(host)
    lay.addWidget(widget)
    if width:
        host.setFixedWidth(width)
    host.show()
    QTest.qWaitForWindowExposed(host)
    return widget


def collect(signal):
    got = []
    signal.connect(lambda *args: got.append(args[0] if len(args) == 1 else args))
    return got


# --------------------------------------------------------------------------- оформление
def test_fonts_register(themed):
    assert theme.load_fonts() is True
    assert theme.fonts_loaded()
    assert theme.family("regular") == "Golos Text"
    assert theme.family("semibold") == "Golos Text SemiBold"
    assert theme.family("mono") == "JetBrains Mono"


def test_fonts_fall_back_to_system(themed, monkeypatch, tmp_path):
    monkeypatch.setitem(theme._BUNDLED, "semibold", ("Нет Такого Шрифта", 400))
    try:
        assert theme.load_fonts(str(tmp_path)) is False
        assert theme.family("semibold") != "Нет Такого Шрифта"
        assert theme.font("semibold", 13).weight() == QFont.DemiBold
        # Qt5 делит font-weight из QSS на 8: заголовок должен стать DemiBold (63), а не Bold (75)
        h2 = QLabel("Заголовок")
        h2.setProperty("kind", "h2")
        h2.setStyleSheet(theme.build_stylesheet())
        h2.ensurePolished()
        assert h2.font().weight() == QFont.DemiBold
        monkeypatch.setitem(theme._BUNDLED, "medium", ("Нет Такого Шрифта", 400))
        theme.load_fonts(str(tmp_path))
        assert theme.font("medium", 13).weight() == QFont.Medium
        button = QLabel("Кнопка")
        button.setProperty("kind", "medium")
        button.setStyleSheet(theme.build_stylesheet())
        button.ensurePolished()
        assert button.font().weight() == QFont.Medium
    finally:
        monkeypatch.undo()
        assert theme.load_fonts() is True


def test_stylesheet_parses_and_covers_variants(themed):
    warnings = []
    previous = qInstallMessageHandler(lambda mode, ctx, msg: warnings.append(msg))
    try:
        qss = theme.build_stylesheet()
        themed.setStyleSheet(qss)
        w = QWidget()
        w.setStyleSheet("")  # заставляет Qt разобрать таблицу стилей приложения
        w.ensurePolished()
    finally:
        qInstallMessageHandler(previous)
    assert not [m for m in warnings if "style" in m.lower()], warnings
    assert qss.count("{") == qss.count("}")
    for selector in ('[variant="primary"]', '[variant="ghost"]', '[variant="danger"]', '[variant="danger-solid"]',
                     '[small="true"]', '[iconOnly="true"]', ":disabled", "QLineEdit", "QAbstractSpinBox",
                     "QCheckBox", '[kind="card"]', '[kind="divider"]', '[kind="notice"]', '[kind="badge"]',
                     '[kind="segmented"]', '[kind="seg"]', '[kind="chip"]', "QScrollBar",
                     "QMenu", "QMessageBox"):
        assert selector in qss, selector
    assert C.ACCENT in qss and C.BORDER in qss
    assert "QToolTip" not in qss  # всплывающих подсказок в программе нет


def test_helpers_mix_and_props(themed):
    assert theme.mix("#000000", "#FFFFFF", 0.5) == "#808080"
    assert theme.faded(C.TEXT) != C.TEXT
    b = W.Button("Кнопка")
    theme.set_props(b, variant="primary", small=True)
    assert b.property("variant") == "primary"
    assert b.property("small") == "true"
    theme.set_props(b, variant=None)
    assert b.property("variant") is None


def test_palette_is_light(themed):
    pal = theme.build_palette()
    assert pal.color(pal.Window).name().upper() == C.WIN
    assert pal.color(pal.Highlight).name().upper() == C.ACCENT


def test_px_to_pt_round_trip(themed):
    f = theme.font("regular", 12.5)
    dpi = themed.primaryScreen().logicalDotsPerInchY()
    assert abs(f.pointSizeF() * dpi / 72 - 12.5) < 0.01


# --------------------------------------------------------------------------- иконки
def test_every_icon_renders_hidpi(themed):
    for name in icons.NAMES:
        for dpr in (1.0, 1.25, 2.0):
            pm = icons.pix(name, C.TEXT2, 16, dpr=dpr)
            assert not pm.isNull()
            assert pm.width() == int(-(-16 * dpr // 1))
            assert abs(pm.devicePixelRatio() * 16 - pm.width()) < 0.01
            image = pm.toImage()
            assert any(QColor.fromRgba(image.pixel(x, y)).alpha() > 0
                       for x in range(image.width()) for y in range(image.height())), name


def test_icon_names_aliases_and_cache(themed):
    assert icons.pix("folder_plus", C.TEXT, 15) is icons.pix("folder-plus", C.TEXT, 15)
    for name in ("shield", "shield-plain", "minus-circle", "off", "window", "logout", "monitor", "play"):
        assert not icons.pix(name, C.TEXT, 16).isNull()
    with pytest.raises(KeyError):
        icons.pix("no-such-icon", C.TEXT, 16)
    assert 'stroke="#1f5fd1"' in icons.svg_text("shield", C.ACCENT).lower()
    assert 'fill="#3a4552"' in icons.svg_text("play", C.TEXT2).lower()


def test_icon_engine_has_disabled_color(themed):
    icon = icons.icon("trash", "#000000", disabled_color="#FF0000")
    normal = icon.pixmap(32, 32, QIcon.Normal).toImage()
    disabled = icon.pixmap(32, 32, QIcon.Disabled).toImage()

    def reds(image):
        return sum(1 for x in range(image.width()) for y in range(image.height())
                   if QColor.fromRgba(image.pixel(x, y)).red() > 200 and QColor.fromRgba(image.pixel(x, y)).alpha())

    assert reds(disabled) > 0 and reds(normal) == 0


# --------------------------------------------------------------------------- кнопки и переключатели
def test_button_variants_sizes_and_elide(host):
    primary = W.Button("Копировать сейчас", "primary", icon="play")
    small = W.Button("Добавить папку", small=True, icon="folder-plus")
    icon_only = W.Button(icon="trash", icon_only=True, accessible_name="Удалить вкладку")
    long = W.Button("Копировать все вкладки", icon="layers", elide=True)
    for b in (primary, small, icon_only, long):
        show_in(host, b)
    long.setFixedWidth(120)
    pump(host)
    assert primary.height() == small.height() == theme.CONTROL_HEIGHT == 32
    assert icon_only.size().width() == icon_only.size().height() == 32
    assert icon_only.accessibleName() == "Удалить вкладку"
    assert primary.property("variant") == "primary" and primary.icon_name() == "play"
    assert long.text() == "Копировать все вкладки" and long.is_elided()
    assert long.toolTip() == "" and icon_only.toolTip() == ""  # всплывающих подсказок нет
    primary.set_variant("ghost")
    assert primary.variant() == "ghost" and primary.property("variant") == "ghost"
    primary.setEnabled(False)
    primary.grab()  # рисуется и в недоступном виде
    long.setText("Все")
    assert not long.is_elided()
    long.setText("Копировать все вкладки сразу")
    assert long.is_elided() and long.toolTip() == ""


def _ink_columns(widget, color_test):
    image = widget.grab().toImage()
    return [x for x in range(image.width())
            if any(color_test(QColor.fromRgb(image.pixel(x, y))) for y in range(image.height()))]


def test_button_elide_without_icon(host):
    plain = show_in(host, W.Button("Сбросить все настройки по умолчанию", variant="danger", elide=True))
    plain.setFixedWidth(140)
    pump(host)
    assert plain.is_elided() and plain.toolTip() == ""
    assert plain._shown_text().endswith("…")
    # текст начинается у левого поля (12px), а не обрезан по краям, как у QPushButton без «…»
    red = _ink_columns(plain, lambda c: c.red() > 150 and c.green() < 90 and c.blue() < 90)
    border = [x for x in red if 3 <= x <= plain.width() - 4]
    assert border and min(border) >= 10
    plain.setFixedWidth(400)
    pump(host)
    assert not plain.is_elided()


class _EventCounter(QObject):
    """Считает события одного типа во всем приложении и ничего не задерживает."""

    def __init__(self, kind):
        super().__init__()
        self.kind, self.count = kind, 0

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == self.kind:
            self.count += 1
        return False


def test_tooltips_never_show(themed, host):
    """Всплывающих подсказок нет нигде: даже заданная вручную подсказка не появляется при наведении."""
    button = show_in(host, W.Button("Копировать все вкладки"))
    button.setToolTip("Подсказка")
    counter = _EventCounter(QEvent.ToolTip)
    themed.installEventFilter(counter)  # установлен последним, поэтому видит событие раньше блокировщика
    try:
        host.activateWindow()
        QTest.mouseMove(button, QPoint(2, 2))
        QTest.mouseMove(button, button.rect().center())
        for _ in range(150):  # Qt присылает событие подсказки через 700 мс покоя мыши
            if counter.count:
                break
            QTest.qWait(20)
        assert counter.count, "Qt не прислал событие подсказки: проверка ничего не доказывает"
        QTest.qWait(100)
        shown = [w for w in QApplication.topLevelWidgets() if w.objectName() == "qtooltip_label" and w.isVisible()]
        assert shown == []
    finally:
        themed.removeEventFilter(counter)


def test_toggle_switch(host):
    sw = show_in(host, W.ToggleSwitch(False, accessible_name="Копировать по расписанию"))
    got = collect(sw.toggled)
    assert sw.size().width() == 38 and sw.size().height() == 22
    QTest.mouseClick(sw, Qt.LeftButton)
    assert sw.isChecked() and got == [True]
    sw.set_checked_silent(False)
    assert not sw.isChecked() and got == [True] and sw.knob == 0.0
    sw.setChecked(True)
    assert wait_for(QApplication.instance(), lambda: sw.knob == pytest.approx(1.0), timeout=5)
    assert sw.property("kind") == "switch"


def test_segmented(host):
    seg = show_in(host, W.Segmented([("daily", "Ежедневно"), ("weekly", "Еженедельно"),
                                     ("monthly", "Ежемесячно")], "daily"))
    got = collect(seg.changed)
    assert seg.height() == theme.CONTROL_HEIGHT and seg.button("daily").height() == 28
    QTest.mouseClick(seg.button("weekly"), Qt.LeftButton)
    assert seg.value() == "weekly" and got == ["weekly"]
    QTest.mouseClick(seg.button("weekly"), Qt.LeftButton)
    assert got == ["weekly"] and seg.button("weekly").isChecked()
    seg.set_value("monthly")
    assert seg.value() == "monthly" and got == ["weekly"]
    QTest.keyClick(seg, Qt.Key_Right)
    assert seg.value() == "daily" and got[-1] == "daily"


def test_segmented_shares_free_space_like_flex_auto(host):
    seg = show_in(host, W.Segmented([("daily", "Ежедневно"), ("weekly", "Еженедельно"),
                                     ("monthly", "Ежемесячно")], "daily"), width=420)
    pump(host)
    hints = [seg.button(k).sizeHint().width() for k in seg.keys()]
    widths = [seg.button(k).width() for k in seg.keys()]
    extras = [w - h for w, h in zip(widths, hints)]
    assert max(extras) - min(extras) <= 1 and min(extras) > 0     # лишнее место — поровну, а не равные сегменты
    assert widths[1] > widths[0]                                   # «Еженедельно» шире «Ежедневно»
    assert seg.button("monthly").geometry().right() == seg.width() - 3


def test_segmented_elides_in_narrow_column(host):
    seg = show_in(host, W.Segmented([("daily", "Ежедневно"), ("weekly", "Еженедельно"),
                                     ("monthly", "Ежемесячно")], "daily"), width=282)
    pump(host)
    weekly = seg.button("weekly")
    assert weekly.width() < weekly.sizeHint().width()
    assert weekly.is_elided() and weekly._shown_text().endswith("…") and weekly.toolTip() == ""
    seg.grab()
    host.setFixedWidth(600)
    pump(host)
    assert not weekly.is_elided() and weekly.toolTip() == ""


def _pixel(widget, x, y):
    """Цвет точки (x, y) виджета (в px окна) на снимке grab() с учетом масштаба экрана."""
    image = widget.grab().toImage()
    ratio = image.devicePixelRatio()
    return QColor(image.pixel(int((x + 0.5) * ratio), int((y + 0.5) * ratio)))


def _near(color, hex_color, tol=3):
    want = QColor(hex_color)
    return all(abs(a - b) <= tol for a, b in ((color.red(), want.red()), (color.green(), want.green()),
                                               (color.blue(), want.blue())))


def test_segmented_ring_is_outside_the_selected_segment(host):
    # макет: box-shadow 0 0 0 1px #D3DAE3 СНАРУЖИ сегмента 28px; сам сегмент белый до края
    seg = show_in(host, W.Segmented([("daily", "Ежедневно"), ("weekly", "Еженедельно")], "daily"), width=400)
    pump(host)
    box = seg.button("daily").geometry()
    mid = box.center().x()
    assert box.height() == 28
    assert _near(_pixel(seg, mid, box.top() - 1), C.RING)      # обводка — над сегментом
    assert _near(_pixel(seg, mid, box.top()), C.CARD)          # верхний ряд сегмента — белый
    assert _near(_pixel(seg, box.left() - 1, box.center().y()), C.RING, tol=8)   # слева (+ тень 0.04)
    other = seg.button("weekly").geometry()
    assert _near(_pixel(seg, other.center().x(), other.top()), C.DIVIDER)   # невыбранный — фон группы
    seg.set_value("weekly")
    pump(host)
    assert _near(_pixel(seg, other.center().x(), other.top() - 1), C.RING)
    assert _near(_pixel(seg, mid, box.top() - 1), C.DIVIDER)


def test_elided_text_has_no_space_before_ellipsis(themed):
    from PyQt5.QtGui import QFontMetrics
    metrics = QFontMetrics(theme.font("semibold", 13))
    text = "Очень длинное название вкладки для проверки обрезки текста в списке"
    raw_space = False
    for width in range(30, metrics.horizontalAdvance(text) + 10):
        shown = W.elided(metrics, text, width)
        raw_space = raw_space or metrics.elidedText(text, Qt.ElideRight, width).endswith(" …")
        if shown == text:
            continue
        assert shown.endswith("…") and not shown[:-1].endswith(" ")
        assert text.startswith(shown[:-1])
    assert raw_space                                    # Qt оставляет пробел при какой-то ширине — его и убрали
    assert W.elided(metrics, "Коротко ", 500) == "Коротко "   # непрерывный текст не меняется


def test_half_leading_is_floored_like_chromium():
    # LayoutNG: отступ текста от верха строки — половина разницы, округленная вниз до целых px
    assert W.half_leading(12 * 1.4, 15) == 0          # 12px: 0.9 → 0
    assert W.half_leading(12.5 * 1.4, 15) == 1        # 12.5px: 1.25 → 1
    assert W.half_leading(13 * 1.4, 16) == 1          # 13px: 1.1 → 1
    assert W.half_leading(11.5 * 1.4, 14) == 1        # 11.5px: 1.05 → 1
    assert W.half_leading(10, 15) == 0


def test_empty_note_dashed_border(host):
    note = show_in(host, W.EmptyNote("Список пуст. Добавьте папки или файлы кнопками выше."), width=600)
    pump(host)
    # 1.5px макета округляются вниз до пикселей экрана: при 100 % — 1px
    ratio = max(1.0, note.devicePixelRatioF())
    assert note.border_width() * ratio == max(1, math.floor(1.5 * ratio + 1e-6))
    # 1 + 18 + строка 17.5 (→ 18) + 17 + 1 = 55, как блок 55.5px макета в Chromium
    assert note.heightForWidth(note.width()) == 55
    dashes = W.EmptyNote._dashes(100.0, 3.0, 2.0)
    assert dashes[0][0] == 0 and dashes[-1][0] + dashes[-1][1] == pytest.approx(100.0)
    steps = {round(b[0] - a[0], 6) for a, b in zip(dashes, dashes[1:])}
    assert len(steps) == 1 and 4.5 <= steps.pop() <= 5.5        # штрих 3, промежуток около 2
    assert W.EmptyNote._dashes(2.0, 3.0, 2.0) == [(0.0, 2.0)]
    note.grab()                                                    # рисуется без ошибок


def test_day_chips(host):
    chips = show_in(host, W.DayChips(0))
    got = collect(chips.changed)
    assert chips.button(0).text() == "Пн" and chips.button(6).text() == "Вс"
    assert chips.button(3).size().width() == 34 and chips.button(3).size().height() == theme.CONTROL_HEIGHT
    QTest.mouseClick(chips.button(3), Qt.LeftButton)
    assert chips.value() == 3 and got == [3]
    assert [chips.button(i).isChecked() for i in range(7)] == [i == 3 for i in range(7)]
    chips.set_value(6)
    assert got == [3] and chips.button(6).isChecked()
    # не помещаются в строку — переносятся (flex-wrap)
    assert chips.heightForWidth(120) > chips.heightForWidth(400) == theme.CONTROL_HEIGHT


def test_monthday_stepper_wraps(host):
    stepper = show_in(host, W.MonthdayStepper(31))
    assert stepper.height() == theme.CONTROL_HEIGHT and stepper.up_button.height() == theme.CONTROL_HEIGHT - 2
    got = collect(stepper.changed)
    QTest.mouseClick(stepper.up_button, Qt.LeftButton)
    assert stepper.value() == 1 and stepper.value_label.text() == "1"
    QTest.mouseClick(stepper.down_button, Qt.LeftButton)
    assert stepper.value() == 31
    stepper.step(-1)
    assert stepper.value() == 30
    assert got == [1, 31, 30]
    stepper.set_value(40)
    assert stepper.value() == 31
    # стрелки и +/- на кнопках шагают, а не уводят фокус
    stepper.up_button.setFocus(Qt.TabFocusReason)
    QTest.keyClick(stepper.up_button, Qt.Key_Up)
    assert stepper.value() == 1 and got[-1] == 1
    QTest.keyClick(stepper.up_button, Qt.Key_Left)
    QTest.keyClick(stepper.down_button, Qt.Key_Down)
    assert stepper.value() == 30
    QTest.keyClick(stepper.down_button, Qt.Key_Plus)
    assert stepper.value() == 31 and got[-4:] == [1, 31, 30, 31]


def test_switch_row_and_option_check(host):
    row = show_in(host, W.SwitchRow("Фоновый режим работы", "Закрытие окна прячет его в трей.", True))
    got = collect(row.toggled)
    QTest.mouseClick(row.switch, Qt.LeftButton)
    assert got == [False] and not row.is_checked()
    row.set_checked(True)
    assert row.is_checked() and got == [False]
    row.set_hint("")
    assert row.hint_label.isHidden()

    opt = show_in(host, W.OptionCheck("Копировать только содержимое папок", "выбранные папки не создаются"))
    toggled = collect(opt.toggled)
    QTest.mouseClick(opt.text_label, Qt.LeftButton)  # щелчок по подписи переключает флажок
    pump(host)
    assert opt.isChecked() and toggled == [True]
    opt.setChecked(False, silent=True)
    assert not opt.isChecked() and toggled == [True]


def test_rows_keep_text_together_when_taller(host):
    row = W.SwitchRow("Запускать вместе с Windows", "Программа запускается при входе в систему", title_kind="h3",
                      margins=(0, 0, 0, 0))
    opt = W.OptionCheck("Хранить историю копий", "старые копии не удаляются")
    for w in (row, opt):
        show_in(host, w)
        w.setFixedHeight(160)
    pump(host)
    # строки по line-height 1.4: 13px → 18, 12px → 17 (в макете 18.2 + 16.8 = 35)
    assert row.title_label.height() == 18 and row.hint_label.height() == 17
    assert row.hint_label.y() == row.title_label.geometry().bottom() + 1
    text_mid = (row.title_label.y() + row.hint_label.geometry().bottom()) / 2
    assert abs(text_mid - row.switch.geometry().center().y()) <= 2  # align-items: center
    assert opt.hint_label.y() == opt.text_label.geometry().bottom() + 1
    assert opt.text_label.y() <= 8  # align-items: flex-start
    lone = W.SwitchRow("Без подсказки")
    assert lone.hint_label.isHidden() and not lone.hint_label.isWindow()


def test_label_line_boxes_and_field_heights(host):
    holder = QWidget()
    lay = QVBoxLayout(holder)
    labels = {kind: W.label("Копировать по расписанию", kind) for kind in ("medium", "muted", "h2", "h1", "caps")}
    search, field = QLineEdit(), QLineEdit()
    theme.set_props(search, small=True)
    for w in list(labels.values()) + [search, field]:
        lay.addWidget(w)
    lay.addStretch(1)
    show_in(host, holder)
    pump(host)
    assert {k: w.height() for k, w in labels.items()} == {"medium": 18, "muted": 17, "h2": 19, "h1": 25, "caps": 15}
    assert theme.line_box(13) == 18 and theme.line_box(12.5) == 18
    assert search.height() == field.height() == theme.CONTROL_HEIGHT == 32


# --------------------------------------------------------------------------- карточки и текст
def test_card_with_header_and_footer(host):
    card = W.Card("Что копировать", "folder", header_divider=True)
    extra = card.add_header_widget(W.label("1 папка", "muted"))
    card.add_header_stretch()
    footer = card.add_footer()
    footer.addWidget(W.CapsLabel("Так будет выглядеть копия"))
    show_in(host, card)
    assert card.property("kind") == "card"
    assert card.title_label.text() == "Что копировать" and card.icon_label.icon_name == "folder"
    assert extra.parent() is card.header and card.footer.property("kind") == "card-footer"
    caps = card.footer.findChild(QLabel)
    assert caps.text() == "ТАК БУДЕТ ВЫГЛЯДЕТЬ КОПИЯ" and caps.font().letterSpacing() > 0


def test_notice_banner(host):
    notice = show_in(host, W.NoticeBanner("Папка не добавлена", "Системная папка не может быть источником"))
    got = collect(notice.closed)
    assert notice.text_label.text() == "Папка не добавлена. Системная папка не может быть источником"
    QTest.mouseClick(notice.close_button, Qt.LeftButton)
    assert notice.isHidden() and len(got) == 1
    notice.show_message("Папка не выбрана", "Системная папка")
    assert notice.isVisible() and notice.title() == "Папка не выбрана" and notice.text() == "Системная папка"


def test_elided_and_wrapping_labels(host):
    elided = W.ElidedLabel("Очень длинное название вкладки, которое не помещается", "medium")
    wrap = W.WrapAnywhereLabel("C:/Users/user/Pictures/Lightroom/" + "очень_длинное_имя_без_пробелов" * 3)
    badge = W.Badge("действуют только для «Очень длинное имя вкладки, которое обрезается»")
    holder = QWidget()
    lay = QVBoxLayout(holder)
    for w in (elided, wrap, badge):
        lay.addWidget(w)
    show_in(host, holder, width=200)
    pump(host)
    assert elided.text().startswith("Очень длинное") and elided.is_elided()
    assert elided.elided_text().endswith("…") and elided.toolTip() == ""
    elided.setText("коротко")
    assert not elided.is_elided()
    assert wrap.heightForWidth(120) > wrap.heightForWidth(1200)
    assert wrap.height() >= wrap.heightForWidth(wrap.width()) - 1
    assert badge.width() <= 260 and badge.is_elided()


def test_spinner_and_progress(host):
    spinner = show_in(host, W.Spinner(15))
    bar = show_in(host, W.ProgressBar())
    indet = show_in(host, W.IndeterminateBar())
    pump(host)
    assert spinner.is_spinning() and spinner.size().width() == 15
    angle = spinner.angle
    # Ждем поворота, а не фиксированные 80 мс: на медленной машине (macOS в CI) QTest.qWait
    # мог проспать весь срок и ни разу не обработать таймер спиннера.
    assert wait_for(QApplication.instance(), lambda: spinner.angle != angle, timeout=5)
    spinner.hide()
    assert not spinner.is_spinning()
    assert bar.height() == 6 and not bar.is_indeterminate() and not bar.is_animating()
    bar.setValue(40)
    assert bar.value() == 40
    assert indet.is_indeterminate() and indet.is_animating()
    assert indet.block_rect(0.0).right() < 0 < indet.block_rect(0.5).center().x()
    indet.set_indeterminate(False)
    assert not indet.is_animating()
    bar.grab()
    indet.grab()


# --------------------------------------------------------------------------- разделитель и список вкладок
def test_grip_splitter_clamps_and_resets(host):
    side, main = QWidget(), QWidget()
    splitter = W.GripSplitter(side, main)
    show_in(host, splitter, width=1000)
    pump(host)
    got = collect(splitter.side_width_changed)
    assert splitter.handleWidth() == 8 and splitter.side_width() == 240
    assert splitter.set_side_width(100) == 180
    assert splitter.set_side_width(1000) == 440
    assert splitter.set_side_width(300) == 300
    handle = splitter.handle_widget()
    assert isinstance(handle, W.GripHandle) and handle.toolTip() == ""
    QTest.mouseDClick(handle, Qt.LeftButton)
    assert splitter.side_width() == 240
    handle.setFocus()
    QTest.keyClick(handle, Qt.Key_Right)
    assert splitter.side_width() == 256
    QTest.keyClick(handle, Qt.Key_Return)
    assert splitter.side_width() == 240
    assert got == [180, 440, 300, 240, 256, 240]
    assert main.minimumWidth() == 380
    handle.hovered = True
    assert handle.is_active()
    handle.grab()


def entries(n=3):
    base = [W.TabEntry("a", "Документы", "Каждый день · 09:00", "on"),
            W.TabEntry("b", "Фото", "По воскресеньям · 22:00", "off"),
            W.TabEntry("c", "Рабочие проекты", "Не выбрана папка назначения", "warn")]
    base += [W.TabEntry(f"x{i}", "Без названия", "Не выбраны исходные файлы и папки", "warn") for i in range(n - 3)]
    return base


def test_sidebar_tab_list_selection_and_filter(host):
    tabs = W.SidebarTabList()
    show_in(host, tabs)
    tabs.setFixedHeight(400)
    tabs.set_entries(entries())
    got = collect(tabs.tab_selected)
    tabs.set_current("b")
    assert tabs.current_uid() == "b" and got == []
    tabs.select_row(2)
    assert tabs.current_uid() == "c" and got == ["c"]
    rect = tabs.visualRect(tabs.proxy.index(0, 0))
    QTest.mouseClick(tabs.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    assert got == ["c", "a"]
    assert tabs.proxy.index(0, 0).data(Qt.ToolTipRole) is None  # у строк нет всплывающих подсказок
    assert tabs.entry("c").sub_color is None
    assert tabs.proxy.index(2, 0).data(W.ROLE_SUB_COLOR) == C.WARN
    # строки дробные, как в макете (48.3 + 2): 51, 50, 50, 51 …
    assert rect.height() == W.TabDelegate.row_height(0) == 51
    assert [W.TabDelegate.row_top(i) for i in range(5)] == [0, 51, 101, 151, 202]

    tabs.set_query("  ФО ")
    assert tabs.visible_uids() == ["b"] and tabs.visible_count() == 1
    assert tabs.current_uid() == "a" and got == ["c", "a"]  # скрытая фильтром вкладка остается выбранной
    tabs.set_query("нет такой")
    assert tabs.visible_count() == 0
    tabs.set_empty_text("Нет вкладок с «нет такой»")
    tabs.grab()
    tabs.set_query("")
    assert tabs.visible_count() == 3
    # переименованная выбранная вкладка, переставшая подходить под поиск, остается выбранной и без сигнала
    tabs.set_query("док")
    assert tabs.visible_uids() == ["a"]
    assert tabs.update_entry(W.TabEntry("a", "Архив", "Каждый день · 09:00", W.STATUS_ON))
    assert tabs.current_uid() == "a" and got == ["c", "a"] and tabs.visible_count() == 0
    assert tabs.update_entries([W.TabEntry("a", "Документы", "x"), W.TabEntry("zz", "нет")]) == 1
    assert tabs.visible_uids() == ["a"] and tabs.selectionModel().isSelected(tabs.proxy.index(0, 0))
    tabs.set_query("")
    assert tabs.selectionModel().isSelected(tabs.proxy.index(0, 0)) and got == ["c", "a"]

    tabs.set_current(None)
    assert tabs.current_uid() is None
    tabs.set_current("a")
    tabs.set_entries(list(reversed(entries())))
    assert tabs.current_uid() == "a" and got == ["c", "a"]
    assert tabs.update_entry(W.TabEntry("a", "Документы", "Копирование... 40%", "running"))
    assert tabs.entry("a").status == "running"
    assert tabs._spin_timer.isActive()
    tabs.update_entry(W.TabEntry("a", "Документы", "Каждый день · 09:00", "on"))
    assert not tabs._spin_timer.isActive()
    assert not tabs.update_entry(W.TabEntry("zz", "?"))
    tabs.grab()


def test_sidebar_edge_shadows(host):
    tabs = W.SidebarTabList()
    show_in(host, tabs)
    tabs.setFixedHeight(160)
    tabs.set_entries(entries(12))
    pump(host)
    assert tabs.shadows_visible() == (False, True)
    tabs.verticalScrollBar().setValue(tabs.verticalScrollBar().maximum())
    assert tabs.shadows_visible() == (True, False)
    tabs.verticalScrollBar().setValue(tabs.verticalScrollBar().maximum() // 2)
    assert tabs.shadows_visible() == (True, True)


# --------------------------------------------------------------------------- тост, модальное окно, заголовок
def test_toast_anchors_and_hides(host):
    host.show()
    toast = W.Toast(host)
    got = collect(toast.closed)
    toast.show_message("Расписание не запущено", "Выберите исходные файлы/папки и папку назначения!", "warn")
    pump(host)
    assert toast.isVisible() and toast.timer.isActive() and toast.timer.interval() == 5000
    assert toast.width() == 340 and toast.kind == "warn"
    assert toast.geometry().right() == host.width() - 16 - 1
    assert toast.geometry().bottom() == host.height() - 56 - 1
    assert toast.title() == "Расписание не запущено"
    host.resize(500, 400)
    pump(host)
    assert toast.geometry().right() == host.width() - 16 - 1
    toast.show_message("Сброс выполнен", "", "info", timeout=30)
    assert toast.text_label.isHidden()
    assert wait_for(QApplication.instance(), toast.isHidden, timeout=5) and len(got) == 1
    toast.show_message("x", "y")
    QTest.mouseClick(toast.close_button, Qt.LeftButton)
    assert toast.isHidden() and len(got) == 2


def test_overlay_dialog_preset_answer(host, monkeypatch):
    monkeypatch.setattr(W.OverlayDialog, "preset_answer", True)
    monkeypatch.setattr(W.OverlayDialog, "asked", [])
    assert W.confirm(host, "Подтверждение сброса", "Вы уверены?") is True
    monkeypatch.setattr(W.OverlayDialog, "preset_answer", False)
    assert W.confirm(host, "Удалить вкладку «Фото»?", "Удаляются только настройки") is False
    assert W.OverlayDialog.asked == [("Подтверждение сброса", "Вы уверены?"),
                                     ("Удалить вкладку «Фото»?", "Удаляются только настройки")]


def test_overlay_dialog_real_loop(host):
    host.show()
    dialog = W.OverlayDialog(host, "Удалить вкладку «Фото»?", "Удаляются только настройки этой вкладки.",
                             ok_text="Удалить вкладку", cancel_text="Отмена")
    QTimer.singleShot(0, lambda: (dialog.isVisible() and dialog.geometry() == host.rect()) and dialog.ok_button.click())
    assert dialog.exec_() is True
    assert dialog.isHidden()
    assert dialog.card.width() == 400 and dialog.ok_button.property("variant") == "danger-solid"

    def escape():
        assert dialog.isVisible()
        QTest.keyClick(dialog.cancel_button, Qt.Key_Escape)

    dialog.result_ = None
    QTimer.singleShot(0, escape)
    assert dialog.exec_() is False

    finished = collect(dialog.finished)
    dialog.result_ = None
    dialog.open()
    assert dialog.focusNextPrevChild(True)
    dialog.reject()
    assert finished == [False]


def test_overlay_dialog_returns_focus(host):
    before = W.Button("Удалить вкладку")
    show_in(host, before)
    QApplication.setActiveWindow(host)
    pump()
    before.setFocus(Qt.TabFocusReason)
    pump()
    assert QApplication.focusWidget() is before
    dialog = W.OverlayDialog(host, "Удалить вкладку «Фото»?", "Удаляются только настройки этой вкладки.")
    assert QApplication.activeWindow() is host  # надписи не открываются отдельными окнами

    def answer():
        assert QApplication.focusWidget() is dialog.cancel_button
        QTest.mouseClick(dialog.ok_button, Qt.LeftButton)

    QTimer.singleShot(0, answer)
    assert dialog.exec_() is True
    assert QApplication.focusWidget() is before


def test_focus_ring_only_from_keyboard(host):
    """Рамка фокуса — как :focus-visible: после Tab есть, после щелчков мышью нет."""
    side = W.Button("Настройки", variant="nav", checkable=True)
    stack = QStackedWidget()
    page1, page2 = QWidget(), QWidget()
    title = W.TitleEdit("Документы")
    QVBoxLayout(page1).addWidget(title)
    row = W.SwitchRow("Запускать вместе с Windows")
    reset = W.Button("Сбросить", variant="danger")
    lay2 = QVBoxLayout(page2)
    lay2.addWidget(row)
    lay2.addWidget(reset)
    stack.addWidget(page1)
    stack.addWidget(page2)
    side.clicked.connect(lambda: stack.setCurrentIndex(1))
    holder = QWidget()
    lay = QHBoxLayout(holder)
    lay.addWidget(side)
    lay.addWidget(stack)
    show_in(host, holder)
    QApplication.setActiveWindow(host)
    pump()
    focused = QApplication.focusWidget()
    assert focused is None or not theme.has_keyboard_focus(focused)  # окно только что открыто
    QTest.mouseClick(title.line_edit, Qt.LeftButton)
    QTest.mouseClick(side, Qt.LeftButton)  # страница сменилась, Qt сам перевел фокус «по Tab»
    pump()
    assert QApplication.focusWidget() is row.switch
    assert not theme.has_keyboard_focus(row.switch) and row.switch.property("kbfocus") is None
    QTest.keyClick(row.switch, Qt.Key_Tab)
    pump()
    assert QApplication.focusWidget() is reset
    assert theme.has_keyboard_focus(reset) and reset.property("kbfocus") == "true"
    QTest.keyClick(reset, Qt.Key_Backtab)
    pump()
    assert theme.has_keyboard_focus(row.switch) and reset.property("kbfocus") is None
    row.switch.grab()
    QTest.mouseClick(row.switch, Qt.LeftButton)  # щелчок мышью снимает рамку
    assert not theme.has_keyboard_focus(row.switch)
    assert '[kbfocus="true"]' in theme.build_stylesheet()
    assert 'QPushButton:focus' not in theme.build_stylesheet()


def test_title_edit(host):
    title = show_in(host, W.TitleEdit("Документы"))
    assert title.line_edit.height() == theme.CONTROL_HEIGHT
    assert title.findChildren(W.IconLabel) == [] and "pencil" not in icons.NAMES  # значка карандаша нет
    host.layout().addWidget(QLineEdit())  # есть куда уйти фокусу
    QApplication.setActiveWindow(host)  # с активным окном уход фокуса тоже дает editingFinished
    pump()
    edited, finished = collect(title.text_edited), collect(title.editing_finished)
    assert title.chars() == 11
    title.line_edit.setFocus()
    title.line_edit.selectAll()
    QTest.keyClicks(title.line_edit, "Photo")
    assert edited[-1] == "Photo" and title.text() == "Photo"
    QTest.keyClick(title.line_edit, Qt.Key_Escape)
    assert title.text() == "Документы"
    assert finished == ["Документы"]  # Esc сообщает прежнее имя один раз
    title.line_edit.setFocus()
    title.line_edit.selectAll()
    QTest.keyClick(title.line_edit, Qt.Key_Delete)
    QTest.keyClick(title.line_edit, Qt.Key_Return)
    pump()
    assert title.text() == "Без названия" and finished == ["Документы", "Без названия"]  # Enter — ровно один раз
    title.line_edit.setFocus()
    QTest.keyClicks(title.line_edit, "X")
    QTest.keyClick(title.line_edit, Qt.Key_Enter)
    title.line_edit.clearFocus()
    pump()
    assert finished[2:] == [title.text()]
    title.set_text("x" * 100)
    assert title.chars() == 48 and edited[-1] != "x" * 100
    title.set_text("ab")
    assert title.chars() == 6
    title.grab()


def test_title_edit_width_and_focus_halo(host):
    title = show_in(host, W.TitleEdit("Документы"))
    other = QLineEdit()
    host.layout().addWidget(other)
    QApplication.setActiveWindow(host)
    other.setFocus()
    pump()
    fm = title.line_edit.fontMetrics()
    # как <input size=11>: 11 средних знаков + (наибольшая − средняя) + рамка и поля (1 + 7 с каждой стороны)
    extra = W.size_attribute_extra(title.line_edit.font())
    assert 0 < extra < fm.height()
    assert title.line_edit.width() == fm.averageCharWidth() * 11 + extra + 16
    assert not title.halo.isVisible()
    title.line_edit.setFocus()
    pump()
    halo = title.halo
    assert halo.isVisible()
    field = title.line_edit.rect().translated(title.line_edit.mapTo(halo.parentWidget(), QPoint(0, 0)))
    assert halo.geometry() == field.adjusted(-3, -3, 3, 3)
    image = halo.grab().toImage()
    assert image.pixelColor(1, halo.height() // 2).alpha() > 0      # обводка слева от поля
    title.line_edit.clearFocus()
    pump()
    assert not halo.isVisible()


def indicator_size(checkbox):
    """Размер квадрата флажка, как его рисует стиль (с учетом QSS ::indicator)."""
    option = QStyleOptionButton()
    checkbox.initStyleOption(option)
    rect = checkbox.style().subElementRect(QStyle.SE_CheckBoxIndicator, option, checkbox)
    return rect.width(), rect.height()


def test_textless_checkboxes_leave_gap_to_layout(host):
    from backup_app.frontend.history_panel import FilterCheck
    option = show_in(host, W.OptionCheck("Копировать только содержимое папок", "подсказка"))
    check = show_in(host, FilterCheck())
    check.setText("Только «Документы»")
    pump()
    assert option.checkbox.width() == 15                            # без места под текст флажка
    assert option.text_label.x() == option.checkbox.geometry().right() + 1 + 9
    assert check.checkbox.width() == check.checkbox.height() == 15
    assert indicator_size(check.checkbox) == indicator_size(option.checkbox) == (15, 15)  # все флажки одного размера
    assert check.text_label.x() == check.checkbox.geometry().right() + 1 + 6


def mockup_text_width(f, text, px):
    """Ширина текста в макете (браузер рисует дробный размер без округления до целых пикселей).

    Меряем тем же шрифтом размером 200px и пересчитываем: при таком размере хинтинг и округление
    ширин знаков (на каждой системе свои) дают ошибку меньше сотой пикселя на знак.
    """
    from PyQt5.QtGui import QFontMetricsF
    big = QFont(f)
    big.setPointSizeF(theme.px_to_pt(200))
    return QFontMetricsF(big).horizontalAdvance(text) * px / 200


def test_fractional_font_widths_follow_the_mockup(host):
    from PyQt5.QtGui import QFontMetrics, QFontMetricsF
    from PyQt5.QtWidgets import QPushButton
    small = show_in(host, W.Button("Открыть подробный журнал", "ghost", small=True))
    heading = show_in(host, W.label("Настройки вкладки", "h2"))
    pump()
    assert theme.font_px(small.font()) == pytest.approx(12.5)
    text = small.text()
    # Qt5 рисует 12.5px целым 13px; насколько это шире, зависит от хинтинга системы (Linux — 7 px,
    # Windows — 2 px), поэтому проверяем не число, а результат: место под текст — как в макете
    rounded = QFontMetrics(small.font()).horizontalAdvance(text)
    exact_w = QFontMetricsF(theme.exact(small.font())).horizontalAdvance(text)
    delta = W.exact_width_delta(small.font(), text)
    assert delta == max(0, rounded - math.ceil(exact_w))
    assert small.sizeHint().width() == QPushButton.sizeHint(small).width() - delta
    room = rounded - delta                                   # ширина под текст в кнопке
    mockup = mockup_text_width(small.font(), text, 12.5)
    assert abs(room - mockup) <= abs(rounded - mockup)       # не дальше от макета, чем целый 13px
    if rounded - mockup >= 2:                                # 13px заметно шире макета — кнопка уже
        assert room < rounded
    text_w = QFontMetricsF(theme.exact(heading.font())).horizontalAdvance(heading.text())
    assert heading.sizeHint().width() <= text_w + 2


def test_flow_layout_wraps(themed):
    holder = QWidget()
    flow = W.FlowLayout(holder, 8, 8)
    for text in ("Добавить папку", "Добавить файл", "Очистить список"):
        flow.addWidget(W.Button(text, small=True))
    assert flow.count() == 3
    assert flow.heightForWidth(1000) == theme.CONTROL_HEIGHT
    assert flow.heightForWidth(150) > theme.CONTROL_HEIGHT * 2


def test_style_menu(themed):
    menu = QMenu()
    W.style_menu(menu)
    menu.addAction(icons.icon("window"), "Открыть окно")
    assert menu.testAttribute(Qt.WA_TranslucentBackground)
    menu.popup(QPoint(0, 0))
    menu.grab()
    menu.close()


def test_status_line(host):
    line = show_in(host, W.StatusLine("ok", "Следующее копирование: завтра в 09:00"))
    pump()
    assert line.text() == "Следующее копирование: завтра в 09:00"
    assert line.icon_label.isVisible() and line.icon_label.icon_name == "clock" and not line.spinner.isVisible()
    assert line.text_label.property("tone") == "ok"
    line.set_status("run", "Идет копирование…")
    assert line.spinner.isVisible() and line.spinner.is_spinning() and not line.icon_label.isVisible()
    line.set_status("warn", "Не выбрана папка назначения")
    assert line.icon_label.icon_name == "alert" and line.text_label.property("tone") == "warn"
    host.setFixedWidth(220)
    pump()
    line.set_status("warn", "Не выбраны исходные файлы/папки и папка назначения")
    pump()
    assert line.text_label.is_elided() and line.text_label.toolTip() == ""
    assert line.text_label.palette().color(line.text_label.foregroundRole()).name().upper() == C.WARN
