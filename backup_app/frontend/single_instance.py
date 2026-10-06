"""Защита от второго экземпляра приложения.

Первый экземпляр слушает локальный сокет. Второй подключается к нему,
просит показать окно и завершается.
"""
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activated = pyqtSignal()  # другой экземпляр попросил показать окно

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.key = key
        self._server = None

    @property
    def is_primary(self) -> bool:
        return self._server is not None

    def try_acquire(self, timeout_ms: int = 300) -> bool:
        """True, если мы первый экземпляр. Иначе первому отправлен запрос показать окно."""
        socket = QLocalSocket()
        socket.connectToServer(self.key)
        if socket.waitForConnected(timeout_ms):
            socket.write(b"show")
            socket.waitForBytesWritten(timeout_ms)
            socket.disconnectFromServer()
            return False

        QLocalServer.removeServer(self.key)  # убрать "мертвый" сокет после сбоя
        server = QLocalServer(self)
        server.newConnection.connect(self._on_new_connection)
        if server.listen(self.key):
            self._server = server
        else:
            server.deleteLater()
            self._server = QLocalServer(self)  # считаем себя единственным экземпляром
        return True

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        QLocalServer.removeServer(self.key)

    def _on_new_connection(self) -> None:
        server = self._server
        while server is not None and server.hasPendingConnections():
            connection = server.nextPendingConnection()
            if connection is not None:
                connection.disconnected.connect(connection.deleteLater)
                connection.readAll()
        self.activated.emit()
