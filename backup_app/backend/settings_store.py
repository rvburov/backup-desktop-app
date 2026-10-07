"""Хранение настроек в settings.ini. Без Qt.

Секция [General] хранит общие настройки приложения, секции [Tab_N] хранят вкладки: что
копировать, куда, расписание и параметры копирования вкладки. Файл читается и пишется модулем ini.

Файлы версии 9 хранили расписание и параметры копирования одни на все приложение в [General].
При чтении такого файла каждая вкладка получает эти общие значения, а включенное расписание
достается всем вкладкам с данными (если было «копировать все вкладки») или выбранной вкладке.
"""
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set

from .constants import DEFAULT_TAB_TITLE, NO_DESTINATION, NO_SOURCES
from .copier import BackupOptions
from .ini import IniValue, read_ini, write_ini
from .safety import DEFAULT_MAX_FILE_SIZE_GB
from .scheduler import PERIOD_DAILY, PERIODS, Schedule, parse_time

MAX_TABS = 500
MAX_FILE_SIZE_GB_LIMIT = 1_000_000
DEFAULT_BACKUP_TIME = "09:00"

_UID = re.compile(r"[0-9A-Za-z_-]{1,64}")


def new_tab_uid() -> str:
    """Новый постоянный идентификатор вкладки."""
    return uuid.uuid4().hex[:12]


@dataclass
class TabConfig:
    uid: str = field(default_factory=new_tab_uid)
    title: str = DEFAULT_TAB_TITLE
    folders: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    destination: str = ""
    # расписание вкладки: пользователь меняет в окне все, кроме schedule_on
    schedule_on: bool = False
    period_type: str = PERIOD_DAILY
    backup_time: str = DEFAULT_BACKUP_TIME
    weekday: int = 0      # 0 = понедельник
    monthday: int = 1
    # параметры копирования вкладки; у новой вкладки, при первом запуске и после сброса все выключены
    copy_folder_contents: bool = False
    create_backup_folder: bool = False
    keep_history: bool = False
    copy_only_changed: bool = False
    # служебные отметки вкладки, их ведет сервис
    timer_started_at: Optional[datetime] = None
    last_backup_time: Optional[datetime] = None

    def has_sources(self) -> bool:
        return bool(self.folders or self.files)

    def problems(self) -> List[str]:
        """Что мешает скопировать вкладку: нет источников и (или) нет папки назначения."""
        problems = []
        if not self.has_sources():
            problems.append(NO_SOURCES)
        if not self.destination:
            problems.append(NO_DESTINATION)
        return problems

    def schedule(self) -> Schedule:
        return Schedule(self.period_type, parse_time(self.backup_time), self.weekday, self.monthday)

    def options(self) -> BackupOptions:
        return BackupOptions(copy_folder_contents=self.copy_folder_contents,
                             keep_history=self.keep_history,
                             create_backup_folder=self.create_backup_folder,
                             copy_only_changed=self.copy_only_changed)


@dataclass
class AppConfig:
    # при первом запуске и после сброса все переключатели страницы «Настройки» выключены
    auto_start: bool = False
    minimize_to_tray: bool = False
    show_notifications: bool = False
    run_missed: bool = False
    max_file_size_gb: int = DEFAULT_MAX_FILE_SIZE_GB
    active_tab: int = 0
    tabs: List[TabConfig] = field(default_factory=lambda: [TabConfig()])

    def current_tab(self) -> TabConfig:
        if not self.tabs:
            return TabConfig()
        if 0 <= self.active_tab < len(self.tabs):
            return self.tabs[self.active_tab]
        return self.tabs[0]

    def tab(self, uid: str) -> Optional[TabConfig]:
        """Вкладка с идентификатором uid или None."""
        for tab in self.tabs:
            if tab.uid == uid:
                return tab
        return None


# Общие настройки, которые пользователь меняет в окне. auto_start меняет только сервис.
EDITABLE_FIELDS = ("minimize_to_tray", "show_notifications", "run_missed", "max_file_size_gb", "active_tab", "tabs")
# Поля вкладки, которые ведет сервис: окно их не меняет.
SERVICE_TAB_FIELDS = ("schedule_on", "timer_started_at", "last_backup_time")

GENERAL_BOOL_KEYS = ("auto_start", "minimize_to_tray", "show_notifications", "run_missed")
TAB_BOOL_KEYS = ("copy_folder_contents", "create_backup_folder", "keep_history", "copy_only_changed")
TAB_DATETIME_KEYS = ("timer_started_at", "last_backup_time")
_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off", ""}


def _as_list(value: IniValue) -> List[str]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item]
    text = str(value)
    return [text] if text else []


def _as_text(value: IniValue, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value if item is not None)
    return str(value)


def _as_int(value: IniValue, default: int, low: int, high: int) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return number if low <= number <= high else default


