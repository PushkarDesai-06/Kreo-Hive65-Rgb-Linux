#!/usr/bin/env python3
"""Effect rendering: static effects (gradient / rainbow / wave) and the
audio-reactive spectrum and 2D-field visualizers. Every effect reads its grid
geometry from the active profile (`k.p`), so the same code scales to any board.

Each render helper fills the Kbd frame buffer; the animated ones own their loop
and re-send via device._flush (which rides out firmware resets)."""
import argparse
import math
import time

from audio import AudioTap, Spectrum
from color import hsv, palette_at, parse_hex
from device import Kbd, _flush

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
# split: the left edge is a bass source, the right edge a treble source; each
# glows from its own side and fades to dark in the middle, so the light reads as
# originating from the two sides. Bass shows warm (red), treble cool (cyan).
SPLIT_BASS_HUE = 0.0
SPLIT_TREBLE_HUE = 0.5
# flow: only the LEFT column samples the bass "now"; every other column shows the
# bass level from a moment earlier, so a bass punch enters at the left edge and
# travels across to the right like a waterfall. Columns read a smoothly
# interpolated slice of that history (no blocky per-column steps). Travel speed
# is set by --flow-speed (columns/sec).
FLOW_SPEED_DEFAULT = 8.0  # columns/sec a bass punch travels across the board


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


def bar_fill(level, idx, n):
    """Coverage [0..1] of cell `idx` (0-based) in a stack of `n`, for a bar of
    normalized length `level` growing from idx 0 outward. cell 0 lights first,
    cell n-1 last; the bar reaches the far end at level 1. Direction is chosen by
    the caller's choice of idx (e.g. row vs rows-1-row flips top/bottom)."""
    return min(1.0, max(0.0, level * n - idx))


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


def render_gradient(k, c1, c2):
    """Left-to-right interpolation between two colors across the columns."""
    denom = (k.p.cols - 1) or 1
    for name, col, row in k.p.keys_tuples:
        t = col / denom
        k.set_key(name, *(int(x + (y - x) * t) for x, y in zip(c1, c2)))


def render_rainbow(k):
    """Static hue sweep across the columns."""
    for name, col, row in k.p.keys_tuples:
        k.set_key(name, *hsv(col / k.p.cols))


def run_wave(k, dur):
    """Animated hue wave rolling across the columns until Ctrl-C (or `dur` secs)."""
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


# --- audio-reactive effect registry -----------------------------------------
# Each effect is a small strategy object: it declares whether it runs one band
# per row (horizontal) or per column, sets up any cross-frame state in __init__,
# advances that state once per frame in frame(), and returns (val, hue) for one
# key in render(). Adding an effect is a new class + one EFFECTS entry — the
# render loop in run_audio never changes. Mirrors the ENCODERS registry in
# kbd_profiles: dispatch by name, open for extension, closed for modification.


class _Frame:
    """Per-frame audio features handed to the active effect's frame()/render()."""

    __slots__ = ("disp", "energy", "bass", "treble", "t")

    def __init__(self, disp, energy, bass, treble, t):
        self.disp = disp
        self.energy = energy
        self.bass = bass
        self.treble = treble
        self.t = t


class Effect:
    """Base audio effect. Subclasses override frame()/render() (and is_horizontal
    when the band-per-row vs band-per-column choice depends on the options)."""

    horizontal = False  # band-per-row when True, band-per-column when False

    @classmethod
    def is_horizontal(cls, o):
        return cls.horizontal

    def __init__(self, k, o, nlanes):
        self.o = o
        self.ncols = k.p.cols
        self.nrows = k.p.rows
        self.nlanes = nlanes
        self.geom = k.p.geom

    def frame(self, f, frame_dt):
        """Advance cross-frame state before the per-key render pass (default: none)."""

    def render(self, f, name, col, row):
        """Return (val, hue) in [0..1] for one key."""
        raise NotImplementedError


class WaveEffect(Effect):
    """Center-out column spectrum with a scrolling gradient."""

    def render(self, f, name, col, row):
        val = cell_coverage(f.disp[col], row, self.nrows, "wave")
        hue = col / self.ncols - self.o.scroll * f.t
        return val, hue


