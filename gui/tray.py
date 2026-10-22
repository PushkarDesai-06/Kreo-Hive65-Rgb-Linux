"""System tray icon: open the window, start any effect in the background,
apply presets, stop the lighting and toggle launch-on-login."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from gui import autostart, catalog, icons, theme


def app_icon():
    t = theme.tokens()
    ic = QIcon()
    for size in (16, 22, 24, 32, 48, 64, 128):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.qcolor("accent"))
        p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.24, size * 0.24)
        inner = int(size * 0.62)
        p.drawPixmap(int((size - inner) / 2), int((size - inner) / 2),
                     icons.pixmap("keyboard", t["accent_fg"], inner).scaled(
                         inner, inner, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        p.end()
        ic.addPixmap(pm)
    return ic


class Tray(QSystemTrayIcon):
    def __init__(self, studio, window):
        super().__init__(app_icon())
        self.studio, self.window = studio, window
        self.setToolTip("Keyboard Studio")
        self.menu = QMenu()
        self.setContextMenu(self.menu)
        self.menu.aboutToShow.connect(self._build)
        self.activated.connect(self._activated)
        theme.ThemeManager.get().changed.connect(lambda: self.setIcon(app_icon()))
        self._build()

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.window.isVisible():
                self.window.hide()
            else:
                self.window.bring_to_front()

    def _build(self):
        s, m, t = self.studio, self.menu, theme.tokens()
        m.clear()
        m.addAction(icons.icon("keyboard", t["fg"]), "Open Keyboard Studio", self.window.bring_to_front)
        rec = s.runner.owner
        if s.send:
            status = f"Live preview: {s.mode.label}"
        elif rec and rec.get("kind") in ("runner", "cli"):
            status = f"Running: {s.owner_label(rec)}"
        else:
            status = "Keyboard lighting is off"
        st = m.addAction(status)
        st.setEnabled(False)
        m.addSeparator()
        fx = m.addMenu(icons.icon("play", t["fg"]), "Run effect in background")
        for gid, gname in catalog.GROUPS:
            sub = fx.addMenu(gname)
            for mode in catalog.MODES:
                if mode.group == gid:
                    sub.addAction(icons.icon(mode.icon, t["fg"]), mode.label,
                                  lambda md=mode: s.run_in_background(
                                      md, md.values(s.settings["params"].get(md.id))))
        presets = s.presets()
        pm = m.addMenu(icons.icon("star", t["fg"]), "Presets")
        pm.setEnabled(bool(presets))
        for p in presets:
            def run(pid=p["id"]):
                _p, mode, values = s.preset_target(pid)
                s.run_in_background(mode, values)
            pm.addAction(p["name"], run)
        stop = m.addAction(icons.icon("stop", t["fg"]), "Stop lighting", self._stop)
        stop.setEnabled(s.send or bool(rec and rec.get("kind") in ("runner", "cli")))
        m.addSeparator()
        login = m.addAction("Launch on login")
        login.setCheckable(True)
        login.setChecked(autostart.is_enabled())
        login.toggled.connect(self._login)
        m.addAction(icons.icon("x", t["fg"]), "Quit", self.quit)

    def _stop(self):
        if self.studio.send:
            self.studio.set_send(False)
        self.studio.stop_background()

    def _login(self, on):
        autostart.set_enabled(on)
        self.studio.settings["autostart"] = on

    def quit(self):
        self.studio.handoff_on_close()
        self.window.quitting = True
        QApplication.instance().quit()
