"""App logic, kept apart from the widgets: the selected mode and its values,
the live preview engine, mirroring to the physical keyboard, the background
runner, presets and board detection. The main window only wires signals."""
import os

from PySide6.QtCore import QObject, QTimer, Signal

import devlock
from device import PROFILES
from engine import DeviceSink, LiveEngine
from gui import catalog, hardware
from gui.background import Runner, label_for_argv, shell_command, slug, toggle_script


class Studio(QObject):
    modeChanged = Signal(object, dict, object)  # mode, values, preset id or None
    valuesChanged = Signal(dict)
    profileChanged = Signal(object)
    deviceChanged = Signal(dict)
    sendChanged = Signal(bool)
    ownerChanged = Signal(object)
    engineEvent = Signal(dict)
    presetsChanged = Signal(list)
    toast = Signal(str, str)
    showRequested = Signal()
    _engine_evt = Signal(dict)
    _sink_evt = Signal(dict)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.send = False
        self.sink = None
        self.sink_state = None
        self.lock = devlock.DeviceLock("gui")
        self.device = None
        self.hidden = False
        self.active_preset = None

        self._engine_evt.connect(self._on_engine_event)
        self._sink_evt.connect(self._on_sink_event)
        self.engine = LiveEngine(on_event=self._engine_evt.emit)
        self.engine.start()

        self.runner = Runner(self)
        self.runner.changed.connect(self.ownerChanged)
        self.runner.failed.connect(lambda msg: self.toast.emit(
            f"The background effect stopped: {msg}", "danger"))

        mode_id = settings["last_mode"] if settings["last_mode"] in catalog.BY_ID else catalog.DEFAULT_MODE
        self.mode = catalog.BY_ID[mode_id]
        self.values = self.mode.values(settings["params"].get(mode_id))
        self.profile = PROFILES[self._fallback_profile()]
        self.rescan(initial=True)
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(2000)
        self._scan_timer.timeout.connect(self.rescan)
        self._scan_timer.start()

    # -- startup ------------------------------------------------------------
    def start_preview(self):
        self._push()
        self.modeChanged.emit(self.mode, self.values, self.active_preset)

    # -- profiles & hardware ------------------------------------------------
    def _fallback_profile(self):
        pid = self.settings["profile"]
        usable = [p.id for p in hardware.usable_profiles()]
        if pid in usable:
            return pid
        return "hive65" if "hive65" in usable else usable[0]

    def _preferred_profile(self, dev):
        if dev is None:
            return self._fallback_profile()
        saved = self.settings["profile_for_usb"].get(dev["usb"])
        if saved in dev["profiles"]:
            return saved
        stable = [p for p in dev["profiles"] if not PROFILES[p].experimental]
        return (stable or dev["profiles"])[0]

    def rescan(self, initial=False):
        devs = hardware.scan()
        dev = devs[0] if devs else None
        changed = dev != self.device
        self.device = dev
        if initial or (changed and dev is not None):
            pid = self._preferred_profile(dev)
            if pid != self.profile.id:
                self.set_profile(pid, remember=False)
        if changed or initial:
            self.deviceChanged.emit(self.device_state())

    def device_state(self):
        dev = self.device
        if self.send and self.sink_state == "reconnecting":
            return {"state": "reconnecting", "label": "Reconnecting…"}
        if dev is None:
            return {"state": "missing", "label": "Not connected"}
        if not dev["writable"]:
            return {"state": "permission", "label": "No permission", "dev": dev["dev"]}
        if self.profile.id not in dev["profiles"]:
            return {"state": "mismatch", "label": "Different model", "dev": dev["dev"]}
        return {"state": "connected", "label": "Connected", "dev": dev["dev"]}

    def detected_profiles(self):
        return set(self.device["profiles"]) if self.device else set()

    def set_profile(self, pid, remember=True):
        if pid not in PROFILES:
            return
        if remember:
            if self.device and pid in self.device["profiles"]:
                self.settings["profile_for_usb"][self.device["usb"]] = pid
            else:
                self.settings["profile"] = pid
            self.settings.save()
        if pid == self.profile.id:
            return
        self.profile = PROFILES[pid]
        was_sending = self.send
        if was_sending:
            self._stop_sink()
        self._push()
        self.profileChanged.emit(self.profile)
        self.deviceChanged.emit(self.device_state())
        if was_sending:
            self.set_send(True)

    # -- modes & values -----------------------------------------------------
    def _push(self):
        self.engine.set_effect(self.mode.factory, self.mode.spec, self.values, self.profile)
        if self.lock.held:
            self.lock.update(mode=self.mode.label)

    def _user_values(self, values=None):
        values = self.values if values is None else values
        return {k: v for k, v in values.items() if k not in self.mode.fixed}

    def select_mode(self, mode_id):
        mode = catalog.BY_ID[mode_id]
        self.mode = mode
        self.values = mode.values(self.settings["params"].get(mode_id))
        self.active_preset = None
        self.settings["last_mode"] = mode_id
        self._push()
        self.modeChanged.emit(mode, self.values, None)

    def set_values(self, values):
        self.values = self.mode.spec.validate({**values, **self.mode.fixed})
        self.settings["params"][self.mode.id] = self._user_values()
        self.settings.save()
        self.engine.update(self.values)
        self.valuesChanged.emit(self.values)

    def reset_values(self):
        self.values = self.mode.values({})
        self.settings["params"].pop(self.mode.id, None)
        self.settings.save()
        self.engine.update(self.values)
        self.modeChanged.emit(self.mode, self.values, self.active_preset)

    # -- presets --------------------------------------------------------------
    def presets(self):
        return self.settings["presets"]

    def save_preset(self, name):
        p = self.settings.add_preset(name, self.mode.id, self._user_values())
        self.active_preset = p["id"]
        self.presetsChanged.emit(self.presets())
        self.modeChanged.emit(self.mode, self.values, self.active_preset)
        self.toast.emit(f"Saved preset “{name}”.", "success")

    def apply_preset(self, pid):
        p = self.settings.preset(pid)
        if not p or p["mode"] not in catalog.BY_ID:
            return
        self.mode = catalog.BY_ID[p["mode"]]
        self.values = self.mode.values(p["values"])
        self.active_preset = pid
        self.settings["params"][self.mode.id] = self._user_values()
        self.settings["last_mode"] = self.mode.id
        self._push()
        self.modeChanged.emit(self.mode, self.values, pid)

    def preset_target(self, pid):
        p = self.settings.preset(pid)
        mode = catalog.BY_ID[p["mode"]]
        return p, mode, mode.values(p["values"])

    def rename_preset(self, pid, name):
        self.settings.update_preset(pid, name=name)
        self.presetsChanged.emit(self.presets())

    def duplicate_preset(self, pid):
        p = self.settings.preset(pid)
        self.settings.add_preset(p["name"] + " copy", p["mode"], p["values"])
        self.presetsChanged.emit(self.presets())

    def delete_preset(self, pid):
        p = self.settings.preset(pid)
        self.settings.delete_preset(pid)
        if self.active_preset == pid:
            self.active_preset = None
        self.presetsChanged.emit(self.presets())
        if p:
            self.toast.emit(f"Deleted preset “{p['name']}”.", "info")

    # -- live on keyboard -----------------------------------------------------
    def set_send(self, on):
        if on == self.send:
            self.sendChanged.emit(self.send)
            return self.send
        if not on:
            self._stop_sink()
            self.send = False
            self.sendChanged.emit(False)
            self.engine.pause(self.hidden)
            self.deviceChanged.emit(self.device_state())
            return False
        st = self.device_state()
        if st["state"] != "connected":
            msg = {
                "missing": "Connect your keyboard (wired mode) to light it up.",
                "permission": "The keyboard was found but this app can't write to it. "
                              "See the setup hint above.",
                "mismatch": "The connected keyboard is a different model. Pick it in the "
                            "keyboard menu at the top.",
            }.get(st["state"], "The keyboard isn't ready yet.")
            self.toast.emit(msg, "warning")
            self.sendChanged.emit(False)
            return False
        rec = devlock.owner()
        if rec and rec.get("pid") != os.getpid():
            if not devlock.request_release(rec):
                self.toast.emit("Couldn't take over the keyboard from " + devlock.describe(rec), "danger")
                self.sendChanged.emit(False)
                return False
            self.toast.emit("Stopped the background effect so the preview can drive the keyboard.",
                            "info")
            self.runner.poll()
        if not self.lock.try_acquire():
            self.toast.emit("Another program is using the keyboard.", "danger")
            self.sendChanged.emit(False)
            return False
        self.lock.update(mode=self.mode.label)
        self.sink_state = None
        self.sink = DeviceSink(self.profile, self.device["dev"], on_event=self._sink_evt.emit)
        self.sink.start()
        self.engine.set_sink(self.sink)
        self.send = True
        self.engine.pause(False)
        self.sendChanged.emit(True)
        return True

    def _stop_sink(self, clear=False):
        self.engine.set_sink(None)
        if self.sink is not None:
            self.sink.stop(clear=clear)
            self.sink = None
        self.sink_state = None
        self.lock.release()

    def _on_sink_event(self, ev):
        t = ev["type"]
        if t == "connected":
            self.sink_state = "connected"
        elif t == "reconnecting":
            self.sink_state = "reconnecting"
        elif t == "lost":
            self.sink_state = "reconnecting"
            self.toast.emit("Lost the keyboard. Waiting for it to come back…", "warning")
        elif t == "permission":
            self.toast.emit("No permission to write to the keyboard. See Settings → Permissions.",
                            "danger")
            self.set_send(False)
            return
        self.deviceChanged.emit(self.device_state())

    # -- background -------------------------------------------------------------
    def run_in_background(self, mode=None, values=None, quiet=False):
        mode = mode or self.mode
        values = self.values if values is None else values
        if self.send:
            self.set_send(False)  # hand the board to the runner
        self.runner.start(self.profile.id, mode.argv(values))
        self.settings["last_applied"] = {
            "mode": mode.id, "profile": self.profile.id,
            "values": {k: v for k, v in values.items() if k not in mode.fixed},
        }
        if not quiet:
            self.toast.emit(f"“{mode.label}” is running in the background. It keeps going "
                            "after you close the app.", "success")

    def resume_last(self):
        """Login: restart the last background effect unless something already runs."""
        last = self.settings["last_applied"]
        if not last or devlock.owner() is not None or last.get("mode") not in catalog.BY_ID:
            return False
        mode = catalog.BY_ID[last["mode"]]
        if last.get("profile") in PROFILES:
            self.profile = PROFILES[last["profile"]]
        self.run_in_background(mode, mode.values(last.get("values")), quiet=True)
        return True

    def stop_background(self):
        rec = self.runner.owner
        if rec is None:
            return
        self.runner.stop()
        self.toast.emit(f"Stopped {self.owner_label(rec) or 'the background effect'}.", "info")

    def owner_label(self, rec):
        if rec is None:
            return None
        if rec.get("kind") == "gui":
            return rec.get("mode")
        return label_for_argv(rec.get("argv"))

    # -- commands & scripts -------------------------------------------------------
    def command(self, mode=None, values=None):
        mode = mode or self.mode
        return shell_command(self.profile.id, mode.argv(self.values if values is None else values))

    def script(self, title, mode=None, values=None):
        mode = mode or self.mode
        values = self.values if values is None else values
        name = slug(title)
        path = os.path.expanduser(f"~/.local/bin/keyboardrgb-{name}.sh")
        return path, toggle_script(title, self.profile.id, mode.argv(values), name)

    # -- engine, window, socket -------------------------------------------------------
    def inject_key(self, name, down):
        self.engine.inject_key(name, down)

    def _on_engine_event(self, ev):
        self.engineEvent.emit(ev)

    def set_window_visible(self, visible):
        self.hidden = not visible
        self.engine.pause(self.hidden and not self.send)

    def handle_socket(self, msg):
        cmd = msg.get("cmd")
        if cmd == "show":
            self.showRequested.emit()
        elif cmd == "release":
            if self.send:
                self.set_send(False)
                self.toast.emit("Another program took over the keyboard.", "info")
        elif cmd == "status":
            return {"ok": True, "send": self.send, "mode": self.mode.id}
        return {"ok": True}

    def handoff_on_close(self):
        """Window closing while live: keep the lighting by starting a runner."""
        if self.send and self.settings["keep_lighting_on_close"]:
            self.run_in_background(quiet=True)

    def shutdown(self):
        self._scan_timer.stop()
        if self.send:
            self._stop_sink()
            self.send = False
        self.engine.shutdown()
        self.settings.flush()
