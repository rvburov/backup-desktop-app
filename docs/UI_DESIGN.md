# Оформление интерфейса

Окно повторяет макет `Main.dc.html` (главное окно) и `Tray.dc.html` (меню трея и уведомления).
Все цвета, шрифты и стили собраны в трех модулях — меняйте их, а не отдельные виджеты:

| Модуль | Что в нем |
|---|---|
| `backup_app/frontend/theme.py` | цвета `C`, размеры, шрифты, палитра, таблица стилей (QSS), стиль Qt, `set_props()` |
| `backup_app/frontend/icons.py` | все иконки макета (SVG 24×24) → `pix()` / `icon()` / `paint()` |
| `backup_app/frontend/widgets.py` | готовые элементы: кнопки, переключатели, карточки, список вкладок, тост, модальное окно |

Запуск оформления — в `app.py`: `theme.enable_hidpi()` до создания `QApplication`, затем `theme.apply(app)`
(стиль Fusion, шрифты из `fonts/`, светлая палитра, QSS).

## Цвета (`theme.C`)

| Токен | Цвет | Где |
|---|---|---|
| `WIN` | `#F5F7FA` | фон окна и рабочей области |
| `SIDE` | `#ECEFF4` | боковая панель |
| `CARD` | `#FFFFFF` | карточки, поля, строка состояния, история |
| `BORDER` | `#DDE2E9` | рамка карточек, линия над историей и строкой состояния |
| `DIVIDER` | `#EEF1F5` | линии внутри карточек, фон сегментов |
| `SIDE_DIVIDER` | `#D6DCE4` | линия в боковой панели |
| `RING` | `#D3DAE3` | обводка выбранной вкладки и сегмента, линия разделителя панелей |
| `INPUT` | `#C9D0DA` | рамка полей и обычных кнопок |
| `TEXT` / `TEXT2` | `#18202B` / `#3A4552` | основной / вторичный текст, иконки |
| `MUTED` / `FAINT` | `#5A6573` / `#8A94A3` | подсказки / совсем бледный текст |
| `ACCENT` (`ACCENT_HOVER`) | `#1F5FD1` (`#174FB3`) | основная кнопка, переключатели, фокус, выбранный день |
| `ACCENT_SOFT` + `ACCENT_SOFT_TEXT` | `#E8EFFC` + `#1F4FA8` | «таблетки» |
| `OK` | `#17803D` | расписание запущено, успешный результат |
| `WARN` / `WARN_ICON` | `#9A5A06` / `#B26A00` | текст / значок предупреждения |
| `DANGER` | `#B42318` | ошибки, удаление (`DANGER_SOFT` `#FDF1EF`, `DANGER_BORDER` `#E9B8B2`) |
| `NOTICE_TEXT` | `#8E1C12` | текст красной плашки |
| `FOLDER` / `FILE` | `#A86A12` / `#3F679F` | иконки папки / файла в списке |
| `SWITCH_OFF` | `#B4BDC9` | выключенный переключатель |
| `TOAST_BG` / `TOAST_TEXT` | `#1F2733` / `#D5DBE4` | тост; иконка `TOAST_INFO` `#7FB0FF`, `TOAST_WARN` `#F4B740`, `TOAST_OK` `#6FD08C` |

Недоступные элементы в макете — `opacity: .45`; в QSS это готовые смешанные цвета (`theme.faded()`, `theme.mix()`).

## Шрифты

* Golos Text 13px — основной текст. Межстрочный 1.4 (`theme.LINE_HEIGHT`): у однострочных `QLabel[kind]` QSS
  задает `min-height` = размер × 1.4 (`theme.line_box()`: 13px → 18, 12px → 17), многострочный текст —
  `WrapAnywhereLabel` (каждая строка 1.4). Заголовки и подсказки `SwitchRow`/`OptionCheck` — `WrapAnywhereLabel`.
* Заголовки карточек 13.5px/600, заголовок страницы 18px/600, подписи капителью 11px/600 с разрядкой .06em
  (`CapsLabel`), подсказки 12px `MUTED`.
* JetBrains Mono — пути: 11px в списке источников, 12px в поле папки и в «Так будет выглядеть копия»,
  11.5px — время в истории.
* Начертания Golos регистрируются как **отдельные семейства** («Golos Text», «Golos Text Medium»,
  «Golos Text SemiBold»), поэтому жирность в QSS задается семейством: `theme.qss_font("semibold", 13.5)`,
  в коде рисования — `theme.font("semibold", 13.5)`. Если шрифты не загрузились, роли получают системный шрифт
  с `font-weight` 456/504: Qt5 делит вес из QSS на 8, и только так выходят Medium (57) и DemiBold (63), а не
  DemiBold/Bold — пишите стили только через эти функции.
