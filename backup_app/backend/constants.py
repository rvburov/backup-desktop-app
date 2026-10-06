"""Общие константы бэкенда."""

APP_NAME = "BackupApp"
VERSION = "9.0.0"

DEFAULT_TAB_TITLE = "Без названия"
BACKUP_FOLDER_PREFIX = "Резервное копирование"

# Как часто планировщик сверяется с расписанием, секунды.
CHECK_INTERVAL_SECONDS = 60.0
# Через сколько секунд после запуска выполнять пропущенное копирование.
MISSED_RUN_DELAY_SECONDS = 3.0

AUTOSTART_ENTRY_NAME = "BackupApp"
MINIMIZED_FLAG = "--minimized"

SETTINGS_FILE_NAME = "settings.ini"
LOG_FILE_NAME = "backup-app.log"
LOGGER_NAME = "backup_app"
