"""One app instance at a time, plus a control socket for the CLI.

The first instance listens on <runtime>/gui.sock (devlock.gui_socket_path). A
second launch sends {"cmd": "show"} and exits, which raises the existing
window. The CLI sends {"cmd": "release"} when it wants the board the app is
driving. Messages are newline-delimited JSON; every one gets a JSON reply."""
import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

import devlock


class SingleInstance(QObject):
    command = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = devlock.gui_socket_path()
        self.server = None
        self.handler = None   # fn(dict) -> dict reply

    def notify_existing(self, msg):
        """True if another instance answered (and got `msg`)."""
        sock = QLocalSocket()
        sock.connectToServer(self.path)
        if not sock.waitForConnected(300):
            return False
        sock.write(json.dumps(msg).encode() + b"\n")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.waitForReadyRead(500)
        sock.disconnectFromServer()
        return True

    def listen(self):
        QLocalServer.removeServer(self.path)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        ok = self.server.listen(self.path)
        self.server.newConnection.connect(self._accept)
        return ok

    def _accept(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(sock.deleteLater)

    def _read(self, sock):
        while sock.canReadLine():
            line = bytes(sock.readLine()).strip()
            try:
                msg = json.loads(line)
            except ValueError:
                msg = {}
            reply = self.handler(msg) if self.handler else {}
            sock.write(json.dumps(reply or {"ok": True}).encode() + b"\n")
            sock.flush()

    def close(self):
        if self.server:
            self.server.close()
