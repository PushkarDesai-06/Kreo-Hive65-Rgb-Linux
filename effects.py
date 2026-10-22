#!/usr/bin/env python3
"""Effect rendering: static effects (color / gradient / rainbow), the animated
wave and flux, the audio-reactive spectrum and 2D-field visualizers, and screen
sync. Every effect reads its grid geometry from the active profile (`k.p`), so
the same code scales to any board.

Each effect is an engine.LightingEffect that renders one frame at a time into a
canvas; its EffectSpec declares the options once for both the CLI parser and
the GUI controls. The run_* functions are the CLI entry points: parse argv,
then engine.drive() the effect on the board."""
import math
import random
import time

from audio import AudioTap, Spectrum  # noqa: F401 (engine.Inputs reads effects.AudioTap)
from color import COLORFUL_PALETTE, hsv, palette_at, parse_hex, parse_palette
from engine import LightingEffect, drive
from params import EffectSpec, Param

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


def idle_color(effect, col, row, ncols, t, palette=COLORFUL_PALETTE):
    """Non-audio 'default' effect shown when music is silent; uses the same
    palette as colorful mode. `t` is elapsed seconds."""
    if effect == "off":
        return (0, 0, 0)
    if effect == "breathe":  # whole board drifts through the palette, breathing
        v = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 1.2))
        return palette_at(t * 0.05, v=v, palette=palette)
    if effect == "wave":  # palette gradient with a brightness wave rolling across
        vv = 0.5 + 0.5 * math.sin(col * 0.55 - t * 2.2)
        return palette_at(col / ncols - t * 0.08, v=0.35 + 0.65 * vv, palette=palette)
    # gradient (default): the Gradient Lab look — palette scrolling across columns
    return palette_at(col / ncols - t * 0.08, palette=palette)


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


# --- static effects (the CLI color/gradient/rainbow commands hold these) ------
SOLID_SPEC = EffectSpec("color", (
    Param("color", "color", "ff8800", positional=True,
          label="Color", tooltip="The color every key lights up in."),
))

GRADIENT_SPEC = EffectSpec("gradient", (
    Param("start", "color", "ff0000", positional=True, label="Left color",
          tooltip="Color at the left edge of the keyboard."),
    Param("end", "color", "0000ff", positional=True, label="Right color",
          tooltip="Color at the right edge. Keys in between blend smoothly."),
))

RAINBOW_SPEC = EffectSpec("rainbow", ())


class SolidColor(LightingEffect):
    spec = SOLID_SPEC
    animated = False

    def step(self, canvas, now, t):
        canvas.fill(*parse_hex(self.o.color))
        return True


class Gradient(LightingEffect):
    spec = GRADIENT_SPEC
    animated = False

    def step(self, canvas, now, t):
        render_gradient(canvas, parse_hex(self.o.start), parse_hex(self.o.end))
        return True


class Rainbow(LightingEffect):
    spec = RAINBOW_SPEC
    animated = False

    def step(self, canvas, now, t):
        render_rainbow(canvas)
        return True


# --- wave: animated hue wave --------------------------------------------------
WAVE_SPEED_DEFAULT = 0.4  # hue cycles/sec

WAVE_SPEC = EffectSpec("wave", (
    Param("secs", "float", None, positional=True, nargs="?", argtype=float,
          help="stop after N seconds (default: run until Ctrl-C)", gui=False),
    Param("speed", "float", WAVE_SPEED_DEFAULT, flags=("--speed",), argtype=float,
          help=f"hue cycles/sec (default {WAVE_SPEED_DEFAULT:g})",
          label="Speed", tooltip="How fast the rainbow rolls across the keyboard.",
          min=0.02, max=3.0, step=0.02, decimals=2, unit="cycles/s", group="Motion"),
), description="animated hue wave rolling across the columns")


class RainbowWave(LightingEffect):
    """Animated hue wave rolling across the columns. Keeps the legacy loop's
    quirks: wall clock, a fixed 1/60 s sleep, and no blanking on exit."""

    spec = WAVE_SPEC
    clock = "wall"
    fixed_sleep = True
    clear_on_exit = False
    summary = False

    @property
    def frame_dt(self):
        return 1 / 60

    def step(self, canvas, now, t):
        ph = t * self.o.speed
        cols = self.p.cols
        for name, col, row in self.p.keys_tuples:
            canvas.set_key(name, *hsv((col / cols + ph) % 1.0))
        return True


