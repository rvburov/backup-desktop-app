"""Запуск интерфейса: QApplication, защита от второго экземпляра, окно и трей."""
import getpass
import os
from typing import List, Optional

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication

from ..backend import APP_NAME, BackupService, get_logger
from .bridge import ServiceBridge
from .constants import SINGLE_INSTANCE_KEY
from .main_window import MainWindow
from .resources import resource_path
from .single_instance import SingleInstance


# Переменная окружения, задающая свой ключ одиночного экземпляра. Нужна, чтобы запустить
# отладочную копию рядом с рабочей: без неё вторая копия только покажет окно первой.
INSTANCE_KEY_ENV = "BACKUPAPP_INSTANCE_KEY"


def instance_key() -> str:
    override = os.environ.get(INSTANCE_KEY_ENV)
    if override:
        return override
    try:
        user = getpass.getuser()
    except Exception:  # pragma: no cover - экзотические окружения
        user = "user"
    return f"{SINGLE_INSTANCE_KEY}-{user}"


class QtFrontend:
    def __init__(self, argv: List[str], key: Optional[str] = None):
        app = QApplication.instance() or QApplication(argv)
        app.setStyle("Fusion")
        app.setApplicationName(APP_NAME)
        app.setQuitOnLastWindowClosed(False)
        icon_path = resource_path("icon.ico")
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
        self.app = app
        self.instance = SingleInstance(key or instance_key())
        self.window: Optional[MainWindow] = None
        self.bridge: Optional[ServiceBridge] = None

    def acquire_single_instance(self) -> bool:
        """True, если это первый экземпляр. Иначе работающему экземпляру отправлен запрос показать окно."""
        return self.instance.try_acquire()

    def create_window(self, service: BackupService) -> MainWindow:
        self.bridge = ServiceBridge(service)
        self.window = MainWindow(service, self.bridge)
        self.instance.activated.connect(self.window.show_from_tray)
        return self.window

    def run(self, service: BackupService, minimized: bool = False) -> int:
        window = self.create_window(service)
        service.start()
        if minimized and window.tray is not None:
            get_logger().info("Запуск в фоновом режиме: окно скрыто, иконка в трее")
        else:
            window.show()
        code = self.app.exec_()
        self.bridge.close()
        return code

    def release(self) -> None:
        self.instance.release()
