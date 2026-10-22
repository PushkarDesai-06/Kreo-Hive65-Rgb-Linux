"""Main window: sidebar of modes on the left, the live keyboard preview in the
center and the selected effect's adjustments below it. The header holds the
keyboard model, connection status, the live-on-keyboard switch and the
background controls."""
import os

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
                               QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget)

from device import PROFILES
from gui import catalog, hardware, icons, permissions, theme
from gui.widgets.controls import (Badge, Banner, Card, Switch, ToastHost, button, label,
                                  refresh_icons)
from gui.widgets.dialogs import (INPUT_CMD, ExportDialog, NameDialog, SettingsDialog,
                                 copy_text)
from gui.widgets.keyboard_view import KeyboardView
from gui.widgets.param_panel import ParamPanel
from gui.widgets.sidebar import Sidebar
from gui.widgets.tooltip import set_tip

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ModeIcon(QLabel):
    def __init__(self):
        super().__init__()
        self.setFixedSize(40, 40)
        self.setAlignment(Qt.AlignCenter)
        self.name = "keyboard"

    def set_icon(self, name):
        self.name = name
        t = theme.tokens()
        self.setStyleSheet(f"background: {t['surface2']}; border: 1px solid {t['border']};"
                           "border-radius: 10px;")
        self.setPixmap(icons.pixmap(name, t["fg"], 20))