def run_wave(k, argv=None):
    """Animated hue wave rolling across the columns until Ctrl-C (or `secs`)."""
    o = WAVE_SPEC.parse(list(argv or []))
    drive(k, RainbowWave(k.p, o), o.secs)


# --- flux: drifting multi-source gradient (non-audio) ------------------------
# `--colors` color "sources" wander the board; every key is an inverse-distance
# blend of them, so the whole surface reads as one smooth gradient that morphs
# as the sources move. Two motions: 'walk' random-walks each source's heading at
# constant speed and reflects it off the edges (organic, different every run);
# 'drift' places each source with a sum of sine waves at incommensurate
# frequencies (silky, never exactly repeats, deterministic/reproducible).
FLUX_BASE_SPEED = 0.35  # source travel, board-units/sec at --speed 1 (walk)
FLUX_WALK_TURN = 1.6  # heading random-walk, radians/sec at --speed 1 (walk)
FLUX_DRIFT_FREQS_X = (0.061, 0.127, 0.211)  # Hz, incommensurate -> non-repeating
FLUX_DRIFT_FREQS_Y = (0.083, 0.149, 0.193)
FLUX_DRIFT_AMPS = (0.5, 0.3, 0.2)  # sum 1.0 -> the sine sum spans [-1, 1] exactly


def _flux_bounds(geom):
    """Bounding box (xmin, xmax, ymin, ymax) of the profile's key geometry, so
    sources roam only where keys actually are."""
    xs = [g[0] for g in geom.values()]
    ys = [g[1] for g in geom.values()]
    return min(xs), max(xs), min(ys), max(ys)


FLUX_SPEC = EffectSpec("flux", (
    Param("colors", "choice", 3, flags=("--colors",), argtype=int, choices=(2, 3, 4),
          help="number of moving color sources (default 3)",
          label="Color count", labels=("2", "3", "4"),
          tooltip="How many moving color sources blend across the keyboard."),
    Param("motion", "choice", "walk", flags=("--motion",), choices=("walk", "drift"),
          help="walk = random-walk + edge bounce (organic, unique each "
               "run); drift = sum-of-sines (silky, deterministic)",
          label="Motion style", labels=("Wander", "Drift"), group="Motion",
          tooltip="Wander: colors roam randomly and bounce off the edges, "
                  "different every time. Drift: smooth, flowing, repeatable movement."),
    Param("hex", "colors", None, flags=("--hex",),
          help="comma-separated source colors (e.g. ff4242,7c3aed,06b6d4); "
               "default samples the colorful palette",
          label="Colors", count_from="colors",
          tooltip="The color of each moving source. Defaults to the built-in palette."),
    Param("speed", "float", 1.0, flags=("--speed",), argtype=float,
          help="motion speed multiplier (default 1.0)",
          label="Speed", tooltip="How fast the colors move across the keyboard.",
          min=0.05, max=5.0, step=0.05, decimals=2, unit="x", group="Motion"),
    Param("sharp", "float", 2.0, flags=("--sharp",), argtype=float,
          help="blend sharpness: 2 = soft gradient, higher = tighter "
               "cells around each source (default 2.0)",
          label="Edge sharpness", min=0.5, max=10.0, step=0.1, decimals=1,
          tooltip="Low values blend the colors into one soft gradient. High values "
                  "give each color its own distinct zone."),
    Param("fps", "float", 60.0, flags=("--fps",), argtype=float,
          label="Frame rate", min=10, max=60, step=1, decimals=0, unit="fps",
          group="Advanced", live=False,
          tooltip="How many times per second the lighting updates. Lower values use less CPU."),
    Param("seed", "int", None, flags=("--seed",), argtype=int,
          help="walk only: RNG seed for a repeatable wander (default random)", gui=False),
    Param("duration", "float", None, flags=("--duration",), argtype=float,
          help="stop after N seconds", gui=False),
), description="drifting multi-source gradient")


def _flux_colors(o):
    """Source colors: an explicit --hex list wins, else the first N palette entries."""
    if o.hex:
        return [tuple(map(float, parse_hex(h))) for h in o.hex.split(",") if h.strip()]
    return [tuple(map(float, c)) for c in COLORFUL_PALETTE[:o.colors]]