* Дробные размеры (12.5px, 13.5px) QSS в px не понимает: `theme.build_stylesheet()` переводит их в pt
  с учетом DPI экрана, `theme.font()` делает то же самое.
* Файлы — `fonts/` (лицензия SIL OFL 1.1: `OFL-GolosText.txt`, `OFL-JetBrainsMono.txt`), в сборку их добавляет
  `BackupApp.spec`.

## Варианты через свойства

Вид задается динамическими свойствами, QSS их подхватывает. Для уже показанного виджета меняйте их через
`theme.set_props(widget, variant="primary")` — он обновляет стиль (`repolish`).

| Свойство | Значения |
|---|---|
| `QPushButton[variant]` | нет (обычная), `primary`, `ghost`, `link` (синий текст слева), `danger`, `danger-solid`, `nav` (пункт боковой панели) |
| `QPushButton[small="true"]`, `[iconOnly="true"]` | 28px, квадратная |
| `[kbfocus="true"]` | ставит `theme.FocusTracker` сам: фокус пришел с клавиатуры (рамка фокуса). Вручную не задавайте |
| `QLabel[kind]` | `h1`, `h2`, `h3`, `medium`, `semibold`, `muted`, `muted-sm`, `secondary`, `faint`, `caps`, `count`, `warn`, `danger`, `ok`, `status` (+`tone`), `mono`, `mono-body`, `mono-time`, `badge`, `pill`, `note`, `note-sm`, `empty` |
| `QFrame[kind]` | `card`, `card-footer`, `divider`, `vdivider`, `side-divider`, `sidebar`, `panel` (белая полоса с линией сверху), `row` (строка списка с линией и подсветкой), `row-plain`, `notice`, `note`, `stepper` |
| `QLineEdit` | `[readOnly="true"]` — серый фон, `[mono="true"]` — моноширинный 12px, `[small="true"]` — поиск 30px (`FIELD_HEIGHT_SMALL`) |
| `QCheckBox[kind="filter"]` | 12.5px `TEXT2` (фильтр истории) |
| `QWidget[kind="page"]` | фон окна (нужен `WA_StyledBackground`) |

## Элементы (`widgets.py`)

| Элемент | Когда |
|---|---|
| `Button(text, variant, small, icon, icon_only, tooltip, elide, checkable)` | любая кнопка; иконка окрашивается в цвет текста, зазор 6px (у `nav` 10px) |
| `ToggleSwitch` | включение функции (расписание, настройки приложения); `toggled(bool)`, `set_checked_silent()` |
| `SwitchRow(title, hint, checked, title_kind, top_border)` | строка «заголовок + подсказка … переключатель» |
| `OptionCheck(text, hint, checked)` | параметр копирования: флажок + полужирная подпись + подсказка, щелчок по строке |
| `Segmented(options, value)` | выбор одного из 2–4 вариантов (периодичность); `changed(str)`; в узкой колонке подписи с «…» |
| `DayChips(value)` | день недели; `changed(int)`, переносится в узком окне |
| `MonthdayStepper(value)` | число месяца 1…31 по кругу; `changed(int)`; стрелки и +/− на кнопках — шаг |
| `Card(title, icon_name, header_divider, header_margins, body_margins)` | любой раздел; `add_header_widget()`, `body_layout`, `add_footer()` |
| `NoticeBanner(title, text)` | ошибка внутри карточки (отказ добавить папку); `closed` |
| `Badge(text, "badge"/"pill")` | «действуют только для …», «Следующее копирование: …» |
| `ElidedLabel`, `WrapAnywhereLabel` | одна строка с «…» / перенос где угодно (пути, имена без пробелов) |
| `Spinner`, `ProgressBar`, `IndeterminateBar` | идет копирование / ход / подготовка |
| `GripSplitter(side, main)` | боковая панель 180…440 px (240 по умолчанию) и рабочая область от 380 px |
| `SidebarTabList` + `TabEntry` | список вкладок со статусом, фильтром, тенями у краев |
| `Toast(parent)` | короткое сообщение в окне (5 с) вместо `QMessageBox`: отказ расписания, «сброс выполнен» |
| `OverlayDialog` / `confirm()` | подтверждение удаления и сброса внутри окна; после ответа фокус возвращается туда, где был |
| `TitleEdit` | название вкладки, редактируемое на месте; `editing_finished` — один раз (Enter, Esc или уход фокуса), только если имя изменилось (Esc — всегда) |
| `StatusLine(tone, text)` | строка под названием вкладки: `run` / `warn` / `ok` / `off` |
| `FlowLayout`, `label()`, `hline()`, `vline()`, `IconLabel`, `CapsLabel`, `style_menu()` | мелкие помощники |

