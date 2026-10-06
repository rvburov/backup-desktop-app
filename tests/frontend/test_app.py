import os
from types import SimpleNamespace

from backup_app import main as main_module
from backup_app.frontend import app as app_module
from backup_app.frontend.app import QtFrontend, instance_key
from backup_app.frontend.constants import SINGLE_INSTANCE_KEY


def test_parse_args():
    assert main_module.parse_args(["app"]) == {"minimized": False}
    assert main_module.parse_args(["app", "--minimized"]) == {"minimized": True}
    assert main_module.parse_args(["app", "--hidden"]) == {"minimized": True}
    assert main_module.parse_args(["app", "-m"]) == {"minimized": True}


def test_instance_key_is_per_user(monkeypatch):
    monkeypatch.delenv("BACKUPAPP_INSTANCE_KEY", raising=False)
    assert instance_key().startswith(SINGLE_INSTANCE_KEY + "-")
    monkeypatch.setenv("BACKUPAPP_INSTANCE_KEY", "dev-copy")
    assert instance_key() == "dev-copy"


def test_frontend_single_instance(qapp):
    key = f"backupapp-test-frontend-{os.getpid()}"
    first = QtFrontend([], key=key)
    try:
        assert first.acquire_single_instance() is True
        second = QtFrontend([], key=key)
        assert second.acquire_single_instance() is False
        assert first.app is qapp
    finally:
        first.release()


def fake_ctypes(calls):
    def set_app_id(app_id):
        calls.append(app_id)
        return 0

    return SimpleNamespace(windll=SimpleNamespace(shell32=SimpleNamespace(
        SetCurrentProcessExplicitAppUserModelID=set_app_id)))


def test_script_run_on_windows_gets_own_taskbar_group(monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "ctypes", fake_ctypes(calls))
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    monkeypatch.delattr(app_module.sys, "frozen", raising=False)
    assert app_module.set_windows_app_id() is True
    assert calls == ["BackupApp"]


def test_exe_and_other_systems_keep_default_taskbar_group(monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "ctypes", fake_ctypes(calls))
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    monkeypatch.setattr(app_module.sys, "frozen", True, raising=False)
    assert app_module.set_windows_app_id() is False
    monkeypatch.setattr(app_module.sys, "frozen", False)
    monkeypatch.setattr(app_module.sys, "platform", "linux")
    assert app_module.set_windows_app_id() is False
    assert calls == []
