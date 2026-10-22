#!/usr/bin/env python3
"""How the app starts itself and the CLI from a source checkout vs. a packaged
build (PyInstaller bundle, AppImage). No Qt needed except for the rule-install
command, which is skipped without PySide6."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui import runtime  # noqa: E402  (stdlib-only module)


class TestRuntime(unittest.TestCase):
    def test_source_checkout(self):
        with mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.object(runtime, "FROZEN", False):
            os.environ.pop("APPIMAGE", None)
            self.assertFalse(runtime.packaged())
            self.assertEqual(runtime.cli_command(), [sys.executable, runtime.CLI_SCRIPT])
            self.assertEqual(runtime.cli_display(), ["python3", runtime.CLI_SCRIPT])
            self.assertEqual(runtime.app_command(), [sys.executable, runtime.GUI_SCRIPT])

    def test_appimage_restarts_the_image_not_the_mount(self):
        with mock.patch.dict(os.environ, {"APPIMAGE": "/home/u/Keyboard_Studio.AppImage"}), \
                mock.patch.object(runtime, "FROZEN", True):
            self.assertTrue(runtime.packaged())
            self.assertEqual(runtime.cli_command(), ["/home/u/Keyboard_Studio.AppImage", "--cli"])
            self.assertEqual(runtime.app_command(), ["/home/u/Keyboard_Studio.AppImage"])

    def test_frozen_without_appimage(self):
        with mock.patch.object(runtime, "FROZEN", True):
            env = dict(os.environ)
            env.pop("APPIMAGE", None)
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(runtime.cli_command(), [sys.executable, "--cli"])

    def test_toggle_script_uses_packaged_cli(self):
        try:
            from gui import background
        except ImportError:
            self.skipTest("PySide6 not installed")
        with mock.patch.dict(os.environ, {"APPIMAGE": "/opt/KS.AppImage"}), \
                mock.patch.object(runtime, "FROZEN", True):
            text = background.toggle_script("Bars", "hive65", ["audio", "--effect", "bars"], "bars")
            cmd = background.shell_command("hive65", ["rainbow"])
        self.assertIn("KEYBOARDRGB_RUNNER=1 /opt/KS.AppImage --cli --profile hive65 audio "
                      "--effect bars", text)
        self.assertEqual(cmd, "/opt/KS.AppImage --cli --profile hive65 rainbow")

    def test_rule_command_copies_out_of_the_mount_first(self):
        try:
            from gui import permissions
        except ImportError:
            self.skipTest("PySide6 not installed")
        with mock.patch.dict(os.environ, {"APPIMAGE": "/opt/KS.AppImage"}):
            cmd = permissions.sudo_command()
        self.assertTrue(cmd.startswith("cp "))
        self.assertIn('sudo install -m 0644 "$XDG_RUNTIME_DIR/60-keyboardrgb.rules"', cmd)


if __name__ == "__main__":
    unittest.main()
