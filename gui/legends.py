"""Printed keycap legends for profile key names."""

LEGENDS = {
    "esc": "Esc", "grave": "`", "minus": "-", "equal": "=", "backspace": "Backspace",
    "tab": "Tab", "lbracket": "[", "rbracket": "]", "backslash": "\\",
    "capslock": "Caps", "semicolon": ";", "quote": "'", "enter": "Enter",
    "lshift": "Shift", "rshift": "Shift", "comma": ",", "period": ".", "slash": "/",
    "lctrl": "Ctrl", "rctrl": "Ctrl", "lwin": "Super", "lalt": "Alt", "ralt": "Alt",
    "fn": "Fn", "space": "", "knob": "",
    "home": "Home", "end": "End", "del": "Del", "pgup": "PgUp", "pgdn": "PgDn",
    "up": "↑", "down": "↓", "left": "←", "right": "→",
}

# friendlier names for hover text
NAMES = {
    "esc": "Escape", "grave": "Backtick", "minus": "Minus", "equal": "Equals",
    "lbracket": "Left bracket", "rbracket": "Right bracket", "backslash": "Backslash",
    "capslock": "Caps Lock", "semicolon": "Semicolon", "quote": "Quote",
    "lshift": "Left Shift", "rshift": "Right Shift", "lctrl": "Left Ctrl",
    "rctrl": "Right Ctrl", "lwin": "Super", "lalt": "Left Alt", "ralt": "Right Alt",
    "fn": "Fn", "space": "Space", "knob": "Volume knob", "del": "Delete",
    "pgup": "Page Up", "pgdn": "Page Down", "up": "Up arrow", "down": "Down arrow",
    "left": "Left arrow", "right": "Right arrow",
}


def legend(name, override=None):
    if override is not None:
        return override
    if name in LEGENDS:
        return LEGENDS[name]
    return name.upper() if len(name) <= 3 else name.title()


def friendly(name):
    return NAMES.get(name, legend(name) or name.title())
