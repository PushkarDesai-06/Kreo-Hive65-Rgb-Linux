"""Left sidebar: brand, search, the grouped effect list and saved presets."""
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import (QAbstractButton, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QScrollArea, QVBoxLayout, QWidget)

from gui import catalog, icons, theme
from gui.widgets.controls import button, icon_label, label, qc
from gui.widgets.tooltip import set_tip


class NavItem(QAbstractButton):
    """One sidebar row: icon, label, and a dot when it is what the keyboard is
    showing right now (live or in the background)."""

    def __init__(self, key, text, icon, parent=None):
        super().__init__(parent)
        self.key, self._text, self._icon = key, text, icon
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(34)
        self.active_dot = False
        self._kbd_focus = False

    def focusInEvent(self, e):
        # ring only for keyboard navigation, not after clicks or programmatic focus
        self._kbd_focus = e.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._kbd_focus = False
        super().focusOutEvent(e)

    def sizeHint(self):
        return QSize(200, 34)

    def set_text(self, text):
        self._text = text
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        sel = self.isChecked()
        if sel:
            p.setPen(Qt.NoPen)
            p.setBrush(qc("surface3"))
            p.drawRoundedRect(r, 8, 8)
            p.setBrush(qc("accent"))
            p.drawRoundedRect(QRectF(r.left(), r.top() + 8, 3, r.height() - 16), 1.5, 1.5)
        elif self.underMouse():
            p.setPen(Qt.NoPen)
            p.setBrush(qc("surface2"))
            p.drawRoundedRect(r, 8, 8)
        if self.hasFocus() and self._kbd_focus and not sel:
            p.setPen(qc("ring"))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        t = theme.tokens()
        pm = icons.pixmap(self._icon, t["fg"] if sel else t["muted"], 16)
        p.drawPixmap(12, int(r.center().y() - 8), pm)
        f = self.font()
        f.setPixelSize(13)
        f.setWeight(f.Weight.DemiBold if sel else f.Weight.Medium)
        p.setFont(f)
        p.setPen(qc("fg") if sel else qc("muted"))
        right = 30 if self.active_dot else 10
        text = QFontMetrics(f).elidedText(self._text, Qt.ElideRight, int(r.width() - 38 - right))
        p.drawText(QRectF(38, r.top(), r.width() - 38 - right, r.height()), Qt.AlignVCenter, text)
        if self.active_dot:
            c = r.center()
            p.setPen(Qt.NoPen)
            p.setBrush(qc("success", 0.25))
            p.drawEllipse(QRectF(r.right() - 22, c.y() - 6, 12, 12))
            p.setBrush(qc("success"))
            p.drawEllipse(QRectF(r.right() - 19, c.y() - 3, 6, 6))

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()


