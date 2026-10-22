"""Dialogs: settings (theme, startup, permissions), preset naming and the
toggle-script export."""
import grp
import os

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QDialog, QFileDialog, QGridLayout, QHBoxLayout,
                               QLineEdit, QPlainTextEdit, QScrollArea, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

from gui import autostart, permissions, theme
from gui.widgets.controls import (Card, ColorSwatch, Switch, button, label, qc, separator)
from gui.widgets.tooltip import set_tip

INPUT_CMD = "sudo usermod -aG input $USER"


def copy_text(text):
    QGuiApplication.clipboard().setText(text)


def code_row(text, on_copied=None, tip_title="Copy command"):
    """Monospace command with a copy button."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    code = label(text, "code", wrap=True)
    code.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lay.addWidget(code, 1)
    b = button(icon="copy", size="icon", tip=tip_title, tip_body="Copy to the clipboard.")

    def do():
        copy_text(text)
        if on_copied:
            on_copied()
    b.clicked.connect(do)
    lay.addWidget(b, 0, Qt.AlignTop)
    return w


def setting_row(title, desc, control):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(16)
    col = QVBoxLayout()
    col.setSpacing(2)
    t = label(title)
    t.setStyleSheet("font-weight: 500;")
    col.addWidget(t)
    col.addWidget(label(desc, "small", wrap=True))
    lay.addLayout(col, 1)
    lay.addWidget(control, 0, Qt.AlignVCenter)
    set_tip(w, title, desc)
    return w


class ThemeTile(QAbstractButton):
    """Preset preview: base swatch with an accent bar."""

    def __init__(self, pid, name, base, accent, parent=None):
        super().__init__(parent)
        self.pid, self.name, self.base, self.accent = pid, name, base, accent
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(134, 76)
        set_tip(self, name, f"Background {base}, accent {accent}.")

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        p.setPen(QPen(qc("accent") if self.isChecked() else qc("border"), 2 if self.isChecked() else 1))
        p.setBrush(qc("surface"))
        p.drawRoundedRect(r, 10, 10)
        sw = QRectF(r.left() + 8, r.top() + 8, r.width() - 16, 34)
        t = theme.Theme(self.base, self.accent).tokens()
        p.setPen(QPen(QColor(t["border"]), 1))
        p.setBrush(QColor(self.base))
        p.drawRoundedRect(sw, 6, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t["surface3"]))
        p.drawRoundedRect(QRectF(sw.left() + 8, sw.top() + 9, 40, 6), 3, 3)
        p.drawRoundedRect(QRectF(sw.left() + 8, sw.top() + 19, 28, 6), 3, 3)
        p.setBrush(QColor(self.accent))
        p.drawRoundedRect(QRectF(sw.right() - 38, sw.top() + 10, 30, 14), 7, 7)
        p.setPen(qc("fg"))
        f = self.font()
        f.setPixelSize(12)
        f.setWeight(f.Weight.Medium)
        p.setFont(f)
        p.drawText(QRectF(r.left() + 10, sw.bottom() + 4, r.width() - 20, 22), Qt.AlignVCenter, self.name)


class SettingsDialog(QDialog):
    themeChanged = Signal(str, str, str)   # preset id ("custom"), base, accent

    def __init__(self, settings, root, toast, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.toast = toast
        self.setWindowTitle("Settings")
        self.resize(680, 720)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(16)
        lay.addWidget(label("Settings", "title"))
        lay.addWidget(label("Make the app look the way you like and decide what happens "
                            "when you log in or close the window.", "muted", wrap=True))

        # appearance
        card = Card("Appearance", "palette")
        grid = QGridLayout()
        grid.setSpacing(10)
        self.tiles = []
        cur = settings["theme"]
        for i, (pid, name, base, accent) in enumerate(theme.PRESETS):
            tile = ThemeTile(pid, name, base, accent)
            tile.setChecked(cur.get("preset") == pid)
            tile.clicked.connect(lambda _=False, t=tile: self._preset(t))
            self.tiles.append(tile)
            grid.addWidget(tile, i // 4, i % 4)
        card.body_layout.addLayout(grid)
        card.body_layout.addWidget(separator())
        self.base_sw = ColorSwatch(cur["base"].lstrip("#"))
        self.base_sw.colorChanged.connect(lambda hx: self._custom())
        set_tip(self.base_sw, "Background color", "The window background. Every other "
                "surface and text color is derived from it.")
        card.body_layout.addWidget(setting_row(
            "Background", "Custom background color. Surfaces and text adapt automatically.",
            self.base_sw))
        self.accent_sw = ColorSwatch(cur["accent"].lstrip("#"))
        self.accent_sw.colorChanged.connect(lambda hx: self._custom())
        set_tip(self.accent_sw, "Accent color", "Used for buttons, sliders, switches and "
                "highlights.")
        card.body_layout.addWidget(setting_row(
            "Accent", "The single highlight color used across the app.", self.accent_sw))
        lay.addWidget(card)

        # startup & background
        card = Card("Startup & background", "rocket")
        self.autostart = Switch()
        self.autostart.setChecked(autostart.is_enabled())
        self.autostart.toggled.connect(self._autostart)
        card.body_layout.addWidget(setting_row(
            "Launch on login",
            "Starts hidden in the system tray when you log in and turns your last "
            "background lighting back on.", self.autostart))
        if autostart.needs_hypr_hint():
            card.body_layout.addWidget(label(
                "Hyprland only runs login items through uwsm or dex. If you use neither, "
                "add this line to your hyprland.conf instead:", "small", wrap=True))
            card.body_layout.addWidget(code_row(
                autostart.hyprland_line(), lambda: toast("Copied to clipboard.", "success")))
        self.keep = Switch()
        self.keep.setChecked(settings["keep_lighting_on_close"])
        self.keep.toggled.connect(lambda on: settings.__setitem__("keep_lighting_on_close", on))
        card.body_layout.addWidget(setting_row(
            "Keep lighting when the window closes",
            "If the preview is live on your keyboard, it carries on as a background effect "
            "after you close the window.", self.keep))
        self.tray = Switch()
        has_tray = QSystemTrayIcon.isSystemTrayAvailable()
        self.tray.setChecked(settings["close_to_tray"] and has_tray)
        self.tray.setEnabled(has_tray)
        self.tray.toggled.connect(lambda on: settings.__setitem__("close_to_tray", on))
        card.body_layout.addWidget(setting_row(
            "Close to tray",
            "Closing the window keeps the app in the system tray." if has_tray else
            "No system tray was found (on Hyprland, enable a tray in your bar, like "
            "waybar's tray module).", self.tray))
        launcher = button("Installed" if autostart.launcher_installed() else "Add",
                          icon="external", size="sm", tip="Add to app launcher",
                          tip_body="Creates a desktop entry so the app shows up in your launcher.")
        launcher.clicked.connect(lambda: (autostart.install_launcher(), launcher.setText("Installed"),
                                          toast("Added Keyboard Studio to your app launcher.",
                                                "success")))
        card.body_layout.addWidget(setting_row(
            "App launcher entry", "Show Keyboard Studio in rofi, wofi, fuzzel or your app menu.",
            launcher))
        lay.addWidget(card)

        # permissions
        card = Card("Permissions", "plug")
        in_input = _in_group("input")
        installed = permissions.rule_installed()
        self.rule_btn = button("Installed" if installed else "Install", icon="plug", size="sm",
                               variant=None if installed else "primary",
                               tip="Install keyboard access",
                               tip_body="Installs the udev rule so the app can light your "
                                        "keyboard without root. Asks for your password once.")
        self.installer = permissions.RuleInstaller(self)
        self.installer.finished.connect(self._rule_done)
        self.rule_btn.clicked.connect(self._install_rule)
        card.body_layout.addWidget(setting_row(
            "Keyboard access",
            "Lets the app write lighting to the keyboard. Needed once per computer.",
            self.rule_btn))
        card.body_layout.addWidget(label("Or run it yourself in a terminal:", "small"))
        card.body_layout.addWidget(code_row(permissions.sudo_command(),
                                            lambda: toast("Copied to clipboard.", "success")))
        card.body_layout.addWidget(label(
            ("Typing effects can see key presses everywhere: you are in the input group."
             if in_input else
             "Typing effects: to react to keys pressed in any app (not just this window), "
             "join the input group, then log out and back in. Note that this lets programs "
             "you run read all keystrokes."), "small", wrap=True))
        if not in_input:
            card.body_layout.addWidget(code_row(INPUT_CMD,
                                                lambda: toast("Copied to clipboard.", "success")))
        lay.addWidget(card)
        lay.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(24, 12, 24, 16)
        foot.addStretch(1)
        done = button("Done", variant="primary", tip="Close settings")
        done.clicked.connect(self.accept)
        foot.addWidget(done)
        outer.addLayout(foot)

    def _preset(self, tile):
        for t in self.tiles:
            t.setChecked(t is tile)
        self.base_sw.setValue(tile.base.lstrip("#"))
        self.accent_sw.setValue(tile.accent.lstrip("#"))
        self.themeChanged.emit(tile.pid, tile.base, tile.accent)

    def _custom(self):
        for t in self.tiles:
            t.setChecked(False)
        self.themeChanged.emit("custom", "#" + self.base_sw.value(), "#" + self.accent_sw.value())

    def _install_rule(self):
        self.rule_btn.setEnabled(False)
        self.rule_btn.setText("Waiting…")
        self.installer.start()

    def _rule_done(self, ok, msg):
        self.rule_btn.setEnabled(True)
        self.rule_btn.setText("Installed" if ok else "Install")
        self.toast(msg, "success" if ok else "warning")

    def _autostart(self, on):
        try:
            autostart.set_enabled(on)
        except OSError as e:
            self.toast(f"Couldn't change login startup: {e}", "danger")
            return
        self.settings["autostart"] = on
        self.toast("Keyboard Studio will start when you log in." if on else
                   "Keyboard Studio won't start at login anymore.", "success")


def _in_group(name):
    try:
        gid = grp.getgrnam(name).gr_gid
    except KeyError:
        return False
    return gid in os.getgroups()


class NameDialog(QDialog):
    """Ask for a preset name."""

    def __init__(self, title, prompt, value="", action="Save", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        lay.addWidget(label(title, "title"))
        lay.addWidget(label(prompt, "muted", wrap=True))
        self.edit = QLineEdit(value)
        self.edit.setPlaceholderText("e.g. Chill evening")
        self.edit.selectAll()
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Cancel", tip="Cancel")
        cancel.clicked.connect(self.reject)
        ok = button(action, variant="primary", tip=action)
        ok.clicked.connect(self._ok)
        ok.setDefault(True)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        self.edit.returnPressed.connect(self._ok)

    def _ok(self):
        if self.edit.text().strip():
            self.accept()

    def value(self):
        return self.edit.text().strip()


class ExportDialog(QDialog):
    """Save a start/stop toggle script for a keybind."""

    def __init__(self, title, path, text, toast, parent=None):
        super().__init__(parent)
        self.toast = toast
        self.text = text
        self.setWindowTitle("Export toggle script")
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        lay.addWidget(label("Export toggle script", "title"))
        lay.addWidget(label(f"A small shell script that turns “{title}” on, and off again "
                            "the next time it runs. Bind it to a key in your compositor.",
                            "muted", wrap=True))
        row = QHBoxLayout()
        self.path = QLineEdit(path)
        set_tip(self.path, "Save location", "Where the script is written. ~/.local/bin is on "
                "most PATHs.")
        row.addWidget(self.path, 1)
        browse = button("Browse…", tip="Choose where to save the script")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        lay.addLayout(row)
        preview = QPlainTextEdit(text)
        preview.setReadOnly(True)
        lay.addWidget(preview, 1)
        lay.addWidget(label("Hyprland keybind (add to hyprland.conf):", "small"))
        self.bind_row = QVBoxLayout()
        lay.addLayout(self.bind_row)
        self._bind()
        self.path.textChanged.connect(self._bind)
        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = button("Cancel", tip="Close without saving")
        cancel.clicked.connect(self.reject)
        save = button("Save script", icon="download", variant="primary",
                      tip="Save script", tip_body="Write the script and make it executable.")
        save.clicked.connect(self._save)
        foot.addWidget(cancel)
        foot.addWidget(save)
        lay.addLayout(foot)

    def _bind(self):
        while self.bind_row.count():
            w = self.bind_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        line = f"bind = SUPER, K, exec, {os.path.expanduser(self.path.text())}"
        self.bind_row.addWidget(code_row(line, lambda: self.toast("Copied to clipboard.", "success")))

    def _browse(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save toggle script", self.path.text(),
                                           "Shell scripts (*.sh)")
        if p:
            self.path.setText(p)

    def _save(self):
        from gui.background import write_script
        path = os.path.expanduser(self.path.text().strip())
        try:
            write_script(path, self.text)
        except OSError as e:
            self.toast(f"Couldn't save the script: {e}", "danger")
            return
        self.toast(f"Saved {path}", "success")
        self.accept()