class Flux(LightingEffect):
    """Multi-source drifting gradient. `--colors` moving color sources wander the
    board and every key is an inverse-distance blend of them, so the surface is
    one smooth gradient that morphs as they move."""

    spec = FLUX_SPEC

    @property
    def frame_dt(self):
        return 1.0 / self.o.fps if self.o.fps > 0 else 1.0 / 60.0

    def start(self):
        o = self.o
        self.colf = _flux_colors(o)
        n = len(self.colf)
        geom = self.p.geom
        self.xmin, self.xmax, self.ymin, self.ymax = _flux_bounds(geom)
        xmin, xmax, ymin, ymax = self.xmin, self.xmax, self.ymin, self.ymax
        self.cx, self.cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
        self.hx, self.hy = (xmax - xmin) / 2.0 or 1e-6, (ymax - ymin) / 2.0 or 1e-6
        self.retune()
        self.rng = rng = random.Random(o.seed)  # seed None -> fresh wander each launch
        # walk state: constant speed, only the heading random-walks (stays smooth)
        self.px = [rng.uniform(xmin, xmax) for _ in range(n)]
        self.py = [rng.uniform(ymin, ymax) for _ in range(n)]
        self.ang = [rng.uniform(0.0, TAU) for _ in range(n)]
        self.sx, self.sy = [0.0] * n, [0.0] * n

    def retune(self):
        o = self.o
        self.half_sharp = o.sharp / 2.0  # weight = 1/(dist**sharp + eps) = 1/(d2**half + eps)
        self.base_v = FLUX_BASE_SPEED * o.speed  # walk: constant travel speed
        self.turn = FLUX_WALK_TURN * o.speed * self.frame_dt  # walk: heading jitter per frame
        colf = _flux_colors(o)
        if hasattr(self, "colf") and len(colf) != len(self.colf):
            self._resize(len(colf))
        self.colf = colf

    def _resize(self, n):
        """Add or drop sources live (GUI color-count changes) without a restart."""
        rng = self.rng
        while len(self.px) < n:
            self.px.append(rng.uniform(self.xmin, self.xmax))
            self.py.append(rng.uniform(self.ymin, self.ymax))
            self.ang.append(rng.uniform(0.0, TAU))
            self.sx.append(0.0)
            self.sy.append(0.0)
        for arr in (self.px, self.py, self.ang, self.sx, self.sy):
            del arr[n:]

    def describe(self):
        o = self.o
        return (f"flux: colors={len(self.colf)} motion={o.motion} speed={o.speed:g} "
                f"sharp={o.sharp:g} fps={o.fps:g}"
                + (f" seed={o.seed}" if o.motion == "walk" and o.seed is not None else ""))

    def step(self, canvas, now, t):
        o = self.o
        n = len(self.colf)
        sx, sy, px, py, ang = self.sx, self.sy, self.px, self.py, self.ang
        if o.motion == "drift":  # deterministic sum-of-sines per source/axis
            cx, cy, hx, hy = self.cx, self.cy, self.hx, self.hy
            for i in range(n):
                ph = i * 1.7
                xs = sum(FLUX_DRIFT_AMPS[j] * math.sin(
                    TAU * FLUX_DRIFT_FREQS_X[j] * t * o.speed + ph + j * 0.9)
                    for j in range(3))
                ys = sum(FLUX_DRIFT_AMPS[j] * math.sin(
                    TAU * FLUX_DRIFT_FREQS_Y[j] * t * o.speed + ph + 1.3 + j * 1.1)
                    for j in range(3))
                sx[i], sy[i] = cx + hx * xs, cy + hy * ys
        else:  # walk: step at constant speed, reflect heading off the edges
            rng, turn, base_v, frame_dt = self.rng, self.turn, self.base_v, self.frame_dt
            xmin, xmax, ymin, ymax = self.xmin, self.xmax, self.ymin, self.ymax
            for i in range(n):
                ang[i] += rng.uniform(-turn, turn)
                px[i] += base_v * math.cos(ang[i]) * frame_dt
                py[i] += base_v * math.sin(ang[i]) * frame_dt
                if px[i] < xmin or px[i] > xmax:
                    px[i] = min(max(px[i], xmin), xmax)
                    ang[i] = math.pi - ang[i]
                if py[i] < ymin or py[i] > ymax:
                    py[i] = min(max(py[i], ymin), ymax)
                    ang[i] = -ang[i]
                sx[i], sy[i] = px[i], py[i]

        geom, colf, half_sharp, eps = self.p.geom, self.colf, self.half_sharp, 1e-3
        for name, col, row in self.p.keys_tuples:
            nx, ny = geom[name][0], geom[name][1]
            wsum = r = g = b = 0.0
            for i in range(n):
                dx, dy = nx - sx[i], ny - sy[i]
                w = 1.0 / ((dx * dx + dy * dy) ** half_sharp + eps)
                cr, cg, cb = colf[i]
                r += w * cr
                g += w * cg
                b += w * cb
                wsum += w
            canvas.set_key(name, int(r / wsum), int(g / wsum), int(b / wsum))
        return True


