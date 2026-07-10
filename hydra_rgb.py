#!/usr/bin/env python3
"""RGB control for BY Tech / SinoWealth 68-key keyboard (258a:010c) on Linux.

Protocol (reverse-engineered; verified against SignalRGB Hydra 10 plugin):
  HID SET_FEATURE on the vendor interface (usage page 0xFF00, interface 1),
  report ID 0x06, 520 bytes:
    [0x06, 0x08, 0x00, 0x00, 0x01, 0x00, 0x7A, 0x01] + rgb[378] + pad -> 520
  rgb payload: per-LED triplets, LED index = column*6 + row + 1 (column-major,
  6 slots/column). Colors latch immediately, no apply command.

Usage:
  hydra_rgb.py color <rrggbb>              # whole board one color
  hydra_rgb.py key <keyname> <rrggbb> ...  # per-key colors (pairs), rest off
  hydra_rgb.py gradient <rrggbb> <rrggbb>  # left-to-right gradient
  hydra_rgb.py rainbow                     # rainbow across columns
  hydra_rgb.py wave [seconds]              # animated hue wave (forever if no time)
  hydra_rgb.py off                         # all LEDs off
  hydra_rgb.py raw <hex...>                # send raw feature report

  color/key/gradient/rainbow/wave stay on until Ctrl-C: the board reverts to
  its onboard lighting once streaming stops, so the tool holds the frame by
  re-sending it. Add --once to set a single frame and exit (for scripts).
  hydra_rgb.py audio [options]             # audio-reactive spectrum wave
      --mode colorful|single   coloring (default colorful rainbow)
      --color RRGGBB           color for single mode (default 009bde)
      --gain FLOAT             amplitude multiplier (default 1.0)
      --smooth FLOAT           smoothness multiplier (default 1.0)
      --scroll FLOAT           colorful gradient scroll speed in hue
                               cycles/sec, left-to-right; 0 = static (0.15)
      --effect NAME            wave  = center-out spectrum (default)
                               bars  = bottom-up equalizer
                               vortex= black hole: dark center, rainbow ring
                                       spinning around it (faster when loud)
                               ripple= rings pushed outward by bass
                               (--shape is a backward-compatible alias)
      --radius FLOAT           vortex event-horizon (hole) size 0..1 (0.18)
      --fps N --source NAME --duration SEC --debug
    Captures system sound from the default sink's monitor via parec
    (PipeWire/PulseAudio); override with --source (see: pactl list short
    sources), or --source - to pipe raw s16le mono PCM on stdin.

Device node autodetected from /sys/class/hidraw (BY Tech + vendor descriptor).
"""

import argparse
import cmath
import math
import struct
import subprocess
import sys
import os
import fcntl
import glob
import time


def _IOC(dirn, typ, nr, size):
    return (dirn << 30) | (size << 16) | (ord(typ) << 8) | nr


def HIDIOCSFEATURE(length):
    return _IOC(3, "H", 0x06, length)


HDR = bytes([0x06, 0x08, 0x00, 0x00, 0x01, 0x00, 0x7A, 0x01])
PKT_LEN = 520
NUM_SLOTS = 126  # firmware accepts 0x17A bytes = 126 LED slots

