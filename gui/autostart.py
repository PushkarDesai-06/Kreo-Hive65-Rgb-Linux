"""Launch on login (XDG autostart) and the app-launcher entry."""
import os
import shlex
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROOT, "keyboardrgb_gui.py")
NAME = "keyboardrgb-studio.desktop"


def _config_home():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def autostart_path():
    return os.path.join(_config_home(), "autostart", NAME)


def launcher_path():
    data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(data, "applications", NAME)


def exec_line(tray=False):
    cmd = [sys.executable, GUI] + (["--tray"] if tray else [])
    return shlex.join(cmd)


def _desktop(tray):
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=Keyboard Studio",
        "Comment=Preview and run RGB keyboard lighting effects",
        f"Exec={exec_line(tray)}",
        "Icon=input-keyboard",
        "Terminal=false",
        "Categories=Utility;Settings;HardwareSettings;",
        "StartupNotify=false",
        "X-GNOME-Autostart-enabled=true" if tray else "",
        "",
    ])


def is_enabled():
    return os.path.exists(autostart_path())


def set_enabled(on):
    path = autostart_path()
    if on:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(_desktop(tray=True))
    elif os.path.exists(path):
        os.remove(path)


def install_launcher():
    path = launcher_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(_desktop(tray=False))
    return path


def launcher_installed():
    return os.path.exists(launcher_path())


def hyprland():
    return "hyprland" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower()


def hyprland_line():
    """What to put in hyprland.conf when the session doesn't run XDG autostart
    entries (Hyprland only does that through uwsm or dex)."""
    return f"exec-once = {exec_line(tray=True)}"


def needs_hypr_hint():
    return hyprland() and not (shutil.which("uwsm") or shutil.which("dex"))
