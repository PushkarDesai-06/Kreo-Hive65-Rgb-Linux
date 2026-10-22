"""One-click install of the udev rule that lets the app (and the CLI) write to
the keyboard. Runs through pkexec, so the desktop's normal password prompt
appears; with no polkit agent running, people fall back to the copyable
sudo command."""
import os
import shlex
import shutil
import tempfile

from PySide6.QtCore import QObject, QProcess, Signal

from gui.runtime import data_path, packaged

RULE_NAME = "60-keyboardrgb.rules"
RULE_DEST = "/etc/udev/rules.d/" + RULE_NAME


def rule_source():
    return data_path(RULE_NAME)


def rule_installed():
    return os.path.exists(RULE_DEST)


def sudo_command():
    """The manual fallback. A packaged app's files sit on a FUSE mount root
    can't read, so the rule is copied somewhere readable first."""
    tail = (" && sudo udevadm control --reload"
            " && sudo udevadm trigger --subsystem-match=hidraw")
    src = rule_source()
    if packaged():
        tmp = '"$XDG_RUNTIME_DIR/' + RULE_NAME + '"'
        return (f"cp {shlex.quote(src)} {tmp} && sudo install -m 0644 {tmp} "
                f"/etc/udev/rules.d/{tail}")
    return f"sudo install -m 0644 {shlex.quote(src)} /etc/udev/rules.d/{tail}"


class RuleInstaller(QObject):
    """finished(ok, message)"""

    finished = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc = None
        self.tmpdir = None

    def available(self):
        return shutil.which("pkexec") is not None

    def start(self):
        if self.proc is not None:
            return
        if not self.available():
            self.finished.emit(False, "pkexec isn't installed. Use the copy button and run "
                                      "the command in a terminal instead.")
            return
        # private copy root can read (the app may be running from a FUSE mount)
        self.tmpdir = tempfile.mkdtemp(prefix="keyboardrgb-")
        src = os.path.join(self.tmpdir, RULE_NAME)
        shutil.copyfile(rule_source(), src)
        os.chmod(src, 0o644)
        script = (f"install -m 0644 {shlex.quote(src)} {RULE_DEST} && "
                  "udevadm control --reload && udevadm trigger --subsystem-match=hidraw")
        self.proc = QProcess(self)
        self.proc.setProgram("pkexec")
        self.proc.setArguments(["/bin/sh", "-c", script])
        self.proc.finished.connect(self._done)
        self.proc.errorOccurred.connect(self._error)
        self.proc.start()

    def _cleanup(self):
        if self.tmpdir:
            shutil.rmtree(self.tmpdir, ignore_errors=True)
            self.tmpdir = None
        if self.proc is not None:
            self.proc.deleteLater()
            self.proc = None

    def _error(self, err):
        if err == QProcess.FailedToStart:
            self._cleanup()
            self.finished.emit(False, "Couldn't start pkexec. Use the copy button and run "
                                      "the command in a terminal instead.")

    def _done(self, code, _status):
        err = bytes(self.proc.readAllStandardError()).decode(errors="replace").strip()
        self._cleanup()
        if code == 0:
            self.finished.emit(True, "Keyboard access installed. If it still shows as "
                                     "locked, unplug the keyboard and plug it back in.")
        elif code == 126:
            self.finished.emit(False, "Install cancelled.")
        elif code == 127:
            self.finished.emit(False, "No password prompt is available (no polkit agent "
                                      "running). Use the copy button and run the command "
                                      "in a terminal instead.")
        else:
            self.finished.emit(False, f"Install failed: {err or f'exit code {code}'}")