## Отступы и размеры

* Рабочая область: поля 16px, между карточками 12px. Боковая панель: сверху 12, снизу 10, список — слева 10,
  справа 6; строка вкладки 48px + 2px зазор.
* Карточка: рамка 1px, скругление 8. Шапка — поля 9px 12px (на странице «Настройки» 9px 14px), иконка 16px
  `TEXT2`, зазор 8. Содержимое — 12px по бокам; колонки «Настройки вкладки» — 12px 14px, линия между ними.
* `TitleEdit` и `OptionCheck` в макете выступают влево (margin-left: -8px), чтобы текст стоял по линии
  соседних строк: уменьшайте отступ раскладки на `TitleEdit.TEXT_INSET` (9) и `OptionCheck.INSET` (8).
* Строка списка: поля 6px 8px 6px 12px, иконка 18px, зазор 10, линия `DIVIDER` сверху.
* Высоты: кнопки и поля 32, малые кнопки 28, поле поиска 30, сегменты 28 в подложке 32, дни 34×28, переключатель 38×22,
  полоска хода 6, строка состояния от 40.
* Скругления: карточка 8, поле и кнопка 6, сегмент и день 5, плашки 6, тост и модальное окно 10,
  «таблетка» 9 (Qt не рисует скругление больше половины высоты — тогда угол становится прямым).

## Фокус

Рамка фокуса — только при работе с клавиатуры, как `:focus-visible` макета. `theme.apply()` ставит фильтр
`FocusTracker`: виджет, получивший фокус клавишей (Tab, Shift+Tab, сочетание, стрелки), получает свойство
`kbfocus="true"`, щелчок мышью и уход фокуса его снимают. В QSS рамку кнопок задавайте селектором
`[kbfocus="true"]`, а не `:focus`; в своем `paintEvent` проверяйте `theme.has_keyboard_focus(self)`, в своем
`focusInEvent` — `theme.keyboard_focus_reason(event.reason())`. Поля ввода (`QLineEdit`) подсвечиваются при любом
фокусе (`:focus`), как в браузере.

Виджет без родителя не показывайте (`setVisible(True)`, `show()`): Qt откроет его отдельным окном. Скрывайте и
показывайте надписи после того, как они добавлены в раскладку.

## Как добавить новый блок в том же стиле

1. Возьмите `Card("Заголовок", "иконка")`; иконку добавьте в `icons._STROKE` (путь из SVG 24×24).
2. Внутрь кладите элементы из `widgets.py`; подписи — `label(text, "muted")` и т. п., а не `setStyleSheet`.
3. Новый цвет — сначала в `theme.C`, затем в QSS через свойство (`kind`/`variant`). Не пишите цвета в коде окна.
4. Текст, который может быть длинным (пути, имена), — `ElidedLabel` (одна строка) или `WrapAnywhereLabel`.
5. Многострочный текст в раскладке не выравнивайте флагами (`addWidget(w, 0, Qt.AlignTop)`): с выравниванием Qt
   не пересчитывает высоту по ширине и текст обрезается. Используйте растяжки (`addStretch`).
6. Проверьте вид без экрана (ниже) и сравните с макетом.

## Снимки окна без экрана

```bash
QT_QPA_PLATFORM=offscreen python3 - <<'EOF'
from PyQt5.QtWidgets import QApplication
from backup_app.frontend import theme, widgets
theme.enable_hidpi()
app = QApplication([])
theme.apply(app)
card = widgets.Card("Папка сохранения", "drive")
card.resize(600, 120)
card.show()
app.processEvents()
card.grab().save("card.png")
EOF
```

Масштаб 125/150/200 % — переменная `QT_SCALE_FACTOR=1.5`. Иконки и текст рисуются вектором и остаются четкими.

## Тесты

`tests/frontend/test_widgets.py` создает каждый элемент без экрана и проверяет его поведение. Модальное окно
в тестах отвечает без цикла событий: `OverlayDialog.preset_answer = True` (ответ) и `OverlayDialog.asked`
(что спросили). `QTest.keyClicks` в этой сборке Qt принимает только латиницу.