def run_flux(k, argv):
    """Multi-source drifting gradient until Ctrl-C (or --duration)."""
    o = FLUX_SPEC.parse(argv)
    drive(k, Flux(k.p, o), o.duration)


# --- audio-reactive effect registry -----------------------------------------
# Each effect is a small strategy object: it declares whether it runs one band
# per row (horizontal) or per column, sets up any cross-frame state in __init__,
# advances that state once per frame in frame(), and returns (val, hue) for one
# key in render(). Adding an effect is a new class + one EFFECTS entry — the
# render loop in AudioVisualizer.step never changes. Mirrors the ENCODERS registry in
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


class AudioShape:
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


Effect = AudioShape  # pre-refactor name


class WaveEffect(AudioShape):
    """Center-out column spectrum with a scrolling gradient."""

    def render(self, f, name, col, row):
        val = cell_coverage(f.disp[col], row, self.nrows, "wave")
        hue = col / self.ncols - self.o.scroll * f.t
        return val, hue


class BarsEffect(AudioShape):
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


class SplitEffect(AudioShape):
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


class FlowEffect(AudioShape):
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


class VortexEffect(AudioShape):
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


class RippleEffect(AudioShape):
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


_COLOR_STYLE = dict(choices=("colorful", "single"), labels=("Multicolor", "Single color"),
                    label="Color style",
                    tooltip="Multicolor paints with a flowing palette. Single color uses "
                            "one color of your choice.")

