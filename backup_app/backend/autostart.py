"""Автозапуск при входе в систему: Windows (реестр), Linux (.desktop), macOS (LaunchAgents).

Приложение запускается с флагом --minimized, то есть сразу в трей.
В режиме скрипта на Windows используется pythonw.exe, чтобы не открывалось окно консоли.
"""
import html
import os
import platform
import shlex
import sys
import textwrap
from typing import List

from .constants import AUTOSTART_ENTRY_NAME, MINIMIZED_FLAG
from .paths import is_frozen, launcher_path

WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
LINUX_DESKTOP_FILE = "~/.config/autostart/backupapp.desktop"
MACOS_PLIST_FILE = "~/Library/LaunchAgents/com.mycompany.backupapp.plist"
MACOS_LABEL = "com.mycompany.backupapp"


def system_name() -> str:
    return platform.system()


def launch_command() -> List[str]:
    """Команда запуска приложения в фоновом режиме."""
    if is_frozen():
        return [sys.executable, MINIMIZED_FLAG]
    interpreter = sys.executable
    if os.name == "nt":
        windowless = os.path.join(os.path.dirname(interpreter), "pythonw.exe")
        if os.path.exists(windowless):
            interpreter = windowless
    return [interpreter, launcher_path(), MINIMIZED_FLAG]


def windows_command_line(parts: List[str]) -> str:
    return " ".join(part if part.startswith("--") else f'"{part}"' for part in parts)


def enable() -> bool:
    name = system_name()
    if name == "Windows":
        return _enable_windows()
    if name == "Linux":
        return _enable_linux()
    if name == "Darwin":
        return _enable_macos()
    raise OSError(f"Автозапуск для ОС {name} не поддерживается")


def disable() -> None:
    name = system_name()
    if name == "Windows":
        _disable_windows()
    elif name == "Linux":
        _remove_file(LINUX_DESKTOP_FILE)
    elif name == "Darwin":
        _remove_file(MACOS_PLIST_FILE)


def is_enabled() -> bool:
    name = system_name()
    if name == "Windows":
        return _is_enabled_windows()
    if name == "Linux":
        return os.path.exists(os.path.expanduser(LINUX_DESKTOP_FILE))
    if name == "Darwin":
        return os.path.exists(os.path.expanduser(MACOS_PLIST_FILE))
    return False


# ------------------------------------------------------------------ Windows
def _enable_windows() -> bool:
    import winreg

    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0, winreg.KEY_SET_VALUE)
    try:
        winreg.SetValueEx(key, AUTOSTART_ENTRY_NAME, 0, winreg.REG_SZ,
                          windows_command_line(launch_command()))
    finally:
        winreg.CloseKey(key)
    return True


def _disable_windows() -> None:
    import winreg

    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0, winreg.KEY_SET_VALUE)
    try:
        winreg.DeleteValue(key, AUTOSTART_ENTRY_NAME)
    except FileNotFoundError:
        pass
    finally:
        winreg.CloseKey(key)


def _is_enabled_windows() -> bool:
    import winreg

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0, winreg.KEY_READ)
    except OSError:
        return False
    try:
        value, _ = winreg.QueryValueEx(key, AUTOSTART_ENTRY_NAME)
    except FileNotFoundError:
        return False
    finally:
        winreg.CloseKey(key)
    return launcher_path().lower() in str(value).lower()


# -------------------------------------------------------------------- Linux
def _enable_linux() -> bool:
    path = os.path.expanduser(LINUX_DESKTOP_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    exec_line = " ".join(shlex.quote(part) for part in launch_command())
    content = textwrap.dedent(f"""\
        [Desktop Entry]
        Type=Application
        Name=BackupApp
        Exec={exec_line}
        Hidden=false
        NoDisplay=false
        X-GNOME-Autostart-enabled=true
        Comment=Automated backup application
        """)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.chmod(path, 0o644)
    return True


# -------------------------------------------------------------------- macOS
def _enable_macos() -> bool:
    path = os.path.expanduser(MACOS_PLIST_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    arguments = "\n".join(f"        <string>{html.escape(part)}</string>" for part in launch_command())
    content = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{MACOS_LABEL}</string>
            <key>ProgramArguments</key>
            <array>
        {arguments}
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <false/>
        </dict>
        </plist>
        """)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return True


def _remove_file(user_path: str) -> None:
    path = os.path.expanduser(user_path)
    if os.path.exists(path):
        os.remove(path)
