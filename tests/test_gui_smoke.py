#!/usr/bin/env python3
"""Keyboard Studio smoke test (offscreen, no hardware): every mode previews,
live send streams frames to a fake board and releases it, presets round-trip,
the background runner starts/stops through devlock, the CLI's release message
turns live send off, and typing effects fall back to keys from the window.

Skipped when PySide6 isn't installed (the CLI itself doesn't need it)."""
import os
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import PySide6  # noqa: F401
except ImportError:  # pragma: no cover
    PySide6 = None

TMP = tempfile.mkdtemp(prefix="kbdrgb-gui-")
for var, sub in (("KEYBOARDRGB_CONFIG_DIR", "cfg"), ("KEYBOARDRGB_RUNTIME_DIR", "rt"),
                 ("XDG_STATE_HOME", "state"), ("XDG_CACHE_HOME", "cache"),
                 ("XDG_CONFIG_HOME", "config")):
    os.environ[var] = os.path.join(TMP, sub)
os.environ["QT_QPA_PLATFORM"] = "offscreen"

FAKE_RUNNER = textwrap.dedent(f"""
    import os, signal, sys, time
    sys.path.insert(0, {ROOT!r})
    import devlock
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    lock = devlock.DeviceLock("runner", mode=sys.argv[3], argv=sys.argv[1:])
    lock.acquire(takeover=True)
    time.sleep(30)
""")


