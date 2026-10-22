#!/usr/bin/env python3
"""Device ownership: at most one process streams to the keyboard at a time.

Whoever holds an exclusive flock on <runtime>/device.lock owns the board. The
kernel drops the lock when the holder exits (even on SIGKILL), so there are no
stale pid files to clean up. The holder writes an owner record
{pid, kind, mode, argv, started} into the lock file so others can see who has
the board and ask it to let go: a CLI or background-runner holder gets SIGTERM
(which the CLI turns into its normal Ctrl-C cleanup); the GUI gets a
{"cmd": "release"} line on its control socket and stops sending.

The newest writer wins: starting a CLI effect while another one runs replaces
it instead of the two fighting over the board.
"""
import fcntl
import json
import os
import signal
import socket
import time


def runtime_dir():
    """Per-user runtime directory for the lock and the GUI socket.
    KEYBOARDRGB_RUNTIME_DIR overrides it (tests use a throwaway one)."""
    d = os.environ.get("KEYBOARDRGB_RUNTIME_DIR")
    if not d:
        base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/keyboardrgb-{os.getuid()}"
        d = os.path.join(base, "keyboardrgb")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def lock_path():
    return os.path.join(runtime_dir(), "device.lock")


def gui_socket_path():
    return os.path.join(runtime_dir(), "gui.sock")


class DeviceLock:
    """The board-ownership lock for this process. kind: cli | runner | gui."""

    def __init__(self, kind, mode=None, argv=None):
        self.kind = kind
        self.mode = mode
        self.argv = argv
        self.fd = None

    @property
    def held(self):
        return self.fd is not None

    def try_acquire(self):
        if self.fd is not None:
            return True
        fd = os.open(lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        self.fd = fd
        self._write()
        return True

    def acquire(self, takeover=True, timeout=4.0):
        """Take the board, asking the current holder to stop if `takeover`."""
        if self.try_acquire():
            return True
        if not takeover:
            return False
        request_release(timeout=timeout)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if self.try_acquire():
                return True
            time.sleep(0.05)
        return False

    def update(self, mode=None, argv=None):
        self.mode, self.argv = mode, argv
        if self.fd is not None:
            self._write()

    def _write(self):
        rec = {"pid": os.getpid(), "kind": self.kind, "mode": self.mode,
               "argv": self.argv, "started": time.time()}
        os.ftruncate(self.fd, 0)
        os.pwrite(self.fd, json.dumps(rec).encode(), 0)

    def release(self):
        fd, self.fd = self.fd, None
        if fd is None:
            return
        try:
            os.ftruncate(fd, 0)
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def owner():
    """The current holder's record, or None when nobody holds the board."""
    try:
        fd = os.open(lock_path(), os.O_RDWR)
    except FileNotFoundError:
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            data = os.pread(fd, 65536, 0)
            try:
                rec = json.loads(data)
            except ValueError:  # holder is mid-write
                rec = {}
            return rec if isinstance(rec, dict) else {}
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    finally:
        os.close(fd)


def send_gui(msg, timeout=1.0):
    """Send one JSON command to a running GUI; returns its reply dict or None."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(gui_socket_path())
        s.sendall(json.dumps(msg).encode() + b"\n")
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf) if buf.strip() else {}
    except (OSError, ValueError):
        return None
    finally:
        s.close()


def _wait_free(timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if owner() is None:
            return True
        time.sleep(0.05)
    return owner() is None


def request_release(rec=None, timeout=3.0):
    """Ask the current holder to let go of the board. Returns True once free."""
    rec = rec if rec is not None else owner()
    if rec is None:
        return True
    pid = rec.get("pid")
    if rec.get("kind") == "gui":
        send_gui({"cmd": "release"})
        return _wait_free(timeout)
    if not pid or pid == os.getpid():
        return _wait_free(timeout)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return _wait_free(timeout)
    if _wait_free(timeout):
        return True
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return _wait_free(1.0)


def describe(rec):
    """One-line human description of an owner record."""
    if rec is None:
        return "idle (nothing is driving the keyboard)"
    who = {"gui": "the app", "runner": "background runner", "cli": "command line"}
    since = rec.get("started")
    age = f", for {int(time.time() - since)}s" if since else ""
    mode = rec.get("mode") or "?"
    return f"running {mode} ({who.get(rec.get('kind'), rec.get('kind'))}, pid {rec.get('pid')}{age})"
