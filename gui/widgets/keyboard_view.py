"""The on-screen keyboard: realistic keycaps (from the profile's visual layout,
or the plain col/row grid when a profile has none) lit with the live frame.

Each key gets an additive underglow in its LED color, a tinted keycap and a
shine-through legend, so the preview reads like the real board in a dark room.
Clicking a key sends a press/release, which drives the typing effects."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import QSizePolicy, QWidget

from gui import legends, theme
from gui.widgets.tooltip import tip
from kbd_profiles import KeyCap

PAD = 0.42     # case padding around the keys, in key units
GAP = 0.075    # gap between neighbouring keycaps, in key units


def _mix(a, b, t):
    return QColor(int(a.red() + (b.red() - a.red()) * t),
                  int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


class KeyboardView(QWidget):
    keyPressed = Signal(str, bool)   # key name, down

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile = None
        self.caps = {}
        self.order = []
        self.colors = {}
        self.hover = None
        self.pressed = None
        self.setMouseTracking(True)
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        theme.ThemeManager.get().changed.connect(self.update)

    # -- data -------------------------------------------------------------
    def set_profile(self, profile):
        self.profile = profile
        if profile.visual:
            self.caps = dict(profile.visual)
        else:
            self.caps = {n: KeyCap(float(c), float(r), 1.0, 1.0, "rect", None,
                                   n not in profile.unlit)
                         for n, c, r in profile.keys_tuples}
        self.order = [n for n, _c, _r in profile.keys_tuples]
        self.colors = {n: (0, 0, 0) for n in self.order}
        self.hover = self.pressed = None
        self.update()

    def set_frame(self, colors):
        if self.profile is None or colors is None:
            return
        self.colors = dict(zip(self.order, colors))
        self.update()

    # -- geometry -----------------------------------------------------------
    def _metrics(self):
        caps = self.caps.values()
        tw = max(c.x + c.w for c in caps) + 2 * PAD
        th = max(c.y + c.h for c in caps) + 2 * PAD
        avail = QRectF(self.rect()).adjusted(12, 12, -12, -12)
        u = min(avail.width() / tw, avail.height() / th, 72.0)
        w, h = tw * u, th * u
        ox = avail.left() + (avail.width() - w) / 2
        oy = avail.top() + (avail.height() - h) / 2
        return u, QRectF(ox, oy, w, h)

    def _cap_rect(self, cap, u, case):
        g = GAP * u / 2
        return QRectF(case.left() + (PAD + cap.x) * u + g, case.top() + (PAD + cap.y) * u + g,
                      cap.w * u - 2 * g, cap.h * u - 2 * g)

    def key_at(self, pos):
        if not self.caps:
            return None
        u, case = self._metrics()
        for name, cap in self.caps.items():
            if self._cap_rect(cap, u, case).contains(pos):
                return name
        return None

    def tooltip_at(self, pos):
        name = self.key_at(QPointF(pos))
        if name is None:
            return None
        if not self.caps[name].lit:
            return tip("Volume knob", "Turn it to change the volume. It has no light, so "
                       "effects never color it.")
        r, g, b = self.colors.get(name, (0, 0, 0))
        return tip(legends.friendly(name), f"LED color #{r:02x}{g:02x}{b:02x}",
                   "Click to simulate a key press")

    # -- input --------------------------------------------------------------
    def mouseMoveEvent(self, e):
        name = self.key_at(e.position())
        if name != self.hover:
            self.hover = name
            clickable = name is not None and self.caps[name].lit
            self.setCursor(Qt.PointingHandCursor if clickable else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, e):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        name = self.key_at(e.position())
        if name and self.caps[name].lit:
            self.pressed = name
            self.keyPressed.emit(name, True)
            self.update()

    def mouseReleaseEvent(self, e):
        if self.pressed:
            self.keyPressed.emit(self.pressed, False)
            self.pressed = None
            self.update()

    # -- painting -----------------------------------------------------------
    def paintEvent(self, _ev):
        if not self.caps:
            return
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        u, case = self._metrics()
        dark = theme.ThemeManager.get().theme.dark

        # soft drop shadow under the case
        for i in range(6, 0, -1):
            sh = QColor(0, 0, 0, 10 if dark else 6)
            p.setPen(Qt.NoPen)
            p.setBrush(sh)
            p.drawRoundedRect(case.adjusted(-i, -i + 4, i, i + 4), 0.36 * u + i, 0.36 * u + i)

        grad = QLinearGradient(case.topLeft(), case.bottomLeft())
        grad.setColorAt(0, QColor(t["case_edge"]))
        grad.setColorAt(0.04, QColor(t["case"]))
        grad.setColorAt(1, _mix(QColor(t["case"]), QColor(t["bg"]), 0.35))
        p.setBrush(grad)
        p.setPen(QPen(QColor(t["case_edge"]), 1))
        p.drawRoundedRect(case, 0.36 * u, 0.36 * u)

        # additive underglow so neighbouring LEDs blend like light does
        p.save()
        p.setClipRect(case.adjusted(2, 2, -2, -2))
        p.setCompositionMode(QPainter.CompositionMode_Plus if dark
                             else QPainter.CompositionMode_SourceOver)
        p.setPen(Qt.NoPen)
        for name, cap in self.caps.items():
            r, g, b = self.colors.get(name, (0, 0, 0))
            lvl = max(r, g, b) / 255.0
            if lvl < 0.02 or not cap.lit:
                continue
            rect = self._cap_rect(cap, u, case)
            rad = max(rect.width(), rect.height()) * 0.5 + u * 0.55
            rg = QRadialGradient(rect.center(), rad)
            c0 = QColor(r, g, b, int(150 if dark else 90))
            c1 = QColor(r, g, b, 0)
            rg.setColorAt(0.0, c0)
            rg.setColorAt(0.55, QColor(r, g, b, int(55 if dark else 30)))
            rg.setColorAt(1.0, c1)
            p.setBrush(rg)
            p.drawEllipse(rect.center(), rad, rad * (0.75 if cap.w > 1.5 else 1.0))
        p.restore()

        cap_base = QColor(t["cap"])
        edge = QColor(t["cap_edge"])
        white = QColor(255, 255, 255)
        legend_off = QColor(t["subtle"])
        font = QFont(theme.FONT_FAMILY)
        font.setWeight(QFont.Medium)
        for name, cap in self.caps.items():
            r, g, b = self.colors.get(name, (0, 0, 0))
            led = QColor(r, g, b)
            lvl = max(r, g, b) / 255.0
            rect = self._cap_rect(cap, u, case)
            down = name == self.pressed
            if down:
                rect = rect.adjusted(0, u * 0.03, 0, u * 0.03)
            rad = 0.13 * u
            if cap.shape == "knob" or not cap.lit:
                self._paint_knob(p, rect, u, name == self.hover)
                continue
            skirt = _mix(cap_base, led, 0.5 * lvl ** 0.8)
            top = _mix(_mix(cap_base, white, 0.05 if dark else 0.0), led, 0.3 * lvl ** 0.8)

            if cap.shape == "circle":
                d = min(rect.width(), rect.height())
                cr = QRectF(rect.center().x() - d / 2, rect.center().y() - d / 2, d, d)
                p.setPen(QPen(edge, 1))
                p.setBrush(skirt)
                p.drawEllipse(cr)
                p.setBrush(top)
                p.drawEllipse(cr.adjusted(d * 0.14, d * 0.14, -d * 0.14, -d * 0.14))
                p.setPen(QPen(_mix(edge, led, 0.5 * lvl), max(1.0, u * 0.02)))
                c = cr.center()
                for i in range(12):
                    a = i * math.pi / 6
                    p.drawLine(QPointF(c.x() + math.cos(a) * d * 0.36, c.y() + math.sin(a) * d * 0.36),
                               QPointF(c.x() + math.cos(a) * d * 0.46, c.y() + math.sin(a) * d * 0.46))
                continue

            p.setPen(QPen(_mix(edge, led, 0.35 * lvl), 1))
            p.setBrush(skirt)
            p.drawRoundedRect(rect, rad, rad)
            inner = rect.adjusted(u * 0.1, u * 0.05, -u * 0.1, -u * 0.16)
            tg = QLinearGradient(inner.topLeft(), inner.bottomLeft())
            tg.setColorAt(0, _mix(top, white, 0.06 if dark else 0.25))
            tg.setColorAt(1, top)
            p.setPen(Qt.NoPen)
            p.setBrush(tg)
            p.drawRoundedRect(inner, rad * 0.85, rad * 0.85)

            if name == self.hover:
                p.setPen(QPen(theme.qcolor("accent", 0.9), 1.6))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), rad + 1, rad + 1)

            text = legends.legend(name, cap.legend)
            if text:
                size = u * (0.22 if len(text) <= 2 else 0.17 if len(text) <= 5 else 0.15)
                font.setPixelSize(max(8, int(size)))
                p.setFont(font)
                fm = QFontMetricsF(font)
                text = fm.elidedText(text, Qt.ElideRight, inner.width() - 4)
                if lvl < 0.06:
                    lc = legend_off
                else:
                    lc = _mix(led, white, 0.55)
                    lc.setAlpha(int(140 + 115 * min(1.0, lvl * 1.4)))
                p.setPen(lc)
                p.drawText(inner, Qt.AlignCenter, text)

    def _paint_knob(self, p, rect, u, hover):
        """A volume knob: no LED, so it ignores the frame and stays brushed metal."""
        t = theme.tokens()
        d = min(rect.width(), rect.height()) * 0.96
        c = rect.center()
        cr = QRectF(c.x() - d / 2, c.y() - d / 2, d, d)
        base = QColor(t["cap"])
        light = _mix(base, QColor(255, 255, 255), 0.22)
        shadow = QColor(0, 0, 0, 90)
        p.setPen(Qt.NoPen)
        p.setBrush(shadow)
        p.drawEllipse(cr.translated(0, u * 0.03))
        body = QRadialGradient(QPointF(c.x() - d * 0.18, c.y() - d * 0.22), d * 0.75)
        body.setColorAt(0, light)
        body.setColorAt(1, base)
        p.setBrush(body)
        p.setPen(QPen(theme.qcolor("accent", 0.9) if hover else QColor(t["cap_edge"]),
                      1.6 if hover else 1))
        p.drawEllipse(cr)
        # knurled grip around the rim
        p.setPen(QPen(_mix(base, QColor(0, 0, 0), 0.35), max(1.0, u * 0.018)))
        for i in range(28):
            a = i * math.pi / 14
            p.drawLine(QPointF(c.x() + math.cos(a) * d * 0.40, c.y() + math.sin(a) * d * 0.40),
                       QPointF(c.x() + math.cos(a) * d * 0.48, c.y() + math.sin(a) * d * 0.48))
        cap_top = QRadialGradient(QPointF(c.x() - d * 0.1, c.y() - d * 0.14), d * 0.45)
        cap_top.setColorAt(0, _mix(light, QColor(255, 255, 255), 0.12))
        cap_top.setColorAt(1, _mix(base, QColor(255, 255, 255), 0.06))
        p.setPen(Qt.NoPen)
        p.setBrush(cap_top)
        inner = d * 0.34
        p.drawEllipse(c, inner, inner)
        # position marker
        p.setBrush(QColor(t["subtle"]))
        p.drawEllipse(QPointF(c.x(), c.y() - inner * 0.62), d * 0.035, d * 0.035)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.update()
