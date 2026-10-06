"""Хранение настроек в settings.ini. Без Qt.

Формат совместим с прежними версиями: секция [General] с теми же ключами и секции
[Tab_N] для вкладок. Файл читается и пишется модулем ini.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from .constants import DEFAULT_TAB_TITLE
from .ini import IniValue, read_ini, write_ini
from .safety import DEFAULT_MAX_FILE_SIZE_GB
from .scheduler import PERIOD_DAILY, PERIODS, Schedule, parse_time

MAX_TABS = 500
MAX_FILE_SIZE_GB_LIMIT = 1_000_000


@dataclass
class TabConfig:
    title: str = DEFAULT_TAB_TITLE
    folders: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    destination: str = ""

    def has_sources(self) -> bool:
        return bool(self.folders or self.files)


@dataclass
class AppConfig:
    period_type: str = PERIOD_DAILY
    backup_time: str = "00:00"
    weekday: int = 0
    monthday: int = 1
    keep_history: bool = True
    create_backup_folder: bool = True
    auto_start: bool = False
    timer_active: bool = False
    copy_folder_contents: bool = False
    copy_all_tabs: bool = False
    minimize_to_tray: bool = True
    show_notifications: bool = True
    run_missed: bool = True
    max_file_size_gb: int = DEFAULT_MAX_FILE_SIZE_GB
    active_tab: int = 0
    last_backup_time: Optional[datetime] = None
    timer_started_at: Optional[datetime] = None
    tabs: List[TabConfig] = field(default_factory=lambda: [TabConfig()])

    def schedule(self) -> Schedule:
        return Schedule(self.period_type, parse_time(self.backup_time), self.weekday, self.monthday)

    def current_tab(self) -> TabConfig:
        if not self.tabs:
            return TabConfig()
        if 0 <= self.active_tab < len(self.tabs):
            return self.tabs[self.active_tab]
        return self.tabs[0]


# Поля, которые меняет пользователь в окне. Остальные поля ведёт сервис.
EDITABLE_FIELDS = (
    "period_type", "backup_time", "weekday", "monthday", "keep_history", "create_backup_folder",
    "copy_folder_contents", "copy_all_tabs", "minimize_to_tray", "show_notifications", "run_missed",
    "max_file_size_gb", "active_tab", "tabs",
)

BOOL_KEYS = (
    "keep_history", "create_backup_folder", "auto_start", "timer_active", "copy_folder_contents",
    "copy_all_tabs", "minimize_to_tray", "show_notifications", "run_missed",
)
DATETIME_KEYS = ("last_backup_time", "timer_started_at")
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


def _as_time_text(value: IniValue) -> str:
    moment = parse_time(_as_text(value), None)
    return f"{moment.hour:02d}:{moment.minute:02d}" if moment else "00:00"


class SettingsStore:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> AppConfig:
        try:
            values = read_ini(self.path)
        except OSError:
            values = {}
        config = AppConfig()

        period = _as_text(values.get("period_type"))
        config.period_type = period if period in PERIODS else PERIOD_DAILY
        config.backup_time = _as_time_text(values.get("backup_time", config.backup_time))
        config.weekday = _as_int(values.get("weekday"), 0, 0, 6)
        config.monthday = _as_int(values.get("monthday"), 1, 1, 31)
        config.max_file_size_gb = _as_int(values.get("max_file_size_gb"), DEFAULT_MAX_FILE_SIZE_GB,
                                          0, MAX_FILE_SIZE_GB_LIMIT)
        for key in BOOL_KEYS:
            setattr(config, key, _as_bool(values.get(key), getattr(config, key)))
        for key in DATETIME_KEYS:
            setattr(config, key, _as_datetime(values.get(key)))

        tabs = []
        for index in range(_as_int(values.get("tab_count"), 1, 1, MAX_TABS)):
            prefix = f"Tab_{index}/"
            title = _as_text(values.get(prefix + "tab_title")).strip() or DEFAULT_TAB_TITLE
            tabs.append(TabConfig(
                title=title,
                folders=_as_list(values.get(prefix + "source_folders")),
                files=_as_list(values.get(prefix + "source_files")),
                destination=_as_text(values.get(prefix + "destination_folder")).strip(),
            ))
        config.tabs = tabs or [TabConfig()]
        config.active_tab = _as_int(values.get("active_tab"), 0, 0, len(config.tabs) - 1)
        return config

    def save(self, config: AppConfig) -> None:
        tabs = config.tabs or [TabConfig()]
        titles = [tab.title or DEFAULT_TAB_TITLE for tab in tabs]
        general = [
            ("period_type", config.period_type),
            ("backup_time", config.backup_time),
            ("weekday", int(config.weekday)),
            ("monthday", int(config.monthday)),
        ]
        general += [(key, bool(getattr(config, key))) for key in BOOL_KEYS]
        general += [
            ("max_file_size_gb", int(config.max_file_size_gb)),
            ("active_tab", int(config.active_tab)),
        ]
        for key in DATETIME_KEYS:
            moment = getattr(config, key)
            general.append((key, moment.isoformat(timespec="seconds") if moment else ""))
        general += [
            ("tab_count", len(tabs)),
            ("tab_names", titles[0] if len(titles) == 1 else titles),
        ]
        sections = [("", general)]
        for index, tab in enumerate(tabs):
            sections.append((f"Tab_{index}", [
                ("source_folders", list(tab.folders)),
                ("source_files", list(tab.files)),
                ("destination_folder", tab.destination or ""),
                ("tab_title", tab.title or DEFAULT_TAB_TITLE),
            ]))
        write_ini(self.path, sections)

    def reset(self) -> AppConfig:
        """Записывает настройки по умолчанию и возвращает их."""
        config = AppConfig()
        self.save(config)
        return config
