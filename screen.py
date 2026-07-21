#!/usr/bin/env python3
"""Screen capture for the screen-sync effect: a continuous low-res, blurred
mirror of a monitor, delivered as small RGB grids sized to the keyboard.

The platform's native capture tool (grim on wlroots Wayland) grabs full frames
— a cheap GPU->shm copy — which are piped through one long-lived ffmpeg that
downscales to ~144p, gaussian-blurs, and area-downscales to the key grid.
Python only reads a few hundred bytes per frame, so the effect stays light.
This mirrors audio.AudioTap: an external capture tool feeding stdlib Python.

Follow-focus (Hyprland): the grabbed output is re-queried from hyprctl every
few hundred ms, so the mirror tracks whichever monitor currently has focus.
On X11 (no WAYLAND_DISPLAY) ffmpeg's x11grab captures the display directly and
no grim pump is needed.
"""
import json
import os
import shutil
import subprocess
import threading
import time


def hypr_monitors():
    """[(name, focused)] from hyprctl, or [] if Hyprland/hyprctl isn't there."""
    try:
        out = subprocess.check_output(
            ["hyprctl", "monitors", "-j"], text=True, stderr=subprocess.DEVNULL
        )
        return [(m["name"], bool(m.get("focused"))) for m in json.loads(out)]
    except (OSError, ValueError, KeyError):
        return []


def wlr_outputs():
    """Output names from wlr-randr (generic wlroots), or [] if unavailable."""
    try:
        out = subprocess.check_output(
            ["wlr-randr"], text=True, stderr=subprocess.DEVNULL
        )
    except OSError:
        return []
    # output lines start at column 0; mode/property lines are indented
    return [ln.split()[0] for ln in out.splitlines() if ln and not ln[0].isspace()]


def list_outputs():
    """Every connected output name (hyprctl first, then wlr-randr)."""
    return [n for n, _ in hypr_monitors()] or wlr_outputs()


def focused_output():
    """Name of the focused monitor (Hyprland), or None if not discoverable."""
    for name, foc in hypr_monitors():
        if foc:
            return name
    return None


def default_output():
    """A sensible monitor to capture: the focused one, else the first listed."""
    return focused_output() or (list_outputs() or [None])[0]


class ScreenTap:
    """Continuous blurred low-res screen mirror as keyboard-sized RGB grids.

    output/follow: a fixed output name, or follow=True to track the focused
    monitor. read() returns the newest cols*rows grid of (r,g,b), or None.
    """

    def __init__(self, output, follow, cols, rows, res=144, blur=2.0, fps=24.0):
        if shutil.which("ffmpeg") is None:
            raise SystemExit("screen sync needs ffmpeg (not found on PATH)")
        self.cols, self.rows = cols, rows
        self.frame_bytes = cols * rows * 3
        self.follow = follow
        self.fps = fps
        self._stop = threading.Event()
        self.buf = bytearray()
        self.eof = False
        self._pump = None
        self._last_focus_check = 0.0

        # capture height sets the "144p" working resolution; -2 keeps the aspect
        # (and an even width). fast_bilinear + a box blur (avgblur) is ~half the
        # CPU of bicubic+gaussian and visually identical once crushed to the grid.
        parts = [f"scale=-2:{int(res)}:flags=fast_bilinear"]
        rad = int(round(blur))
        if rad >= 1:
            parts.append(f"avgblur={rad}")
        parts.append(f"scale={cols}:{rows}:flags=area")
        vf = ",".join(parts)

        if os.environ.get("WAYLAND_DISPLAY"):
            if shutil.which("grim") is None:
                raise SystemExit("screen sync on Wayland needs grim (not on PATH)")
            self.backend = "grim"
            self.output = output or default_output()
            if self.output is None:
                raise SystemExit(
                    "could not determine a monitor to capture; pass --output "
                    "(see: hyprctl monitors / wlr-randr)"
                )
            self.ff = subprocess.Popen(
                ["ffmpeg", "-hide_banner", "-loglevel", "error",
                 "-f", "image2pipe", "-c:v", "ppm", "-i", "-",
                 "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._pump = threading.Thread(target=self._pump_grim, daemon=True)
            self._pump.start()
        elif os.environ.get("DISPLAY"):
            self.backend = "x11"
            self.output = output or os.environ["DISPLAY"]
            self.ff = subprocess.Popen(
                ["ffmpeg", "-hide_banner", "-loglevel", "error",
                 "-f", "x11grab", "-framerate", f"{fps:g}", "-i", self.output,
                 "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        else:
            raise SystemExit(
                "no WAYLAND_DISPLAY or DISPLAY set; cannot find a screen to capture"
            )

        self.fd = self.ff.stdout.fileno()
        os.set_blocking(self.fd, False)

    def _maybe_update_focus(self, now, interval=0.3):
        if self.follow and now - self._last_focus_check >= interval:
            self._last_focus_check = now
            f = focused_output()
            if f:
                self.output = f

    def _pump_grim(self):
        """Grab full frames with grim and feed them to ffmpeg's stdin, throttled
        to the target fps. Runs in a daemon thread until close() or ffmpeg dies."""
        period = 1.0 / self.fps if self.fps > 0 else 0.0
        try:
            while not self._stop.is_set():
                t = time.monotonic()
                self._maybe_update_focus(t)
                try:
                    g = subprocess.run(
                        ["grim", "-o", self.output, "-t", "ppm", "-"],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    )
                except OSError:
                    break
                if g.returncode == 0 and g.stdout:
                    try:
                        self.ff.stdin.write(g.stdout)
                        self.ff.stdin.flush()
                    except (BrokenPipeError, ValueError, OSError):
                        break  # ffmpeg went away
                dt = time.monotonic() - t
                if period > dt:
                    self._stop.wait(period - dt)
        finally:
            try:
                self.ff.stdin.close()
            except OSError:
                pass

    def read(self):
        """Drain ffmpeg's output and return the newest complete grid as a flat
        list of (r,g,b) tuples (cols*rows of them), or None if none is ready."""
        while True:
            try:
                chunk = os.read(self.fd, 1 << 16)
            except BlockingIOError:
                break
            if not chunk:
                self.eof = True
                if self.ff.poll() is not None:
                    err = (self.ff.stderr.read() or b"").decode(errors="replace")
                    raise SystemExit(
                        f"ffmpeg exited ({self.ff.returncode}): {err.strip()}"
                    )
                break
            self.buf += chunk
        fb = self.frame_bytes
        if len(self.buf) < fb:
            return None
        drop = (len(self.buf) // fb - 1) * fb  # keep only the most recent frame
        if drop:
            del self.buf[:drop]
        frame = self.buf[:fb]
        del self.buf[:fb]
        return [(frame[i], frame[i + 1], frame[i + 2]) for i in range(0, fb, 3)]

    def close(self):
        self._stop.set()
        if self._pump:
            self._pump.join(timeout=1.0)
        if self.ff:
            self.ff.terminate()
            try:
                self.ff.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.ff.kill()
