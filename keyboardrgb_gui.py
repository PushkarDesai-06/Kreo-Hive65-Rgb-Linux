#!/usr/bin/env python3
"""Keyboard Studio: a desktop app to preview every lighting effect on an
on-screen keyboard, tune it live, mirror it to the physical board and leave it
running in the background. The CLI (keyboardrgb.py) needs nothing extra; this
app needs PySide6:

    python3 -m venv .venv && .venv/bin/pip install -r requirements-gui.txt
    .venv/bin/python keyboardrgb_gui.py           # open the app
    .venv/bin/python keyboardrgb_gui.py --tray    # start hidden in the tray
    .venv/bin/python keyboardrgb_gui.py --cli ... # same as keyboardrgb.py ...
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if getattr(sys, "frozen", False):
    # PyInstaller points LD_LIBRARY_PATH at its bundled libs. This process has
    # already resolved its own libraries, so restore the original for the
    # system tools we spawn (parec, grim, ffmpeg, pkexec).
    _orig = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if _orig is not None:
        os.environ["LD_LIBRARY_PATH"] = _orig
    else:
        os.environ.pop("LD_LIBRARY_PATH", None)

if len(sys.argv) > 1 and sys.argv[1] == "--cli":
    # `keyboard-studio --cli <args>` is keyboardrgb.py <args>: lets a packaged
    # build (no Python, no .py files on disk) run the background effects and
    # the exported toggle scripts. Stdlib only, no Qt.
    import keyboardrgb

    sys.argv = ["keyboardrgb.py", *sys.argv[2:]]
    sys.exit(keyboardrgb.main())

try:
    from gui.app import main
except ImportError as e:
    if "PySide6" not in str(e):
        raise
    sys.exit("Keyboard Studio needs PySide6: pip install -r requirements-gui.txt")

if __name__ == "__main__":
    sys.exit(main())
