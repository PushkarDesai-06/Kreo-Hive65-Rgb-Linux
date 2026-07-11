#!/usr/bin/env python3
"""RGB control for SinoWealth / BY Tech RGB keyboards on Linux.

Each supported board is described by a JSON *profile* in profiles/ (USB id,
frame format, and key→LED layout); the driver auto-detects the attached board
and every effect reads its geometry from the profile, so the same code drives
different-sized keyboards. Adding a board is a new profiles/<id>.json file — no
code changes. See kbd_profiles.py. The default board is the Kreo Hive 65
(258a:010c): report 6, 520-byte frame, 68 keys, LED index = col*6 + row + 1.

Board selection (any subcommand):
  --profile NAME     force a specific profile (see --list-profiles)
  --device /dev/hidrawN   force the hidraw node
  --vid XXXX --pid XXXX   also match this USB id (test an uninstalled rebrand)
  --list-profiles    list known boards and exit

Usage:
  hydra_rgb.py color <rrggbb>              # whole board one color
  hydra_rgb.py key <keyname> <rrggbb> ...  # per-key colors (pairs), rest off
  hydra_rgb.py gradient <rrggbb> <rrggbb>  # left-to-right gradient
  hydra_rgb.py rainbow                     # rainbow across columns
  hydra_rgb.py wave [seconds]              # animated hue wave (forever if no time)
  hydra_rgb.py off                         # all LEDs off
  hydra_rgb.py raw <hex...>                # send raw feature report
  hydra_rgb.py walk [--delay S] [--start N] [--end N]
      # light one LED slot at a time to map a new board's layout (report-6 only)

  color/key/gradient/rainbow/wave stay on until Ctrl-C: the board reverts to
  its onboard lighting once streaming stops, so the tool holds the frame by
  re-sending it. Add --once to set a single frame and exit (for scripts).
  hydra_rgb.py audio [options]             # audio-reactive spectrum wave
      --mode colorful|single   coloring (default colorful = 4-color gradient)
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
      --default NAME           non-audio effect shown when music is silent:
                               gradient(default)|breathe|wave|off. After
                               --idle-gap secs of silence it crossfades in;
                               sound returning fades back to audio instantly.
      --idle-gap SEC           silence before switching to --default (5.0)
      --silence-level FLOAT    peak below this = silence (0.004; tune per system)
      --fps N --source NAME --duration SEC --debug
    Captures system sound from the default sink's monitor via parec
    (PipeWire/PulseAudio); override with --source (see: pactl list short
    sources), or --source - to pipe raw s16le mono PCM on stdin.

Device node + profile autodetected from /sys/class/hidraw (USB id + report id).
"""

import argparse
import cmath
import json
import math
import struct
import subprocess
import sys
import os
import fcntl
import glob
import time

import kbd_profiles


def _IOC(dirn, typ, nr, size):
    return (dirn << 30) | (size << 16) | (ord(typ) << 8) | nr


def HIDIOCSFEATURE(length):
    return _IOC(3, "H", 0x06, length)


# --- keyboard identity + protocol + layout live in profiles/*.json -----------
# Loaded once at import; adding a board is a new JSON file, not a code change.
# Each Kbd holds its own Profile (self.p) and every effect reads geometry/slots
# from it, so the same code drives boards of different sizes and frame formats.
PROFILES = kbd_profiles.load_all()
DEFAULT_PROFILE = "hive65"
_DEFAULT = PROFILES[DEFAULT_PROFILE]

# Back-compat aliases bound to the default profile so kbd_ws_server.py (which
# reads drv.LAYOUT / SLOT / NUM_SLOTS / MAXCOL / ROWS) keeps working unchanged.
LAYOUT = _DEFAULT.keys_tuples
SLOT = _DEFAULT.slot
NUM_SLOTS = _DEFAULT.num_slots
ROWS = _DEFAULT.rows
MAXCOL = _DEFAULT.cols - 1