def _as_bool(value: IniValue, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    text = _as_text(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE and value is not None:
        return False
    return default


def _as_datetime(value: IniValue) -> Optional[datetime]:
    text = _as_text(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _as_time_text(value: IniValue, default: str = DEFAULT_BACKUP_TIME) -> str:
    moment = parse_time(_as_text(value), None)
    return f"{moment.hour:02d}:{moment.minute:02d}" if moment else default


def _datetime_text(moment: Optional[datetime]) -> str:
    return moment.isoformat(timespec="seconds") if moment else ""


class _TabValues:
    """Ключи одной секции [Tab_N]. Отсутствующий ключ берется из [General] (файлы версии 9)."""

    def __init__(self, values: Dict[str, IniValue], index: int):
        self._values = values
        self._prefix = f"Tab_{index}/"

    def own(self, key: str) -> IniValue:
        return self._values.get(self._prefix + key)

    def has(self, key: str) -> bool:
        return self._prefix + key in self._values

    def get(self, key: str) -> IniValue:
        return self.own(key) if self.has(key) else self._values.get(key)


class SettingsStore:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> AppConfig:
        try:
            values = read_ini(self.path)
        except OSError:
            values = {}
        config = AppConfig()
        config.max_file_size_gb = _as_int(values.get("max_file_size_gb"), DEFAULT_MAX_FILE_SIZE_GB,
                                          0, MAX_FILE_SIZE_GB_LIMIT)
        for key in GENERAL_BOOL_KEYS:
            setattr(config, key, _as_bool(values.get(key), getattr(config, key)))

        count = _as_int(values.get("tab_count"), 1, 1, MAX_TABS)
        config.active_tab = _as_int(values.get("active_tab"), 0, 0, count - 1)
        used: Set[str] = set()
        config.tabs = [self._load_tab(_TabValues(values, index), used) for index in range(count)]
        self._migrate_schedule(values, config)
        return config

    @staticmethod
    def _load_tab(values: _TabValues, used: Set[str]) -> TabConfig:
        tab = TabConfig()
        uid = _as_text(values.own("tab_id")).strip()
        if _UID.fullmatch(uid) and uid not in used:
            tab.uid = uid
        while tab.uid in used:
            tab.uid = new_tab_uid()
        used.add(tab.uid)
        tab.title = _as_text(values.own("tab_title")).strip() or DEFAULT_TAB_TITLE
        tab.folders = _as_list(values.own("source_folders"))
        tab.files = _as_list(values.own("source_files"))
        tab.destination = _as_text(values.own("destination_folder")).strip()
        tab.schedule_on = _as_bool(values.own("timer_active"), False)

        period = _as_text(values.get("period_type"))
        tab.period_type = period if period in PERIODS else PERIOD_DAILY
        tab.backup_time = _as_time_text(values.get("backup_time"))
        tab.weekday = _as_int(values.get("weekday"), 0, 0, 6)
        tab.monthday = _as_int(values.get("monthday"), 1, 1, 31)
        for key in TAB_BOOL_KEYS:
            setattr(tab, key, _as_bool(values.get(key), getattr(tab, key)))
        for key in TAB_DATETIME_KEYS:
            setattr(tab, key, _as_datetime(values.get(key)))
        return tab

    @staticmethod
    def _migrate_schedule(values: Dict[str, IniValue], config: AppConfig) -> None:
        """Общее расписание версии 9 становится расписанием вкладок, у которых нет своего."""
        if not _as_bool(values.get("timer_active"), False):
            return
        copy_all = _as_bool(values.get("copy_all_tabs"), False)
        for index, tab in enumerate(config.tabs):
            if f"Tab_{index}/timer_active" in values:
                continue
            tab.schedule_on = not tab.problems() if copy_all else index == config.active_tab

    def save(self, config: AppConfig) -> None:
        tabs = config.tabs or [TabConfig()]
        titles = [tab.title or DEFAULT_TAB_TITLE for tab in tabs]
        general = [(key, bool(getattr(config, key))) for key in GENERAL_BOOL_KEYS]
        general += [
            ("max_file_size_gb", int(config.max_file_size_gb)),
            ("active_tab", int(config.active_tab)),
            ("tab_count", len(tabs)),
            ("tab_names", titles[0] if len(titles) == 1 else titles),
        ]
        sections = [("", general)]
        for index, tab in enumerate(tabs):
            sections.append((f"Tab_{index}", self._tab_items(tab)))
        write_ini(self.path, sections)

    @staticmethod
    def _tab_items(tab: TabConfig) -> list:
        items = [
            ("tab_id", tab.uid),
            ("tab_title", tab.title or DEFAULT_TAB_TITLE),
            ("source_folders", list(tab.folders)),
            ("source_files", list(tab.files)),
            ("destination_folder", tab.destination or ""),
            ("timer_active", bool(tab.schedule_on)),
            ("period_type", tab.period_type),
            ("backup_time", tab.backup_time),
            ("weekday", int(tab.weekday)),
            ("monthday", int(tab.monthday)),
        ]
        items += [(key, bool(getattr(tab, key))) for key in TAB_BOOL_KEYS]
        items += [(key, _datetime_text(getattr(tab, key))) for key in TAB_DATETIME_KEYS]
        return items

    def reset(self) -> AppConfig:
        """Записывает настройки по умолчанию и возвращает их."""
        config = AppConfig()
        self.save(config)
        return config