class BarsEffect(Effect):
    """Equalizer bars; --direction picks the edge they grow from. left/right/sides
    are horizontal (one band per row); bottom/top are vertical (one per column)."""

    @classmethod
    def is_horizontal(cls, o):
        return o.direction in ("left", "right", "sides")

    def render(self, f, name, col, row):
        o, disp, ncols, nrows = self.o, f.disp, self.ncols, self.nrows
        if o.direction == "bottom":  # grow bottom-up (per column)
            val = bar_fill(disp[col], nrows - 1 - row, nrows)
            hue = col / ncols - o.scroll * f.t
        elif o.direction == "top":  # grow top-down (per column)
            val = bar_fill(disp[col], row, nrows)
            hue = col / ncols - o.scroll * f.t
        elif o.direction == "left":  # grow left-to-right (per row)
            val = bar_fill(disp[row], col, ncols)
            hue = row / nrows - o.scroll * f.t
        elif o.direction == "right":  # grow right-to-left (per row)
            val = bar_fill(disp[row], ncols - 1 - col, ncols)
            hue = row / nrows - o.scroll * f.t
        else:  # sides: grow inward from both edges toward the middle
            edge = min(col, ncols - 1 - col)
            val = bar_fill(disp[row], edge, ncols // 2 + 1)
            hue = row / nrows - o.scroll * f.t
        return val, hue


class SplitEffect(Effect):
    """Bass grows from the left edge, treble from the right, dark in the middle."""

    def render(self, f, name, col, row):
        ncols = self.ncols
        x = col / (ncols - 1) if ncols > 1 else 0.0
        left = f.bass * max(0.0, 1.0 - 2.0 * x)  # bright at left -> 0 mid
        right = f.treble * max(0.0, 2.0 * x - 1.0)  # 0 mid -> bright right
        if left >= right:
            val, hue0 = left, SPLIT_BASS_HUE
        else:
            val, hue0 = right, SPLIT_TREBLE_HUE
        val = min(1.0, val)
        hue = hue0 - self.o.scroll * f.t
        return val, hue


class FlowEffect(Effect):
    """Bass waterfall: the left column samples the bass now and that punch scrolls
    left-to-right. flow_hist[0] is the newest (left edge); column `col` reads the
    bass from col/flow_cpf frames ago, linearly interpolated for a smooth glide."""

    def __init__(self, k, o, nlanes):
        super().__init__(k, o, nlanes)
        frame_dt = 1.0 / o.fps
        self.flow_cpf = max(1e-4, o.flow_speed * frame_dt)  # columns advanced per frame
        self.flow_len = min(4096, int(self.ncols / self.flow_cpf) + 4)
        self.flow_hist = [0.0] * self.flow_len

    def frame(self, f, frame_dt):
        self.flow_hist.insert(0, f.bass)  # push the current bass onto the left, scroll
        del self.flow_hist[self.flow_len:]

    def render(self, f, name, col, row):
        fidx = col / self.flow_cpf
        lo = int(fidx)
        fr = fidx - lo
        hist, hlen = self.flow_hist, self.flow_len
        if lo + 1 < hlen:
            bv = hist[lo] * (1.0 - fr) + hist[lo + 1] * fr
        elif lo < hlen:
            bv = hist[lo]
        else:
            bv = 0.0
        val = bar_fill(bv, self.nrows - 1 - row, self.nrows)  # bottom-up, soft top
        hue = col / self.ncols - self.o.scroll * f.t
        return val, hue


class VortexEffect(Effect):
    """Black hole: a dark event horizon ringed by a rainbow accretion disk that
    spins faster when louder; bass swells the hole and shoves the ring outward."""

    def __init__(self, k, o, nlanes):
        super().__init__(k, o, nlanes)
        self.rot_phase = 0.0  # accumulated rotation (revolutions)
        self.hole = 0.0
        self.ring = 0.0

    def frame(self, f, frame_dt):
        self.rot_phase += (VORTEX_BASE + f.energy * VORTEX_SPIN) * frame_dt
        self.hole = self.o.radius + f.bass * HOLE_SWELL  # event horizon breathes
        self.ring = self.hole + RING_GAP + f.bass * RING_PUSH  # disk shoved out by bass

    def render(self, f, name, col, row):
        nx, ny, rad, ang = self.geom[name]
        if rad < self.hole:
            val = 0.0  # inside the event horizon: dark void
        else:
            d = rad - self.ring
            shape = math.exp(-(d * d) / (2.0 * RING_W * RING_W))
            # each band lights its own angular sector of the ring
            bi = int((ang / TAU + 0.5) * self.ncols) % self.ncols
            val = shape * (0.12 + 0.88 * f.disp[bi])
        hue = ang / TAU + self.rot_phase + rad * 0.15  # rainbow spun by rot_phase
        return val, hue


class RippleEffect(Effect):
    """Concentric rings pushed outward by bass hits."""

    def __init__(self, k, o, nlanes):
        super().__init__(k, o, nlanes)
        self.ring_phase = 0.0  # accumulated ripple travel (ring cycles)

    def frame(self, f, frame_dt):
        self.ring_phase += (RIPPLE_BASE + f.bass * RIPPLE_SPEED) * frame_dt

    def render(self, f, name, col, row):
        nx, ny, rad, ang = self.geom[name]
        ring = 0.5 + 0.5 * math.cos((rad * RIPPLE_RINGS - self.ring_phase) * TAU)
        core = max(0.0, 1.0 - rad * 1.8) * f.bass
        val = min(1.0, ring * (0.12 + 0.88 * f.energy) + core)
        hue = rad - self.o.scroll * f.t
        return val, hue


# name -> effect class; the --effect choices and the render dispatch both read this
EFFECTS = {
    "wave": WaveEffect,
    "bars": BarsEffect,
    "vortex": VortexEffect,
    "ripple": RippleEffect,
    "split": SplitEffect,
    "flow": FlowEffect,
}


def run_audio(k, argv):
    p = argparse.ArgumentParser(
        prog="keyboardrgb.py audio", description="audio-reactive spectrum wave"
    )
    p.add_argument("--mode", choices=["colorful", "single"], default="colorful")
    p.add_argument("--color", default="009bde", help="color for single mode")
    p.add_argument("--gain", type=float, default=1.0, help="amplitude multiplier")
    p.add_argument("--smooth", type=float, default=1.0, help="smoothness multiplier")
    p.add_argument(
        "--effect",
        "--shape",  # backward-compatible alias
        dest="effect",
        choices=list(EFFECTS),
        default="wave",
        help="wave/bars = spectrum shapes; vortex/ripple = 2D audio-reactive "
        "fields; split = bass grows from the left edge, treble from the right; "
        "flow = the left column tracks the bass and that punch travels "
        "left-to-right across the board (see --flow-speed)",
    )
    p.add_argument(
        "--direction",
        "--dir",
        dest="direction",
        choices=["bottom", "top", "left", "right", "sides"],
        default="bottom",
        help="bars only: which edge the bars grow from — bottom (default) or top "
        "(vertical), left/right (horizontal), or sides (inward from both edges)",
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
    p.add_argument(
        "--flow-speed",
        dest="flow_speed",
        type=float,
        default=FLOW_SPEED_DEFAULT,
        help="flow only: how fast a bass punch travels left-to-right, in "
        f"columns/sec (default {FLOW_SPEED_DEFAULT:g}); lower = slower travel",
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
    nrows = k.p.rows
    fx_cls = EFFECTS[o.effect]
    # Horizontal bars run one frequency band per row (bars grow sideways); every
    # other effect runs one band per column. The spectrum is sized to match, and
    # `disp` is indexed by row for horizontal bars, by column otherwise.
    nlanes = nrows if fx_cls.is_horizontal(o) else ncols
    N = 1024
    spec = Spectrum(N, o.rate, nlanes)
    tap = AudioTap(o.source, o.rate, N)
    fx = fx_cls(k, o, nlanes)
    base = parse_hex(o.color)
    print(
        f"audio-reactive: source={tap.source} mode={o.mode} effect={o.effect}"
        f"{'/' + o.direction if o.effect == 'bars' else ''} "
        f"gain={o.gain} smooth={o.smooth} fps={o.fps:g} "
        f"default={o.default} idle-gap={o.idle_gap:g}s"
    )

    smooth = max(o.smooth, 0.05)
    frame_dt = 1.0 / o.fps
    atk = math.exp(-frame_dt / (0.020 * smooth))
    dec = math.exp(-frame_dt / (0.150 * smooth))
    spatial = min(0.45, 0.15 * smooth)
    ref, REF_DECAY, REF_FLOOR = 1e-3, 0.998, 2e-4  # slow auto-gain reference
    levels = [0.0] * nlanes
    raw = [0.0] * nlanes
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
                raw = [0.0] * nlanes
            ref = max(ref * REF_DECAY, max(raw), REF_FLOOR)
            for i in range(nlanes):
                target = min(1.0, (raw[i] / ref) ** 0.65 * o.gain)
                coef = atk if target > levels[i] else dec
                levels[i] = target + (levels[i] - target) * coef
            disp = [
                levels[i] * (1 - spatial)
                + (levels[max(i - 1, 0)] + levels[min(i + 1, nlanes - 1)]) * spatial / 2
                for i in range(nlanes)
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
            energy = sum(levels) / nlanes
            nb = min(4, nlanes)  # lowest/highest bands -> bass/treble scalars
            bass = sum(levels[:nb]) / nb
            treble = sum(levels[nlanes - nb:]) / nb
            f = _Frame(disp, energy, bass, treble, t)
            fx.frame(f, frame_dt)

            for name, col, row in k.p.keys_tuples:
                val, hue = fx.render(f, name, col, row)
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


def apply_look(rgb, sat, gain, gamma):
    """Punch up a captured pixel for RGB LEDs: push saturation away from its
    luma, optional gamma, then a brightness gain. sat=gain=gamma=1 is a no-op
    (faithful). Returns a clamped 0..255 (r,g,b)."""
    r, g, b = rgb
    if sat != 1.0:
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        r = luma + (r - luma) * sat
        g = luma + (g - luma) * sat
        b = luma + (b - luma) * sat
    if gamma != 1.0:
        inv = 1.0 / gamma
        r = 255.0 * (max(0.0, r) / 255.0) ** inv
        g = 255.0 * (max(0.0, g) / 255.0) ** inv
        b = 255.0 * (max(0.0, b) / 255.0) ** inv
    r, g, b = r * gain, g * gain, b * gain
    return (
        min(255, max(0, int(r))),
        min(255, max(0, int(g))),
        min(255, max(0, int(b))),
    )


def run_screen(k, argv):
    """Mirror a monitor onto the keyboard: capture at 144p, blur, and stream it
    to the keys. Follows the focused monitor by default (Hyprland). Held live by
    re-sending each frame, so no separate keepalive is needed."""
    from screen import ScreenTap

    p = argparse.ArgumentParser(
        prog="keyboardrgb.py screen",
        description="mirror a monitor onto the keyboard (144p, blurred)",
    )
    p.add_argument("--output", default=None,
                   help="monitor to capture (default: the focused one); "
                        "see hyprctl monitors / wlr-randr")
    p.add_argument("--follow", dest="follow", action="store_true", default=True,
                   help="track the focused monitor (default)")
    p.add_argument("--no-follow", dest="follow", action="store_false",
                   help="pin to --output (or the current focus) instead")
    p.add_argument("--fps", type=float, default=24.0, help="frames per second")
    p.add_argument("--res", type=int, default=144,
                   help="capture height in px — the '144p' working resolution")
    p.add_argument("--blur", type=float, default=2.0,
                   help="blur radius in px at 144p (0 = none)")
    p.add_argument("--saturation", "--sat", dest="saturation", type=float,
                   default=1.5, help="saturation multiplier (1 = faithful)")
    p.add_argument("--gain", type=float, default=1.1,
                   help="brightness multiplier")
    p.add_argument("--gamma", type=float, default=1.0,
                   help="gamma (<1 brightens mid-tones)")
    p.add_argument("--smooth", type=float, default=0.5,
                   help="temporal smoothing 0..0.95 (0 = none, higher = calmer)")
    p.add_argument("--raw", action="store_true",
                   help="faithful colors: disable saturation/gain/gamma")
    p.add_argument("--duration", type=float, default=None,
                   help="stop after N seconds")
    p.add_argument("--debug", action="store_true")
    o = p.parse_args(argv)

    if o.output:  # an explicit monitor means don't chase focus
        o.follow = False
    sat = 1.0 if o.raw else o.saturation
    gain = 1.0 if o.raw else o.gain
    gamma = 1.0 if o.raw else o.gamma
    ema = min(0.95, max(0.0, o.smooth))

    tap = ScreenTap(o.output, o.follow, k.p.cols, k.p.rows,
                    res=o.res, blur=o.blur, fps=o.fps)
    # map each key to its cell in the row-major cols*rows grid (top-left origin)
    key_cell = [(name, row * k.p.cols + col) for name, col, row in k.p.keys_tuples]
    following = o.follow and tap.backend == "grim"
    print(
        f"screen sync: output={tap.output}{' (follow)' if following else ''} "
        f"res={o.res}p blur={o.blur:g} fps={o.fps:g} sat={sat:g} gain={gain:g}"
    )

    frame_dt = 1.0 / o.fps if o.fps > 0 else 0.0
    smoothed = None
    t0 = time.monotonic()
    frames = 0
    try:
        while o.duration is None or time.monotonic() - t0 < o.duration:
            tstart = time.monotonic()
            grid = tap.read()
            if grid is not None:
                if ema > 0.0:
                    if smoothed is None:
                        smoothed = [list(c) for c in grid]
                    else:
                        for i, c in enumerate(grid):
                            s = smoothed[i]
                            s[0] += (c[0] - s[0]) * (1 - ema)
                            s[1] += (c[1] - s[1]) * (1 - ema)
                            s[2] += (c[2] - s[2]) * (1 - ema)
                    src = smoothed
                else:
                    src = grid
                for name, cell in key_cell:
                    k.set_key(name, *apply_look(src[cell], sat, gain, gamma))
                _flush(k)
                frames += 1
                if o.debug and frames % max(1, int(o.fps)) == 0:
                    print(f"output={tap.output} frame "
                          f"{(time.monotonic() - tstart) * 1000:.1f}ms")
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