AUDIO_SPEC = EffectSpec("audio", (
    Param("mode", "choice", "colorful", flags=("--mode",), **_COLOR_STYLE),
    Param("color", "color", "009bde", flags=("--color",), help="color for single mode",
          label="Color", show_if={"mode": ("single",)},
          tooltip="The color used in single-color style."),
    Param("palette", "colors", None, flags=("--palette",),
          help="colorful-mode gradient colors, comma-separated hex "
               "(default ff4242,7c3aed,06b6d4,eab308)",
          label="Gradient colors", show_if={"mode": ("colorful",)},
          tooltip="The colors the multicolor gradient flows through, in order. "
                  "Also used by the idle effect when the music stops."),
    Param("gain", "float", 1.0, flags=("--gain",), argtype=float,
          help="amplitude multiplier", label="Sensitivity",
          min=0.1, max=4.0, step=0.05, decimals=2, unit="x", group="Audio",
          tooltip="Boosts how strongly the lights react. Raise it for quiet music."),
    Param("smooth", "float", 1.0, flags=("--smooth",), argtype=float,
          help="smoothness multiplier", label="Smoothing",
          min=0.05, max=4.0, step=0.05, decimals=2, unit="x", group="Motion",
          tooltip="Higher values make movement calmer and less jittery. Lower values "
                  "react instantly to every beat."),
    Param("effect", "choice", "wave", flags=("--effect", "--shape"),
          choices=tuple(EFFECTS),
          help="wave/bars = spectrum shapes; vortex/ripple = 2D audio-reactive "
               "fields; split = bass grows from the left edge, treble from the right; "
               "flow = the left column tracks the bass and that punch travels "
               "left-to-right across the board (see --flow-speed)",
          label="Visualizer", live=False,
          labels=("Spectrum Wave", "Equalizer Bars", "Black Hole", "Bass Ripple",
                  "Bass & Treble", "Bass Waterfall"),
          tooltip="Which visualizer shape to draw."),
    Param("direction", "choice", "bottom", flags=("--direction", "--dir"),
          choices=("bottom", "top", "left", "right", "sides"),
          help="bars only: which edge the bars grow from — bottom (default) or top "
               "(vertical), left/right (horizontal), or sides (inward from both edges)",
          label="Bar direction", labels=("Bottom", "Top", "Left", "Right", "Both sides"),
          show_if={"effect": ("bars",)}, live=False,
          tooltip="Which edge of the keyboard the bars grow from."),
    Param("scroll", "float", 0.15, flags=("--scroll",), argtype=float,
          help="colorful-mode gradient scroll speed, hue cycles/sec "
               "left-to-right (0 = static); ignored by vortex (it spins on its own)",
          label="Color drift", min=0.0, max=1.0, step=0.01, decimals=2, unit="cycles/s",
          group="Motion", show_if={"mode": ("colorful",)},
          tooltip="How fast the colors slide across the keyboard. 0 keeps them still."),
    Param("radius", "float", 0.18, flags=("--radius",), argtype=float,
          help="vortex event-horizon (dark hole) radius, 0..1 (default 0.18)",
          label="Hole size", min=0.0, max=1.0, step=0.01, decimals=2,
          show_if={"effect": ("vortex",)},
          tooltip="Size of the dark center the glowing ring orbits around."),
    Param("flow_speed", "float", FLOW_SPEED_DEFAULT, flags=("--flow-speed",), argtype=float,
          help="flow only: how fast a bass punch travels left-to-right, in "
               f"columns/sec (default {FLOW_SPEED_DEFAULT:g}); lower = slower travel",
          label="Travel speed", min=1.0, max=30.0, step=0.5, decimals=1, unit="keys/s",
          group="Motion", show_if={"effect": ("flow",)}, live=False,
          tooltip="How fast each bass hit travels from the left edge to the right."),
    Param("fps", "float", 30.0, flags=("--fps",), argtype=float,
          label="Frame rate", min=10, max=60, step=1, decimals=0, unit="fps",
          group="Advanced", live=False,
          tooltip="How many times per second the lighting updates. Lower values use less CPU."),
    Param("rate", "int", 48000, flags=("--rate",), argtype=int, gui=False),
    Param("source", "text", None, flags=("--source",),
          help="pulse source name, or - for stdin",
          label="Audio source", group="Audio", live=False, source="audio_sources",
          auto_label="System output",
          tooltip="Where to listen. System output reacts to whatever is playing; "
                  "pick a microphone to react to the room."),
    Param("duration", "float", None, flags=("--duration",), argtype=float,
          help="stop after N seconds", gui=False),
    Param("default", "choice", "gradient", flags=("--default",),
          choices=("gradient", "breathe", "wave", "off"),
          help="non-audio effect to crossfade to when music is silent",
          label="When music stops", labels=("Gradient", "Breathe", "Wave", "Lights off"),
          group="Audio",
          tooltip="What the keyboard shows after a few seconds of silence."),
    Param("idle_gap", "float", 5.0, flags=("--idle-gap",), argtype=float,
          help="seconds of silence before switching to the --default effect",
          label="Silence delay", min=0.0, max=30.0, step=0.5, decimals=1, unit="s",
          group="Audio",
          tooltip="How long the music must be silent before the idle effect fades in."),
    Param("silence_level", "float", 0.004, flags=("--silence-level",), argtype=float,
          help="audio peak below this counts as silence (tune per system)",
          label="Silence threshold", min=0.0, max=0.05, step=0.001, decimals=3,
          group="Advanced",
          tooltip="Audio quieter than this counts as silence. Raise it if background "
                  "hiss keeps the visualizer awake."),
    Param("erase", "bool", False, flags=("--erase",), action="store_true",
          help="overlay the reactive erase effect: pressed keys and their "
               "neighbors go dark on top of the audio effect, fading back on release",
          label="Typing erase", group="Typing", live=False,
          tooltip="Keys you press go dark on top of the visualizer and fade back "
                  "when released."),
    Param("erase_radius", "float", 1.5, flags=("--erase-radius",), argtype=float,
          help="erase: darkened area around the pressed key in grid cells (default 1.5)",
          label="Erase radius", min=0.5, max=5.0, step=0.1, decimals=1, unit="keys",
          group="Typing", show_if={"erase": (True,)},
          tooltip="How many neighboring keys go dark around each press."),
    Param("erase_fade", "float", 0.5, flags=("--erase-fade",), argtype=float,
          help="erase: seconds for a released key's color to fade back (default 0.5)",
          label="Erase fade", min=0.05, max=3.0, step=0.05, decimals=2, unit="s",
          group="Typing", show_if={"erase": (True,)},
          tooltip="How long a released key takes to light back up."),
    Param("input", "text", None, flags=("--input",),
          help="erase: evdev input device (default: auto-detect the keyboard)",
          label="Typing input device", group="Advanced", live=False, source="inputs",
          show_if={"erase": (True,)}, auto_label="Detect automatically",
          tooltip="Which keyboard to watch for key presses."),
    Param("debug", "bool", False, flags=("--debug",), action="store_true", gui=False),
), description="audio-reactive spectrum wave")


