"""Hover tooltips: a rounded, themed popup with a bold title, a plain-language
description and an optional muted hint line (e.g. the matching CLI flag).

Widgets opt in with set_tip(); an app-wide event filter swaps Qt's default
tooltip for the popup. A widget can also provide tooltip_at(pos) to return
position-dependent text (the keyboard view uses this for per-key hover)."""
import html

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QProxyStyle, QStyle, QVBoxLayout, QWidget

from gui import theme


def tip(title, body=None, hint=None):
    t = theme.tokens()
    parts = [f"<div style='font-weight:600; color:{t['fg']}'>{html.escape(title)}</div>"]
    if body:
        parts.append(f"<div style='color:{t['muted']}; margin-top:3px'>{html.escape(body)}</div>")
    if hint:
        parts.append(f"<div style='color:{t['subtle']}; margin-top:5px; font-family:"
                     f"\"{theme.MONO_FAMILY}\"; font-size:11px'>{html.escape(hint)}</div>")
    return "".join(parts)


def set_tip(widget, title, body=None, hint=None):
    widget.setToolTip(tip(title, body, hint))


class TipStyle(QProxyStyle):
    """Fusion with a quicker tooltip wake-up."""

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.SH_ToolTip_WakeUpDelay:
            return 450
        if hint == QStyle.SH_ToolTip_FallAsleepDelay:
            return 1500
        return super().styleHint(hint, option, widget, returnData)


class TooltipPopup(QWidget):
    def __init__(self, parent):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint
                         | Qt.WindowTransparentForInput | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 10)
        self.label = QLabel()
        self.label.setTextFormat(Qt.RichText)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("font-size: 12px;")
        lay.addWidget(self.label)
        self.owner = None
        self.text = None

    def show_text(self, owner, text, global_pos):
        self.owner, self.text = owner, text
        self.label.setText(text)
        self.label.setMaximumWidth(300)
        self.label.adjustSize()
        self.adjustSize()
        pos = global_pos + QPoint(12, 18)
        screen = QGuiApplication.screenAt(global_pos)
        if screen is not None:
            g = screen.availableGeometry()
            if pos.x() + self.width() > g.right():
                pos.setX(global_pos.x() - self.width() - 8)
            if pos.y() + self.height() > g.bottom():
                pos.setY(global_pos.y() - self.height() - 10)
        self.move(pos)
        self.show()
        self.raise_()

    def paintEvent(self, _ev):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.fillPath(path, QColor(t["surface"]))
        p.setPen(QPen(QColor(t["border_strong"]), 1))
        p.drawPath(path)


class TooltipFilter(QObject):
    """Installed on the QApplication; owns one popup per top-level window."""

    def __init__(self, app):
        super().__init__(app)
        self._popups = {}
        self._watch = QTimer(self)
        self._watch.setInterval(120)
        self._watch.timeout.connect(self._check_cursor)

    def _popup(self, owner):
        win = owner.window()
        p = self._popups.get(win)
        if p is None:
            p = self._popups[win] = TooltipPopup(win)
        return p

    def hide(self):
        for p in self._popups.values():
            if p.isVisible():
                p.hide()
            p.owner = None
        self._watch.stop()

    def _check_cursor(self):
        for p in self._popups.values():
            o = p.owner
            if o is None or not p.isVisible():
                continue
            try:
                inside = o.isVisible() and o.rect().contains(o.mapFromGlobal(QCursor.pos()))
            except RuntimeError:  # owner deleted
                inside = False
            if not inside:
                self.hide()

    def eventFilter(self, obj, ev):
        et = ev.type()
        if et == QEvent.ToolTip and isinstance(obj, QWidget):
            text = obj.tooltip_at(ev.pos()) if hasattr(obj, "tooltip_at") else obj.toolTip()
            if not text:
                return False  # let it bubble to a parent that has one
            self._popup(obj).show_text(obj, text, ev.globalPos())
            self._watch.start()
            return True
        if et in (QEvent.Leave, QEvent.MouseButtonPress, QEvent.Wheel, QEvent.Hide,
                  QEvent.KeyPress, QEvent.WindowDeactivate):
            for p in self._popups.values():
                if p.owner is obj and p.isVisible():
                    self.hide()
                    break
        elif et == QEvent.MouseMove and hasattr(obj, "tooltip_at"):
            for p in self._popups.values():
                if p.owner is obj and p.isVisible():
                    text = obj.tooltip_at(ev.position().toPoint())
                    if not text:
                        self.hide()
                    elif text != p.text:
                        p.show_text(obj, text, ev.globalPosition().toPoint())
        return False