TAU = 2.0 * math.pi
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
RIPPLE_RINGS = 1
RIPPLE_BASE = 0.05  # idle ring cycles/sec
RIPPLE_SPEED = 0.8  # extra cycles/sec driven by bass


def _match_node(sysfs_path, profiles):
    """Return the profile that owns this hidraw node (USB id matches and the
    profile's report id is present on this interface), or None."""
    try:
        with open(sysfs_path + "/device/uevent") as f:
            uevent = f.read().upper()
        with open(sysfs_path + "/device/report_descriptor", "rb") as f:
            desc = f.read()
    except OSError:
        # node is mid-teardown during a firmware reset; skip it
        return None
    for prof in profiles:
        if prof.matches_uevent(uevent) and prof.desc_marker() in desc:
            return prof
    return None


def find_device(profiles=None, sysfs_root="/sys/class/hidraw"):
    """Scan hidraw nodes for a known keyboard. Returns (devnode, Profile).

    `profiles` restricts the search (e.g. to a --profile choice); default is all
    loaded profiles. On multiple matches with no restriction, the first is used
    and the alternatives are reported so the user can disambiguate."""
    if profiles is None:
        profiles = list(PROFILES.values())
    matches = []
    for path in sorted(glob.glob(sysfs_root + "/hidraw*")):
        prof = _match_node(path, profiles)
        if prof is not None:
            matches.append(("/dev/" + os.path.basename(path), prof))
    if not matches:
        known = ", ".join(sorted({u for p in profiles for u in p.usb_ids}))
        raise SystemExit(
            "keyboard vendor interface not found (is it plugged in, wired mode?). "
            f"known ids: {known} — see --list-profiles"
        )
    if len(matches) > 1:
        alts = ", ".join(f"{d} ({p.id})" for d, p in matches)
        print(f"multiple keyboards matched: {alts}; using {matches[0][0]} "
              "(pick one with --device/--profile)", file=sys.stderr)
    return matches[0]


class Kbd:
    # errnos seen when the board's firmware resets and it re-enumerates
    GONE_ERRNOS = (5, 19, 32, 71)  # EIO, ENODEV, EPIPE, EPROTO

    def __init__(self, profile=None, dev=None):
        if profile is None or dev is None:
            found_dev, found_prof = find_device(
                [profile] if profile is not None else None
            )
            profile = profile or found_prof
            dev = dev or found_dev
        self.p = profile
        self.dev = dev
        self.fd = os.open(self.dev, os.O_RDWR)
        self.rgb = bytearray(profile.num_slots * 3)

    def reopen(self, timeout=10.0):
        """Reattach after a USB drop; the hidraw node may have moved. Re-locks
        onto the same profile so a firmware reset can't switch boards."""
        try:
            os.close(self.fd)
        except OSError:
            pass
        deadline = time.monotonic() + timeout
        denied = False
        while time.monotonic() < deadline:
            try:
                self.dev = find_device([self.p])[0]
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
        # store in the board's wire byte order (e.g. GRB) so the buffer can be
        # streamed as-is; 'rgb' boards are unaffected
        self.rgb[slot * 3 : slot * 3 + 3] = bytes(
            kbd_profiles.reorder(self.p.color_order, r, g, b)
        )

    def set_key(self, name, r, g, b):
        self.set_slot(self.p.slot[name], r, g, b)

    def fill(self, r, g, b):
        for s in range(self.p.num_slots):
            self.set_slot(s, r, g, b)

    def clear(self):
        self.rgb = bytearray(self.p.num_slots * 3)

    def build_packet(self):
        """The exact bytes flush() would SET_FEATURE — the testable seam."""
        return self.p.encode(self.rgb)

    def flush(self):
        pkt = bytearray(self.build_packet())
        fcntl.ioctl(self.fd, HIDIOCSFEATURE(len(pkt)), pkt, True)


