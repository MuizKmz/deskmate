"""Make sure only one DeskMate runs at a time.

The first copy opens a tiny local "mailbox" (a named pipe on Windows). A second
copy finds the mailbox, posts "show" so the first one pops up, and exits.
"""

from __future__ import annotations

import getpass
import hashlib
import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger(__name__)


def default_key() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    digest = hashlib.sha1(user.encode("utf-8", "replace")).hexdigest()[:10]
    return f"DeskMate-{digest}"


class SingleInstance(QObject):
    activated = Signal()  # another copy asked us to show ourselves

    def __init__(self, key: str | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.key = key or default_key()
        self._server: QLocalServer | None = None

    def notify_running_instance(self) -> bool:
        """True if another copy is running (and was told to show itself)."""
        socket = QLocalSocket()
        socket.connectToServer(self.key)
        if not socket.waitForConnected(400):
            return False
        socket.write(b"show\n")
        socket.flush()
        socket.waitForBytesWritten(400)
        socket.disconnectFromServer()
        return True

    def listen(self) -> bool:
        self._server = QLocalServer(self)
        if not self._server.listen(self.key):
            # A crash can leave a stale socket file behind (macOS/Linux). Clear it and retry.
            QLocalServer.removeServer(self.key)
            if not self._server.listen(self.key):
                log.warning("Single-instance guard unavailable: %s", self._server.errorString())
                return False
        self._server.newConnection.connect(self._on_connection)
        return True

    def _on_connection(self) -> None:
        while self._server and self._server.hasPendingConnections():
            connection = self._server.nextPendingConnection()
            connection.readyRead.connect(lambda c=connection: self._read(c))
            connection.disconnected.connect(connection.deleteLater)
            if connection.bytesAvailable():
                self._read(connection)

    def _read(self, connection: QLocalSocket) -> None:
        data = bytes(connection.readAll()).strip()
        if data.startswith(b"show"):
            log.info("Another copy was started; showing this one instead")
            self.activated.emit()