class AudioVisualizer(LightingEffect):
    """Audio-reactive visualizer: FFT bands drive the active AudioShape, crossfading
    to an idle effect after a stretch of silence, with an optional erase overlay."""

    spec = AUDIO_SPEC
    needs = frozenset({"audio"})
    N = 1024

    def start(self):
        o = self.o
        self.listener = None
        if o.erase:
            # imported here: reactive imports idle_color from this module
            from reactive import apply_erase, erase_mask

            self._apply_erase, self._erase_mask = apply_erase, erase_mask
            self.needs = self.needs | {"keys"}
            self.listener, input_dev = self.inputs.keys(
                o.input, {name for name, _, _ in self.p.keys_tuples}, self.p.key_aliases)
            self.log(f"erase overlay: radius={o.erase_radius:g} fade={o.erase_fade:g}s "
                     f"input={input_dev}")
        fx_cls = EFFECTS[o.effect]
        # Horizontal bars run one frequency band per row (bars grow sideways); every
        # other effect runs one band per column. The spectrum is sized to match, and
        # `disp` is indexed by row for horizontal bars, by column otherwise.
        self.nlanes = nlanes = self.p.rows if fx_cls.is_horizontal(o) else self.p.cols
        self.spectrum = Spectrum(self.N, o.rate, nlanes)
        self.tap = self.inputs.audio(o.source, o.rate, self.N)
        self.fx = fx_cls(self, o, nlanes)
        self.retune()
        self.ref = 1e-3  # slow auto-gain reference
        self.levels = [0.0] * nlanes
        self.raw = [0.0] * nlanes
        # idle<->audio crossfade: mix 0 = idle (default effect), 1 = audio-reactive
        self.mix = 0.0  # start on the idle effect; fade up when music begins
        self.last_sound_t = None
        self.t_fft = 0.0

    def retune(self):
        o = self.o
        smooth = max(o.smooth, 0.05)
        frame_dt = self.frame_dt
        self.atk = math.exp(-frame_dt / (0.020 * smooth))
        self.dec = math.exp(-frame_dt / (0.150 * smooth))
        self.spatial = min(0.45, 0.15 * smooth)
        self.base = parse_hex(o.color)
        self.palette = parse_palette(o.palette)

    def describe(self):
        o = self.o
        return (
            f"audio-reactive: source={self.tap.source} mode={o.mode} effect={o.effect}"
            f"{'/' + o.direction if o.effect == 'bars' else ''} "
            f"gain={o.gain} smooth={o.smooth} fps={o.fps:g} "
            f"default={o.default} idle-gap={o.idle_gap:g}s"
        )

    def step(self, canvas, tstart, t):
        REF_DECAY, REF_FLOOR = 0.998, 2e-4
        TAU_UP, TAU_DOWN = 0.30, 0.90  # crossfade time constants (up = snappier)
        o, nlanes, levels, frame_dt = self.o, self.nlanes, self.levels, self.frame_dt
        if self.last_sound_t is None:
            self.last_sound_t = tstart - t - o.idle_gap - 1.0  # startup = already silent
        samples = self.tap.read()
        self.t_fft = 0.0
        if samples:
            self.raw = self.spectrum.bands(samples)
            self.t_fft = time.monotonic() - tstart
        elif self.tap.eof:
            self.raw = [0.0] * nlanes
        raw = self.raw
        self.ref = ref = max(self.ref * REF_DECAY, max(raw), REF_FLOOR)
        atk, dec, spatial = self.atk, self.dec, self.spatial
        for i in range(nlanes):
            target = min(1.0, (raw[i] / ref) ** 0.65 * o.gain)
            coef = atk if target > levels[i] else dec
            levels[i] = target + (levels[i] - target) * coef
        disp = [
            levels[i] * (1 - spatial)
            + (levels[max(i - 1, 0)] + levels[min(i + 1, nlanes - 1)]) * spatial / 2
            for i in range(nlanes)
        ]
        # idle/audio crossfade: any sound refreshes the timer and keeps us
        # in audio; only after idle_gap seconds of silence do we ease over
        # to the --default effect. Sound returning snaps target back to
        # audio at once, but the mix still eases (no hard cuts either way).
        if max(raw) > o.silence_level:
            self.last_sound_t = tstart
        m_target = 1.0 if (tstart - self.last_sound_t) < o.idle_gap else 0.0
        tau = TAU_UP if m_target > self.mix else TAU_DOWN
        self.mix = mix = self.mix + (m_target - self.mix) * (1.0 - math.exp(-frame_dt / tau))
        energy = sum(levels) / nlanes
        nb = min(4, nlanes)  # lowest/highest bands -> bass/treble scalars
        bass = sum(levels[:nb]) / nb
        treble = sum(levels[nlanes - nb:]) / nb
        f = _Frame(disp, energy, bass, treble, t)
        fx = self.fx
        fx.frame(f, frame_dt)
        listener = self.listener
        if listener is not None:
            state = listener.snapshot()[0]
            mask = self._erase_mask(self.p.keys_tuples, state, tstart,
                                    o.erase_radius, o.erase_fade)

        ncols, base, colorful, pal = self.p.cols, self.base, o.mode == "colorful", self.palette
        for name, col, row in self.p.keys_tuples:
            val, hue = fx.render(f, name, col, row)
            if colorful:
                a_rgb = palette_at(hue, v=val, palette=pal)
            else:
                a_rgb = (int(base[0] * val), int(base[1] * val), int(base[2] * val))
            if mix >= 0.999:  # fully audio
                rgb = a_rgb
            else:  # crossfade toward the idle default effect
                ir, ig, ib = idle_color(o.default, col, row, ncols, t, pal)
                rgb = (
                    int(ir + (a_rgb[0] - ir) * mix),
                    int(ig + (a_rgb[1] - ig) * mix),
                    int(ib + (a_rgb[2] - ib) * mix),
                )
            if listener is not None:
                rgb = self._apply_erase(rgb, mask.get(name, 0.0))
            canvas.set_key(name, *rgb)
        return True

    def debug_line(self, frames, tstart, tflush):
        now = time.monotonic()
        state = "audio" if self.mix > 0.5 else self.o.default
        line = (
            f"peak={max(self.raw):.5f} mix={self.mix:.2f}({state}) "
            f"levels[max]={max(self.levels):.2f} frame={(now - tstart) * 1000:.1f}ms "
            f"(fft={self.t_fft * 1000:.1f} flush={(now - tflush) * 1000:.1f}) "
            f"drained={self.tap.drained}B"
        )
        self.tap.drained = 0
        return line

    def stop(self):
        self.tap.close()
        if self.listener is not None and hasattr(self.listener, "stop"):
            self.listener.stop()


