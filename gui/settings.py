"""Persistent app settings: one JSON file under $XDG_CONFIG_HOME/keyboardrgb.
Writes are debounced and atomic (temp file + rename)."""
import copy
import json
import os
import uuid

from PySide6.QtCore import QObject, QTimer

VERSION = 1

DEFAULTS = {
    "version": VERSION,
    "theme": {"preset": "midnight-lemon", "base": "#09090b", "accent": "#f0ec57"},
    "last_mode": None,
    "params": {},              # mode id -> user values
    "last_applied": None,      # {"mode", "values", "profile"}: what login resumes
    "presets": [],             # [{"id", "name", "mode", "values"}]
    "profile_for_usb": {},     # "258a:010c" -> profile id (boards share USB ids)
    "profile": None,           # chosen profile when no board is connected
    "autostart": False,
    "close_to_tray": True,
    "keep_lighting_on_close": True,
    "window": None,
}


def config_dir():
    d = os.environ.get("KEYBOARDRGB_CONFIG_DIR")
    if not d:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        d = os.path.join(base, "keyboardrgb")
    return d


def state_dir():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    d = os.path.join(base, "keyboardrgb")
    os.makedirs(d, exist_ok=True)
    return d


class Settings(QObject):
    def __init__(self, path=None):
        super().__init__()
        self.path = path or os.path.join(config_dir(), "settings.json")
        self.data = copy.deepcopy(DEFAULTS)
        try:
            with open(self.path) as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                for k in DEFAULTS:
                    if k in loaded and type(loaded[k]) is type(DEFAULTS[k]) or (
                            k in loaded and DEFAULTS[k] is None):
                        self.data[k] = loaded[k]
        except (OSError, ValueError):
            pass
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.flush)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value
        self.save()

    def save(self):
        self._timer.start()

    def flush(self):
        self._timer.stop()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)

    # -- presets --------------------------------------------------------
    def add_preset(self, name, mode, values):
        p = {"id": uuid.uuid4().hex[:10], "name": name, "mode": mode, "values": dict(values)}
        self.data["presets"].append(p)
        self.save()
        return p

    def preset(self, pid):
        return next((p for p in self.data["presets"] if p["id"] == pid), None)

    def update_preset(self, pid, **fields):
        p = self.preset(pid)
        if p:
            p.update(fields)
            self.save()

    def delete_preset(self, pid):
        self.data["presets"] = [p for p in self.data["presets"] if p["id"] != pid]
        self.save()