ROWS = 5
# physical layout -> LED slot index (col*6 + row + 1), from the 68-key map
LAYOUT = [
    # (name, col, row)
    ("esc", 0, 0),
    ("1", 1, 0),
    ("2", 2, 0),
    ("3", 3, 0),
    ("4", 4, 0),
    ("5", 5, 0),
    ("6", 6, 0),
    ("7", 7, 0),
    ("8", 8, 0),
    ("9", 9, 0),
    ("0", 10, 0),
    ("minus", 11, 0),
    ("equal", 12, 0),
    ("backspace", 13, 0),
    ("home", 15, 0),
    ("tab", 0, 1),
    ("q", 1, 1),
    ("w", 2, 1),
    ("e", 3, 1),
    ("r", 4, 1),
    ("t", 5, 1),
    ("y", 6, 1),
    ("u", 7, 1),
    ("i", 8, 1),
    ("o", 9, 1),
    ("p", 10, 1),
    ("lbracket", 11, 1),
    ("rbracket", 12, 1),
    ("backslash", 13, 1),
    ("del", 15, 1),
    ("capslock", 0, 2),
    ("a", 1, 2),
    ("s", 2, 2),
    ("d", 3, 2),
    ("f", 4, 2),
    ("g", 5, 2),
    ("h", 6, 2),
    ("j", 7, 2),
    ("k", 8, 2),
    ("l", 9, 2),
    ("semicolon", 10, 2),
    ("quote", 11, 2),
    ("enter", 13, 2),
    ("pgup", 15, 2),
    ("lshift", 0, 3),
    ("z", 1, 3),
    ("x", 2, 3),
    ("c", 3, 3),
    ("v", 4, 3),
    ("b", 5, 3),
    ("n", 6, 3),
    ("m", 7, 3),
    ("comma", 8, 3),
    ("period", 9, 3),
    ("slash", 10, 3),
    ("rshift", 13, 3),
    ("up", 14, 3),
    ("pgdn", 15, 3),
    ("lctrl", 0, 4),
    ("lwin", 1, 4),
    ("lalt", 2, 4),
    ("space", 5, 4),
    ("ralt", 8, 4),
    ("fn", 9, 4),
    ("rctrl", 10, 4),
    ("left", 13, 4),
    ("down", 14, 4),
    ("right", 15, 4),
]
SLOT = {name: col * 6 + row + 1 for name, col, row in LAYOUT}
MAXCOL = 15

# Per-key geometry for 2D (field) effects: normalized position, radius and
# angle from the board's center. Columns/rows are each scaled to roughly
# [-1, 1] so a "circle" fills the wide 16x5 grid. Precomputed once.
TAU = 2.0 * math.pi
_CX, _CY = MAXCOL / 2.0, (ROWS - 1) / 2.0  # center at col 7.5, row 2
_XN, _YN = MAXCOL / 2.0 + 0.5, (ROWS - 1) / 2.0 + 0.5
GEOM = {
    name: (
        (col - _CX) / _XN,
        (row - _CY) / _YN,
        math.hypot((col - _CX) / _XN, (row - _CY) / _YN),
        math.atan2((row - _CY) / _YN, (col - _CX) / _XN),
    )
    for name, col, row in LAYOUT
}
# vortex: a black hole. A dark event horizon sits in the middle, ringed by a
# bright accretion disk whose rainbow gradient rotates around it (faster when
# louder). Bass swells the horizon and shoves the ring outward; each frequency
# band lights up its own sector of the ring.
VORTEX_BASE = 0.10  # idle color-rotation, revolutions/sec
VORTEX_SPIN = 1.2  # extra rev/sec at full energy
HOLE_SWELL = 0.18  # how much bass grows the event-horizon radius
RING_GAP = 0.28  # accretion ring sits this far outside the hole
RING_PUSH = 0.22  # bass shoves the ring further out (beat ripple)
RING_W = 0.16  # accretion-ring thickness (gaussian sigma)
# ripple: concentric rings pushed outward by bass hits
RIPPLE_RINGS = 2.5
RIPPLE_BASE = 0.15  # idle ring cycles/sec
RIPPLE_SPEED = 1.2  # extra cycles/sec driven by bass


def find_device():
    for path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            uevent = open(path + "/device/uevent").read().upper()
            if "V0000258AP0000010C" not in uevent:
                continue
            # vendor interface = the one exposing report id 6 as a feature
            desc = open(path + "/device/report_descriptor", "rb").read()
        except OSError:
            # node is mid-teardown during a firmware reset; skip it
            continue
        if b"\x85\x06" in desc:  # Report ID 6 present
            return "/dev/" + os.path.basename(path)
    raise SystemExit(
        "keyboard vendor interface not found (is it plugged in, wired mode?)"
    )


