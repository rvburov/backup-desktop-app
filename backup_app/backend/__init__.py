"""Бэкенд: копирование, расписание, настройки, правила безопасности, автозапуск,
история копирования и подробный журнал.

Бэкенд написан на чистом Python и не зависит ни от Qt, ни от интерфейса. Интерфейс
обращается к нему только через имена, перечисленные здесь: создает BackupService,
вызывает его методы и получает от него события.
"""
from . import paths
from .constants import APP_NAME, MINIMIZED_FLAG, VERSION
from .copier import STATUS_CANCELLED, STATUS_FAILED, STATUS_OK, STATUS_PARTIAL, BackupResult
from .events import (AppProblem, BackupFinished, BackupProgress, BackupStarted, ConfigChanged, HistoryAdded,
                     RunSkipped, ScheduleChanged)
from .history import HistoryEntry
from .logger import close_logging, get_logger, setup_file_logging
from .safety import DEFAULT_MAX_FILE_SIZE_GB, MAX_PATH_LENGTH, SECURITY_TAG
from .scheduler import PERIOD_DAILY, PERIOD_MONTHLY, PERIOD_WEEKLY, PERIODS, WEEKDAYS, format_run_time
from .service import ALREADY_RUNNING, BackupService
from .settings_store import AppConfig, SettingsStore, TabConfig

__all__ = [
    "ALREADY_RUNNING", "APP_NAME", "AppConfig", "AppProblem", "BackupFinished", "BackupProgress",
    "BackupResult", "BackupService", "BackupStarted", "ConfigChanged", "DEFAULT_MAX_FILE_SIZE_GB",
    "HistoryAdded", "HistoryEntry", "MAX_PATH_LENGTH", "MINIMIZED_FLAG", "PERIODS", "PERIOD_DAILY",
    "PERIOD_MONTHLY", "PERIOD_WEEKLY", "RunSkipped", "SECURITY_TAG", "STATUS_CANCELLED", "STATUS_FAILED",
    "STATUS_OK", "STATUS_PARTIAL", "ScheduleChanged", "SettingsStore", "TabConfig", "VERSION", "WEEKDAYS",
    "close_logging", "create_service", "format_run_time", "get_logger", "paths", "setup_file_logging",
]


def create_service() -> BackupService:
    """Сервис с настройками и журналом в стандартной папке пользователя."""
    log_path = setup_file_logging(paths.log_dir())
    return BackupService(SettingsStore(paths.settings_path()), log_path=log_path)
