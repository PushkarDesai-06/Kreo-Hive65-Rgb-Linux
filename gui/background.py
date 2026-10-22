"""Background lighting: the effect keeps running after the window closes. The
runner is simply the CLI started as a detached process, so "Copy command", the
exported toggle scripts and the background runner all run the same code the
preview showed. Ownership of the board goes through devlock."""
import os
import re
import shlex
import stat
import subprocess
import sys
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

import devlock
from gui import catalog
from gui.settings import state_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "keyboardrgb.py")
GLOBAL_OPTS = ("--profile", "--device", "--vid", "--pid")


def cli_argv(profile_id, mode_argv):
    return ["--profile", profile_id, *mode_argv]


def shell_command(profile_id, mode_argv):
    return shlex.join(["python3", CLI, *cli_argv(profile_id, mode_argv)])


def label_for_argv(argv):
    """Friendly mode name for a CLI argv (as recorded in the owner record)."""
    if not argv:
        return None
    a = list(argv)
    i = 0
    while i < len(a) and a[i].startswith("--"):
        i += 2 if a[i] in GLOBAL_OPTS else 1
    if i >= len(a):
        return None
    cmd, rest = a[i], a[i + 1:]
    sub = None
    for flag in ("--effect", "--shape"):
        if flag in rest and rest.index(flag) + 1 < len(rest):
            sub = rest[rest.index(flag) + 1]
    simple = {"color": "solid", "gradient": "gradient", "rainbow": "rainbow", "wave": "wave",
              "flux": "flux", "screen": "screen"}
    if cmd in simple:
        return catalog.BY_ID[simple[cmd]].label
    if cmd == "audio":
        m = catalog.BY_ID.get(f"music-{sub or 'wave'}")
        return m.label if m else "Music Visualizer"
    if cmd == "reactive":
        m = catalog.BY_ID.get(f"typing-{sub or 'splash'}")
        return m.label if m else "Typing Effects"
    return {"key": "Per-key colors", "off": "Lights off", "walk": "Layout mapping"}.get(cmd, cmd)


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "effect"


def toggle_script(title, profile_id, mode_argv, name):
    """A start/stop toggle (for a compositor keybind) running this effect."""
    args = shlex.join(cli_argv(profile_id, mode_argv))
    return f"""#!/bin/sh
# Toggle "{title}" on the keyboard. Exported by Keyboard Studio.
# Run once to start the lighting, run again to stop it. Hyprland keybind:
#   bind = SUPER, K, exec, {os.path.expanduser('~/.local/bin/')}keyboardrgb-{name}.sh
KBD={shlex.quote(CLI)}
PIDFILE="${{XDG_RUNTIME_DIR:-/tmp}}/keyboardrgb-{name}.pid"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    kill "$(cat "$PIDFILE")"
    rm -f "$PIDFILE"
else
    KEYBOARDRGB_RUNNER=1 python3 "$KBD" {args} >/dev/null 2>&1 &
    echo $! > "$PIDFILE"
fi
"""


def write_script(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class Runner(QObject):
    """Starts/stops the background process and tracks who owns the board.
    `changed(rec)` fires with the devlock owner record (or None)."""

    changed = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.owner = None
        self.proc = None
        self._started = 0.0
        self._log = os.path.join(state_dir(), "runner.log")
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.poll)
        self._timer.start()
        self.poll()

    def poll(self):
        if self.proc is not None and self.proc.poll() is not None:
            code, self.proc = self.proc.returncode, None
            if code not in (0, -15) and time.monotonic() - self._started < 8:
                self.failed.emit(self._last_log_line() or f"exited with code {code}")
        rec = devlock.owner()
        if rec != self.owner:
            self.owner = rec
            self.changed.emit(rec)

    def _last_log_line(self):
        try:
            with open(self._log) as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            return lines[-1] if lines else None
        except OSError:
            return None

    @property
    def running(self):
        return self.owner is not None and self.owner.get("kind") in ("runner", "cli")

    def start(self, profile_id, mode_argv):
        argv = [sys.executable, CLI, *cli_argv(profile_id, mode_argv)]
        env = dict(os.environ, KEYBOARDRGB_RUNNER="1", PYTHONUNBUFFERED="1")
        log = open(self._log, "w")
        self.proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        log.close()
        self._started = time.monotonic()
        QTimer.singleShot(400, self.poll)

    def stop(self, done=None):
        """Stop whatever the background/CLI owner is, off the UI thread."""
        rec = self.owner

        def work():
            devlock.request_release(rec)
            if done:
                done()
        threading.Thread(target=work, daemon=True).start()
        QTimer.singleShot(300, self.poll)
        QTimer.singleShot(1200, self.poll)
