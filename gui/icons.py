"""Small line-icon set (24px grid, 2px strokes) rendered from inline SVG in any
theme color. Kept in code so the app ships no image files."""
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_F = 'fill="currentColor" stroke="none"'

PATHS = {
    "solid": '<rect x="4" y="4" width="16" height="16" rx="4"/>'
             '<rect x="8" y="8" width="8" height="8" rx="2" ' + _F + '/>',
    "gradient": '<rect x="3" y="5" width="18" height="14" rx="3"/>'
                '<path d="M9 5v14" opacity=".35"/><path d="M15 5v14" opacity=".7"/>',
    "rainbow": '<path d="M3 18a9 9 0 0 1 18 0"/><path d="M7 18a5 5 0 0 1 10 0"/>'
               '<path d="M11 18a1 1 0 0 1 2 0"/>',
    "wave": '<path d="M2 9c2.5-4 5-4 7.5 0s5 4 7.5 0 3-3 5-1"/>'
            '<path d="M2 16c2.5-4 5-4 7.5 0s5 4 7.5 0 3-3 5-1" opacity=".55"/>',
    "flux": '<circle cx="9" cy="10" r="5"/><circle cx="15" cy="10" r="5"/>'
            '<circle cx="12" cy="15" r="5"/>',
    "music": '<path d="M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4"/>',
    "bars": '<path d="M5 20v-7M10 20V5M15 20V9M20 20v-4"/>',
    "blackhole": '<circle cx="12" cy="12" r="3" ' + _F + '/>'
                 '<path d="M20 12a8 8 0 0 1-8 8M4 12a8 8 0 0 1 8-8"/>'
                 '<path d="M17 7a7 7 0 0 0-5-2M7 17a7 7 0 0 0 5 2" opacity=".5"/>',
    "ripple": '<circle cx="12" cy="12" r="2"/><circle cx="12" cy="12" r="6" opacity=".7"/>'
              '<circle cx="12" cy="12" r="10" opacity=".4"/>',
    "split": '<path d="M12 4v16" opacity=".4"/><path d="M8 8l-4 4 4 4M16 8l4 4-4 4"/>',
    "flow": '<path d="M3 8h11M3 12h15M3 16h8"/><path d="M17 5l4 3-4 3"/>',
    "splash": '<circle cx="12" cy="12" r="3" ' + _F + '/><path d="M12 3v3M12 18v3M3 12h3'
              'M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
    "radio": '<circle cx="12" cy="12" r="2"/><path d="M16.2 7.8a6 6 0 0 1 0 8.4M7.8 16.2a6 6 0 0 1 0-8.4'
             'M19.1 4.9a10 10 0 0 1 0 14.2M4.9 19.1a10 10 0 0 1 0-14.2"/>',
    "trail": '<path d="M3 19c3-6 6-2 8.5-6.5S16 6 20 6"/><circle cx="20" cy="6" r="1.6" ' + _F + '/>',
    "flame": '<path d="M12 3c1 3.5 5.5 5.5 5.5 10.5a5.5 5.5 0 0 1-11 0c0-2.2 1-3.8 2.2-4.8 '
             '0 2 1 3.3 2.3 3.3 0-3.2-1.2-5.6 1-9z"/>',
    "drop": '<path d="M12 3s5.5 6.2 5.5 10.5a5.5 5.5 0 0 1-11 0C6.5 9.2 12 3 12 3z"/>',
    "radar": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5" opacity=".6"/>'
             '<path d="M12 12l6-6"/>',
    "matrix": '<path d="M6 4v7M6 15v2M12 4v2M12 10v10M18 4v9M18 17v3"/>',
    "crosshair": '<circle cx="12" cy="12" r="8"/><path d="M12 2v6M12 16v6M2 12h6M16 12h6"/>',
    "sparkle": '<path d="M11 3l1.9 5.1L18 10l-5.1 1.9L11 17l-1.9-5.1L4 10l5.1-1.9z"/>'
               '<path d="M19 15v5M16.5 17.5h5"/>',
    "eraser": '<path d="M8 21h12"/><path d="M5.6 14.4l7.6-7.6a2 2 0 0 1 2.8 0l2.2 2.2a2 2 0 0 1 0 2.8'
              'L12 18H9.2z"/><path d="M9 11l4.5 4.5" opacity=".5"/>',
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "keyboard": '<rect x="2" y="6" width="20" height="12" rx="2.5"/>'
                '<path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
    "star": '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>',
    "play": '<path d="M7 4.5l12 7.5-12 7.5z" ' + _F + '/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2" ' + _F + '/>',
    "more": '<circle cx="5" cy="12" r="1.3" ' + _F + '/><circle cx="12" cy="12" r="1.3" ' + _F + '/>'
            '<circle cx="19" cy="12" r="1.3" ' + _F + '/>',
    "sliders": '<path d="M4 6h9M18 6h2M4 12h3M11 12h9M4 18h11M19 18h1"/>'
               '<circle cx="15.5" cy="6" r="2.2"/><circle cx="9" cy="12" r="2.2"/>'
               '<circle cx="17" cy="18" r="2.2"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/>'
            '<path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "terminal": '<path d="M4 17l6-5-6-5M12 19h8"/>',
    "download": '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.8h.01"/>',
    "alert": '<path d="M10.3 4l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3l-8-14a2 2 0 0 0-3.4 0z"/>'
             '<path d="M12 9v4M12 17h.01"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7"/>',
    "reset": '<path d="M3 12a9 9 0 1 0 2.6-6.4L3 8"/><path d="M3 3v5h5"/>',
    "bookmark": '<path d="M6 3h12v18l-6-4-6 4z"/><path d="M12 7v6M9 10h6"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "zap": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    "power": '<path d="M12 3v9"/><path d="M6.3 6.3a8 8 0 1 0 11.4 0"/>',
    "pencil": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    "palette": '<path d="M12 21a9 9 0 1 1 9-9c0 2.5-2 3.5-4 3.5h-2a2 2 0 0 0-1.5 3.3c.6.8.2 2.2-1.5 2.2z"/>'
               '<circle cx="7.5" cy="11" r="1.2" ' + _F + '/><circle cx="10" cy="7" r="1.2" ' + _F + '/>'
               '<circle cx="15" cy="7.5" r="1.2" ' + _F + '/>',
    "rocket": '<path d="M5 15c-1.5 1.5-2 5-2 5s3.5-.5 5-2"/><path d="M9 15l-3-3c2-6 7-9 14-9 '
              '0 7-3 12-9 14z"/><circle cx="15" cy="9" r="1.6"/>',
    "plug": '<path d="M9 2v5M15 2v5M6 7h12v4a6 6 0 0 1-12 0zM12 17v5"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
}

_cache = {}


def svg(name, color):
    body = PATHS[name].replace("currentColor", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round">{body}</svg>')


def pixmap(name, color, size=16):
    dpr = QGuiApplication.instance().devicePixelRatio() if QGuiApplication.instance() else 1.0
    key = (name, color, size, dpr)
    pm = _cache.get(key)
    if pm is None:
        pm = QPixmap(int(size * dpr), int(size * dpr))
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        QSvgRenderer(QByteArray(svg(name, color).encode())).render(p, QRectF(0, 0, size * dpr, size * dpr))
        p.end()
        pm.setDevicePixelRatio(dpr)
        _cache[key] = pm
    return pm


def icon(name, color, size=16):
    return QIcon(pixmap(name, color, size))
