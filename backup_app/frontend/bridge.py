"""Мост между бэкендом и интерфейсом.

Бэкенд сообщает о событиях из своих фоновых потоков. Мост превращает их в сигнал Qt,
поэтому окно получает события в своем потоке и может безопасно менять виджеты.
"""
from PyQt5.QtCore import QObject, pyqtSignal

from ..backend import BackupService


class ServiceBridge(QObject):
    event_received = pyqtSignal(object)  # событие бэкенда из модуля backend.events

    def __init__(self, service: BackupService, parent=None):
        super().__init__(parent)
        self._service = service
        service.subscribe(self._forward)

    def _forward(self, event) -> None:
        self.event_received.emit(event)

    def close(self) -> None:
        self._service.unsubscribe(self._forward)
