"""shadcn-style primitives painted with QPainter so they follow the theme
tokens exactly: Switch, Slider, Segmented, color swatches, badges, banners,
toasts and a few button helpers."""
from PySide6.QtCore import (QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt,
                            QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QColorDialog, QFrame, QGraphicsOpacityEffect,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from gui import icons, theme
from gui.widgets.tooltip import set_tip


def tok(name):
    return theme.tokens()[name]


def qc(name, alpha=None):
    return theme.qcolor(name, alpha)


# ------------------------------------------------------------------ buttons --
def button(text="", icon=None, variant=None, size=None, tip=None, tip_body=None):
    b = QPushButton(text)
    if variant:
        b.setProperty("variant", variant)
    if size:
        b.setProperty("size", size)
    b.setCursor(Qt.PointingHandCursor)
    if icon:
        b.setProperty("icon_name", icon)
        _refresh_icon(b)
        b.setIconSize(QSize(15, 15) if size != "sm" else QSize(14, 14))
    if tip:
        set_tip(b, tip, tip_body)
    return b


def _refresh_icon(b):
    name = b.property("icon_name")
    if not name:
        return
    color = tok("accent_fg") if b.property("variant") == "primary" else (
        tok("danger") if b.property("variant") == "danger" else tok("fg"))
    b.setIcon(icons.icon(name, color, 16))


def refresh_icons(root):
    """Re-tint every icon button under `root` after a theme change."""
    for b in root.findChildren(QPushButton):
        _refresh_icon(b)


def icon_label(name, color_token="muted", size=16):
    lbl = QLabel()
    lbl.setPixmap(icons.pixmap(name, tok(color_token), size))
    lbl.setFixedSize(size, size)
    return lbl


def label(text, role=None, wrap=False):
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    return lbl


def separator():
    f = QFrame()
    f.setProperty("role", "separator")
    return f


# ------------------------------------------------------------------- switch --
class Switch(QAbstractButton):
    """Pill toggle. Emits toggled(bool) like any checkable button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._pos = 0.0
        self._anim = QVariantAnimation(self, duration=140, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_pos)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(38, 22)

    def _set_pos(self, v):
        self._pos = v
        self.update()

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, on):
        super().setChecked(on)
        self._anim.stop()
        self._pos = 1.0 if on else 0.0
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, 38, 22).translated(0, (self.height() - 22) / 2)
        off, on = QColor(tok("surface3")), QColor(tok("accent"))
        k = self._pos
        track = QColor(
            int(off.red() + (on.red() - off.red()) * k),
            int(off.green() + (on.green() - off.green()) * k),
            int(off.blue() + (on.blue() - off.blue()) * k))
        if not self.isEnabled():
            track.setAlphaF(0.5)
        if self.hasFocus():
            p.setPen(QPen(qc("ring"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 13, 13)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, 11, 11)
        d = 16
        x = r.left() + 3 + (r.width() - d - 6) * k
        knob_off, knob_on = QColor(tok("fg")), QColor(tok("accent_fg"))
        knob = knob_on if k > 0.5 else knob_off
        p.setBrush(knob)
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


# ------------------------------------------------------------------- slider --
class Slider(QWidget):
    """Thin track with an accent range and a round thumb. Emits valueChanged
    continuously while dragging and resetRequested on double-click."""

    valueChanged = Signal(float)
    resetRequested = Signal()

    def __init__(self, minimum, maximum, step=None, value=None, parent=None):
        super().__init__(parent)
        self.lo, self.hi = float(minimum), float(maximum)
        self.step = step
        self._v = self.lo if value is None else float(value)
        self._hover = False
        self._drag = False
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setMinimumHeight(24)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def sizeHint(self):
        return QSize(200, 24)

    def value(self):
        return self._v

    def setValue(self, v, emit=False):
        v = self._snap(v)
        if v != self._v:
            self._v = v
            self.update()
            if emit:
                self.valueChanged.emit(v)

    def _snap(self, v):
        v = min(self.hi, max(self.lo, float(v)))
        if self.step:
            v = self.lo + round((v - self.lo) / self.step) * self.step
            v = round(min(self.hi, max(self.lo, v)), 6)
        return v

    def _track(self):
        return QRectF(9, self.height() / 2 - 3, self.width() - 18, 6)

    def _frac(self):
        return 0.0 if self.hi == self.lo else (self._v - self.lo) / (self.hi - self.lo)

    def _from_x(self, x):
        tr = self._track()
        f = min(1.0, max(0.0, (x - tr.left()) / tr.width()))
        self.setValue(self.lo + f * (self.hi - self.lo), emit=True)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = True
            self._from_x(e.position().x())

    def mouseMoveEvent(self, e):
        if self._drag:
            self._from_x(e.position().x())

    def mouseReleaseEvent(self, e):
        self._drag = False
        self.update()

    def mouseDoubleClickEvent(self, e):
        self.resetRequested.emit()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def wheelEvent(self, e):
        e.ignore()  # never hijack the panel's scrolling

    def keyPressEvent(self, e):
        step = self.step or (self.hi - self.lo) / 100.0
        k = e.key()
        if k in (Qt.Key_Right, Qt.Key_Up):
            self.setValue(self._v + step, emit=True)
        elif k in (Qt.Key_Left, Qt.Key_Down):
            self.setValue(self._v - step, emit=True)
        elif k == Qt.Key_PageUp:
            self.setValue(self._v + step * 10, emit=True)
        elif k == Qt.Key_PageDown:
            self.setValue(self._v - step * 10, emit=True)
        elif k == Qt.Key_Home:
            self.setValue(self.lo, emit=True)
        elif k == Qt.Key_End:
            self.setValue(self.hi, emit=True)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        tr = self._track()
        p.setPen(Qt.NoPen)
        p.setBrush(qc("surface3"))
        p.drawRoundedRect(tr, 3, 3)
        x = tr.left() + tr.width() * self._frac()
        fill = QRectF(tr.left(), tr.top(), x - tr.left(), tr.height())
        p.setBrush(qc("accent"))
        p.drawRoundedRect(fill, 3, 3)
        c = QPointF(x, tr.center().y())
        if self._hover or self._drag or self.hasFocus():
            p.setBrush(qc("accent", 0.22))
            p.drawEllipse(c, 12, 12)
        p.setBrush(qc("bg"))
        p.setPen(QPen(qc("accent"), 2))
        p.drawEllipse(c, 7.5, 7.5)


# ---------------------------------------------------------------- segmented --
class Segmented(QWidget):
    """Tabs-style single choice. items: [(value, label)]."""

    valueChanged = Signal(object)

    def __init__(self, items, value=None, parent=None):
        super().__init__(parent)
        self.items = list(items)
        self._v = value if value is not None else self.items[0][0]
        self._hover = -1
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        return QSize(sum(fm.horizontalAdvance(lbl) + 26 for _, lbl in self.items) + 8, 34)

    def minimumSizeHint(self):
        return self.sizeHint()

    def value(self):
        return self._v

    def setValue(self, v):
        self._v = v
        self.update()

    def _rects(self):
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        fm = QFontMetrics(self.font())
        widths = [fm.horizontalAdvance(lbl) + 26 for _, lbl in self.items]
        extra = max(0.0, r.width() - sum(widths)) / len(widths)
        x, out = r.left(), []
        for w in widths:
            out.append(QRectF(x, r.top(), w + extra, r.height()))
            x += w + extra
        return out

    def _index_at(self, pos):
        for i, rr in enumerate(self._rects()):
            if rr.contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e):
        i = self._index_at(e.position())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mousePressEvent(self, e):
        i = self._index_at(e.position())
        if i >= 0:
            self._select(i)

    def keyPressEvent(self, e):
        idx = [v for v, _ in self.items].index(self._v) if self._v in [v for v, _ in self.items] else 0
        if e.key() in (Qt.Key_Right, Qt.Key_Down):
            self._select(min(len(self.items) - 1, idx + 1))
        elif e.key() in (Qt.Key_Left, Qt.Key_Up):
            self._select(max(0, idx - 1))
        else:
            super().keyPressEvent(e)

    def _select(self, i):
        v = self.items[i][0]
        if v != self._v:
            self._v = v
            self.update()
            self.valueChanged.emit(v)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        outer = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(qc("ring") if self.hasFocus() else Qt.transparent, 1))
        p.setBrush(qc("surface2"))
        p.drawRoundedRect(outer, 8, 8)
        for i, (rr, (v, lbl)) in enumerate(zip(self._rects(), self.items)):
            sel = v == self._v
            if sel:
                p.setPen(QPen(qc("border"), 1))
                p.setBrush(qc("bg"))
                p.drawRoundedRect(rr, 6, 6)
            elif i == self._hover:
                p.setPen(Qt.NoPen)
                p.setBrush(qc("surface3"))
                p.drawRoundedRect(rr, 6, 6)
            p.setPen(qc("fg") if sel else qc("muted"))
            f = self.font()
            f.setWeight(f.Weight.DemiBold if sel else f.Weight.Medium)
            p.setFont(f)
            p.drawText(rr, Qt.AlignCenter, lbl)


# ------------------------------------------------------------------- colors --
PRESET_COLORS = (
    "ffffff", "ff4242", "f97316", "f0ec57", "84cc16", "22c55e", "10b981", "06b6d4",
    "009bde", "3b82f6", "6366f1", "7c3aed", "a855f7", "ec4899", "f43f5e", "eab308",
)


class ColorPopover(QFrame):
    """Popup with preset chips, a hex field and the full color dialog."""

    picked = Signal(str)

    def __init__(self, anchor, value):
        super().__init__(anchor.window(), Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.value = value
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, hx in enumerate(PRESET_COLORS):
            chip = ChipButton(hx, size=24)
            set_tip(chip, f"#{hx}")
            chip.clicked.connect(lambda _=False, h=hx: self._choose(h, close=True))
            grid.addWidget(chip, i // 8, i % 8)
        lay.addLayout(grid)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.hex = QLineEdit("#" + value)
        self.hex.setMaxLength(7)
        self.hex.setFixedWidth(104)
        self.hex.setFont(theme.mono_font(12))
        set_tip(self.hex, "Hex color", "Type a color like #ff8800 and press Enter.")
        self.hex.returnPressed.connect(self._from_hex)
        row.addWidget(self.hex)
        more = button("Custom…", icon="palette", size="sm",
                      tip="Custom color", tip_body="Open the full color picker.")
        more.clicked.connect(self._dialog)
        row.addWidget(more)
        lay.addLayout(row)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(qc("border"), 1))
        p.setBrush(qc("surface"))
        p.drawRoundedRect(r, 10, 10)

    def _choose(self, hx, close=False):
        self.value = hx
        self.hex.setText("#" + hx)
        self.picked.emit(hx)
        if close:
            self.close()

    def _from_hex(self):
        s = self.hex.text().strip().lstrip("#")
        if len(s) == 6 and all(c in "0123456789abcdefABCDEF" for c in s):
            self._choose(s.lower(), close=True)

    def _dialog(self):
        start = self.value
        self.close()
        dlg = QColorDialog(QColor("#" + start), self.parentWidget())
        dlg.setOption(QColorDialog.DontUseNativeDialog, True)
        dlg.setWindowTitle("Pick a color")
        dlg.currentColorChanged.connect(lambda c: self.picked.emit(c.name()[1:]))
        if dlg.exec():
            self.picked.emit(dlg.selectedColor().name()[1:])
        else:
            self.picked.emit(start)

    def popup_below(self, anchor):
        self.adjustSize()
        pos = anchor.mapToGlobal(anchor.rect().bottomLeft())
        pos.setY(pos.y() + 6)
        self.move(pos)
        self.show()


class ChipButton(QAbstractButton):
    """A color chip (rounded square)."""

    def __init__(self, hx, size=22, parent=None):
        super().__init__(parent)
        self.hx = hx
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)

    def set_color(self, hx):
        self.hx = hx
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(qc("border_strong") if not self.underMouse() else qc("fg"), 1))
        p.setBrush(QColor("#" + self.hx))
        p.drawRoundedRect(r, 6, 6)


class ColorSwatch(QPushButton):
    """Chip + hex label; opens the ColorPopover. Emits colorChanged(hex)."""

    colorChanged = Signal(str)

    def __init__(self, value, compact=False, parent=None):
        super().__init__(parent)
        self._v = value
        self.compact = compact
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(32)
        if compact:
            self.setFixedWidth(40)
        self.clicked.connect(self._open)

    def sizeHint(self):
        if self.compact:
            return QSize(40, 32)
        # measured with the font the hex is painted in (QSS overrides setFont)
        text_w = QFontMetrics(theme.mono_font(12)).horizontalAdvance("#" + self._v)
        return QSize(7 + 18 + 8 + text_w + 14, 32)

    def minimumSizeHint(self):
        return self.sizeHint()

    def value(self):
        return self._v

    def setValue(self, v):
        self._v = v
        self.update()

    def _open(self):
        pop = ColorPopover(self, self._v)
        pop.picked.connect(self._picked)
        pop.popup_below(self)

    def _picked(self, hx):
        if hx != self._v:
            self._v = hx
            self.update()
            self.colorChanged.emit(hx)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        chip = QRectF(7, (h - 18) / 2, 18, 18) if not self.compact else QRectF(
            (self.width() - 20) / 2, (h - 20) / 2, 20, 20)
        p.setPen(QPen(qc("border_strong"), 1))
        p.setBrush(QColor("#" + self._v))
        p.drawRoundedRect(chip, 5, 5)
        if not self.compact:
            p.setFont(theme.mono_font(12))
            p.setPen(qc("fg"))
            p.drawText(QRectF(chip.right() + 8, 0, self.width(), h), Qt.AlignVCenter, "#" + self._v)


# -------------------------------------------------------------------- badge --
class Badge(QWidget):
    """Status pill with a colored dot. kind: success | warning | danger | muted | accent."""

    def __init__(self, text="", kind="muted", parent=None):
        super().__init__(parent)
        self._text, self._kind = text, kind
        self.setFixedHeight(26)

    def set(self, text, kind):
        self._text, self._kind = text, kind
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self._text) + 34, 26)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        dot = {"success": "success", "warning": "warning", "danger": "danger",
               "accent": "accent"}.get(self._kind, "subtle")
        p.setPen(QPen(qc("border"), 1))
        p.setBrush(qc("surface"))
        p.drawRoundedRect(r, 13, 13)
        c = QPointF(14, r.center().y())
        if self._kind != "muted":
            p.setPen(Qt.NoPen)
            p.setBrush(qc(dot, 0.25))
            p.drawEllipse(c, 6, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(qc(dot))
        p.drawEllipse(c, 3.5, 3.5)
        f = self.font()
        f.setPixelSize(12)
        f.setWeight(f.Weight.Medium)
        p.setFont(f)
        p.setPen(qc("fg"))
        p.drawText(QRectF(24, 0, r.width() - 26, r.height()), Qt.AlignVCenter, self._text)


# ------------------------------------------------------------------- banner --
class Banner(QFrame):
    """Inline notice with an icon, text, optional action buttons and a close X.
    kind: info | warning | danger."""

    dismissed = Signal()

    def __init__(self, kind, title, text, actions=(), parent=None):
        super().__init__(parent)
        self.kind = kind
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 11, 10, 11)
        lay.setSpacing(12)
        ic = {"info": "info", "warning": "alert", "danger": "alert"}[kind]
        color = {"info": "info", "warning": "warning", "danger": "danger"}[kind]
        icl = icon_label(ic, color, 18)
        lay.addWidget(icl, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = label(title)
        t.setStyleSheet("font-weight: 600;")
        col.addWidget(t)
        body = label(text, "muted", wrap=True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        col.addWidget(body)
        lay.addLayout(col, 1)
        for text_, cb, tip_ in actions:
            b = button(text_, size="sm", tip=text_, tip_body=tip_)
            b.clicked.connect(cb)
            lay.addWidget(b, 0, Qt.AlignVCenter)
        close = button(icon="x", variant="ghost", size="icon", tip="Dismiss")
        close.setFixedSize(28, 28)
        close.clicked.connect(self._close)
        lay.addWidget(close, 0, Qt.AlignTop)
        self._color = color

    def _close(self):
        self.hide()
        self.dismissed.emit()
        self.deleteLater()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(qc(self._color, 0.4), 1))
        p.setBrush(qc(self._color, 0.08))
        p.drawRoundedRect(r, 10, 10)


# -------------------------------------------------------------------- toast --
class Toast(QFrame):
    def __init__(self, host, text, kind):
        super().__init__(host)
        self.kind = kind
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 11, 16, 11)
        lay.setSpacing(10)
        ic = {"success": "check", "danger": "alert", "warning": "alert"}.get(kind, "info")
        color = {"success": "success", "danger": "danger", "warning": "warning"}.get(kind, "info")
        lay.addWidget(icon_label(ic, color, 16))
        lbl = label(text, wrap=True)
        lbl.setMaximumWidth(340)
        lay.addWidget(lbl)
        self.opacity = QGraphicsOpacityEffect(self)
        self.opacity.setOpacity(0.0)
        self.setGraphicsEffect(self.opacity)
        self.fade = QPropertyAnimation(self.opacity, b"opacity", self)
        self.fade.setDuration(180)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(qc("border_strong"), 1))
        p.setBrush(qc("surface"))
        p.drawRoundedRect(r, 10, 10)


class ToastHost(QWidget):
    """Transparent overlay that stacks toasts in the bottom-right corner of its
    parent and lets clicks through everywhere else."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.toasts = []
        parent.installEventFilter(self)
        self.resize(parent.size())

    def eventFilter(self, obj, ev):
        if ev.type() == ev.Type.Resize:
            self.resize(obj.size())
            self._layout()
        return False

    def show_toast(self, text, kind="info", ms=3200):
        t = Toast(self, text, kind)
        t.adjustSize()
        t.show()
        self.toasts.append(t)
        self._layout()
        self.raise_()
        t.fade.setStartValue(0.0)
        t.fade.setEndValue(1.0)
        t.fade.start()
        QTimer.singleShot(ms, lambda: self._dismiss(t))

    def _dismiss(self, t):
        if t not in self.toasts:
            return
        t.fade.stop()
        t.fade.setStartValue(t.opacity.opacity())
        t.fade.setEndValue(0.0)
        t.fade.finished.connect(lambda: self._remove(t))
        t.fade.start()

    def _remove(self, t):
        if t in self.toasts:
            self.toasts.remove(t)
            t.deleteLater()
            self._layout()

    def _layout(self):
        y = self.height() - 20
        for t in reversed(self.toasts):
            t.adjustSize()
            y -= t.height()
            t.move(self.width() - t.width() - 20, y)
            y -= 8


# --------------------------------------------------------------------- card --
class Card(QFrame):
    """Rounded bordered panel with an optional title row; collapsible cards
    toggle their body when the header is clicked."""

    def __init__(self, title=None, icon=None, collapsible=False, collapsed=False, parent=None):
        super().__init__(parent)
        self.setProperty("role", "card")
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(16, 14, 16, 16)
        self.outer.setSpacing(12)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(14)
        self.collapsible = collapsible
        if title:
            head = QHBoxLayout()
            head.setSpacing(8)
            if icon:
                head.addWidget(icon_label(icon, "muted", 15))
            self.title = label(title, "h2")
            head.addWidget(self.title)
            head.addStretch(1)
            if collapsible:
                self.chev = button(icon="chevron-down", variant="ghost", size="icon",
                                   tip="Show or hide these settings")
                self.chev.setFixedSize(26, 26)
                self.chev.clicked.connect(self.toggle)
                head.addWidget(self.chev)
            self.outer.addLayout(head)
        self.outer.addWidget(self.body)
        if collapsible and collapsed:
            self.body.hide()

    def toggle(self):
        self.body.setVisible(not self.body.isVisible())
        self.chev.setProperty("icon_name", "chevron-down" if self.body.isVisible() else "chevron-right")
        _refresh_icon(self.chev)

    def mousePressEvent(self, e):
        if self.collapsible and e.position().y() < 44:
            self.toggle()
        super().mousePressEvent(e)