def parse_hex(s):
    s = s.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def hsv(h, s=1.0, v=1.0):
    i = int(h * 6) % 6
    f = h * 6 - int(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return int(r * 255), int(g * 255), int(b * 255)


# "colorful" mode palette — the Gradient Lab default (red / violet / cyan / amber)
COLORFUL_PALETTE = [
    (0xFF, 0x42, 0x42),
    (0x7C, 0x3A, 0xED),
    (0x06, 0xB6, 0xD4),
    (0xEA, 0xB3, 0x08),
]


def palette_at(u, v=1.0, palette=COLORFUL_PALETTE):
    """Sample a looping gradient of `palette` at position u (wraps), scaled by
    brightness v. Mirrors the web Gradient Lab's palAt so colorful mode matches."""
    n = len(palette)
    x = ((u % 1.0) + 1.0) % 1.0 * n
    i = int(x) % n
    f = x - int(x)
    a, b = palette[i], palette[(i + 1) % n]
    return tuple(int((a[c] + (b[c] - a[c]) * f) * v) for c in range(3))


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


def cell_coverage(level, row, rows, shape):
    """Fraction [0..1] of a key at grid row 0(top)..rows-1(bottom) lit by a
    column level in [0..1]. Scales to any row count (identical at rows=5)."""
    if shape == "bars":  # grows bottom-up, `rows` tall
        return min(1.0, max(0.0, level * rows - (rows - 1 - row)))
    center = (rows - 1) / 2.0  # wave: mirrored around the middle row
    d = abs(row - center)
    half = level * (rows / 2.0)
    if d < 0.5:
        return min(1.0, half * 2)
    return min(1.0, max(0.0, half - (d - 0.5)))


def idle_color(effect, col, row, ncols, t):
    """Non-audio 'default' effect shown when music is silent — uses the same
    COLORFUL_PALETTE as colorful mode. `t` is elapsed seconds."""
    if effect == "off":
        return (0, 0, 0)
    if effect == "breathe":  # whole board drifts through the palette, breathing
        v = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 1.2))
        return palette_at(t * 0.05, v=v)
    if effect == "wave":  # palette gradient with a brightness wave rolling across
        vv = 0.5 + 0.5 * math.sin(col * 0.55 - t * 2.2)
        return palette_at(col / ncols - t * 0.08, v=0.35 + 0.65 * vv)
    # gradient (default): the Gradient Lab look — palette scrolling across columns
    return palette_at(col / ncols - t * 0.08)


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
    p.add_argument(
        "--default",
        choices=["gradient", "breathe", "wave", "off"],
        default="gradient",
        help="non-audio effect to crossfade to when music is silent",
    )
    p.add_argument(
        "--idle-gap",
        dest="idle_gap",
        type=float,
        default=5.0,
        help="seconds of silence before switching to the --default effect",
    )
    p.add_argument(
        "--silence-level",
        dest="silence_level",
        type=float,
        default=0.004,
        help="audio peak below this counts as silence (tune per system)",
    )
    p.add_argument("--debug", action="store_true")
    o = p.parse_args(argv)

    ncols = k.p.cols
    N = 1024
    spec = Spectrum(N, o.rate, ncols)
    tap = AudioTap(o.source, o.rate, N)
    base = parse_hex(o.color)
    print(
        f"audio-reactive: source={tap.source} mode={o.mode} effect={o.effect} "
        f"gain={o.gain} smooth={o.smooth} fps={o.fps:g} "
        f"default={o.default} idle-gap={o.idle_gap:g}s"
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
    # idle<->audio crossfade: mix 0 = idle (default effect), 1 = audio-reactive
    mix = 0.0  # start on the idle effect; fade up when music begins
    TAU_UP, TAU_DOWN = 0.30, 0.90  # crossfade time constants (up = snappier)
    t0 = time.monotonic()
    last_sound_t = t0 - o.idle_gap - 1.0  # treat startup as already-silent
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
            # idle/audio crossfade: any sound refreshes the timer and keeps us
            # in audio; only after idle_gap seconds of silence do we ease over
            # to the --default effect. Sound returning snaps target back to
            # audio at once, but the mix still eases (no hard cuts either way).
            if max(raw) > o.silence_level:
                last_sound_t = tstart
            m_target = 1.0 if (tstart - last_sound_t) < o.idle_gap else 0.0
            tau = TAU_UP if m_target > mix else TAU_DOWN
            mix += (m_target - mix) * (1.0 - math.exp(-frame_dt / tau))
            energy = sum(levels) / ncols
            bass = (levels[0] + levels[1] + levels[2] + levels[3]) / 4.0
            hole = ring = 0.0
            if o.effect == "vortex":
                rot_phase += (VORTEX_BASE + energy * VORTEX_SPIN) * frame_dt
                hole = o.radius + bass * HOLE_SWELL  # event horizon breathes
                ring = hole + RING_GAP + bass * RING_PUSH  # disk shoved out by bass
            elif o.effect == "ripple":
                ring_phase += (RIPPLE_BASE + bass * RIPPLE_SPEED) * frame_dt

            for name, col, row in k.p.keys_tuples:
                if o.effect == "vortex":
                    nx, ny, rad, ang = k.p.geom[name]
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
                    nx, ny, rad, ang = k.p.geom[name]
                    ring = 0.5 + 0.5 * math.cos((rad * RIPPLE_RINGS - ring_phase) * TAU)
                    core = max(0.0, 1.0 - rad * 1.8) * bass
                    val = min(1.0, ring * (0.12 + 0.88 * energy) + core)
                    hue = rad - o.scroll * t
                else:  # wave / bars: column spectrum, scrolling gradient
                    val = cell_coverage(disp[col], row, k.p.rows, o.effect)
                    hue = col / ncols - o.scroll * t

                if o.mode == "colorful":
                    a_rgb = palette_at(hue, v=val)
                else:
                    a_rgb = (int(base[0] * val), int(base[1] * val), int(base[2] * val))
                if mix >= 0.999:  # fully audio
                    k.set_key(name, *a_rgb)
                else:  # crossfade toward the idle default effect
                    ir, ig, ib = idle_color(o.default, col, row, ncols, t)
                    k.set_key(
                        name,
                        int(ir + (a_rgb[0] - ir) * mix),
                        int(ig + (a_rgb[1] - ig) * mix),
                        int(ib + (a_rgb[2] - ib) * mix),
                    )
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
                state = "audio" if mix > 0.5 else o.default
                print(
                    f"peak={max(raw):.5f} mix={mix:.2f}({state}) "
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


def hold(k, label, interval=None):
    """Keep the current frame on the board until Ctrl-C. These keyboards revert
    to their onboard firmware lighting once host traffic stops, so we re-send
    the frame on an interval to hold it (and ride out the board's resets)."""
    if interval is None:
        hz = k.p.keepalive_hz
        interval = 1.0 / hz if hz > 0 else 1.0
    print(f"holding {label}; press Ctrl-C to stop")
    try:
        while True:
            time.sleep(interval)
            _flush(k)
    except KeyboardInterrupt:
        pass


def run_walk(k, argv):
    """Light one LED slot at a time so you can see which physical key each slot
    drives — the way to map a brand-new board's layout. Strictly report-6 (the
    RGB framebuffer), so it can never touch the report-5 flash/ISP channel."""
    p = argparse.ArgumentParser(
        prog="hydra_rgb.py walk",
        description="sweep-light LED slots to map a new keyboard's layout",
    )
    p.add_argument("--delay", type=float, default=0.6, help="seconds per slot")
    p.add_argument("--color", default="ffffff", help="slot color (default white)")
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--end", type=int, default=None, help="last slot (default all)")
    o = p.parse_args(argv)
    end = o.end if o.end is not None else k.p.num_slots - 1
    col = parse_hex(o.color)
    print(f"walking slots {o.start}..{end} on {k.p.name}.")
    print("note which physical key lights for each slot; Ctrl-C to stop.\n")
    lit = []
    try:
        for s in range(o.start, end + 1):
            k.clear()
            k.set_slot(s, *col)
            _flush(k)
            print(f"  slot {s}")
            lit.append(s)
            time.sleep(o.delay)
    except KeyboardInterrupt:
        print("\n(stopped)")
    finally:
        k.clear()
        _flush(k)
    # emit a layout skeleton to fill in: replace each name/col/row from what you
    # saw, then save as profiles/<id>.json (copy the protocol block from a probe)
    skel = [{"name": f"slot{s}", "col": 0, "row": 0, "slot": s} for s in lit]
    print("\n# layout skeleton (edit name/col/row per what lit, then save):")
    print(json.dumps({"keys": skel}, indent=2))


def _take_opt(a, name):
    """Pull `--name VALUE` out of arg list a, returning VALUE (or None)."""
    if name in a:
        i = a.index(name)
        val = a[i + 1] if i + 1 < len(a) else None
        del a[i : i + 2]
        return val
    return None


def _select_profile(prof_name, vid, pid):
    """Resolve the profile list to search: a named profile, optionally with an
    extra runtime VID:PID (for an uninstalled same-family board)."""
    if prof_name is not None:
        if prof_name not in PROFILES:
            raise SystemExit(
                f"unknown profile {prof_name!r}; known: {', '.join(sorted(PROFILES))}"
            )
        chosen = [PROFILES[prof_name]]
    else:
        chosen = list(PROFILES.values())
    if vid and pid:
        extra = kbd_profiles._norm_usb(f"{vid}:{pid}")
        for p in chosen:  # match this id too, using the chosen board's protocol
            if extra not in p.usb_ids:
                p.usb_ids.append(extra)
    return chosen


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 1
    # global options (parsed out before the subcommand)
    prof_name = _take_opt(a, "--profile")
    dev_override = _take_opt(a, "--device")
    vid = _take_opt(a, "--vid")
    pid = _take_opt(a, "--pid")
    profiles = _select_profile(prof_name, vid, pid)
    if "--list-profiles" in a:
        for pid_, p in PROFILES.items():
            print(f"{pid_:12s} {p.name}  ({p.key_count()} keys, {p.cols}x{p.rows}, "
                  f"{p.pkt_len}B, usb={','.join(p.usb_ids)})")
        return 0
    if not a:
        print(__doc__)
        return 1
    # color modes hold the frame until Ctrl-C (the board reverts to onboard
    # lighting when streaming stops); --once sets one frame and exits.
    once = "--once" in a
    a = [x for x in a if x != "--once"]
    cmd = a[0]
    if dev_override:
        # forced node: detect its profile (unless --profile pinned it)
        sysfs = os.path.join("/sys/class/hidraw", os.path.basename(dev_override))
        prof = PROFILES[prof_name] if prof_name else _match_node(sysfs, profiles)
        if prof is None:
            raise SystemExit(f"{dev_override}: no known profile matches this node")
        k = Kbd(profile=prof, dev=dev_override)
    else:
        dev, prof = find_device(profiles)
        k = Kbd(profile=prof, dev=dev)
    print(f"device: {k.dev} ({k.p.name})")
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
        denom = (k.p.cols - 1) or 1
        for name, col, row in k.p.keys_tuples:
            t = col / denom
            k.set_key(name, *(int(x + (y - x) * t) for x, y in zip(c1, c2)))
        k.flush()
        if not once:
            hold(k, "gradient")
    elif cmd == "rainbow":
        for name, col, row in k.p.keys_tuples:
            k.set_key(name, *hsv(col / k.p.cols))
        k.flush()
        if not once:
            hold(k, "rainbow")
    elif cmd == "wave":
        dur = float(a[1]) if len(a) > 1 else None  # None = run until Ctrl-C
        t0 = time.time()
        try:
            while dur is None or time.time() - t0 < dur:
                ph = (time.time() - t0) * 0.4
                for name, col, row in k.p.keys_tuples:
                    k.set_key(name, *hsv((col / k.p.cols + ph) % 1.0))
                _flush(k)
                time.sleep(1 / 60)
        except KeyboardInterrupt:
            pass
    elif cmd == "audio":
        run_audio(k, a[1:])
    elif cmd == "walk":
        run_walk(k, a[1:])
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
