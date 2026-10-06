"""Пути к настройкам, журналу и лаунчеру. Без Qt.

Папка настроек совпадает с той, которую выбирал QStandardPaths.AppConfigLocation
в прежних версиях, поэтому существующие настройки находятся на старом месте.
"""
import os
import sys

from .constants import APP_NAME, SETTINGS_FILE_NAME

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(PACKAGE_ROOT)

# Переменная окружения, переопределяющая папку настроек (используется тестами).
CONFIG_DIR_ENV = "BACKUPAPP_CONFIG_DIR"


def is_frozen() -> bool:
    """True, если приложение собрано PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def launcher_path() -> str:
    """Что запускать при автозапуске: собранный exe или скрипт-лаунчер."""
    if is_frozen():
        return sys.executable
    return os.path.join(PROJECT_ROOT, "backup-app.py")


def default_config_dir() -> str:
    """Стандартная папка настроек пользователя для текущей ОС."""
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    elif sys.platform == "darwin":
        base = os.path.join(home, "Library", "Preferences")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return os.path.join(base, APP_NAME)


def config_dir() -> str:
    """Папка настроек. Создаётся при первом обращении."""
    directory = os.environ.get(CONFIG_DIR_ENV) or default_config_dir()
    os.makedirs(directory, exist_ok=True)
    return directory


def settings_path() -> str:
    return os.path.join(config_dir(), SETTINGS_FILE_NAME)


def log_dir() -> str:
    directory = os.path.join(config_dir(), "logs")
    os.makedirs(directory, exist_ok=True)
    return directory
