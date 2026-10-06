"""Иконка в системном трее: меню, подсказка и уведомления (макет Tray.dc.html).

Меню: «Открыть окно», «Копировать все вкладки», ближайшее копирование (недоступный пункт), «Выход».
Левый щелчок по значку открывает окно.
"""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QMenu, QSystemTrayIcon

from . import icons
from . import widgets as W
from .constants import APP_TITLE, NEXT_RUN_STOPPED
from .theme import C


class TrayIcon(QSystemTrayIcon):
    show_requested = pyqtSignal()
    backup_requested = pyqtSignal()   # «Копировать все вкладки»
    quit_requested = pyqtSignal()

    def __init__(self, icon: QIcon, parent=None):
        super().__init__(icon, parent)
        self._menu = QMenu()
        W.style_menu(self._menu)
        self.open_action = self._menu.addAction(icons.icon("window", C.TEXT2), "Открыть окно")
        self.open_action.triggered.connect(self.show_requested.emit)
        self.backup_action = self._menu.addAction(icons.icon("play", C.TEXT2), "Копировать все вкладки")
        self.backup_action.triggered.connect(self.backup_requested.emit)
        self._menu.addSeparator()
        self.next_action = self._menu.addAction(icons.icon("clock", C.FAINT, disabled_color=C.FAINT),
                                                NEXT_RUN_STOPPED)
        self.next_action.setEnabled(False)
        self._menu.addSeparator()
        self.quit_action = self._menu.addAction(icons.icon("logout", C.TEXT2), "Выход")
        self.quit_action.triggered.connect(self.quit_requested.emit)

        self.setContextMenu(self._menu)
        self.setToolTip(f"{APP_TITLE}\n{NEXT_RUN_STOPPED}")
        self.activated.connect(self._on_activated)

    @staticmethod
    def available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def menu(self) -> QMenu:
        return self._menu

    def menu_texts(self):
        """Тексты пунктов меню (разделитель — пустая строка)."""
        return [action.text() for action in self._menu.actions()]

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_requested.emit()

    def set_next_backup(self, text: str) -> None:
        self.next_action.setText(text)
        self.setToolTip(f"{APP_TITLE}\n{text}")

    def set_backup_enabled(self, enabled: bool) -> None:
        self.backup_action.setEnabled(enabled)

    def notify(self, title: str, message: str, kind: str = "info", msecs: int = 6000) -> None:
        icons_by_kind = {
            "info": QSystemTrayIcon.Information,
            "warning": QSystemTrayIcon.Warning,
            "error": QSystemTrayIcon.Critical,
        }
        self.showMessage(title, message, icons_by_kind.get(kind, QSystemTrayIcon.Information), msecs)
