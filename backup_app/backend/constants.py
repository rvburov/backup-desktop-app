"""Общие константы бэкенда."""

APP_NAME = "BackupApp"
VERSION = "9.1.0"

DEFAULT_TAB_TITLE = "Без названия"
BACKUP_FOLDER_PREFIX = "Резервное копирование"
# Дата в имени папки «Резервное копирование дд-мм-гггг».
BACKUP_FOLDER_DATE_FORMAT = "%d-%m-%Y"
# Отметка времени, которая добавляется к имени копии при совпадении имен.
COPY_STAMP_FORMAT = "%d.%m.%Y_%H-%M-%S"

# Почему вкладку нельзя скопировать.
NO_SOURCES = "Не выбраны исходные файлы и папки"
NO_DESTINATION = "Не выбрана папка назначения"

# Как часто планировщик сверяется с расписанием, секунды.
CHECK_INTERVAL_SECONDS = 60.0
# Через сколько секунд после запуска выполнять пропущенное копирование.
MISSED_RUN_DELAY_SECONDS = 3.0

AUTOSTART_ENTRY_NAME = "BackupApp"
MINIMIZED_FLAG = "--minimized"

SETTINGS_FILE_NAME = "settings.ini"
LOG_FILE_NAME = "backup-app.log"
HISTORY_FILE_NAME = "history.txt"
LOGGER_NAME = "backup_app"
