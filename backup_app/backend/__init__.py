"""Бэкенд: копирование, расписание, настройки, правила безопасности, автозапуск,
история копирования и подробный журнал.

Бэкенд написан на чистом Python и не зависит ни от Qt, ни от интерфейса. Интерфейс
обращается к нему только через имена, перечисленные здесь: создает BackupService,
вызывает его методы и получает от него события.
"""
from . import paths
from .constants import (APP_NAME, BACKUP_FOLDER_PREFIX, DEFAULT_TAB_TITLE, MINIMIZED_FLAG, NO_DESTINATION,
                        NO_SOURCES, VERSION)
from .copier import (STATUS_CANCELLED, STATUS_FAILED, STATUS_OK, STATUS_PARTIAL, BackupOptions, BackupResult,
                     backup_folder_name, folder_copy_name)
from .events import (AppProblem, BackupFinished, BackupProgress, BackupStarted, ConfigChanged, HistoryAdded,
                     RunSkipped, ScheduleChanged)
from .history import ICON_ERROR, ICON_OK, ICON_WARNING, HistoryEntry
from .logger import close_logging, get_logger, setup_file_logging
from .safety import DEFAULT_MAX_FILE_SIZE_GB, MAX_PATH_LENGTH, PATH_SYSTEM, PATH_UNAVAILABLE, SECURITY_TAG
from .scheduler import (PERIOD_DAILY, PERIOD_MONTHLY, PERIOD_WEEKLY, PERIODS, WEEKDAYS, Schedule, format_run_time,
                        next_run)
from .service import ALREADY_RUNNING, NO_TABS_WITH_DATA, SCHEDULED_WHILE_RUNNING, BackupService
from .settings_store import MAX_FILE_SIZE_GB_LIMIT, AppConfig, SettingsStore, TabConfig, new_tab_uid
from .wording import count_files, count_tabs_genitive, plural

__all__ = [
    "ALREADY_RUNNING", "APP_NAME", "AppConfig", "AppProblem", "BACKUP_FOLDER_PREFIX", "BackupFinished",
    "BackupOptions", "BackupProgress", "BackupResult", "BackupService", "BackupStarted", "ConfigChanged",
    "DEFAULT_MAX_FILE_SIZE_GB", "DEFAULT_TAB_TITLE", "HistoryAdded", "HistoryEntry", "ICON_ERROR", "ICON_OK",
    "ICON_WARNING", "MAX_FILE_SIZE_GB_LIMIT", "MAX_PATH_LENGTH", "MINIMIZED_FLAG", "NO_DESTINATION", "NO_SOURCES",
    "NO_TABS_WITH_DATA", "PATH_SYSTEM", "PATH_UNAVAILABLE", "PERIODS", "PERIOD_DAILY", "PERIOD_MONTHLY",
    "PERIOD_WEEKLY", "RunSkipped", "SCHEDULED_WHILE_RUNNING", "SECURITY_TAG", "STATUS_CANCELLED", "STATUS_FAILED",
    "STATUS_OK", "STATUS_PARTIAL", "Schedule", "ScheduleChanged", "SettingsStore", "TabConfig", "VERSION",
    "WEEKDAYS", "backup_folder_name", "close_logging", "count_files", "count_tabs_genitive", "create_service",
    "folder_copy_name", "format_run_time", "get_logger", "new_tab_uid", "next_run", "paths", "plural",
    "setup_file_logging",
]


def create_service() -> BackupService:
    """Сервис с настройками и журналом в стандартной папке пользователя."""
    log_path = setup_file_logging(paths.log_dir())
    return BackupService(SettingsStore(paths.settings_path()), log_path=log_path)
