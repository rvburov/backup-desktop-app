import os
import sys

import pytest

from backup_app.backend import autostart
from backup_app.backend.paths import launcher_path


class FakeWinreg:
    HKEY_CURRENT_USER = 1
    KEY_SET_VALUE = 2
    KEY_READ = 4
    REG_SZ = 1
    store = {}

    @staticmethod
    def OpenKey(*_args, **_kwargs):
        return "key"

    @staticmethod
    def CloseKey(_key):
        pass

    @staticmethod
    def QueryValueEx(_key, name):
        if name in FakeWinreg.store:
            return FakeWinreg.store[name], 1
        raise FileNotFoundError(name)

    @staticmethod
    def SetValueEx(_key, name, _reserved, _type, value):
        FakeWinreg.store[name] = value

    @staticmethod
    def DeleteValue(_key, name):
        if name not in FakeWinreg.store:
            raise FileNotFoundError(name)
        del FakeWinreg.store[name]


@pytest.fixture
def fake_registry(monkeypatch):
    FakeWinreg.store.clear()
    monkeypatch.setitem(sys.modules, "winreg", FakeWinreg)
    monkeypatch.setattr(autostart, "system_name", lambda: "Windows")
    return FakeWinreg


def test_script_command_uses_pythonw_and_minimized_flag(monkeypatch, tmp_path):
    fake_python = tmp_path / "python.exe"
    fake_python.write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    monkeypatch.setattr(sys, "executable", str(fake_python))
    monkeypatch.setattr(autostart.os, "name", "nt")
    parts = autostart.launch_command()
    assert parts[0].lower().endswith("pythonw.exe")
    assert parts[1] == launcher_path() and parts[1].endswith("backup-app.py")
    assert parts[-1] == "--minimized"
    command = autostart.windows_command_line(parts)
    assert command.endswith('" --minimized') and command.startswith('"')


def test_frozen_command_is_the_exe_with_flag(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "C:/App/BackupApp.exe")
    assert autostart.launch_command() == ["C:/App/BackupApp.exe", "--minimized"]


def test_windows_enable_disable_roundtrip(fake_registry):
    assert not autostart.is_enabled()
    assert autostart.enable() is True
    value = fake_registry.store["BackupApp"]
    assert launcher_path().lower() in value.lower() and "--minimized" in value
    assert autostart.is_enabled()
    autostart.disable()
    assert not autostart.is_enabled()
    autostart.disable()  # повторное отключение не падает


def test_linux_desktop_file_has_no_indentation(monkeypatch, tmp_path):
    monkeypatch.setattr(autostart, "system_name", lambda: "Linux")
    monkeypatch.setattr(autostart.os.path, "expanduser", lambda p: p.replace("~", str(tmp_path)))
    assert autostart.enable() is True
    path = os.path.join(str(tmp_path), ".config", "autostart", "backupapp.desktop")
    content = open(path, encoding="utf-8").read()
    lines = content.splitlines()
    assert lines[0] == "[Desktop Entry]"
    assert all(not line.startswith(" ") for line in lines)
    assert "--minimized" in content
    assert autostart.is_enabled()
    autostart.disable()
    assert not os.path.exists(path) and not autostart.is_enabled()


def test_macos_plist_lists_every_argument(monkeypatch, tmp_path):
    monkeypatch.setattr(autostart, "system_name", lambda: "Darwin")
    monkeypatch.setattr(autostart.os.path, "expanduser", lambda p: p.replace("~", str(tmp_path)))
    assert autostart.enable() is True
    path = os.path.join(str(tmp_path), "Library", "LaunchAgents", "com.mycompany.backupapp.plist")
    content = open(path, encoding="utf-8").read()
    assert content.startswith("<?xml")
    assert content.count("<string>") == len(autostart.launch_command()) + 1  # + Label
    assert "<string>--minimized</string>" in content
    autostart.disable()
    assert not os.path.exists(path)


def test_unknown_system_raises(monkeypatch):
    monkeypatch.setattr(autostart, "system_name", lambda: "Plan9")
    with pytest.raises(OSError):
        autostart.enable()
    assert autostart.is_enabled() is False
    autostart.disable()