class MainWindow(QMainWindow):
    def __init__(self, studio, has_tray=False):
        super().__init__()
        self.studio = studio
        self.settings = studio.settings
        self.has_tray = has_tray
        self.quitting = False
        self.capture_keys = False
        self.banners = {}
        self._last_seq = -1
        self.setWindowTitle("Keyboard Studio")
        self.setMinimumSize(1060, 700)
        self.resize(1340, 880)

        central = QWidget()
        central.setObjectName("Central")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.sidebar = Sidebar()
        root.addWidget(self.sidebar)
        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.addWidget(self._build_header())
        main.addWidget(self._build_content(), 1)
        root.addLayout(main, 1)
        self.setCentralWidget(central)
        self.toasts = ToastHost(central)

        self._wire()
        self.keyboard.set_profile(studio.profile)
        self._refresh_profiles()
        self._on_device(studio.device_state())
        self._on_owner(studio.runner.owner)
        self.sidebar.set_presets(studio.presets())

        self.frame_timer = QTimer(self)
        self.frame_timer.setInterval(16)
        self.frame_timer.timeout.connect(self._poll_frame)
        self.frame_timer.start()
        QGuiApplication.instance().installEventFilter(self)
        geo = self.settings["window"]
        if geo:
            from PySide6.QtCore import QByteArray
            self.restoreGeometry(QByteArray.fromBase64(geo.encode()))

    # -- layout ---------------------------------------------------------------
    def _build_header(self):
        h = QWidget()
        h.setObjectName("Header")
        h.setAttribute(Qt.WA_StyledBackground)
        h.setFixedHeight(62)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(24, 0, 20, 0)
        lay.setSpacing(10)

        kb = QLabel()
        kb.setPixmap(icons.pixmap("keyboard", theme.tokens()["muted"], 18))
        self._kb_icon = kb
        lay.addWidget(kb)
        self.profile_box = QComboBox()
        self.profile_box.setMinimumWidth(250)
        self.profile_box.setCursor(Qt.PointingHandCursor)
        set_tip(self.profile_box, "Keyboard model",
                "Which keyboard layout to preview and drive. Boards that share a USB id "
                "can't be told apart automatically, so pick yours once and it is remembered.")
        lay.addWidget(self.profile_box)
        self.conn = Badge("Not connected")
        lay.addWidget(self.conn)
        lay.addStretch(1)

        self.owner_badge = Badge("", "success")
        lay.addWidget(self.owner_badge)
        self.stop_btn = button("Stop", icon="stop", variant="danger", size="sm",
                               tip="Stop lighting",
                               tip_body="Stop the effect that is running in the background.")
        self.stop_btn.clicked.connect(self.studio.stop_background)
        lay.addWidget(self.stop_btn)
        lay.addSpacing(8)

        live = QWidget()
        ll = QHBoxLayout(live)
        ll.setContentsMargins(10, 0, 10, 0)
        ll.setSpacing(9)
        self.live_switch = Switch()
        ll.addWidget(self.live_switch)
        self.live_label = label("Live on keyboard")
        self.live_label.setStyleSheet("font-weight: 500;")
        ll.addWidget(self.live_label)
        set_tip(live, "Live on keyboard",
                "Mirror the preview on your physical keyboard in real time while you "
                "experiment. Turn it off to just preview on screen.")
        set_tip(self.live_switch, "Live on keyboard",
                "Mirror the preview on your physical keyboard in real time while you "
                "experiment. Turn it off to just preview on screen.")
        self.live_label.mousePressEvent = lambda e: self.live_switch.toggle()
        lay.addWidget(live)

        self.run_btn = button("Run in background", icon="play", variant="primary",
                              tip="Run in background",
                              tip_body="Keep this effect on your keyboard after you close the "
                                       "app. It runs as a small background process with no window.")
        lay.addWidget(self.run_btn)
        self.more_btn = button(icon="more", size="icon", tip="More actions",
                               tip_body="Copy the command, export a toggle script, settings.")
        self.more_btn.clicked.connect(self._more_menu)
        lay.addWidget(self.more_btn)
        return h

    def _build_content(self):
        w = QWidget()
        w.setObjectName("Content")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 22, 28, 0)
        lay.setSpacing(14)

        title_row = QHBoxLayout()
        title_row.setSpacing(14)
        self.mode_icon = ModeIcon()
        title_row.addWidget(self.mode_icon, 0, Qt.AlignTop)
        tcol = QVBoxLayout()
        tcol.setSpacing(3)
        crumb = QHBoxLayout()
        crumb.setSpacing(6)
        self.group_lbl = label("", "small")
        crumb.addWidget(self.group_lbl)
        self.preset_lbl = label("", "small")
        crumb.addWidget(self.preset_lbl)
        crumb.addStretch(1)
        tcol.addLayout(crumb)
        self.title = label("", "title")
        tcol.addWidget(self.title)
        self.desc = label("", "muted", wrap=True)
        tcol.addWidget(self.desc)
        title_row.addLayout(tcol, 1)
        self.reset_btn = button("Reset", icon="reset", tip="Reset to defaults",
                                tip_body="Put every setting of this effect back to its default.")
        self.save_btn = button("Save preset", icon="bookmark", tip="Save as preset",
                               tip_body="Save this effect with its current settings as a named "
                                        "favorite in the sidebar.")
        self.copy_btn = button(icon="terminal", size="icon", tip="Copy command",
                               tip_body="Copy the terminal command that runs exactly this effect.")
        for b in (self.reset_btn, self.save_btn, self.copy_btn):
            title_row.addWidget(b, 0, Qt.AlignTop)
        lay.addLayout(title_row)

        self.banner_box = QVBoxLayout()
        self.banner_box.setSpacing(8)
        lay.addLayout(self.banner_box)

        kcard = Card()
        kcard.outer.setContentsMargins(10, 10, 10, 10)
        kcard.outer.setSpacing(4)
        self.keyboard = KeyboardView()
        self.keyboard.setMinimumHeight(230)
        kcard.body_layout.addWidget(self.keyboard)
        cap = QHBoxLayout()
        cap.setContentsMargins(8, 0, 8, 2)
        self.caption = label("", "small")
        cap.addWidget(self.caption)
        cap.addStretch(1)
        self.live_caption = label("", "small")
        cap.addWidget(self.live_caption)
        kcard.body_layout.addLayout(cap)
        kcard.setMaximumHeight(400)
        lay.addWidget(kcard, 5)

        adj = QHBoxLayout()
        adj.setContentsMargins(0, 6, 0, 0)
        adj.addWidget(label("Adjustments", "h2"))
        adj.addSpacing(8)
        adj.addWidget(label("Changes apply instantly.", "small"))
        adj.addStretch(1)
        lay.addLayout(adj)

        self.panel = ParamPanel()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 4, 24)
        hl.addWidget(self.panel)
        hl.addStretch(1)
        scroll.setWidget(holder)
        lay.addWidget(scroll, 4)
        return w

    # -- wiring ----------------------------------------------------------------
    def _wire(self):
        s = self.studio
        self.sidebar.modeSelected.connect(s.select_mode)
        self.sidebar.presetSelected.connect(s.apply_preset)
        self.sidebar.presetAction.connect(self._preset_action)
        self.sidebar.settingsRequested.connect(self.open_settings)
        self.panel.changed.connect(s.set_values)
        self.keyboard.keyPressed.connect(s.inject_key)
        self.live_switch.toggled.connect(self._live_toggled)
        self.run_btn.clicked.connect(lambda: s.run_in_background())
        self.reset_btn.clicked.connect(s.reset_values)
        self.save_btn.clicked.connect(self._save_preset)
        self.copy_btn.clicked.connect(self._copy_command)
        self.profile_box.activated.connect(
            lambda i: s.set_profile(self.profile_box.itemData(i)))

        s.modeChanged.connect(self._on_mode)
        s.valuesChanged.connect(self._on_values)
        s.profileChanged.connect(self._on_profile)
        s.deviceChanged.connect(self._on_device)
        s.sendChanged.connect(self._on_send)
        s.ownerChanged.connect(self._on_owner)
        s.engineEvent.connect(self._on_engine)
        s.presetsChanged.connect(self.sidebar.set_presets)
        s.toast.connect(self.toast)
        s.showRequested.connect(self.bring_to_front)
        theme.ThemeManager.get().changed.connect(self._on_theme)

        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.live_switch.toggle)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=lambda: s.run_in_background())
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._save_preset)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.sidebar.search.setFocus)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self.open_settings)
        set_tip(self.run_btn, "Run in background (Ctrl+B)",
                "Keep this effect on your keyboard after you close the app. It runs as a "
                "small background process with no window.")

    def toast(self, text, kind="info"):
        self.toasts.show_toast(text, kind)

    # -- state updates -----------------------------------------------------------
    def _on_mode(self, mode, values, preset_id):
        group = dict(catalog.GROUPS)[mode.group]
        self.group_lbl.setText(group)
        if preset_id:
            p = self.settings.preset(preset_id)
            self.preset_lbl.setText(f"·  Preset: {p['name']}" if p else "")
        else:
            self.preset_lbl.setText("")
        self.title.setText(mode.label)
        self.desc.setText(mode.description)
        self.mode_icon.set_icon(mode.icon)
        self.panel.set_mode(mode, values)
        self.sidebar.select("preset:" + preset_id if preset_id else mode.id)
        for key in list(self.banners):
            if key in ("audio", "input", "error"):
                self._drop_banner(key)
        self.capture_keys = False
        self._update_caption()
        self._mark_active()

    def _on_values(self, values):
        if self.studio.active_preset:
            self.studio.active_preset = None
            self.preset_lbl.setText("")
            self.sidebar.select(self.studio.mode.id)

    def _refresh_profiles(self):
        box = self.profile_box
        box.blockSignals(True)
        box.clear()
        detected = self.studio.detected_profiles()
        for p in hardware.usable_profiles():
            name = p.name.split(" (")[0]
            if p.experimental:
                name += " (experimental)"
            if p.id in detected:
                name += "  ·  detected"
            box.addItem(name, p.id)
        box.setCurrentIndex(max(0, box.findData(self.studio.profile.id)))
        box.blockSignals(False)

    def _on_profile(self, profile):
        self._refresh_profiles()
        self.keyboard.set_profile(profile)
        self._update_caption()

    def _on_device(self, st):
        state = st["state"]
        kind = {"connected": "success", "permission": "warning", "mismatch": "warning",
                "reconnecting": "warning"}.get(state, "muted")
        label_ = st["label"]
        if state == "connected" and st.get("dev"):
            label_ = f"Connected · {os.path.basename(st['dev'])}"
        self.conn.set(label_, kind)
        tips = {
            "connected": ("Keyboard connected", "Ready to light up. Turn on “Live on keyboard” "
                          "or run an effect in the background."),
            "missing": ("Keyboard not connected", "Plug the keyboard in (wired mode). You can "
                        "still preview every effect on screen."),
            "permission": ("No permission", "The keyboard was found but the app can't write "
                           "to it. Install the udev rule (see the notice above)."),
            "mismatch": ("Different model connected", "The connected keyboard doesn't match "
                         "the model selected on the left. Pick it in the keyboard menu."),
            "reconnecting": ("Reconnecting", "The keyboard reset itself. Reconnecting…"),
        }
        set_tip(self.conn, *tips.get(state, ("Keyboard", "")))
        self._refresh_profiles()
        if state == "permission":
            cmd = permissions.sudo_command()
            self._banner("device", "warning", "The keyboard is locked",
                         "Your keyboard was found but this app isn't allowed to write to it. "
                         "Install keyboard access once (asks for your password).",
                         [("Install access", self._install_rule,
                           "Install the udev rule now. Your desktop asks for your password."),
                          ("Copy command", lambda: self._copy(cmd),
                           "Copy the command to run it in a terminal yourself.")])
        elif state == "mismatch":
            dev = self.studio.device
            target = dev["profiles"][0] if dev else None
            name = PROFILES[target].name.split(" (")[0] if target else "it"
            self._banner("device", "info", "A different keyboard is connected",
                         f"The connected keyboard looks like a {name}. Switch the model to "
                         "light it up.",
                         [("Switch model", lambda: self.studio.set_profile(target),
                           "Use the connected keyboard's layout.")] if target else [])
        else:
            self._drop_banner("device")
        self._update_caption()

    def _on_send(self, on):
        self.live_switch.blockSignals(True)
        self.live_switch.setChecked(on)
        self.live_switch.blockSignals(False)
        self._update_caption()
        self._mark_active()

    def _live_toggled(self, on):
        self.studio.set_send(on)

    def _on_owner(self, rec):
        studio = self.studio
        visible = rec is not None and rec.get("kind") in ("runner", "cli")
        if visible:
            where = "In background" if rec.get("kind") == "runner" else "From terminal"
            self.owner_badge.set(f"{where} · {studio.owner_label(rec) or 'effect'}", "success")
            set_tip(self.owner_badge, "Running now",
                    f"{studio.owner_label(rec)} is driving your keyboard (process "
                    f"{rec.get('pid')}). It keeps running after you close this app.")
        self.owner_badge.setVisible(visible)
        self.stop_btn.setVisible(visible)
        self._mark_active()

    def _mark_active(self):
        keys = set()
        if self.studio.send:
            keys.add(self.studio.mode.id)
            if self.studio.active_preset:
                keys.add("preset:" + self.studio.active_preset)
        rec = self.studio.runner.owner
        if rec and rec.get("kind") in ("runner", "cli"):
            lbl = self.studio.owner_label(rec)
            keys |= {m.id for m in catalog.MODES if m.label == lbl}
        self.sidebar.mark_active(keys)

    def _update_caption(self):
        p = self.studio.profile
        st = self.studio.device_state()["state"]
        hint = ("Click keys or type to try it" if "keys" in self.studio.mode.needs
                else "Hover a key to see its color")
        where = "Preview" if st == "connected" else "Preview only"
        self.caption.setText(f"{where}  ·  {p.name.split(' (')[0]}  ·  {hint}")
        if self.studio.send:
            self.live_caption.setText(
                f"<span style='color:{theme.tokens()['success']}'>●</span>&nbsp; Live on your keyboard")
        else:
            self.live_caption.setText("")

    def _on_engine(self, ev):
        t = ev["type"]
        if t == "warning" and ev["kind"] == "audio":
            self._banner("audio", "warning", "Can't hear any audio",
                         f"{ev['msg']} The idle effect is shown instead.")
        elif t == "warning" and ev["kind"] == "input":
            self.capture_keys = True
            self._banner("input", "info", "Typing effects respond inside this window",
                         "Keyboard Studio can't see key presses in other apps yet, so type "
                         "here or click keys on the preview. To react everywhere, join the "
                         "input group and log back in.",
                         [("Copy command", lambda: self._copy(INPUT_CMD),
                           "Copy the command that adds you to the input group.")])
        elif t == "error":
            title = {"deps": "Something needed is missing", "screen": "Screen capture failed",
                     "audio": "Audio capture failed", "input": "Can't read the keyboard",
                     }.get(ev["kind"], "This effect hit a problem")
            self._banner("error", "danger", title, ev["msg"])
        elif t == "started":
            self.capture_keys = bool(ev.get("virtual_keys"))
            if not self.capture_keys:
                self._drop_banner("input")

    def _banner(self, key, kind, title, text, actions=()):
        self._drop_banner(key)
        b = Banner(kind, title, text, actions)
        b.dismissed.connect(lambda k=key: self.banners.pop(k, None))
        self.banners[key] = b
        self.banner_box.addWidget(b)

    def _drop_banner(self, key):
        b = self.banners.pop(key, None)
        if b is not None:
            b.setParent(None)
            b.deleteLater()

    def _on_theme(self):
        refresh_icons(self)
        self._kb_icon.setPixmap(icons.pixmap("keyboard", theme.tokens()["muted"], 18))
        self.mode_icon.set_icon(self.mode_icon.name)
        self.panel.set_values(self.studio.values)
        self._update_caption()
        self.update()

    def _poll_frame(self):
        seq, prof, colors, _bg = self.studio.engine.latest
        if seq != self._last_seq and prof is self.studio.profile:
            self._last_seq = seq
            self.keyboard.set_frame(colors)

    # -- actions ------------------------------------------------------------------
    def _copy(self, text, msg="Copied to clipboard."):
        copy_text(text)
        self.toast(msg, "success")

    def _copy_command(self):
        self._copy(self.studio.command(), "Command copied. Paste it in a terminal to run "
                   "this effect.")

    def _save_preset(self):
        dlg = NameDialog("Save preset", f"Give this {self.studio.mode.label} setup a name. "
                         "It appears under Saved presets in the sidebar.", parent=self)
        if dlg.exec():
            self.studio.save_preset(dlg.value())

    def _preset_action(self, action, pid):
        s = self.studio
        p, mode, values = s.preset_target(pid)
        if action == "apply":
            s.apply_preset(pid)
        elif action == "background":
            s.run_in_background(mode, values)
        elif action == "export":
            self.export_script(p["name"], mode, values)
        elif action == "rename":
            dlg = NameDialog("Rename preset", "Pick a new name.", p["name"], "Rename", self)
            if dlg.exec():
                s.rename_preset(pid, dlg.value())
        elif action == "duplicate":
            s.duplicate_preset(pid)
        elif action == "delete":
            s.delete_preset(pid)

    def _install_rule(self):
        if not hasattr(self, "_installer"):
            self._installer = permissions.RuleInstaller(self)
            self._installer.finished.connect(self._rule_done)
        self.toast("Waiting for your password…", "info")
        self._installer.start()

    def _rule_done(self, ok, msg):
        self.toast(msg, "success" if ok else "warning")
        if ok:
            self.studio.rescan()

    def export_script(self, title=None, mode=None, values=None):
        title = title or self.studio.mode.label
        path, text = self.studio.script(title, mode, values)
        ExportDialog(title, path, text, self.toast, self).exec()

    def _more_menu(self):
        t = theme.tokens()
        m = QMenu(self)
        m.addAction(icons.icon("terminal", t["fg"]), "Copy command", self._copy_command)
        m.addAction(icons.icon("download", t["fg"]), "Export toggle script…", self.export_script)
        m.addSeparator()
        m.addAction(icons.icon("sliders", t["fg"]), "Settings", self.open_settings)
        manual = os.path.join(ROOT, "manual.md")
        if os.path.exists(manual):
            m.addAction(icons.icon("info", t["fg"]), "Open the manual",
                        lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(manual)))
        m.exec(self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()))

    def open_settings(self):
        dlg = SettingsDialog(self.settings, ROOT, self.toast, self)
        dlg.themeChanged.connect(self._set_theme)
        dlg.exec()

    def _set_theme(self, preset, base, accent):
        self.settings["theme"] = {"preset": preset, "base": base, "accent": accent}
        theme.ThemeManager.get().apply(base, accent)

    def bring_to_front(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()
        self.studio.set_window_visible(True)

    # -- typing fallback -----------------------------------------------------------
    def eventFilter(self, obj, ev):
        et = ev.type()
        if self.capture_keys and et in (QEvent.KeyPress, QEvent.KeyRelease) and self.isActiveWindow():
            focus = QGuiApplication.focusObject()
            if not isinstance(focus, (QLineEdit, QPlainTextEdit, QComboBox)):
                import reactive
                name = reactive.EVDEV_TO_NAME.get(ev.nativeScanCode() - 8)
                if name is not None and obj is self.windowHandle():
                    if not ev.isAutoRepeat():
                        self.studio.inject_key(name, et == QEvent.KeyPress)
                    return True
                if name is not None:
                    return False
        return super().eventFilter(obj, ev)

    # -- window lifecycle ------------------------------------------------------------
    def showEvent(self, e):
        super().showEvent(e)
        self.studio.set_window_visible(True)
        item = self.sidebar.items.get(self.studio.mode.id)
        if item is not None and not self.sidebar.search.text():
            item.setFocus(Qt.OtherFocusReason)  # not the search box

    def hideEvent(self, e):
        super().hideEvent(e)
        self.studio.set_window_visible(False)

    def closeEvent(self, e):
        self.settings["window"] = bytes(self.saveGeometry().toBase64()).decode()
        if self.quitting:
            e.accept()
            return
        self.studio.handoff_on_close()
        if self.has_tray and self.settings["close_to_tray"]:
            e.ignore()
            self.hide()
            return
        e.accept()
        QGuiApplication.instance().quit()

    def sizeHint(self):
        return QSize(1340, 880)
