"""Adjustments for the selected effect, built from its param schema: sliders,
switches, segmented choices, color pickers and device selects, grouped into
cards. Emits the full value dict on every change so the preview updates live."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from color import COLORFUL_PALETTE
from gui import sources, theme
from gui.widgets.controls import (Card, ColorSwatch, Segmented, Slider, Switch, button,
                                  label)
from gui.widgets.tooltip import set_tip

GROUPS = (
    ("Appearance", "palette"),
    ("Motion", "wave"),
    ("Audio", "music"),
    ("Typing", "keyboard"),
    ("Capture", "monitor"),
    ("Advanced", "sliders"),
)

PALETTE_HEX = ["%02x%02x%02x" % c for c in COLORFUL_PALETTE]
EXTRA_HEX = ["22c55e", "ec4899", "f97316", "ffffff"]  # offered when adding a color
MIN_COLORS, MAX_COLORS = 2, 6


def _fmt(prm, v):
    if v is None:
        return ""
    if prm.kind == "int":
        return str(int(v))
    d = prm.decimals if prm.decimals is not None else 2
    return f"{v:.{d}f}"


class ParamPanel(QWidget):
    changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = None
        self.values = {}
        self._cards = []
        self._cols = 0
        self._adv_open = False
        self._labels = {}
        # independent columns (a grid would force cards side by side to share row heights)
        self.columns = QHBoxLayout(self)
        self.columns.setContentsMargins(0, 0, 0, 0)
        self.columns.setSpacing(14)
        self._colboxes = []
        for _ in range(2):
            box = QVBoxLayout()
            box.setSpacing(14)
            box.setAlignment(Qt.AlignTop)
            self.columns.addLayout(box, 1)
            self._colboxes.append(box)

    # -- public -------------------------------------------------------------
    def set_mode(self, mode, values):
        self.mode = mode
        self.values = dict(values)
        self._rebuild()

    def set_values(self, values):
        self.values = dict(values)
        self._rebuild()

    # -- building -------------------------------------------------------------
    def _deps(self):
        return {d for p in self.mode.spec.params for d in p.show_if}

    def _rebuild(self):
        for c in self._cards:
            if c.collapsible:
                self._adv_open = c.body.isVisible()
            c.setParent(None)
            c.deleteLater()
        self._cards = []
        self._labels = {}
        params = self.mode.user_params(self.values)
        if not params:
            card = Card()
            row = QHBoxLayout()
            row.addWidget(label("This effect has no adjustable settings. It looks the same "
                                "every time.", "muted", wrap=True))
            card.body_layout.addLayout(row)
            self._cards.append(card)
        for gname, gicon in GROUPS:
            group = [p for p in params if p.group == gname]
            if not group:
                continue
            adv = gname == "Advanced"
            card = Card(gname, gicon, collapsible=adv, collapsed=adv and not self._adv_open)
            for prm in group:
                card.body_layout.addWidget(self._row(prm))
            self._cards.append(card)
        self._cols = 0
        self._place()

    def _place(self):
        cols = 2 if self.width() >= 760 and len(self._cards) > 1 else 1
        if cols == self._cols:
            return
        self._cols = cols
        for box in self._colboxes:
            for c in self._cards:
                box.removeWidget(c)
        heights = [0.0] * cols
        for c in self._cards:
            col = heights.index(min(heights))
            self._colboxes[col].addWidget(c)
            heights[col] += c.body_layout.count() + 1.5
        self.columns.setStretch(1, 1 if cols == 2 else 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()

    def _hint(self, prm):
        if prm.flags:
            return f"Command line: {prm.flags[0]}"
        return None

    def _row(self, prm):
        w = QWidget()
        v = self.values.get(prm.name)
        modified = v != prm.default
        set_tip(w, prm.label, prm.tooltip, self._hint(prm))
        if prm.kind in ("float", "int"):
            return self._slider_row(w, prm, v, modified)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(self._label(prm, modified))
        head.addStretch(1)
        lay.addLayout(head)
        if prm.kind == "bool":
            sw = Switch()
            sw.setChecked(bool(v))
            set_tip(sw, prm.label, prm.tooltip, self._hint(prm))
            sw.toggled.connect(lambda on, n=prm.name: self._set(n, on))
            head.addWidget(sw)
        elif prm.kind == "color":
            sw = ColorSwatch(v or prm.default)
            set_tip(sw, prm.label, prm.tooltip, self._hint(prm))
            sw.colorChanged.connect(lambda hx, n=prm.name: self._set(n, hx))
            head.addWidget(sw)
        elif prm.kind == "colors":
            head.addLayout(self._colors(prm, v))
        elif prm.kind == "choice":
            items = list(zip(prm.choices, prm.labels or [str(c) for c in prm.choices]))
            if len(items) <= 4:
                seg = Segmented(items, v)
                set_tip(seg, prm.label, prm.tooltip, self._hint(prm))
                seg.valueChanged.connect(lambda val, n=prm.name: self._set(n, val))
                lay.addWidget(seg)
            else:
                lay.addWidget(self._combo(prm, items, v))
        elif prm.kind == "text":
            items = [(None, prm.auto_label)]
            if prm.source:
                items += sources.choices(prm.source)
            if v is not None and v not in [i[0] for i in items]:
                items.append((v, v))
            lay.addWidget(self._combo(prm, items, v))
        return w

    def _label_text(self, prm, modified):
        dot = (f"&nbsp;&nbsp;<span style='color:{theme.tokens()['accent']}'>●</span>"
               if modified else "")
        return prm.label + dot

    def _label(self, prm, modified):
        lbl = label(self._label_text(prm, modified))
        lbl.setTextFormat(Qt.RichText)
        lbl.setStyleSheet("font-weight: 500;")
        set_tip(lbl, prm.label, prm.tooltip + (" The dot means it differs from the default."
                                                if modified else ""), self._hint(prm))
        self._labels[prm.name] = (lbl, prm)
        return lbl

    def _combo(self, prm, items, v):
        cb = QComboBox()
        cb.setCursor(Qt.PointingHandCursor)
        for val, text in items:
            cb.addItem(text, val)
        idx = next((i for i, (val, _t) in enumerate(items) if val == v), 0)
        cb.setCurrentIndex(idx)
        set_tip(cb, prm.label, prm.tooltip, self._hint(prm))
        cb.currentIndexChanged.connect(lambda i, n=prm.name, c=cb: self._set(n, c.itemData(i)))
        return cb

    def _slider_row(self, w, prm, v, modified):
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(self._label(prm, modified))
        head.addStretch(1)
        edit = QLineEdit(_fmt(prm, v))
        edit.setProperty("role", "value")
        edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        edit.setFixedWidth(64)
        edit.setValidator(QDoubleValidator(prm.min, prm.max, prm.decimals or 0))
        set_tip(edit, prm.label, "Type an exact value and press Enter.", self._hint(prm))
        head.addWidget(edit)
        if prm.unit:
            head.addWidget(label(prm.unit, "small"))
        lay.addLayout(head)
        step = prm.step or (1 if prm.kind == "int" else (prm.max - prm.min) / 100)
        sl = Slider(prm.min, prm.max, step, v if v is not None else prm.min)
        set_tip(sl, prm.label, prm.tooltip + " Double-click to reset.", self._hint(prm))
        lay.addWidget(sl)

        def from_slider(val, n=prm.name):
            val = int(round(val)) if prm.kind == "int" else val
            edit.setText(_fmt(prm, val))
            self._set(n, val)

        def from_edit(n=prm.name):
            try:
                val = float(edit.text())
            except ValueError:
                edit.setText(_fmt(prm, self.values.get(n)))
                return
            val = max(prm.min, min(prm.max, val))
            val = int(round(val)) if prm.kind == "int" else val
            sl.setValue(val)
            edit.setText(_fmt(prm, val))
            self._set(n, val)

        def reset(n=prm.name):
            sl.setValue(prm.default)
            edit.setText(_fmt(prm, prm.default))
            self._set(n, prm.default)

        sl.valueChanged.connect(from_slider)
        sl.resetRequested.connect(reset)
        edit.editingFinished.connect(from_edit)
        return w

    def _colors(self, prm, v):
        """Swatch row for a color list. With count_from (flux) the count follows
        another param; otherwise (gradient palettes) colors can be added and removed."""
        row = QHBoxLayout()
        row.setSpacing(6)
        if prm.count_from:
            n = int(self.values.get(prm.count_from, 3))
            cur = ((v.split(",") if v else []) + PALETTE_HEX)[:n]
        else:
            cur = v.split(",") if v else list(PALETTE_HEX)
        for i, hx in enumerate(cur):
            sw = ColorSwatch(hx, compact=True)
            set_tip(sw, f"{prm.label}: color {i + 1}", prm.tooltip, self._hint(prm))

            def picked(new, i=i, cur=cur, name=prm.name):
                cur[i] = new
                self._set(name, ",".join(cur))
            sw.colorChanged.connect(picked)
            row.addWidget(sw)
        if not prm.count_from:
            if len(cur) > MIN_COLORS:
                rm = button(icon="minus", variant="ghost", size="icon", tip="Remove a color",
                            tip_body="Drop the last color from the gradient.")
                rm.setFixedSize(30, 30)
                rm.clicked.connect(lambda _=False, cur=cur, name=prm.name: self._set(
                    name, ",".join(cur[:-1]), rebuild=True))
                row.addWidget(rm)
            if len(cur) < MAX_COLORS:
                add = button(icon="plus", variant="ghost", size="icon", tip="Add a color",
                             tip_body="Add another color to the gradient. Click it to pick "
                                      "the shade.")
                add.setFixedSize(30, 30)
                nxt = next((c for c in PALETTE_HEX + EXTRA_HEX if c not in cur), "ffffff")
                add.clicked.connect(lambda _=False, cur=cur, name=prm.name, c=nxt: self._set(
                    name, ",".join(cur + [c]), rebuild=True))
                row.addWidget(add)
        if v:
            rb = button(icon="reset", variant="ghost", size="icon",
                        tip="Use the default colors", tip_body="Go back to the built-in palette.")
            rb.setFixedSize(30, 30)
            rb.clicked.connect(lambda _=False, name=prm.name: self._set(name, None, rebuild=True))
            row.addWidget(rb)
        return row

    # -- changes --------------------------------------------------------------
    def _set(self, name, value, rebuild=False):
        if self.values.get(name) == value and not rebuild:
            return
        self.values[name] = value
        if name == "colors":  # flux: the swatch row follows the color count
            if self.values.get("hex"):
                parts = self.values["hex"].split(",")
                self.values["hex"] = ",".join((parts + PALETTE_HEX)[:int(value)])
            rebuild = True
        self.changed.emit(dict(self.values))
        if rebuild or name in self._deps():
            self._rebuild()
        elif name in self._labels:
            lbl, prm = self._labels[name]
            lbl.setText(self._label_text(prm, value != prm.default))
