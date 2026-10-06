"""Иконка в системном трее: меню, подсказка и уведомления."""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QMenu, QSystemTrayIcon

from .constants import APP_TITLE


class TrayIcon(QSystemTrayIcon):
    show_requested = pyqtSignal()
    backup_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, icon: QIcon, parent=None):
        super().__init__(icon, parent)
        self._menu = QMenu()
        self.open_action = self._menu.addAction("Открыть окно")
        self.open_action.triggered.connect(self.show_requested.emit)
        self.backup_action = self._menu.addAction("Копировать сейчас")
        self.backup_action.triggered.connect(self.backup_requested.emit)
        self._menu.addSeparator()
        self.next_action = self._menu.addAction("Следующее копирование: остановлено")
        self.next_action.setEnabled(False)
        self._menu.addSeparator()
        self.quit_action = self._menu.addAction("Выход")
        self.quit_action.triggered.connect(self.quit_requested.emit)

        self.setContextMenu(self._menu)
        self.setToolTip(APP_TITLE)
        self.activated.connect(self._on_activated)

    @staticmethod
    def available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_requested.emit()

    def set_next_backup(self, text: str) -> None:
        self.next_action.setText(text)
        self.setToolTip(f"{APP_TITLE}\n{text}")

    def set_backup_enabled(self, enabled: bool) -> None:
        self.backup_action.setEnabled(enabled)

    def notify(self, title: str, message: str, kind: str = "info", msecs: int = 6000) -> None:
        icons = {
            "info": QSystemTrayIcon.Information,
            "warning": QSystemTrayIcon.Warning,
            "error": QSystemTrayIcon.Critical,
        }
        self.showMessage(title, message, icons.get(kind, QSystemTrayIcon.Information), msecs)
