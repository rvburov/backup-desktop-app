"""Оформление и готовые элементы интерфейса: собираются без экрана и ведут себя как в макете."""
import pytest
from PyQt5.QtCore import QPoint, Qt, QTimer, qInstallMessageHandler
from PyQt5.QtGui import QColor, QIcon
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLabel, QMenu, QVBoxLayout, QWidget

from backup_app.frontend import icons, theme
from backup_app.frontend import widgets as W
from backup_app.frontend.theme import C


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
        assert "font-weight: 600" in theme.qss_font("semibold")
        assert theme.font("semibold", 13).weight() >= 63
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
                     '[kind="pill"]', '[kind="segmented"]', '[kind="seg"]', '[kind="chip"]', "QScrollBar",
                     "QMenu", "QToolTip", "QMessageBox"):
        assert selector in qss, selector
    assert C.ACCENT in qss and C.BORDER in qss


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
    icon_only = W.Button(icon="trash", icon_only=True, tooltip="Удалить вкладку")
    long = W.Button("Копировать все вкладки", icon="layers", elide=True)
    for b in (primary, small, icon_only, long):
        show_in(host, b)
    long.setFixedWidth(120)
    pump(host)
    assert primary.height() == 32 and small.height() == 28
    assert icon_only.size().width() == icon_only.size().height() == 32
    assert icon_only.accessibleName() == "Удалить вкладку"
    assert primary.property("variant") == "primary" and primary.icon_name() == "play"
    assert long.text() == "Копировать все вкладки" and long.is_elided()
    assert long.toolTip() == "Копировать все вкладки"
    primary.set_variant("ghost")
    assert primary.variant() == "ghost" and primary.property("variant") == "ghost"
    primary.setEnabled(False)
    primary.grab()  # рисуется и в недоступном виде


def test_toggle_switch(host):
    sw = show_in(host, W.ToggleSwitch(False, accessible_name="Копировать по расписанию"))
    got = collect(sw.toggled)
    assert sw.size().width() == 38 and sw.size().height() == 22
    QTest.mouseClick(sw, Qt.LeftButton)
    assert sw.isChecked() and got == [True]
    sw.set_checked_silent(False)
    assert not sw.isChecked() and got == [True] and sw.knob == 0.0
    sw.setChecked(True)
    QTest.qWait(250)
    assert sw.knob == pytest.approx(1.0)
    assert sw.property("kind") == "switch"


def test_segmented(host):
    seg = show_in(host, W.Segmented([("daily", "Ежедневно"), ("weekly", "Еженедельно"),
                                     ("monthly", "Ежемесячно")], "daily"))
    got = collect(seg.changed)
    assert seg.height() == 32 and seg.button("daily").height() == 28
    QTest.mouseClick(seg.button("weekly"), Qt.LeftButton)
    assert seg.value() == "weekly" and got == ["weekly"]
    QTest.mouseClick(seg.button("weekly"), Qt.LeftButton)
    assert got == ["weekly"] and seg.button("weekly").isChecked()
    seg.set_value("monthly")
    assert seg.value() == "monthly" and got == ["weekly"]
    QTest.keyClick(seg, Qt.Key_Right)
    assert seg.value() == "daily" and got[-1] == "daily"


def test_day_chips(host):
    chips = show_in(host, W.DayChips(0))
    got = collect(chips.changed)
    assert chips.button(0).text() == "Пн" and chips.button(6).text() == "Вс"
    assert chips.button(3).size().width() == 34 and chips.button(3).size().height() == 28
    QTest.mouseClick(chips.button(3), Qt.LeftButton)
    assert chips.value() == 3 and got == [3]
    assert [chips.button(i).isChecked() for i in range(7)] == [i == 3 for i in range(7)]
    chips.set_value(6)
    assert got == [3] and chips.button(6).isChecked()
    # не помещаются в строку — переносятся (flex-wrap)
    assert chips.heightForWidth(120) > chips.heightForWidth(400) == 28


def test_monthday_stepper_wraps(host):
    stepper = show_in(host, W.MonthdayStepper(31))
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
    assert elided.elided_text().endswith("…") and elided.toolTip() == elided.text()
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
    QTest.qWait(80)
    assert spinner.angle != angle
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
    assert isinstance(handle, W.GripHandle) and handle.toolTip() == W.SPLITTER_TIP
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
    assert tabs.proxy.index(0, 0).data(Qt.ToolTipRole) == "Документы — Каждый день · 09:00"
    assert tabs.entry("c").sub_color is None
    assert tabs.proxy.index(2, 0).data(W.ROLE_SUB_COLOR) == C.WARN
    assert rect.height() == W.TabDelegate.ROW_HEIGHT

    tabs.set_query("  ФО ")
    assert tabs.visible_uids() == ["b"] and tabs.visible_count() == 1
    assert tabs.current_uid() == "a" and got == ["c", "a"]  # скрытая фильтром вкладка остается выбранной
    tabs.set_query("нет такой")
    assert tabs.visible_count() == 0
    tabs.set_empty_text("Нет вкладок с «нет такой»")
    tabs.grab()
    tabs.set_query("")
    assert tabs.visible_count() == 3
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
    QTest.qWait(120)
    assert toast.isHidden() and len(got) == 1
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


def test_title_edit(host):
    title = show_in(host, W.TitleEdit("Документы"))
    edited, finished = collect(title.text_edited), collect(title.editing_finished)
    assert title.chars() == 11
    title.line_edit.setFocus()
    title.line_edit.selectAll()
    QTest.keyClicks(title.line_edit, "Photo")
    assert edited[-1] == "Photo" and title.text() == "Photo"
    QTest.keyClick(title.line_edit, Qt.Key_Escape)
    assert title.text() == "Документы"
    title.line_edit.setFocus()
    title.line_edit.selectAll()
    QTest.keyClick(title.line_edit, Qt.Key_Delete)
    QTest.keyClick(title.line_edit, Qt.Key_Return)
    assert title.text() == "Без названия" and finished[-1] == "Без названия"
    title.set_text("x" * 100)
    assert title.chars() == 48 and edited[-1] != "x" * 100
    title.set_text("ab")
    assert title.chars() == 6
    title.grab()


def test_flow_layout_wraps(themed):
    holder = QWidget()
    flow = W.FlowLayout(holder, 8, 8)
    for text in ("Добавить папку", "Добавить файл", "Очистить список"):
        flow.addWidget(W.Button(text, small=True))
    assert flow.count() == 3
    assert flow.heightForWidth(1000) == 28
    assert flow.heightForWidth(150) > 28 * 2


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
    assert line.text_label.palette().color(line.text_label.foregroundRole()).name().upper() == C.WARN
