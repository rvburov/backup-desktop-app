import ctypes
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


def fake_user32(calls, metric, icon):
    def load_image(instance, path, kind, cx, cy, flags):
        calls.append(("load", instance, path, kind, cx, cy, flags))
        return icon

    def send_message(hwnd, msg, wparam, lparam):
        calls.append(("send", hwnd, msg, wparam, lparam))
        return 0

    user32 = SimpleNamespace(LoadImageW=load_image, SendMessageW=send_message, GetSystemMetrics=lambda index: metric)
    return SimpleNamespace(WinDLL=lambda name: user32, c_void_p=ctypes.c_void_p, c_wchar_p=ctypes.c_wchar_p,
                           c_uint=ctypes.c_uint, c_int=ctypes.c_int)


def on_windows(monkeypatch, calls, metric=32, icon=777):
    monkeypatch.setattr(app_module, "ctypes", fake_user32(calls, metric, icon))
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    monkeypatch.setattr(app_module, "QGuiApplication", SimpleNamespace(platformName=lambda: "windows"))


def test_taskbar_gets_icon_frame_of_its_own_size(monkeypatch):
    # Панель задач рисует значок в 3/4 от SM_CXICON: 24 при масштабе 100 %, 30 при 125 %, 36 при 150 %.
    window = SimpleNamespace(winId=lambda: 4242)
    for metric, size in ((32, 24), (40, 30), (48, 36)):
        calls = []
        on_windows(monkeypatch, calls, metric)
        assert app_module.set_taskbar_icon(window, "C:/app/icon.ico") is True
        assert calls == [("load", None, "C:/app/icon.ico", 1, size, size, 0x10), ("send", 4242, 0x80, 1, 777)]


def test_taskbar_icon_left_to_qt_without_windows_or_icon_file(monkeypatch):
    window = SimpleNamespace(winId=lambda: 4242)
    calls = []
    on_windows(monkeypatch, calls, icon=None)
    assert app_module.set_taskbar_icon(window, "C:/app/missing.ico") is False
    assert [call[0] for call in calls] == ["load"]
    calls.clear()
    monkeypatch.setattr(app_module, "QGuiApplication", SimpleNamespace(platformName=lambda: "offscreen"))
    assert app_module.set_taskbar_icon(window, "C:/app/icon.ico") is False
    monkeypatch.setattr(app_module, "QGuiApplication", SimpleNamespace(platformName=lambda: "windows"))
    monkeypatch.setattr(app_module.sys, "platform", "linux")
    assert app_module.set_taskbar_icon(window, "C:/app/icon.ico") is False
    assert calls == []
