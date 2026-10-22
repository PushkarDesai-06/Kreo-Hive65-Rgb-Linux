"""Where the app is running from: a source checkout, or a frozen PyInstaller
bundle (optionally inside an AppImage). That decides how to start the CLI and
the app itself, since a frozen build has no keyboardrgb.py to hand to python.

Inside an AppImage every bundled file lives on a FUSE mount that disappears
when this instance quits, so anything that must outlive the window (the
background runner, toggle scripts, launch-on-login) starts the .AppImage file
again rather than pointing into the mount."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN = bool(getattr(sys, "frozen", False))
CLI_SCRIPT = os.path.join(ROOT, "keyboardrgb.py")
GUI_SCRIPT = os.path.join(ROOT, "keyboardrgb_gui.py")


def appimage():
    """Path of the running .AppImage file, or None."""
    return os.environ.get("APPIMAGE") or None


def packaged():
    return FROZEN or appimage() is not None


def app_command():
    """Command that starts this app again."""
    if appimage():
        return [appimage()]
    if FROZEN:
        return [sys.executable]
    return [sys.executable, GUI_SCRIPT]


def cli_command():
    """Command that runs keyboardrgb.py's CLI (arguments follow)."""
    if packaged():
        return app_command() + ["--cli"]
    return [sys.executable, CLI_SCRIPT]


def cli_display():
    """CLI command as shown to people (copy-command, scripts): the plain
    `python3 keyboardrgb.py` for a checkout, the app's --cli mode when packaged."""
    if packaged():
        return app_command() + ["--cli"]
    return ["python3", CLI_SCRIPT]


def data_path(name):
    """A file shipped next to the code (bundled as data when frozen)."""
    return os.path.join(ROOT, name)
