import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
for path in (ROOT, TESTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """QApplication для тестов интерфейса. Тесты бэкенда его не используют."""
    from PyQt5.QtWidgets import QApplication

    from backup_app.backend import APP_NAME

    app = QApplication.instance() or QApplication([])
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """Отдельная папка настроек, чтобы тесты не трогали настройки пользователя."""
    directory = tmp_path / "config"
    directory.mkdir()
    monkeypatch.setenv("BACKUPAPP_CONFIG_DIR", str(directory))
    return directory


@pytest.fixture(autouse=True)
def isolated_autostart(request, monkeypatch):
    """Тесты не изменяют реестр и файлы автозапуска (кроме тестов самого модуля)."""
    if request.module.__name__.endswith("test_autostart"):
        return
    from backup_app.backend import autostart

    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(autostart, "enable", lambda: True)
    monkeypatch.setattr(autostart, "disable", lambda: None)


@pytest.fixture(autouse=True)
def release_log_files():
    """Закрывает файл журнала после каждого теста, чтобы временные папки удалялись."""
    yield
    from backup_app.backend import close_logging

    close_logging()


@pytest.fixture
def log_records():
    """Записи журнала приложения за время теста."""
    import logging

    from backup_app.backend import get_logger

    records = []

    class ListHandler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = ListHandler()
    logger = get_logger()
    logger.addHandler(handler)
    yield records
    logger.removeHandler(handler)