class Kbd:
    # errnos seen when the board's firmware resets and it re-enumerates
    GONE_ERRNOS = (5, 19, 32, 71)  # EIO, ENODEV, EPIPE, EPROTO

    def __init__(self, dev=None):
        self.dev = dev or find_device()
        self.fd = os.open(self.dev, os.O_RDWR)
        self.rgb = bytearray(NUM_SLOTS * 3)

    def reopen(self, timeout=10.0):
        """Reattach after a USB drop; the hidraw node may have moved."""
        try:
            os.close(self.fd)
        except OSError:
            pass
        deadline = time.monotonic() + timeout
        denied = False
        while time.monotonic() < deadline:
            try:
                self.dev = find_device()
                self.fd = os.open(self.dev, os.O_RDWR)
                return True
            except PermissionError:
                denied = True
            except (SystemExit, OSError):
                pass
            time.sleep(0.5)
        if denied:
            print(
                f"{self.dev}: permission denied after reconnect — the fresh "
                "node is root-owned; install 60-hydra-rgb.rules or re-grant access"
            )
        return False

    def set_slot(self, slot, r, g, b):
        self.rgb[slot * 3 : slot * 3 + 3] = bytes((r, g, b))

    def set_key(self, name, r, g, b):
        self.set_slot(SLOT[name], r, g, b)

    def fill(self, r, g, b):
        for s in range(NUM_SLOTS):
            self.set_slot(s, r, g, b)

    def clear(self):
        self.rgb = bytearray(NUM_SLOTS * 3)

    def flush(self):
        pkt = bytearray(PKT_LEN)
        pkt[:8] = HDR
        pkt[8 : 8 + len(self.rgb)] = self.rgb
        fcntl.ioctl(self.fd, HIDIOCSFEATURE(PKT_LEN), pkt, True)


