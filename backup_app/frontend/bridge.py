"""Мост между бэкендом и интерфейсом.

Бэкенд сообщает о событиях и пишет журнал из своих фоновых потоков. Мост превращает это
в сигналы Qt, поэтому окно получает события в своём потоке и может безопасно менять виджеты.
"""
import logging

from PyQt5.QtCore import QObject, pyqtSignal

from ..backend import BackupService, display_formatter, get_logger


class _QtLogHandler(logging.Handler):
    def __init__(self, signal):
        super().__init__()
        self._signal = signal

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._signal.emit(self.format(record))
        except Exception:  # pragma: no cover - защитный код
            self.handleError(record)


class ServiceBridge(QObject):
    event_received = pyqtSignal(object)  # событие бэкенда из модуля backend.events
    log_message = pyqtSignal(str)        # готовая строка журнала

    def __init__(self, service: BackupService, parent=None):
        super().__init__(parent)
        self._service = service
        self._handler = _QtLogHandler(self.log_message)
        self._handler.setFormatter(display_formatter())
        get_logger().addHandler(self._handler)
        service.subscribe(self._forward)

    def _forward(self, event) -> None:
        self.event_received.emit(event)

    def close(self) -> None:
        self._service.unsubscribe(self._forward)
        get_logger().removeHandler(self._handler)
