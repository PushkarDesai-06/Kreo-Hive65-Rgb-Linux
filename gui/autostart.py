"""Launch on login (XDG autostart) and the app-launcher entry."""
import os
import shlex
import shutil

from gui import runtime

NAME = "keyboardrgb-studio.desktop"
ICON = "keyboard-studio"


def _config_home():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def autostart_path():
    return os.path.join(_config_home(), "autostart", NAME)


def launcher_path():
    data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(data, "applications", NAME)


def exec_line(tray=False):
    return shlex.join(runtime.app_command() + (["--tray"] if tray else []))


def _desktop(tray):
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=Keyboard Studio",
        "Comment=Preview and run RGB keyboard lighting effects",
        f"Exec={exec_line(tray)}",
        f"Icon={ICON if _install_icon() else 'input-keyboard'}",
        "Terminal=false",
        "Categories=Utility;Settings;HardwareSettings;",
        "StartupNotify=false",
        "X-GNOME-Autostart-enabled=true" if tray else "",
        "",
    ])


def _install_icon():
    """Copy the app icon into the user's icon theme (a packaged app's own copy
    lives on a mount that vanishes). Returns False if there is no icon file."""
    src = runtime.data_path("packaging/keyboard-studio.png")
    if not os.path.exists(src):
        return False
    data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    dest = os.path.join(data, "icons", "hicolor", "256x256", "apps", ICON + ".png")
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(src, dest)
    except OSError:
        return False
    return True


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
