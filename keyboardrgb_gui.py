#!/usr/bin/env python3
"""Keyboard Studio: a desktop app to preview every lighting effect on an
on-screen keyboard, tune it live, mirror it to the physical board and leave it
running in the background. The CLI (keyboardrgb.py) needs nothing extra; this
app needs PySide6:

    python3 -m venv .venv && .venv/bin/pip install -r requirements-gui.txt
    .venv/bin/python keyboardrgb_gui.py           # open the app
    .venv/bin/python keyboardrgb_gui.py --tray    # start hidden in the tray
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from gui.app import main
except ImportError as e:
    if "PySide6" not in str(e):
        raise
    sys.exit("Keyboard Studio needs PySide6: pip install -r requirements-gui.txt")

if __name__ == "__main__":
    sys.exit(main())
