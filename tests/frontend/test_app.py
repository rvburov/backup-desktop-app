import os

from backup_app import main as main_module
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