def parse_hex(s):
    s = s.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def hsv(h, s=1.0, v=1.0):
    i = int(h * 6) % 6
    f = h * 6 - int(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return int(r * 255), int(g * 255), int(b * 255)


def default_monitor():
    try:
        sink = subprocess.check_output(
            ["pactl", "get-default-sink"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        raise SystemExit(
            "could not query default sink (is pactl/PipeWire running?); "
            "pass --source explicitly (pactl list short sources)"
        )
    return sink + ".monitor"


class AudioTap:
    """Non-blocking system-audio capture: parec on a monitor source, or stdin."""

    def __init__(self, source, rate, nsamples):
        self.nsamples = nsamples
        self.nbytes = nsamples * 2  # s16le mono
        self.buf = bytearray()
        self.drained = 0  # bytes since last check (debug aid)
        self.eof = False
        if source == "-":
            self.proc = None
            self.source = "<stdin>"
            self.fd = sys.stdin.buffer.fileno()
        else:
            self.source = source or default_monitor()
            self.proc = subprocess.Popen(
                [
                    "parec",
                    "--raw",
                    "--format=s16le",
                    f"--rate={rate}",
                    "--channels=1",
                    f"--device={self.source}",
                    "--latency-msec=20",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.fd = self.proc.stdout.fileno()
        os.set_blocking(self.fd, False)

    def read(self):
        """Drain the pipe; return the latest window as int16 tuple, or None."""
        while True:
            try:
                chunk = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            if not chunk:
                self.eof = True
                if self.proc and self.proc.poll() is not None:
                    err = self.proc.stderr.read() or b""
                    raise SystemExit(
                        f"parec exited ({self.proc.returncode}): "
                        f"{err.decode(errors='replace').strip()}\n"
                        "pick a source: pactl list short sources"
                    )
                break
            self.buf += chunk
            self.drained += len(chunk)
        if len(self.buf) > self.nbytes:
            del self.buf[: len(self.buf) - self.nbytes]
        if len(self.buf) < self.nbytes:
            return None
        return struct.unpack(f"<{self.nsamples}h", bytes(self.buf))

    def close(self):
        if self.proc:
            self.proc.terminate()
            self.proc.wait()


class Spectrum:
    """Pure-python radix-2 FFT into log-spaced frequency bands"""

    def __init__(self, n, rate, nbands, fmin=50.0, fmax=16000.0):
        self.n = n
        bits = n.bit_length() - 1
        self.rev = [int(f"{i:0{bits}b}"[::-1], 2) for i in range(n)]
        self.win = [0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)) for i in range(n)]
        self.tw = {}
        m = 2
        while m <= n:
            self.tw[m] = [cmath.exp(-2j * math.pi * k / m) for k in range(m // 2)]
            m *= 2
        edges = [fmin * (fmax / fmin) ** (i / nbands) for i in range(nbands + 1)]
        self.bins = []
        for b in range(nbands):
            lo = max(1, round(edges[b] * n / rate))
            hi = min(max(lo + 1, round(edges[b + 1] * n / rate)), n // 2)
            self.bins.append((lo, hi))
        # gentle treble tilt so highs register against bass-heavy spectra
        self.tilt = [1.0 + 0.05 * b for b in range(nbands)]

    def bands(self, samples):
        """samples: int16 sequence of length n -> list of band magnitudes."""
        n, rev, win = self.n, self.rev, self.win
        x = [complex(samples[rev[i]] * win[rev[i]]) for i in range(n)]
        m = 2
        while m <= n:
            tw = self.tw[m]
            half = m // 2
            for start in range(0, n, m):
                for k in range(half):
                    a = x[start + k]
                    b = x[start + k + half] * tw[k]
                    x[start + k] = a + b
                    x[start + k + half] = a - b
            m *= 2
        out = []
        for (lo, hi), t in zip(self.bins, self.tilt):
            acc = 0.0
            for i in range(lo, hi):
                c = x[i]
                acc += c.real * c.real + c.imag * c.imag
            # band energy (sum, not mean): a pure tone reads the same in any
            # band, and wide treble bands offset music's natural 1/f falloff
            out.append(t * math.sqrt(acc) / (n * 32768.0))
        return out


def cell_coverage(level, row, shape):
    """Fraction [0..1] of a key at grid row 0(top)..4(bottom) lit by a column
    level in [0..1]."""
    if shape == "bars":  # grows bottom-up, 5 rows tall
        return min(1.0, max(0.0, level * 5 - (4 - row)))
    d = abs(row - 2)  # wave: mirrored around the home row
    half = level * 2.5
    if d == 0:
        return min(1.0, half * 2)
    return min(1.0, max(0.0, half - (d - 0.5)))


def run_audio(k, argv):
    p = argparse.ArgumentParser(
        prog="hydra_rgb.py audio", description="audio-reactive spectrum wave"
    )
    p.add_argument("--mode", choices=["colorful", "single"], default="colorful")
    p.add_argument("--color", default="009bde", help="color for single mode")
    p.add_argument("--gain", type=float, default=1.0, help="amplitude multiplier")
    p.add_argument("--smooth", type=float, default=1.0, help="smoothness multiplier")
    p.add_argument(
        "--effect",
        "--shape",  # backward-compatible alias
        dest="effect",
        choices=["wave", "bars", "vortex", "ripple"],
        default="wave",
        help="wave/bars = spectrum shapes; vortex/ripple = 2D audio-reactive fields",
    )
    p.add_argument(
        "--scroll",
        type=float,
        default=0.15,
        help="colorful-mode gradient scroll speed, hue cycles/sec "
        "left-to-right (0 = static); ignored by vortex (it spins on its own)",
    )
    p.add_argument(
        "--radius",
        type=float,
        default=0.18,
        help="vortex event-horizon (dark hole) radius, 0..1 (default 0.18)",
    )
    p.add_argument("--fps", type=float, default=30.0)
    p.add_argument("--rate", type=int, default=48000)
    p.add_argument("--source", default=None, help="pulse source name, or - for stdin")
    p.add_argument("--duration", type=float, default=None, help="stop after N seconds")
    p.add_argument("--debug", action="store_true")
    o = p.parse_args(argv)

    ncols = MAXCOL + 1
    N = 1024
    spec = Spectrum(N, o.rate, ncols)
    tap = AudioTap(o.source, o.rate, N)
    base = parse_hex(o.color)
    print(
        f"audio-reactive: source={tap.source} mode={o.mode} effect={o.effect} "
        f"gain={o.gain} smooth={o.smooth} fps={o.fps:g}"
    )

    smooth = max(o.smooth, 0.05)
    frame_dt = 1.0 / o.fps
    atk = math.exp(-frame_dt / (0.020 * smooth))
    dec = math.exp(-frame_dt / (0.150 * smooth))
    spatial = min(0.45, 0.15 * smooth)
    ref, REF_DECAY, REF_FLOOR = 1e-3, 0.998, 2e-4  # slow auto-gain reference
    levels = [0.0] * ncols
    raw = [0.0] * ncols
    rot_phase = 0.0  # accumulated vortex rotation (revolutions)
    ring_phase = 0.0  # accumulated ripple travel (ring cycles)
    t0 = time.monotonic()
    frames = 0
    try:
        while o.duration is None or time.monotonic() - t0 < o.duration:
            tstart = time.monotonic()
            samples = tap.read()
            t_fft = 0.0
            if samples:
                raw = spec.bands(samples)
                t_fft = time.monotonic() - tstart
            elif tap.eof:
                raw = [0.0] * ncols
            ref = max(ref * REF_DECAY, max(raw), REF_FLOOR)
            for i in range(ncols):
                target = min(1.0, (raw[i] / ref) ** 0.65 * o.gain)
                coef = atk if target > levels[i] else dec
                levels[i] = target + (levels[i] - target) * coef
            disp = [
                levels[i] * (1 - spatial)
                + (levels[max(i - 1, 0)] + levels[min(i + 1, ncols - 1)]) * spatial / 2
                for i in range(ncols)
            ]
            # per-frame audio features driving the 2D field effects
            t = tstart - t0
            energy = sum(levels) / ncols
            bass = (levels[0] + levels[1] + levels[2] + levels[3]) / 4.0
            hole = ring = 0.0
            if o.effect == "vortex":
                rot_phase += (VORTEX_BASE + energy * VORTEX_SPIN) * frame_dt
                hole = o.radius + bass * HOLE_SWELL  # event horizon breathes
                ring = hole + RING_GAP + bass * RING_PUSH  # disk shoved out by bass
            elif o.effect == "ripple":
                ring_phase += (RIPPLE_BASE + bass * RIPPLE_SPEED) * frame_dt

            for name, col, row in LAYOUT:
                if o.effect == "vortex":
                    nx, ny, rad, ang = GEOM[name]
                    if rad < hole:
                        val = 0.0  # inside the event horizon: dark void
                    else:
                        d = rad - ring
                        shape = math.exp(-(d * d) / (2.0 * RING_W * RING_W))
                        # each band lights its own angular sector of the ring
                        bi = int((ang / TAU + 0.5) * ncols) % ncols
                        val = shape * (0.12 + 0.88 * disp[bi])
                    # rainbow wrapped around the ring; rot_phase spins it
                    hue = ang / TAU + rot_phase + rad * 0.15
                elif o.effect == "ripple":
                    nx, ny, rad, ang = GEOM[name]
                    ring = 0.5 + 0.5 * math.cos((rad * RIPPLE_RINGS - ring_phase) * TAU)
                    core = max(0.0, 1.0 - rad * 1.8) * bass
                    val = min(1.0, ring * (0.12 + 0.88 * energy) + core)
                    hue = rad - o.scroll * t
                else:  # wave / bars: column spectrum, scrolling rainbow
                    val = cell_coverage(disp[col], row, o.effect)
                    hue = col / ncols - o.scroll * t

                if o.mode == "colorful":
                    k.set_key(name, *hsv(hue % 1.0, v=val))
                else:
                    k.set_key(name, *(int(c * val) for c in base))
            tflush = time.monotonic()
            try:
                k.flush()
            except OSError as e:
                if e.errno not in Kbd.GONE_ERRNOS:
                    raise
                print("keyboard dropped off the bus (firmware reset), reconnecting...")
                if not k.reopen():
                    raise SystemExit("reconnect failed")
                print(f"reconnected: {k.dev}")
            frames += 1
            if o.debug and frames % int(o.fps) == 0:
                now = time.monotonic()
                print(
                    f"peak={max(raw):.5f} ref={ref:.5f} "
                    f"levels[max]={max(levels):.2f} frame={(now - tstart) * 1000:.1f}ms "
                    f"(fft={t_fft * 1000:.1f} flush={(now - tflush) * 1000:.1f}) "
                    f"drained={tap.drained}B"
                )
                tap.drained = 0
            time.sleep(max(0.0, frame_dt - (time.monotonic() - tstart)))
    except KeyboardInterrupt:
        pass
    finally:
        tap.close()
        try:
            k.clear()
            k.flush()
        except OSError:
            pass
    print(f"{frames} frames in {time.monotonic() - t0:.1f}s")


def _flush(k):
    """Flush the current frame, transparently recovering from a firmware reset."""
    try:
        k.flush()
    except OSError as e:
        if e.errno not in Kbd.GONE_ERRNOS:
            raise
        print("keyboard dropped off the bus (firmware reset), reconnecting...")
        if not k.reopen():
            raise SystemExit("reconnect failed")
        print(f"reconnected: {k.dev}")
        try:
            k.flush()
        except OSError:
            pass


def hold(k, label, interval=1.0):
    """Keep the current frame on the board until Ctrl-C. These keyboards revert
    to their onboard firmware lighting once host traffic stops, so we re-send
    the frame on an interval to hold it (and ride out the board's resets)."""
    print(f"holding {label}; press Ctrl-C to stop")
    try:
        while True:
            time.sleep(interval)
            _flush(k)
    except KeyboardInterrupt:
        pass


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 1
    # color modes hold the frame until Ctrl-C (the board reverts to onboard
    # lighting when streaming stops); --once sets one frame and exits.
    once = "--once" in a
    a = [x for x in a if x != "--once"]
    cmd = a[0]
    k = Kbd()
    print(f"device: {k.dev}")
    if cmd == "color":
        k.fill(*parse_hex(a[1]))
        k.flush()
        if not once:
            hold(k, "color")
    elif cmd == "off":
        k.clear()
        k.flush()
    elif cmd == "key":
        k.clear()
        for name, col in zip(a[1::2], a[2::2]):
            k.set_key(name.lower(), *parse_hex(col))
        k.flush()
        if not once:
            hold(k, "key colors")
    elif cmd == "gradient":
        c1, c2 = parse_hex(a[1]), parse_hex(a[2])
        for name, col, row in LAYOUT:
            t = col / MAXCOL
            k.set_key(name, *(int(x + (y - x) * t) for x, y in zip(c1, c2)))
        k.flush()
        if not once:
            hold(k, "gradient")
    elif cmd == "rainbow":
        for name, col, row in LAYOUT:
            k.set_key(name, *hsv(col / (MAXCOL + 1)))
        k.flush()
        if not once:
            hold(k, "rainbow")
    elif cmd == "wave":
        dur = float(a[1]) if len(a) > 1 else None  # None = run until Ctrl-C
        t0 = time.time()
        try:
            while dur is None or time.time() - t0 < dur:
                ph = (time.time() - t0) * 0.4
                for name, col, row in LAYOUT:
                    k.set_key(name, *hsv((col / (MAXCOL + 1) + ph) % 1.0))
                _flush(k)
                time.sleep(1 / 60)
        except KeyboardInterrupt:
            pass
    elif cmd == "audio":
        run_audio(k, a[1:])
    elif cmd == "raw":
        data = bytes.fromhex("".join(a[1:]))
        buf = bytearray(data)
        fcntl.ioctl(k.fd, HIDIOCSFEATURE(len(buf)), buf, True)
        print(f"sent {len(buf)} bytes")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