class Sidebar(QWidget):
    modeSelected = Signal(str)
    presetSelected = Signal(str)
    presetAction = Signal(str, str)   # action, preset id
    settingsRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedWidth(256)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 14, 12, 12)
        outer.setSpacing(10)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        self.logo = QLabel()
        self.logo.setFixedSize(30, 30)
        brand.addWidget(self.logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label("Keyboard Studio", "brand"))
        col.addWidget(label("RGB lighting", "small"))
        brand.addLayout(col)
        brand.addStretch(1)
        outer.addLayout(brand)

        sw = QWidget()
        sl = QHBoxLayout(sw)
        sl.setContentsMargins(0, 4, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search effects")
        self.search.setProperty("role", "search")
        self.search.setClearButtonEnabled(True)
        set_tip(self.search, "Search effects", "Filter the list by name or description.")
        self.search.textChanged.connect(self._filter)
        sl.addWidget(self.search)
        self.search_icon = icon_label("search", "subtle", 15)
        self.search_icon.setParent(self.search)
        self.search_icon.move(10, 9)
        outer.addWidget(sw)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("SidebarList")
        self.list = QVBoxLayout(body)
        self.list.setContentsMargins(0, 0, 4, 0)
        self.list.setSpacing(1)
        self.items = {}
        self.headers = {}
        for gid, gname in catalog.GROUPS:
            h = label(gname.upper(), "section")
            self.headers[gid] = h
            self.list.addWidget(h)
            for m in catalog.MODES:
                if m.group != gid:
                    continue
                it = NavItem(m.id, m.label, m.icon)
                set_tip(it, m.label, m.description)
                it.clicked.connect(lambda _=False, mid=m.id: self.modeSelected.emit(mid))
                self.items[m.id] = it
                self.list.addWidget(it)
        self.preset_header = label("SAVED PRESETS", "section")
        self.list.addWidget(self.preset_header)
        self.preset_box = QVBoxLayout()
        self.preset_box.setSpacing(1)
        self.list.addLayout(self.preset_box)
        self.preset_empty = label("Save your favorite settings with “Save preset”.", "small", wrap=True)
        self.preset_empty.setContentsMargins(10, 0, 10, 0)
        self.list.addWidget(self.preset_empty)
        self.preset_items = {}
        self.list.addStretch(1)
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll, 1)

        self.settings_btn = button("Settings", icon="sliders", variant="ghost",
                                   tip="Settings", tip_body="Theme, startup and background behavior.")
        self.settings_btn.setStyleSheet("text-align: left; padding-left: 10px;")
        self.settings_btn.clicked.connect(self.settingsRequested.emit)
        outer.addWidget(self.settings_btn)
        self._render_logo()
        theme.ThemeManager.get().changed.connect(self._render_logo)

    def _render_logo(self):
        from PySide6.QtGui import QPixmap
        t = theme.tokens()
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(30 * dpr), int(30 * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(qc("accent"))
        p.drawRoundedRect(QRectF(0, 0, 30, 30), 8, 8)
        p.drawPixmap(7, 7, icons.pixmap("keyboard", t["accent_fg"], 16))
        p.end()
        self.logo.setPixmap(pm)

    # -- state ---------------------------------------------------------------
    def select(self, key):
        for k, it in {**self.items, **self.preset_items}.items():
            it.setChecked(k == key)

    def mark_active(self, keys):
        for k, it in {**self.items, **self.preset_items}.items():
            on = k in keys
            if it.active_dot != on:
                it.active_dot = on
                it.update()

    def set_presets(self, presets):
        for it in self.preset_items.values():
            it.deleteLater()
        self.preset_items = {}
        for pr in presets:
            mode = catalog.BY_ID.get(pr["mode"])
            if mode is None:
                continue
            key = "preset:" + pr["id"]
            it = NavItem(key, pr["name"], "star")
            set_tip(it, pr["name"], f"Saved preset of {mode.label}. Right-click for more options.")
            it.clicked.connect(lambda _=False, pid=pr["id"]: self.presetSelected.emit(pid))
            it.setContextMenuPolicy(Qt.CustomContextMenu)
            it.customContextMenuRequested.connect(
                lambda pos, w=it, pid=pr["id"]: self._preset_menu(w, pid, pos))
            self.preset_items[key] = it
            self.preset_box.addWidget(it)
        self.preset_empty.setVisible(not self.preset_items)
        self._filter(self.search.text())

    def _preset_menu(self, w, pid, pos):
        t = theme.tokens()
        m = QMenu(self)
        for action, text, ic in (("apply", "Apply", "play"), ("background", "Run in background", "rocket"),
                                 ("export", "Export toggle script…", "download"),
                                 (None, None, None),
                                 ("rename", "Rename…", "pencil"), ("duplicate", "Duplicate", "copy"),
                                 (None, None, None), ("delete", "Delete", "trash")):
            if action is None:
                m.addSeparator()
                continue
            a = m.addAction(icons.icon(ic, t["danger"] if action == "delete" else t["fg"]), text)
            a.triggered.connect(lambda _=False, act=action: self.presetAction.emit(act, pid))
        m.exec(w.mapToGlobal(pos))

    def _filter(self, text):
        q = text.strip().lower()
        for gid, _ in catalog.GROUPS:
            any_vis = False
            for m in catalog.MODES:
                if m.group != gid:
                    continue
                vis = not q or q in m.label.lower() or q in m.description.lower()
                self.items[m.id].setVisible(vis)
                any_vis |= vis
            self.headers[gid].setVisible(any_vis)
        pvis = False
        for it in self.preset_items.values():
            vis = not q or q in it._text.lower()
            it.setVisible(vis)
            pvis |= vis
        self.preset_header.setVisible(pvis or not q)
        self.preset_empty.setVisible(not self.preset_items and not q)

    def keyPressEvent(self, e):
        keys = [k for k, it in {**self.items, **self.preset_items}.items() if it.isVisible()]
        cur = next((k for k in keys if ({**self.items, **self.preset_items}[k]).isChecked()), None)
        if e.key() in (Qt.Key_Down, Qt.Key_Up) and keys:
            i = keys.index(cur) if cur in keys else -1
            i = min(len(keys) - 1, i + 1) if e.key() == Qt.Key_Down else max(0, i - 1)
            k = keys[i]
            if k.startswith("preset:"):
                self.presetSelected.emit(k[7:])
            else:
                self.modeSelected.emit(k)
            ({**self.items, **self.preset_items}[k]).setFocus()
        else:
            super().keyPressEvent(e)
