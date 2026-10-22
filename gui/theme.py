"""Design tokens and the app stylesheet.

A theme is two colors: a base (the window background) and an accent. Every
other token (surfaces, borders, text, muted text, focus ring) is mixed from the
base and a foreground picked for contrast, so any base/accent pair stays a
coherent monochrome UI with a single accent, shadcn style."""
import os
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

FONT_FAMILY = "Inter"
MONO_FAMILY = "JetBrains Mono"

# (id, name, base, accent)
PRESETS = (
    ("midnight-lemon", "Midnight Lemon", "#09090b", "#f0ec57"),
    ("zinc-blue", "Zinc Blue", "#09090b", "#3b82f6"),
    ("slate-emerald", "Slate Emerald", "#0b1120", "#10b981"),
    ("stone-orange", "Stone Orange", "#0c0a09", "#f97316"),
    ("neutral-rose", "Neutral Rose", "#0a0a0a", "#f43f5e"),
    ("graphite-violet", "Graphite Violet", "#111113", "#a78bfa"),
    ("paper-indigo", "Paper Indigo", "#ffffff", "#4f46e5"),
)
DEFAULT_PRESET = PRESETS[0]


def hex_rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def mix(a, b, t):
    """Blend hex color a toward b by t (0..1)."""
    ra, rb = hex_rgb(a), hex_rgb(b)
    return rgb_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def luminance(rgb):
    def ch(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = luminance(hex_rgb(a)), luminance(hex_rgb(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def rgba(h, alpha):
    r, g, b = hex_rgb(h)
    return f"rgba({r}, {g}, {b}, {int(alpha * 255)})"


@dataclass(frozen=True)
class Theme:
    base: str
    accent: str

    @property
    def dark(self):
        return luminance(hex_rgb(self.base)) < 0.35

    def tokens(self):
        base, accent, dark = self.base, self.accent, self.dark
        fg = "#fafafa" if dark else "#09090b"
        on_accent = "#09090b" if contrast(accent, "#09090b") >= contrast(accent, "#fafafa") else "#fafafa"
        return {
            "bg": base,
            "sidebar": mix(base, fg, 0.018 if dark else 0.025),
            "surface": mix(base, fg, 0.028 if dark else 0.0),
            "surface2": mix(base, fg, 0.065 if dark else 0.045),
            "surface3": mix(base, fg, 0.11 if dark else 0.085),
            "border": mix(base, fg, 0.12 if dark else 0.11),
            "border_strong": mix(base, fg, 0.2 if dark else 0.2),
            "fg": fg,
            "muted": mix(base, fg, 0.6 if dark else 0.55),
            "subtle": mix(base, fg, 0.38),
            "accent": accent,
            "accent_fg": on_accent,
            "accent_hover": mix(accent, fg if dark else "#000000", 0.12),
            "accent_soft": rgba(accent, 0.13),
            "accent_line": rgba(accent, 0.45),
            "ring": rgba(accent, 0.6),
            "danger": "#ef4444",
            "warning": "#f59e0b",
            "success": "#22c55e",
            "info": "#60a5fa",
            "case": mix(base, fg, 0.045 if dark else 0.06),
            "case_edge": mix(base, fg, 0.1 if dark else 0.14),
            "cap": mix(base, "#000000" if dark else fg, 0.35 if dark else 0.82),
            "cap_edge": mix(base, fg, 0.16),
            "shadow": "rgba(0, 0, 0, 140)" if dark else "rgba(0, 0, 0, 40)",
        }


def _chevron_file(color):
    """QSS can only show images from files: write the select chevron once per color."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    d = os.path.join(base, "keyboardrgb")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"chevron-{color.lstrip('#')}.svg")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                    f'stroke="{color}" stroke-width="2" stroke-linecap="round" '
                    f'stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>')
    return path


def build_qss(t):
    """The application stylesheet, formatted from theme tokens."""
    return f"""
* {{
    font-family: "{FONT_FAMILY}";
    font-size: 13px;
    color: {t['fg']};
    outline: 0;
}}
QMainWindow, QDialog, #Central {{ background: {t['bg']}; }}
QWidget#Sidebar {{ background: {t['sidebar']}; border-right: 1px solid {t['border']}; }}
QWidget#Header {{ background: {t['bg']}; border-bottom: 1px solid {t['border']}; }}
QWidget#SidebarList, QWidget#Content {{ background: transparent; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}

QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 22px; font-weight: 600; letter-spacing: -0.3px; }}
QLabel[role="h2"] {{ font-size: 14px; font-weight: 600; }}
QLabel[role="brand"] {{ font-size: 14px; font-weight: 600; letter-spacing: -0.1px; }}
QLabel[role="muted"] {{ color: {t['muted']}; }}
QLabel[role="small"] {{ color: {t['muted']}; font-size: 12px; }}
QLabel[role="section"] {{
    color: {t['subtle']}; font-size: 11px; font-weight: 600;
    letter-spacing: 0.6px; padding: 14px 10px 6px 10px;
}}
QLabel[role="value"] {{ color: {t['muted']}; font-family: "{MONO_FAMILY}"; font-size: 12px; }}
QLabel[role="code"] {{
    font-family: "{MONO_FAMILY}"; font-size: 12px; color: {t['fg']};
    background: {t['surface2']}; border: 1px solid {t['border']};
    border-radius: 6px; padding: 8px 10px;
}}

QFrame[role="card"] {{
    background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px;
}}
QFrame[role="separator"] {{ background: {t['border']}; max-height: 1px; min-height: 1px; border: none; }}

QPushButton {{
    background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px;
    padding: 0 12px; min-height: 32px; font-weight: 500;
}}
QPushButton:hover {{ background: {t['surface2']}; }}
QPushButton:pressed {{ background: {t['surface3']}; }}
QPushButton:focus {{ border: 1px solid {t['ring']}; }}
QPushButton:disabled {{ color: {t['subtle']}; background: {t['surface']}; }}
QPushButton[variant="primary"] {{
    background: {t['accent']}; color: {t['accent_fg']}; border: 1px solid {t['accent']};
}}
QPushButton[variant="primary"]:hover {{ background: {t['accent_hover']}; border-color: {t['accent_hover']}; }}
QPushButton[variant="primary"]:disabled {{ background: {t['surface2']}; color: {t['subtle']}; border-color: {t['border']}; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; }}
QPushButton[variant="ghost"]:hover {{ background: {t['surface2']}; }}
QPushButton[variant="danger"] {{ color: {t['danger']}; }}
QPushButton[variant="danger"]:hover {{ background: {rgba(t['danger'], 0.12)}; border-color: {rgba(t['danger'], 0.4)}; }}
QPushButton[size="sm"] {{ min-height: 28px; padding: 0 10px; border-radius: 7px; font-size: 12px; }}
QPushButton[size="icon"] {{ min-height: 32px; max-height: 32px; min-width: 32px; max-width: 32px; padding: 0; }}
QPushButton::menu-indicator {{ width: 0; image: none; }}

QLineEdit {{
    background: {t['bg']}; border: 1px solid {t['border']}; border-radius: 8px;
    padding: 0 10px; min-height: 32px; selection-background-color: {t['accent']};
    selection-color: {t['accent_fg']};
}}
QLineEdit:focus {{ border: 1px solid {t['ring']}; }}
QLineEdit[role="value"] {{
    font-family: "{MONO_FAMILY}"; font-size: 12px; min-height: 24px; max-height: 24px;
    padding: 0 6px; border-radius: 6px; background: transparent; border-color: transparent;
    color: {t['muted']};
}}
QLineEdit[role="value"]:hover {{ border-color: {t['border']}; }}
QLineEdit[role="value"]:focus {{ border-color: {t['ring']}; color: {t['fg']}; background: {t['bg']}; }}
QLineEdit[role="search"] {{ background: {t['bg']}; padding-left: 30px; }}

QComboBox {{
    background: {t['bg']}; border: 1px solid {t['border']}; border-radius: 8px;
    padding: 0 30px 0 10px; min-height: 32px;
}}
QComboBox:hover {{ background: {t['surface2']}; }}
QComboBox:focus {{ border: 1px solid {t['ring']}; }}
QComboBox::drop-down {{ border: none; width: 30px; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url({t['chevron']}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{
    background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px;
    padding: 4px; selection-background-color: {t['surface2']}; selection-color: {t['fg']};
}}
QComboBox QAbstractItemView::item {{ min-height: 28px; padding: 0 8px; border-radius: 6px; }}

QMenu {{
    background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px; padding: 5px;
}}
QMenu::item {{ padding: 7px 28px 7px 10px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['surface2']}; }}
QMenu::item:disabled {{ color: {t['subtle']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 5px 4px; }}
QMenu::icon {{ padding-left: 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; left: 8px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t['border_strong']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; width: 0; height: 0;
}}

QToolTip {{
    background: {t['surface']}; color: {t['fg']}; border: 1px solid {t['border']};
    padding: 6px 8px; border-radius: 6px;
}}
QPlainTextEdit {{
    background: {t['bg']}; border: 1px solid {t['border']}; border-radius: 8px;
    font-family: "{MONO_FAMILY}"; font-size: 12px; padding: 6px;
}}
QDialog QLabel[role="title"] {{ font-size: 17px; }}
"""


class ThemeManager(QObject):
    """Holds the active theme; custom-painted widgets read `tokens` at paint
    time and repaint on `changed`."""

    changed = Signal()
    _instance = None

    def __init__(self):
        super().__init__()
        self.theme = Theme(DEFAULT_PRESET[2], DEFAULT_PRESET[3])
        self.tokens = self.theme.tokens()

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = ThemeManager()
        return cls._instance

    def apply(self, base, accent):
        self.theme = Theme(base, accent)
        self.tokens = t = self.theme.tokens()
        app = QApplication.instance()
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor(t["bg"]))
        pal.setColor(QPalette.WindowText, QColor(t["fg"]))
        pal.setColor(QPalette.Base, QColor(t["bg"]))
        pal.setColor(QPalette.AlternateBase, QColor(t["surface"]))
        pal.setColor(QPalette.Text, QColor(t["fg"]))
        pal.setColor(QPalette.Button, QColor(t["surface"]))
        pal.setColor(QPalette.ButtonText, QColor(t["fg"]))
        pal.setColor(QPalette.Highlight, QColor(t["accent"]))
        pal.setColor(QPalette.HighlightedText, QColor(t["accent_fg"]))
        pal.setColor(QPalette.ToolTipBase, QColor(t["surface"]))
        pal.setColor(QPalette.ToolTipText, QColor(t["fg"]))
        pal.setColor(QPalette.PlaceholderText, QColor(t["subtle"]))
        app.setPalette(pal)
        app.setStyleSheet(build_qss({**t, "chevron": _chevron_file(t["muted"])}))
        self.changed.emit()


def tokens():
    return ThemeManager.get().tokens


def qcolor(name, alpha=None):
    c = QColor(tokens()[name]) if not tokens()[name].startswith("rgba") else _parse_rgba(tokens()[name])
    if alpha is not None:
        c.setAlphaF(alpha)
    return c


def _parse_rgba(s):
    r, g, b, a = (int(x) for x in s[s.index("(") + 1:s.index(")")].split(","))
    return QColor(r, g, b, a)


def app_font(px=13, weight=QFont.Normal):
    f = QFont(FONT_FAMILY)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def mono_font(px=12):
    f = QFont(MONO_FAMILY)
    f.setPixelSize(px)
    return f