def run_audio(k, argv):
    o = AUDIO_SPEC.parse(argv)
    drive(k, AudioVisualizer(k.p, o), o.duration, o.debug)


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


_LOOK = {"raw": (False,)}

SCREEN_SPEC = EffectSpec("screen", (
    Param("output", "text", None, flags=("--output",),
          help="monitor to capture (default: the focused one); "
               "see hyprctl monitors / wlr-randr",
          label="Monitor", group="Capture", live=False, source="monitors",
          auto_label="Focused monitor",
          tooltip="Which monitor to mirror. Picking one pins it and turns off "
                  "follow focus."),
    Param("follow", "bool", True, flags=("--follow",), action="store_true",
          help="track the focused monitor (default)",
          neg_flags=("--no-follow",),
          neg_help="pin to --output (or the current focus) instead",
          label="Follow focus", group="Capture", live=False,
          tooltip="Switch to whichever monitor you are working on (Hyprland)."),
    Param("fps", "float", 24.0, flags=("--fps",), argtype=float,
          help="frames per second", label="Frame rate", min=5, max=60, step=1,
          decimals=0, unit="fps", group="Advanced", live=False,
          tooltip="How many screen captures per second. Lower values use less CPU."),
    Param("res", "int", 144, flags=("--res",), argtype=int,
          help="capture height in px — the '144p' working resolution",
          label="Capture resolution", min=36, max=720, step=12, unit="p",
          group="Advanced", live=False,
          tooltip="Working resolution of the capture before it is shrunk to the "
                  "keyboard. Higher is more accurate but uses more CPU."),
    Param("blur", "float", 2.0, flags=("--blur",), argtype=float,
          help="blur radius in px at 144p (0 = none)",
          label="Blur", min=0.0, max=10.0, step=1.0, decimals=0, unit="px",
          group="Capture", live=False,
          tooltip="Softens the image before sampling so small details do not flicker."),
    Param("saturation", "float", 1.5, flags=("--saturation", "--sat"), argtype=float,
          help="saturation multiplier (1 = faithful)",
          label="Saturation", min=0.0, max=3.0, step=0.05, decimals=2, unit="x",
          show_if=_LOOK,
          tooltip="Makes colors more vivid. 1 matches the screen exactly."),
    Param("gain", "float", 1.1, flags=("--gain",), argtype=float,
          help="brightness multiplier", label="Brightness",
          min=0.1, max=3.0, step=0.05, decimals=2, unit="x", show_if=_LOOK,
          tooltip="Overall brightness of the mirrored colors."),
    Param("gamma", "float", 1.0, flags=("--gamma",), argtype=float,
          help="gamma (<1 brightens mid-tones)", label="Gamma",
          min=0.3, max=3.0, step=0.05, decimals=2, show_if=_LOOK,
          tooltip="Below 1 brightens mid-tones, above 1 deepens them."),
    Param("smooth", "float", 0.5, flags=("--smooth",), argtype=float,
          help="temporal smoothing 0..0.95 (0 = none, higher = calmer)",
          label="Smoothing", min=0.0, max=0.95, step=0.01, decimals=2, group="Motion",
          tooltip="Eases color changes over time. Higher values feel calmer; 0 "
                  "reacts instantly."),
    Param("raw", "bool", False, flags=("--raw",), action="store_true",
          help="faithful colors: disable saturation/gain/gamma",
          label="True colors",
          tooltip="Show the screen's exact colors without the saturation, "
                  "brightness and gamma boost."),
    Param("duration", "float", None, flags=("--duration",), argtype=float,
          help="stop after N seconds", gui=False),
    Param("debug", "bool", False, flags=("--debug",), action="store_true", gui=False),
), description="mirror a monitor onto the keyboard (144p, blurred)")


