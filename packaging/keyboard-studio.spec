# PyInstaller spec for Keyboard Studio: a one-folder build that
# packaging/build-appimage.sh wraps into an AppImage.
#
#   python -m PyInstaller --noconfirm packaging/keyboard-studio.spec
import os
import re
import subprocess

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

# Qt modules the app never imports; keeping them out trims tens of MB
UNUSED_QT = [
    "PySide6." + m for m in (
        "QtQml", "QtQuick", "QtQuickWidgets", "QtQuickControls2", "QtPdf", "QtPdfWidgets",
        "QtMultimedia", "QtMultimediaWidgets", "QtWebEngineCore", "QtWebEngineWidgets",
        "QtWebChannel", "QtWebSockets", "QtSql", "QtTest", "QtXml", "QtPrintSupport",
        "QtOpenGLWidgets", "QtConcurrent", "QtHelp", "QtDesigner", "QtUiTools",
        "Qt3DCore", "QtCharts", "QtDataVisualization", "QtBluetooth", "QtPositioning",
        "QtSerialPort", "QtSensors", "QtTextToSpeech", "QtSpatialAudio",
    )
]

a = Analysis(
    [os.path.join(ROOT, "keyboardrgb_gui.py")],
    pathex=[ROOT],
    datas=[
        (os.path.join(ROOT, "profiles"), "profiles"),
        (os.path.join(ROOT, "60-keyboardrgb.rules"), "."),
        (os.path.join(ROOT, "manual.md"), "."),
        (os.path.join(ROOT, "packaging", "keyboard-studio.png"), "packaging"),
    ],
    # the CLI side is imported lazily inside functions; name it so it is always bundled
    hiddenimports=["keyboardrgb", "effects", "reactive", "screen", "audio", "engine",
                   "params", "devlock", "errors", "kbd_profiles", "device", "color"],
    excludes=["tkinter", "unittest", "pydoc", *UNUSED_QT],
    noarchive=False,
)
# Qt plugins the app can't use on a Linux desktop. The GTK3 platform theme is the
# big one: it drags the host's whole GTK stack (and a second ICU) into the bundle.
DROP = re.compile(
    r"PySide6/Qt/(translations/"
    r"|plugins/(platformthemes/libqgtk3"
    r"|platforms/libq(eglfs|linuxfb|minimalegl|vkkhrdisplay|vnc)"
    r"|egldeviceintegrations/|generic/|networkinformation/|tls/"
    r"|imageformats/(?!libqsvg)"
    r"|platforminputcontexts/libibus"
    r"|wayland-graphics-integration-client/lib[\w-]+-server))"
)
binaries = [b for b in a.binaries if not DROP.search(b[0].replace(os.sep, "/"))]
datas = [d for d in a.datas if not DROP.search(d[0].replace(os.sep, "/"))]


def _needed(path):
    """DT_NEEDED sonames of an ELF file."""
    try:
        out = subprocess.run(["readelf", "-d", path], capture_output=True, text=True).stdout
    except OSError:
        return []
    return re.findall(r"\(NEEDED\)\s+Shared library: \[(.+?)\]", out)


# Host libraries land at the top of the bundle as dependencies. Keep only those
# still reachable from what remains (Python, its extensions, Qt and its plugins).
top = {os.path.basename(b[0]): b for b in binaries
       if "/" not in b[0].replace(os.sep, "/") and not b[0].startswith("libpython")}
keep, todo = set(), [b[1] for b in binaries if os.path.basename(b[0]) not in top]
while todo:
    for so in _needed(todo.pop()):
        if so in top and so not in keep:
            keep.add(so)
            todo.append(top[so][1])
binaries = [b for b in binaries if os.path.basename(b[0]) not in top
            or os.path.basename(b[0]) in keep]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="keyboard-studio",
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(exe, binaries, datas, strip=False, upx=False, name="keyboard-studio")