@unittest.skipIf(PySide6 is None, "PySide6 not installed")
class TestStudio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import fcntl

        from PySide6.QtWidgets import QApplication

        cls.packets = []
        fcntl.ioctl = lambda fd, req, arg, mutate=True: cls.packets.append(bytes(arg)) or 0
        cls.app = QApplication.instance() or QApplication([])
        from gui import hardware, theme
        hardware.scan = lambda sysfs_root=None: [{
            "dev": "/dev/null", "usb": "258a:010c", "profiles": ["hive65", "aulaf75"],
            "writable": True}]
        theme.ThemeManager.get().apply("#09090b", "#f0ec57")
        from gui import runtime
        script = os.path.join(TMP, "fake_cli.py")
        with open(script, "w") as f:
            f.write(FAKE_RUNNER)
        cls._cli_patch = mock.patch.object(runtime, "cli_command",
                                           lambda: [sys.executable, script])
        cls._cli_patch.start()
        from gui.controller import Studio
        from gui.main_window import MainWindow
        from gui.settings import Settings
        cls.studio = Studio(Settings())
        cls.win = MainWindow(cls.studio)
        cls.studio.start_preview()
        cls.win.show()

    @classmethod
    def tearDownClass(cls):
        cls.win.quitting = True
        cls.studio.runner.stop()
        cls.studio.shutdown()
        cls.win.close()
        cls._cli_patch.stop()

    def pump(self, sec=0.2, until=None):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            self.app.processEvents()
            if until and until():
                return True
            time.sleep(0.01)
        return bool(until and until())

    def test_every_mode_previews(self):
        from gui import catalog
        for mode in catalog.MODES:
            with self.subTest(mode=mode.id):
                before = self.studio.engine.latest[0]
                self.studio.select_mode(mode.id)
                self.assertEqual(self.win.title.text(), mode.label)
                if mode.id == "screen":
                    continue  # needs a real display to capture
                self.assertTrue(self.pump(2.0, lambda: self.studio.engine.latest[0] > before
                                          and self.studio.engine.latest[1] is self.studio.profile))
        self.studio.select_mode("flux")

    def test_live_values_and_reset(self):
        self.studio.select_mode("flux")
        self.studio.set_values({**self.studio.values, "speed": 2.5})
        self.pump(0.1)
        self.assertEqual(self.studio.engine._fx.o.speed, 2.5)
        self.studio.reset_values()
        self.assertEqual(self.studio.values["speed"], 1.0)

    def test_send_streams_and_releases(self):
        import devlock
        self.studio.select_mode("solid")
        self.packets.clear()
        self.assertTrue(self.studio.set_send(True))
        self.assertTrue(self.pump(2.0, lambda: len(self.packets) > 0))
        self.assertEqual(devlock.owner()["kind"], "gui")
        self.assertTrue(self.win.live_switch.isChecked())
        self.studio.set_send(False)
        self.assertIsNone(devlock.owner())
        self.assertFalse(self.win.live_switch.isChecked())

    def test_release_message_turns_send_off(self):
        import devlock
        from gui.single_instance import SingleInstance
        # kept on the class: Python must not destroy it while Qt still owns its sockets
        single = type(self)._single = SingleInstance(self.studio)
        single.handler = self.studio.handle_socket
        single.listen()
        try:
            self.assertTrue(self.studio.set_send(True))
            done = []
            t = threading.Thread(target=lambda: done.append(devlock.request_release(timeout=3)))
            t.start()
            self.assertTrue(self.pump(4.0, lambda: bool(done)))
            t.join()
            self.assertEqual(done, [True])
            self.assertFalse(self.studio.send)
        finally:
            single.close()

    def test_presets(self):
        self.studio.select_mode("gradient")
        self.studio.set_values({**self.studio.values, "start": "123456"})
        self.studio.save_preset("Ocean")
        pid = self.studio.presets()[-1]["id"]
        self.assertIn("preset:" + pid, self.win.sidebar.preset_items)
        self.studio.select_mode("rainbow")
        self.studio.apply_preset(pid)
        self.assertEqual(self.studio.mode.id, "gradient")
        self.assertEqual(self.studio.values["start"], "123456")
        self.studio.rename_preset(pid, "Deep ocean")
        self.assertEqual(self.studio.settings.preset(pid)["name"], "Deep ocean")
        self.studio.delete_preset(pid)
        self.assertIsNone(self.studio.settings.preset(pid))

    def test_background_runner(self):
        self.studio.select_mode("music-bars")
        self.studio.run_in_background()
        self.assertTrue(self.pump(5.0, lambda: self.studio.runner.running))
        self.assertEqual(self.studio.owner_label(self.studio.runner.owner), "Equalizer Bars")
        self.assertTrue(self.win.stop_btn.isVisible())
        self.assertEqual(self.studio.settings["last_applied"]["mode"], "music-bars")
        self.studio.stop_background()
        self.assertTrue(self.pump(5.0, lambda: self.studio.runner.owner is None))

    def test_command_and_script(self):
        self.studio.select_mode("music-bars")
        cmd = self.studio.command()
        self.assertIn("--profile hive65 audio --effect bars", cmd)
        path, text = self.studio.script("My Bars")
        self.assertTrue(path.endswith("keyboardrgb-my-bars.sh"))
        self.assertIn("audio --effect bars", text)

    def test_typing_falls_back_to_window_keys(self):
        self.studio.select_mode("typing-splash")
        self.studio.set_values({**self.studio.values, "input": "/nonexistent/event99"})
        self.assertTrue(self.pump(2.0, lambda: "input" in self.win.banners))
        self.assertTrue(self.win.capture_keys)
        self.win.keyboard.keyPressed.emit("f", True)
        idx = [n for n, _c, _r in self.studio.profile.keys_tuples].index("f")
        self.assertTrue(self.pump(2.0, lambda: self.studio.engine.latest[2][idx] != (0, 0, 0)))
        self.win.keyboard.keyPressed.emit("f", False)

    def test_profile_switch(self):
        self.studio.set_profile("aulaf75")
        self.assertEqual(self.win.keyboard.profile.id, "aulaf75")
        self.assertEqual(self.studio.settings["profile_for_usb"]["258a:010c"], "aulaf75")
        self.studio.set_profile("hive65")


if __name__ == "__main__":
    unittest.main()