class ScreenSync(LightingEffect):
    """Mirror a monitor onto the keyboard: capture at 144p, blur, and stream it
    to the keys. Follows the focused monitor by default (Hyprland). Held live by
    re-sending each frame, so no separate keepalive is needed."""

    spec = SCREEN_SPEC
    needs = frozenset({"screen"})

    @property
    def frame_dt(self):
        return 1.0 / self.o.fps if self.o.fps > 0 else 0.0

    def start(self):
        o = self.o
        if o.output:  # an explicit monitor means don't chase focus
            o.follow = False
        self.retune()
        p = self.p
        self.tap = self.inputs.screen(o.output, o.follow, p.cols, p.rows,
                                      o.res, o.blur, o.fps)
        # map each key to its cell in the row-major cols*rows grid (top-left origin)
        self.key_cell = [(name, row * p.cols + col) for name, col, row in p.keys_tuples]
        self.smoothed = None

    def retune(self):
        o = self.o
        self.sat = 1.0 if o.raw else o.saturation
        self.gain = 1.0 if o.raw else o.gain
        self.gamma = 1.0 if o.raw else o.gamma
        self.ema = min(0.95, max(0.0, o.smooth))

    def describe(self):
        o = self.o
        following = o.follow and self.tap.backend == "grim"
        return (
            f"screen sync: output={self.tap.output}{' (follow)' if following else ''} "
            f"res={o.res}p blur={o.blur:g} fps={o.fps:g} sat={self.sat:g} gain={self.gain:g}"
        )

    def step(self, canvas, tstart, t):
        grid = self.tap.read()
        if grid is None:
            return False
        ema = self.ema
        if ema > 0.0:
            smoothed = self.smoothed
            if smoothed is None:
                self.smoothed = smoothed = [list(c) for c in grid]
            else:
                for i, c in enumerate(grid):
                    s = smoothed[i]
                    s[0] += (c[0] - s[0]) * (1 - ema)
                    s[1] += (c[1] - s[1]) * (1 - ema)
                    s[2] += (c[2] - s[2]) * (1 - ema)
            src = smoothed
        else:
            src = grid
        sat, gain, gamma = self.sat, self.gain, self.gamma
        for name, cell in self.key_cell:
            canvas.set_key(name, *apply_look(src[cell], sat, gain, gamma))
        return True

    def debug_line(self, frames, tstart, tflush):
        return (f"output={self.tap.output} frame "
                f"{(time.monotonic() - tstart) * 1000:.1f}ms")

    def stop(self):
        self.tap.close()


def run_screen(k, argv):
    """Mirror a monitor onto the keyboard until Ctrl-C (or --duration)."""
    o = SCREEN_SPEC.parse(argv)
    drive(k, ScreenSync(k.p, o), o.duration, o.debug)
