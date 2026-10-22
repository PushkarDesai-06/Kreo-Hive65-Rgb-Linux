"""Keyboard Studio entry point."""
import argparse
import sys

from PySide6.QtWidgets import QApplication, QStyleFactory, QSystemTrayIcon

from gui import theme
from gui.controller import Studio
from gui.settings import Settings
from gui.single_instance import SingleInstance
from gui.widgets.tooltip import TipStyle, TooltipFilter


def main(argv=None):
    ap = argparse.ArgumentParser(prog="keyboardrgb_gui.py",
                                 description="Keyboard Studio: preview and run RGB lighting")
    ap.add_argument("--tray", action="store_true",
                    help="start hidden in the system tray and resume the last lighting "
                         "(used by launch on login)")
    args, qt_args = ap.parse_known_args(argv if argv is not None else sys.argv[1:])

    QApplication.setApplicationName("Keyboard Studio")
    QApplication.setDesktopFileName("keyboardrgb-studio")
    app = QApplication([sys.argv[0], *qt_args])
    app.setStyle(TipStyle(QStyleFactory.create("Fusion")))

    single = SingleInstance()
    if single.notify_existing({"cmd": "show"}):
        return 0  # the running instance raised its window
    single.listen()

    settings = Settings()
    th = settings["theme"]
    theme.ThemeManager.get().apply(th.get("base", "#09090b"), th.get("accent", "#f0ec57"))
    app.setFont(theme.app_font(13))
    app.installEventFilter(TooltipFilter(app))

    from gui.main_window import MainWindow
    from gui.tray import Tray, app_icon

    has_tray = QSystemTrayIcon.isSystemTrayAvailable()
    studio = Studio(settings)
    single.handler = studio.handle_socket
    win = MainWindow(studio, has_tray=has_tray)
    win.setWindowIcon(app_icon())
    app.setWindowIcon(app_icon())
    tray = None
    if has_tray:
        tray = Tray(studio, win)
        tray.show()
        app.setQuitOnLastWindowClosed(False)

    def cleanup():
        studio.shutdown()
        single.close()
    app.aboutToQuit.connect(cleanup)

    if args.tray:
        studio.set_window_visible(False)
        studio.start_preview()
        studio.resume_last()
        if tray is None:
            # nowhere to live without a tray: the background runner carries on
            studio.shutdown()
            single.close()
            return 0
    else:
        studio.start_preview()
        win.show()
    return app.exec()
