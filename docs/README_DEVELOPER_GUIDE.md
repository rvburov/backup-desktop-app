# Руководство разработчика Backup Application

## Содержание

1. [Установка для разработки](#установка-для-разработки)
2. [Архитектура проекта](#архитектура-проекта)
3. [Интерфейс](#интерфейс)
4. [Фоновый режим](#фоновый-режим)
5. [Безопасность копирования](#безопасность-копирования)
6. [Настройки и журнал](#настройки-и-журнал)
7. [Процесс сборки](#процесс-сборки)
8. [Тестирование](#тестирование)
9. [Вклад в проект](#вклад-в-проект)

## Установка для разработки

### Клонирование репозитория

```bash
git clone https://github.com/yourusername/backup-app.git
cd backup-app
```

### Создание виртуального окружения

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/macOS
python3 -m venv venv
source venv/bin/activate
```

### Установка зависимостей

```bash
pip install -r requirements.txt
```

Один файл содержит все: PyQt5 для приложения, PyInstaller для сборки, pytest и pyflakes для проверки.

### Запуск в режиме разработки

```bash
python backup-app.py              # открыть окно
python backup-app.py --minimized  # запуск в фоне: окно скрыто, иконка в трее
python -m backup_app              # то же самое через пакет
```

Две переменные окружения позволяют запустить отладочную копию рядом с рабочей:

- `BACKUPAPP_CONFIG_DIR` задает свою папку настроек, истории и журнала, рабочие настройки не меняются;
- `BACKUPAPP_INSTANCE_KEY` задает свой ключ одиночного экземпляра. Без него вторая копия
  только покажет окно уже запущенной и завершится.

```bash
BACKUPAPP_CONFIG_DIR=/tmp/backupapp-dev BACKUPAPP_INSTANCE_KEY=dev python backup-app.py
```

## Архитектура проекта

Приложение разделено на бэкенд и фронтенд.

- **Бэкенд** (`backup_app/backend`) содержит всю логику: копирование, расписание вкладок, проверки,
  правила безопасности, настройки, автозапуск и журнал. Он написан на чистом Python
  и не импортирует ни Qt, ни фронтенд. Его можно запускать и тестировать без окна.
- **Фронтенд** (`backup_app/frontend`) содержит только интерфейс на PyQt5: окно, страницы, трей,
  оформление, защиту от второго экземпляра. Он показывает состояние бэкенда, передает ему команды
  и получает от него события. К бэкенду обращается только через пакет `backup_app.backend`.
- **Точка сборки** (`backup_app/main.py`) создает бэкенд и фронтенд и связывает их.

Границы проверяются тестами `tests/test_architecture.py`: бэкенд не загружает ни одного модуля
PyQt5, фронтенд импортирует только публичные имена бэкенда и не работает с файлами напрямую
(нет `shutil`, `os.walk`, `os.scandir`, `threading`).

### Структура проекта

```
backup-desktop-app/
├── backup-app.py                  # Точка входа (тонкий лаунчер)
├── backup_app/
│   ├── __main__.py                # python -m backup_app
│   ├── main.py                    # Точка сборки: бэкенд + фронтенд, флаги --minimized/--hidden/-m
│   ├── backend/                   # Логика, чистый Python, без Qt
│   │   ├── __init__.py            # Публичное API бэкенда и create_service()
│   │   ├── service.py             # BackupService: настройки, расписание вкладок, запуск, события
│   │   ├── events.py              # События для интерфейса
│   │   ├── copier.py              # BackupRunner: копирование в два прохода, параметры у каждого задания
│   │   ├── safety.py              # Правила безопасности: ссылки, системные пути, длина пути
│   │   ├── scheduler.py           # Расчет следующего и предыдущего запуска
│   │   ├── settings_store.py      # AppConfig, TabConfig, SettingsStore, перенос старых настроек
│   │   ├── ini.py                 # Чтение и запись INI в формате QSettings
│   │   ├── autostart.py           # Автозапуск: реестр Windows, .desktop, LaunchAgents
│   │   ├── history.py             # История копирования: записи, вкладки записей, файл history.txt
│   │   ├── logger.py              # Подробный журнал: файл с ротацией
│   │   ├── paths.py               # Папка настроек, журнал, путь лаунчера
│   │   ├── wording.py             # Согласование слов с числами: 1 файл, 2 файла
│   │   └── constants.py
│   └── frontend/                  # Интерфейс на PyQt5, без логики
│       ├── app.py                 # QtFrontend: HiDPI, QApplication, оформление, одиночный экземпляр, запуск
│       ├── bridge.py              # ServiceBridge: события бэкенда в поток интерфейса
│       ├── theme.py               # Цвета C, шрифты, палитра, QSS, AppStyle, FocusTracker
│       ├── icons.py               # Иконки макета (SVG) → pix() / icon() / paint()
│       ├── widgets.py             # Готовые элементы: кнопки, переключатели, карточки, список вкладок, тост...
│       ├── tab_page.py            # TabPage: название, «Что копировать», «Папка сохранения», «Настройки вкладки»
│       ├── settings_page.py       # SettingsPage: страница «Настройки»
│       ├── history_panel.py       # HistoryPanel: «История копирования» с фильтром по вкладке
│       ├── main_window.py         # MainWindow: боковая панель, страницы, строка состояния, события, трей
│       ├── tray.py                # TrayIcon: меню, уведомления
│       ├── single_instance.py     # SingleInstance на QLocalServer/QLocalSocket
│       ├── resources.py           # Пути к ресурсам (icon.ico, fonts/) с учетом PyInstaller
│       └── constants.py           # Тексты окна, трея и уведомлений
├── fonts/                         # Golos Text, JetBrains Mono и их лицензии SIL OFL 1.1
├── tests/
│   ├── backend/                   # Тесты бэкенда, без Qt
│   ├── frontend/                  # Тесты интерфейса поверх настоящего бэкенда
│   └── test_architecture.py       # Проверка границ между слоями
├── .github/workflows/
│   ├── tests.yml                  # CI: pyflakes + pytest на Windows, Linux и macOS
│   └── release.yml                # Релиз по тегу vX.Y.Z: сборка для трех систем и публикация
├── scripts/github-release/        # Выпуск релиза: release.sh, проверка версии, история релизов
├── BackupApp.spec                 # Сборка без консоли: один файл, на macOS BackupApp.app
├── requirements.txt               # Все зависимости
├── settings_ example.ini          # Пример файла настроек с описанием ключей
├── icon.ico / icon.png / icon.icns  # в icon.ico размеры от 16 до 256 точек
└── docs/
    ├── README_USER_GUIDE.md
    ├── README_DEVELOPER_GUIDE.md
    └── UI_DESIGN.md               # Правила оформления интерфейса
```

### Модули бэкенда

| Модуль                | Отвечает за                                                                  |
| --------------------- | ---------------------------------------------------------------------------- |
| `service.py`          | единственная точка входа: настройки, расписание вкладок, запуск, проверки, события |
| `copier.py`           | обход папок, копирование, именование копий, проверка места, итог             |
| `safety.py`           | ссылки, системные пути, типы файлов, лимит размера, длина пути               |
| `scheduler.py`        | время следующего и предыдущего запуска                                       |
| `settings_store.py`   | структура настроек, значения по умолчанию, перенос настроек прежних версий   |
| `ini.py`              | формат INI, совместимый с QSettings, включая блоки `@Variant`                |
| `autostart.py`        | включение, отключение и проверка автозапуска                                 |
| `history.py`          | история копирования: записи, вкладки записей, файл `history.txt`, срок хранения |
| `logger.py`           | подробный журнал: файл с ротацией                                            |
| `events.py`           | события, которые получает интерфейс                                          |
| `wording.py`          | согласование слов с числами в сообщениях                                     |

### Модули фронтенда

| Модуль              | Отвечает за                                                                    |
| ------------------- | ------------------------------------------------------------------------------ |
| `app.py`            | `QtFrontend`: `theme.enable_hidpi()`, `QApplication`, `theme.apply()`, иконка, одиночный экземпляр, `run()` |
| `bridge.py`         | `ServiceBridge`: события сервиса → сигнал Qt `event_received` в потоке интерфейса |
| `theme.py`          | цвета `C`, размеры, шрифты (`load_fonts()`, `font()`, `qss_font()`), палитра, QSS, `AppStyle`, `set_props()` |
| `icons.py`          | иконки макета как SVG 24×24 с подстановкой цвета, четкие на HiDPI              |
| `widgets.py`        | `Button`, `ToggleSwitch`, `Segmented`, `DayChips`, `MonthdayStepper`, `SwitchRow`, `OptionCheck`, `Card`, `NoticeBanner`, `StatusLine`, `GripSplitter`, `SidebarTabList`, `Toast`, `OverlayDialog`/`confirm()`, `TitleEdit`, `FlexRow` и другие |
| `tab_page.py`       | `TabPage` — вид выбранной вкладки; функции текстов `fmt_when()`, `sched_short()`, `preview_texts()` |
| `settings_page.py`  | `SettingsPage` — общие настройки: четыре переключателя, лимит размера, сброс   |
| `history_panel.py`  | `HistoryPanel` — история копирования, фильтр «Только «Имя»», кнопка журнала    |
| `main_window.py`    | `MainWindow` — боковая панель (`Sidebar`), разделитель, страницы, `StatusBar`, тост, подтверждения, события, трей |
| `tray.py`           | `TrayIcon` — меню, уведомления                                                 |
| `single_instance.py`| защита от второго экземпляра                                                   |
| `resources.py`      | `resource_path()` — путь к файлам рядом с программой или внутри exe            |
| `constants.py`      | тексты окна, трея и уведомлений                                                |

### Как слои общаются

1. Пользователь меняет вкладку или нажимает кнопку. `MainWindow` вызывает метод `BackupService`:
   `update_config()` (любая правка, сразу), `set_tab_schedule()` (переключатель расписания),
   `run_now([uid])` («Копировать сейчас»), `run_now()` («Копировать все вкладки»), `cancel()`, `reset()`,
   `set_autostart()`. Команды возвращают список проблем, если выполнить их нельзя, и окно показывает тост.
2. Сервис запускает копирование в своем фоновом потоке. Планировщик тоже работает в фоновом
   потоке сервиса и сам вызывает `tick()`.
3. О происходящем сервис сообщает событиями: `BackupStarted`, `BackupProgress`, `BackupFinished`,
   `RunSkipped`, `ScheduleChanged`, `ConfigChanged`, `HistoryAdded` и `AppProblem`.
4. `ServiceBridge` подписан на события сервиса. Он превращает их в сигналы Qt, поэтому окно
   получает их в своем потоке и меняет виджеты безопасно.
5. Окно показывает историю копирования: при запуске берет записи из `service.history()`, затем
   добавляет новые из событий `HistoryAdded`. Журнал `logging` в окно не попадает, его открывает
   кнопка «Открыть подробный журнал» по пути `service.log_path`.

```python
service = create_service()               # бэкенд: настройки, история и журнал в папке пользователя
bridge = ServiceBridge(service)          # фронтенд: доставка событий в поток интерфейса
window = MainWindow(service, bridge)
service.start()                          # синхронизировать автозапуск, возобновить расписания, запустить планировщик
```

### Ключевые классы

#### TabConfig и AppConfig

```python
@dataclass
class TabConfig:
    uid: str                      # постоянный идентификатор, new_tab_uid(): 12 знаков uuid4
    title: str = "Без названия"   # DEFAULT_TAB_TITLE
    folders: List[str]; files: List[str]; destination: str = ""
    # расписание вкладки
    schedule_on: bool = False     # меняет только сервис (set_tab_schedule)
    period_type: str = PERIOD_DAILY
    backup_time: str = "09:00"
    weekday: int = 0              # 0 = понедельник
    monthday: int = 1             # 1..31
    # параметры копирования вкладки
    copy_folder_contents: bool = False
    create_backup_folder: bool = True
    keep_history: bool = True
    # служебные отметки, их ведет сервис
    timer_started_at: Optional[datetime] = None
    last_backup_time: Optional[datetime] = None

    def has_sources(self) -> bool
    def problems(self) -> List[str]       # [NO_SOURCES] и/или [NO_DESTINATION]
    def schedule(self) -> Schedule
    def options(self) -> BackupOptions

@dataclass
class AppConfig:
    auto_start: bool = False              # меняет только сервис (set_autostart)
    minimize_to_tray: bool = True
    show_notifications: bool = True
    run_missed: bool = True
    max_file_size_gb: int = 2             # DEFAULT_MAX_FILE_SIZE_GB, 0 — без ограничения
    active_tab: int = 0
    tabs: List[TabConfig]                 # по умолчанию одна пустая вкладка

    def current_tab(self) -> TabConfig
    def tab(self, uid) -> Optional[TabConfig]
```

`update_config()` берет из окна только поля `EDITABLE_FIELDS` (`minimize_to_tray`, `show_notifications`,
`run_missed`, `max_file_size_gb`, `active_tab`, `tabs`). У вкладок поля `SERVICE_TAB_FIELDS`
(`schedule_on`, `timer_started_at`, `last_backup_time`) сервис берет из своей копии по `uid`, у новой
вкладки они выключены. Если у вкладки с работающим расписанием изменились период, время или день,
следующее копирование пересчитывается и приходит `ScheduleChanged`. Удаление вкладки с работающим
расписанием останавливает его и пишет в историю «Расписание остановлено: <Имя>».

#### BackupService

```python
service.start(run_scheduler=True)  # синхронизация автозапуска, возобновление расписаний вкладок
service.update_config(config)      # изменения из окна; служебные поля сервис ведет сам
service.set_tab_schedule(uid, enabled) -> list  # пустой список, если получилось; иначе проблемы вкладки
service.run_now(tab_ids=None, scheduled=False) -> list  # None — все вкладки с данными
service.cancel()
service.tick(now=None) -> bool     # проверка расписания; вызывается планировщиком
service.problems(tab_id=None) -> list   # что мешает скопировать вкладку или все вкладки
service.next_runs() -> dict        # {uid: следующее копирование} вкладок с работающим расписанием
service.schedule_active            # расписание работает хотя бы у одной вкладки
service.next_run                   # ближайшее копирование среди вкладок или None
service.is_running, service.running_tabs  # идет ли копирование и каких вкладок
service.config                     # глубокая копия AppConfig
service.history() -> list          # записи истории, от старых к новым
service.reset() -> AppConfig
service.set_autostart(enabled)     # при ошибке бросает исключение
service.source_problem(path), service.destination_problem(path), service.path_problem(path)
service.wait_idle(timeout=None) -> bool
service.shutdown()
```

- `set_tab_schedule(uid, True)` для вкладки с проблемами возвращает их (`NO_SOURCES`, `NO_DESTINATION`)
  и ничего не меняет. Иначе ставит `schedule_on`, `timer_started_at`, сохраняет настройки, пишет в историю
  «Расписание запущено: <Имя>, следующее копирование: дд.мм.гггг чч:мм» и шлет `ScheduleChanged`.
  Выключение пишет «Расписание остановлено: <Имя>», если расписание было включено.
- `run_now(None)` копирует все вкладки с данными, остальные молча пропускает; если таких нет —
  `[NO_TABS_WITH_DATA]`. `run_now([uid])` для вкладки с проблемами возвращает ее проблемы. Пока идет
  копирование, новое не запускается: `run_now()` возвращает `[ALREADY_RUNNING]` и шлет `RunSkipped`.
  После успешного или частичного итога у скопированных вкладок обновляется `last_backup_time`.
- `tick(now)`: вкладки, чье время подошло (`now >= next_run`), получают следующее время и копируются
  вместе одним копированием (`scheduled=True`). Вкладка с проблемами не копируется — запись в истории
  «✗ Плановое копирование не запущено (<Имя>): <причины>» и `RunSkipped`, остальные копируются.
  Если в это время идет копирование — «⚠ Плановое копирование не запущено: в это время шло другое
  копирование (<Имя>)» по каждой вкладке.
- Каждое задание копирования (`BackupJob`) несет параметры своей вкладки (`options=tab.options()`).
- Каждая запись истории о конкретных вкладках хранит их идентификаторы (`HistoryEntry.tab_ids`).

В конструктор можно передать свои часы (`now=`), интервал проверки (`check_interval=`), задержку
пропущенного копирования (`missed_run_delay=`) и модуль автозапуска (`autostart=`), так сервис
тестируется без ожидания реального времени и без записи в систему.

#### События

| Событие | Поля | Когда |
|---|---|---|
| `BackupStarted` | `scheduled`, `tab_names`, `tab_ids` | началось копирование |
| `BackupProgress` | `percent`, `text` | ход копирования |
| `BackupFinished` | `result`, `scheduled`, `tab_ids` | копирование закончилось |
| `RunSkipped` | `scheduled`, `reason` | копирование не запущено |
| `ScheduleChanged` | `next_runs`; свойства `active`, `nearest`, `next_run` | изменилось расписание вкладок |
| `ConfigChanged` | `config` | настройки изменились не по команде окна: сброс, синхронизация автозапуска |
| `HistoryAdded` | `entry` | новая запись истории |
| `AppProblem` | `title`, `text` | сбой самого приложения, например запись настроек |

`ScheduleChanged.next_runs` — кортеж пар `(uid, datetime)` каждой вкладки с работающим расписанием,
в порядке вкладок; пустой кортеж — расписание остановлено везде. Это снимок состояния: сервис берет его
прямо перед рассылкой, и последнее полученное событие всегда совпадает с `next_runs()`. Подписчики
вызываются вне блокировки сервиса.

#### BackupRunner

Копирует за два прохода. Первый проход считает файлы и объем и записывает пропуски по правилам
безопасности. Второй проход копирует и записывает ошибки. Параметры копирования задания берутся из
`BackupJob.options`, а если их нет — из `BackupRunner.options` (`options_for(job)`). `BackupResult.status`
принимает значения `ok`, `partial` (были ошибки), `cancelled`, `failed`. Пропуски по правилам безопасности
лежат в `BackupResult.skipped` и ошибками не считаются.

#### Schedule / next_run / previous_run

```python
schedule = Schedule(PERIOD_MONTHLY, time(10, 0), monthday=31)
next_run(schedule, now)      # ближайший запуск строго после now, 31-е обрезается до конца месяца
previous_run(schedule, now)  # последний запуск не позже now, нужен для пропущенных копирований
```

#### MainWindow

- `apply_config()` показывает настройки бэкенда, `collect_config()` собирает их обратно;
  любое изменение сразу уходит в `service.update_config()` (`save_settings()`), название вкладки
  и выбранная вкладка — с паузой `TITLE_COMMIT_MS`.
- `select_tab()`, `add_new_tab()`, `ask_delete_tab()` / `delete_tab()` управляют вкладками;
  `set_schedule()`, `manual_backup()`, `copy_all_tabs()`, `cancel_backup()` — команды сервису.
- `on_backend_event()` отображает события: ход и итог в строке состояния, расписание в списке вкладок,
  на странице и в трее, записи истории, уведомления.
- `show_toast()` — короткое сообщение в окне (`Toast`), а при окне в трее — уведомление.
  `W.confirm()` — подтверждение удаления вкладки и сброса внутри окна.
- `closeEvent()`, `changeEvent()`, `hide_to_tray()`, `show_from_tray()`, `quit_app()` управляют поведением в трее.

Окно показывает одну страницу `TabPage` на все вкладки: `page.bind(tab)` привязывает ее к выбранной
вкладке, поэтому переключение мгновенное и при сотнях вкладок. Страница меняет переданный `TabConfig`
и сообщает сигналами `changed`, `title_edited`, `title_committed`, `run_requested`, `delete_requested`,
`schedule_toggled`; состояние от сервиса она получает через `set_state()`. Пути страница проверяет
через сервис (`source_problem`, `destination_problem`, `path_problem`), диск сама не читает.

## Интерфейс

Окно повторяет макет `Main.dc.html` (главное окно) и `Tray.dc.html` (меню трея и уведомления).
Цвета, шрифты, размеры, варианты элементов через свойства и правила для новых блоков описаны
в [docs/UI_DESIGN.md](UI_DESIGN.md) — прочитайте его перед правкой интерфейса. Коротко:

- цвета только из `theme.C`, стили только через QSS и динамические свойства (`kind`, `variant`,
  `theme.set_props()`), а не `setStyleSheet` в коде окна;
- новые элементы собираются из `widgets.py`, иконки добавляются в `icons.py`;
- тексты окна лежат в `frontend/constants.py` и в начале модулей страниц.

### Шрифты

Интерфейс использует Golos Text (Regular, Medium, SemiBold) и JetBrains Mono (Regular) из папки `fonts/`.
`theme.apply()` загружает их через `theme.load_fonts()`; если файлов нет, роли получают системный шрифт
подходящей жирности, интерфейс остается рабочим. Оба шрифта распространяются по лицензии SIL Open Font
License 1.1, тексты лицензий — `fonts/OFL-GolosText.txt` и `fonts/OFL-JetBrainsMono.txt`; они входят
в сборку вместе со шрифтами. Заменяя шрифт, обновите `theme.FONT_FILES`, `BackupApp.spec` и файл лицензии.

### Снимки окна без экрана

Снимки окна для сверки с макетом снимаются без дисплея: платформа Qt `offscreen`, отдельная папка
настроек и настоящий сервис. Сам набор сценариев (скрипт снимков и эталонные снимки макета) хранится
вне репозитория, в репозиторий он не входит. Подход:

1. Задать `QT_QPA_PLATFORM=offscreen` и временную `BACKUPAPP_CONFIG_DIR`, чтобы не тронуть рабочие
   настройки. Для масштаба 125/150/200 % — `QT_SCALE_FACTOR`.
2. Как в `QtFrontend`: `theme.enable_hidpi()` до создания `QApplication`, затем `theme.apply(app)`.
3. Записать нужные вкладки через `SettingsStore.save(AppConfig(...))` и создать `BackupService` с заглушкой
   автозапуска (объект с `is_enabled`, `enable`, `disable`).
4. Создать `MainWindow(service, ServiceBridge(service))`, вызвать `service.start(run_scheduler=False)`
   и задать размер окна явно: экран `offscreen` маленький, и окно иначе ужмется до минимального 760×560.
5. Привести окно в нужное состояние командами сервиса (`set_tab_schedule()`) и окна (`select_tab()`,
   `show_settings_section()`, `show_toast()`), а состояния копирования — событиями прямо в
   `window.on_backend_event()` (`BackupStarted`, `BackupProgress`, `BackupFinished`), без настоящего копирования.
6. `app.processEvents()` и `window.grab().save(...)`. Меню трея снимается так же: `TrayIcon(...).menu()`,
   `adjustSize()`, `grab()`.

```python
import os, tempfile, types
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["BACKUPAPP_CONFIG_DIR"] = tempfile.mkdtemp()
from PyQt5.QtWidgets import QApplication
from backup_app.backend import (AppConfig, BackupProgress, BackupService, BackupStarted, SettingsStore,
                                TabConfig, paths)
from backup_app.frontend import theme
from backup_app.frontend.bridge import ServiceBridge
from backup_app.frontend.main_window import MainWindow

theme.enable_hidpi()
app = QApplication([])
theme.apply(app)
store = SettingsStore(paths.settings_path())
store.save(AppConfig(tabs=[TabConfig(uid="docs", title="Документы", folders=["/home"], destination="/tmp")]))
stub = types.SimpleNamespace(is_enabled=lambda: False, enable=lambda: True, disable=lambda: None)
service = BackupService(store, autostart=stub)
window = MainWindow(service, ServiceBridge(service))
service.start(run_scheduler=False)
service.set_tab_schedule("docs", True)
window.resize(1180, 868)
window.show()
app.processEvents()
window.grab().save("01-tab.png")
window.on_backend_event(BackupStarted(False, ("Документы",), ("docs",)))
window.on_backend_event(BackupProgress(42, "Копирование..."))
app.processEvents()
window.grab().save("02-running.png")
service.shutdown()
```

Отдельный элемент снимается так же, пример — в разделе «Снимки окна без экрана» файла `docs/UI_DESIGN.md`.

## Фоновый режим

- Главное окно не завершает приложение: `app.setQuitOnLastWindowClosed(False)`, закрытие и
  сворачивание прячут окно в трей, если трей доступен и включена настройка `minimize_to_tray`.
- Флаг `--minimized` (а также `--hidden`, `-m`) запускает приложение без окна. Автозапуск всегда
  использует этот флаг; в режиме скрипта на Windows подставляется `pythonw.exe`.
- `SingleInstance` слушает локальный сокет `BackupApp-single-instance-<пользователь>`.
  Второй экземпляр подключается, просит показать окно и завершается.
- При запуске через python на Windows `set_windows_app_id()` задает приложению свой
  AppUserModelID, иначе Windows показывает на панели задач значок Python. В собранном exe он
  не задается: иконку Windows берет из самого файла, а закрепленный ярлык и запущенное окно
  остаются одной кнопкой.
- Планировщик работает в потоке бэкенда. Он просыпается не реже раза в минуту и точно к ближайшему
  запуску любой вкладки, поэтому копирование начинается вовремя и после выхода компьютера из сна.
- Плановые запуски не открывают диалогов: проблемы пишутся в журнал и историю копирования
  и приходят событием `RunSkipped`, а интерфейс показывает уведомление в трее.
- Сбои самого приложения, например ошибка записи настроек, приходят событием `AppProblem`.
  Окно показывает их диалогом, а при работе в трее уведомлением, даже если уведомления
  о копировании выключены. Ошибка записи настроек показывается один раз до следующей удачной записи.
- Возобновление при запуске (`start()`): у каждой вкладки с `schedule_on` проверяются проблемы. Вкладка
  без источников или папки назначения выключается, в историю пишется «✗ Расписание не возобновлено
  (<Имя>): <причины>». Остальные получают следующее время запуска.
- Пропущенное копирование считается по каждой вкладке: если `previous_run(tab.schedule())` позже
  максимума из `tab.last_backup_time` и `tab.timer_started_at`, вкладка попадает в пропущенные
  (при включенном `run_missed`), в историю пишется «⚠ Пропущено плановое копирование дд.мм.гггг чч:мм,
  выполняется сейчас (<Имя>)». Все пропущенные вкладки копируются вместе через
  `MISSED_RUN_DELAY_SECONDS` после старта.
- Если системный трей недоступен, закрытие окна завершает приложение, об этом пишется
  предупреждение в журнал.

## Безопасность копирования

Правила собраны в `backend/safety.py` и применяются в `backend/copier.py`:

- ссылки и junction внутри выбранных папок пропускаются; явно выбранная ссылка копируется;
- системные папки и файлы нельзя выбрать источником или назначением и они пропускаются при обходе
  (`system_paths()` и имена в корне диска Windows вроде `$Recycle.Bin`);
- копируются только обычные файлы, специальные файлы пропускаются;
- файлы больше лимита пропускаются, лимит берется из настройки `max_file_size_gb`, 0 снимает его;
- путь копии не длиннее `MAX_PATH_LENGTH = 240`: имя файла укорачивается функцией `shorten_name()`,
  слишком глубокая папка пропускается;
- путь копии проверяется функцией `is_inside()`, относительный путь с «..» отбрасывается;
- папка назначения внутри копируемой папки при обходе пропускается.

Каждое событие пишется в журнал с меткой `[SECURITY]`. Однотипных записей за одно копирование
пишется не больше `LOG_LIMIT = 200`, затем итоговое число.

## Настройки и журнал

Папка настроек совпадает с прежней, которую выбирал `QStandardPaths.AppConfigLocation`:

| ОС      | settings.ini                                   | журнал                                         |
| ------- | ---------------------------------------------- | ---------------------------------------------- |
| Windows | `%LOCALAPPDATA%\BackupApp\settings.ini`        | `%LOCALAPPDATA%\BackupApp\logs\backup-app.log` |
| Linux   | `~/.config/BackupApp/settings.ini`             | `~/.config/BackupApp/logs/backup-app.log`      |
| macOS   | `~/Library/Preferences/BackupApp/settings.ini` | рядом, в `logs/`                               |

Файл настроек читается и пишется модулем `backend/ini.py` без Qt, в том же формате, что писал
QSettings. Старые файлы открываются без изменений, включая списки из одного пути, которые
PyQt5 сохранял двоичным блоком `@Variant(...)`. Новые файлы пишут такой список обычной строкой.
Запись атомарная: через временный файл.

### Ключи settings.ini

Секция `[General]` — общие настройки приложения: `auto_start`, `minimize_to_tray`, `show_notifications`,
`run_missed`, `max_file_size_gb`, `active_tab`, `tab_count`, `tab_names`.

Вкладки — секции `[Tab_0]`, `[Tab_1]`, … Каждая хранит:

| Ключ | Поле `TabConfig` |
|---|---|
| `tab_id` | `uid` (латинские буквы, цифры, `_`, `-`; нет или повторяется — создается новый) |
| `tab_title` | `title` |
| `source_folders`, `source_files` | `folders`, `files` |
| `destination_folder` | `destination` |
| `timer_active` | `schedule_on` |
| `period_type`, `backup_time`, `weekday`, `monthday` | расписание вкладки |
| `copy_folder_contents`, `create_backup_folder`, `keep_history` | параметры копирования вкладки |
| `timer_started_at`, `last_backup_time` | служебные отметки (ISO 8601) |

Значения проверяются при чтении: период из `PERIODS`, время «чч:мм», `weekday` 0..6, `monthday` 1..31,
`max_file_size_gb` 0..`MAX_FILE_SIZE_GB_LIMIT`; неверное значение заменяется значением по умолчанию.
Недоступные пути из настроек не удаляются, а подсвечиваются в списке. Полный пример с пояснениями —
`settings_ example.ini`.

### Перенос настроек прежних версий

Прежние версии хранили расписание и параметры копирования одни на все приложение в `[General]`
(`period_type`, `backup_time`, `weekday`, `monthday`, `copy_folder_contents`, `create_backup_folder`,
`keep_history`, `timer_active`, `copy_all_tabs`, `timer_started_at`, `last_backup_time`). `SettingsStore.load()`
переносит их автоматически:

- ключ вкладки, которого нет в `[Tab_N]`, берется из ключа `[General]` с тем же именем
  (`_TabValues.get()`): так каждая вкладка получает общий период, время, день, параметры копирования
  и отметки `timer_started_at`/`last_backup_time`;
- `timer_active` вкладки при отсутствии берется из общего (`_migrate_schedule()`): если в `[General]`
  `timer_active=true`, то при `copy_all_tabs=true` расписание включается у всех вкладок без проблем
  (есть источники и папка назначения), иначе — только у вкладки `active_tab`; иначе выключено;
- ключи, которые уже есть у вкладки, всегда главнее общих;
- нет `tab_id` или он повторяется — вкладка получает новый `uid`.

При следующем сохранении файл пишется в новом виде: общие ключи расписания и параметров в `[General]`
больше не пишутся, лишние секции `[Tab_N]` удаляются. Вкладки и пути нового файла читаются и прежними
версиями, но расписание и параметры копирования они возьмут по умолчанию.

### Журнал и история

Подробный журнал ведется через `logging` с `RotatingFileHandler` (1 МБ, 3 файла). В окно он не
попадает.

История копирования хранится рядом с `settings.ini` в файле `history.txt`, модуль `backend/history.py`.
Запись начинается строкой `дд.мм.гггг чч:мм  текст`, подробности идут следующими строками с отступом
в 20 пробелов. Если запись относится к вкладкам, сразу за первой строкой идет строка с тем же отступом
`#tabs: uid1 uid2` — по ней окно отбирает записи вкладки (фильтр «Только «Имя»»). В окне эта строка
не показывается (`HistoryEntry.lines()`), в файл ее пишет `HistoryEntry.file_lines()`. Файлы прежних
версий без строки `#tabs:` читаются как раньше, их записи ни к одной вкладке не относятся.

```
06.10.2026 09:00  Плановое копирование: Документы, Фото
                    #tabs: 3f2a9c1d7e40 8b51e0c4a2f7
06.10.2026 09:02  ⚠ Скопировано 150 файлов, ошибок: 1
                    #tabs: 3f2a9c1d7e40 8b51e0c4a2f7
                    Не скопирован C:\Документы\отчет.docx: файл занят другой программой
```

Записи старше `RETENTION_DAYS = 365` удаляются при загрузке и при добавлении новых, у одной записи
хранится не больше `MAX_DETAILS = 20` подробностей. Если файл истории не читается, он только
дописывается, чтобы не потерять записи. Причины ошибок в истории короткие («файл занят другой
программой»), их дает `describe_error()` из `copier.py`; технический текст ошибки пишется в журнал.

## Процесс сборки

### Сборка с PyInstaller

```bash
pip install -r requirements.txt
pyinstaller BackupApp.spec
```

PyInstaller собирает программу только для той системы и архитектуры, на которой запущен.
Результат:

- **Windows**: один файл `dist/BackupApp.exe` без окна консоли, иконка `icon.ico`. Номер версии
  виден в свойствах файла (вкладка «Подробно»). Собранный exe автозапуск регистрирует как
  `"...\BackupApp.exe" --minimized`.
- **Linux**: один файл `dist/BackupApp`. Для трея нужна панель с поддержкой
  StatusNotifier/XEmbed; без нее приложение предупредит в журнале и будет завершаться при
  закрытии окна.
- **macOS**: приложение `dist/BackupApp.app` с иконкой `icon.icns` и версией в `Info.plist`.
  Программа для macOS всегда папка-бандл, поэтому здесь сборка папкой внутри бандла, а не
  одним файлом.

В сборку (`datas` в `BackupApp.spec`) включаются `icon.ico`, четыре файла шрифтов и две лицензии
OFL в папку `fonts`; `resource_path()` находит их и в исходниках, и внутри exe (`sys._MEIPASS`).
Модуль `PyQt5.QtNetwork` указан в `hiddenimports`, он нужен для защиты от второго экземпляра.
Номер версии spec берет из `VERSION` в `backup_app/backend/constants.py`. Файл `settings.ini`
при первом запуске приложение создает само.

### Выпуск релиза

Готовые программы для всех трех систем собирает GitHub по команде
`scripts/github-release/release.sh 9.0.1`. Как выпустить версию, что проверяется до выпуска и
что делать, если что-то пошло не так, описано в [README_RELEASE.md](README_RELEASE.md).

## Тестирование

### Запуск

```bash
pip install -r requirements.txt
python -m pyflakes backup_app tests backup-app.py
python -m pytest                       # все тесты
python -m pytest tests/backend         # только бэкенд, Qt не нужен
python -m pytest tests/frontend -v     # интерфейс
```

Так же, как в CI:

```bash
QT_QPA_PLATFORM=offscreen PYTHONUTF8=1 python -m pytest
```

Тесты не требуют дисплея: `conftest.py` выставляет `QT_QPA_PLATFORM=offscreen`, подменяет
функции автозапуска, чтобы ничего не записывать в реестр, и дает тестам окна временную папку
настроек. Тесты junction запускаются только на Windows, тесты символьных ссылок требуют права
на их создание, тест именованного канала запускается только на Linux и macOS.

### Структура тестов

```
tests/
├── conftest.py               # фикстуры qapp, config_dir, log_records, изоляция автозапуска
├── helpers.py                # make_tree, list_rel, pump, wait_for
├── test_architecture.py      # бэкенд без Qt, фронтенд только через API бэкенда
├── backend/
│   ├── test_service.py       # расписание вкладок, запуск, события, пропущенные копирования, автозапуск
│   ├── test_copier.py        # копирование, именование, ошибки, отмена, параметры заданий
│   ├── test_safety.py        # каждое правило безопасности на настоящих файлах
│   ├── test_history.py       # формат и файл истории копирования, строка #tabs, срок хранения
│   ├── test_wording.py       # 1 файл, 2 файла, 5 файлов
│   ├── test_ini.py           # совместимость с форматом QSettings, сверка с настоящим QSettings
│   ├── test_settings_store.py  # ключи вкладок, перенос настроек прежних версий, пример INI
│   ├── test_scheduler.py
│   └── test_autostart.py
└── frontend/
    ├── test_main_window.py   # окно поверх настоящего сервиса
    ├── test_pages.py         # тексты страницы вкладки, пример копии, история, перенос строк
    ├── test_widgets.py       # оформление и готовые элементы без экрана
    ├── test_bridge.py        # события из фоновых потоков приходят в поток интерфейса
    ├── test_single_instance.py
    └── test_app.py
```

### Как тестировать сервис и окно

```python
def test_tick_runs_backup_when_due(make_service, paths):
    service, events, _clock = make_service(ready_config(paths))  # свои часы, без Qt
    service.set_tab_schedule("data", True)
    assert service.tick(NEXT + timedelta(seconds=1)) is True     # наступило время запуска
    assert service.next_run == NEXT + timedelta(days=1)
    assert service.wait_idle(10)
    assert of_type(events, BackupStarted) == [BackupStarted(True, ("Данные",), ("data",))]
```

Фикстура `env` в тестах окна создает настоящий сервис и подменяет `QMessageBox`, `TrayIcon.notify`
и `Toast.show_message` на записывающие заглушки: тест проверяет, что из плановых запусков не открылся
ни один диалог. Модальное окно внутри окна отвечает без цикла событий: `OverlayDialog.preset_answer`
задает ответ, `OverlayDialog.asked` записывает вопросы.

### CI

- `.github/workflows/tests.yml` при каждом push в ветку и в pull request запускает pyflakes и
  pytest на `windows-latest`, `ubuntu-latest` и `macos-latest` (Python 3.11 и 3.12) с
  `QT_QPA_PLATFORM=offscreen` и `PYTHONUTF8=1`, а также тесты скриптов выпуска на тех же трех
  системах. На Linux перед запуском ставятся системные библиотеки Qt.
- `.github/workflows/release.yml` запускается тегом `vX.Y.Z`: собирает программу для
  Windows, macOS и Linux и публикует релиз, см. [README_RELEASE.md](README_RELEASE.md).

## Вклад в проект

### Процесс разработки

1. Форкните репозиторий
2. Создайте feature-ветку: `git checkout -b feature/amazing-feature`
3. Закоммитьте изменения: `git commit -m 'Add amazing feature'`
4. Запушьте ветку: `git push origin feature/amazing-feature`
5. Откройте Pull Request

### Стандарты кода

- Соблюдайте PEP8
- Документируйте публичные методы с использованием docstrings
- Пишите тесты для новой функциональности
- Обновляйте документацию
- Используйте type hints для аргументов и возвращаемых значений
- Логика живет только в бэкенде и не импортирует Qt; интерфейс обращается к бэкенду
  только через `backup_app.backend`. Это проверяет `tests/test_architecture.py`
- Комментарии, docstrings и тексты интерфейса — на русском; всегда пишется «е», в том числе там,
  где обычно ставят букву с двумя точками
- Оформление интерфейса — по правилам `docs/UI_DESIGN.md`

### Структура коммитов

```
feat: добавление новой функциональности
fix: исправление ошибки
docs: обновление документации
test: добавление тестов
refactor: рефакторинг кода без изменения функциональности
style: исправление форматирования (пробелы, запятые и т.д.)
perf: изменения улучшающие производительность
```

### Code Review процесс

1. Проверка соответствия стандартам кодирования
2. Тестирование функциональности на разных платформах
3. Проверка документации и комментариев
4. Проверка покрытия тестами
5. Одобрение двумя участниками проекта

### Особенности разработки для разных платформ

#### Windows

- Учитывайте ограничения длины путей
- Тестируйте работу с автозапуском через реестр (в тестах реестр подменяется)
- Для запуска без консоли используйте `pythonw.exe`
- Проверяйте интерфейс при масштабе 125 % и 150 % (`QT_SCALE_FACTOR`)

#### Linux

- Учитывайте права доступа к файлам
- Тестируйте работу с .desktop файлами и доступность трея в вашей оболочке

#### macOS

- Учитывайте sandbox ограничения
- Тестируйте работу с LaunchAgents
- Проверяйте совместимость с разными версиями macOS

### Отладка и диагностика

Журнал приложения уже пишется в файл (см. раздел «Настройки и журнал»). Чтобы получить больше
подробностей, поднимите уровень при настройке:

```python
import logging
from backup_app.backend import setup_file_logging
setup_file_logging(log_directory, level=logging.DEBUG)
```
