#!/usr/bin/env python3
"""Reactive lighting effects: the keyboard responds to keypresses with
localized light bursts that fade out over time. A background thread reads
evdev input events and stamps key-down/key-up times; the render loop blends
contributions from every recently-active key.

Sub-modes (--effect):
  splash   – a bright disc appears on press and fades out after release
  ripple   – a ring expands outward from the pressed key and fades
  trail    – pressed keys leave a comet trail that decays toward the hue
             of the next key pressed (typing paints a gradient wake)
  heatmap  – keys accumulate heat with each press; the board glows
             warmer the more you hammer a key (decays slowly over time)
  raindrops– each keypress drops a random-colored splash; splashes layer
             and blend like paint drops on water
  sonar    – a thin bright ring pings outward from the pressed key and
             bounces off the board edges (submarine sonar style)
  erase    – the inverse of splash: an ambient base effect (--base) runs on
             the whole board and pressed keys go dark, fading back on release

All modes use the profile's key geometry for distance calculations, so they
scale to any board size.
"""

import argparse
import math
import os
import struct
import threading
import time

from color import COLORFUL_PALETTE, hsv, palette_at, parse_hex
from device import Kbd, _flush
from effects import idle_color

TAU = 2.0 * math.pi

# ---------------------------------------------------------------- evdev ---
# Evdev keycode → profile key-name mapping. Not every keycode has a profile
# key (some boards are 65%, some are full); unmapped codes are silently
# ignored.  The map covers the standard USB HID scan codes that Linux's
# input layer exposes.
#
# evdev constants (linux/input-event-codes.h) used inline to avoid pulling
# the evdev package at import time (we only need struct-level reads).
EV_KEY = 0x01
KEY_DOWN = 1
KEY_UP = 0

# evdev code → profile key name (lowercase, matching profiles/*.json)
EVDEV_TO_NAME = {
    1: "esc",
    2: "1", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6", 8: "7", 9: "8",
    10: "9", 11: "0", 12: "minus", 13: "equal", 14: "backspace",
    15: "tab",
    16: "q", 17: "w", 18: "e", 19: "r", 20: "t", 21: "y", 22: "u",
    23: "i", 24: "o", 25: "p", 26: "lbracket", 27: "rbracket",
    28: "enter", 29: "lctrl",
    30: "a", 31: "s", 32: "d", 33: "f", 34: "g", 35: "h", 36: "j",
    37: "k", 38: "l", 39: "semicolon", 40: "quote",
    42: "lshift", 43: "backslash",
    44: "z", 45: "x", 46: "c", 47: "v", 48: "b", 49: "n", 50: "m",
    51: "comma", 52: "period", 53: "slash", 54: "rshift",
    56: "lalt", 57: "space", 58: "capslock",
    97: "rctrl", 100: "ralt",
    102: "home", 103: "up", 104: "pgup",
    105: "left", 106: "right",
    108: "down", 109: "pgdn",
    111: "del",
    # fn is firmware-internal on most boards (no evdev event), but map it
    # just in case a board does expose it
    464: "fn",
    125: "lwin",
}


def _find_keyboard(device_path=None):
    """Auto-detect the keyboard's evdev node by looking for 'BY Tech' or
    'Gaming Keyboard' in the device name. Returns the /dev/input/eventN path."""
    if device_path:
        return device_path
    # scan /proc/bus/input/devices for a match
    try:
        with open("/proc/bus/input/devices") as f:
            text = f.read()
    except OSError:
        raise SystemExit("cannot read /proc/bus/input/devices")
    blocks = text.strip().split("\n\n")
    for block in blocks:
        name_line = ""
        handler_line = ""
        for line in block.split("\n"):
            if line.startswith("N:"):
                name_line = line.upper()
            if line.startswith("H:"):
                handler_line = line
        # look for the BY Tech keyboard (the main event interface, not
        # Consumer Control or System Control)
        if "BY TECH" in name_line and "GAMING KEYBOARD" in name_line:
            # prefer the node that has "kbd" in its handlers
            if "kbd" in handler_line.lower():
                for part in handler_line.split():
                    if part.startswith("event"):
                        return f"/dev/input/{part}"
    # fallback: any keyboard-like device
    for block in blocks:
        name_line = ""
        handler_line = ""
        for line in block.split("\n"):
            if line.startswith("N:"):
                name_line = line
            if line.startswith("H:"):
                handler_line = line
        if "kbd" in handler_line.lower():
            for part in handler_line.split():
                if part.startswith("event"):
                    # skip power buttons, lid switches
                    if "button" not in name_line.lower() and "switch" not in name_line.lower():
                        return f"/dev/input/{part}"
    raise SystemExit(
        "no keyboard input device found; specify --input /dev/input/eventN"
    )


# evdev input_event struct: time_sec (long), time_usec (long), type (u16),
# code (u16), value (s32). Size depends on the arch (LP64: 24 bytes).
_EVENT_FMT = "llHHi"
_EVENT_SIZE = struct.calcsize(_EVENT_FMT)


class KeyListener(threading.Thread):
    """Background thread that reads evdev events and records press/release
    timestamps for each profile key-name. Thread-safe via a lock."""

    def __init__(self, device_path, profile_keys):
        super().__init__(daemon=True)
        self.device_path = device_path
        self.profile_keys = set(profile_keys)  # known key names from profile
        self.lock = threading.Lock()
        # key_name → {down_t, up_t, held}
        self.state = {}
        # for heatmap: key_name → cumulative press count (never reset)
        self.press_count = {}
        # ordered list of (time, key_name) for trail mode
        self.recent_presses = []
        self._fd = None

    def run(self):
        self._fd = os.open(self.device_path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            while True:
                try:
                    data = os.read(self._fd, _EVENT_SIZE * 64)
                except BlockingIOError:
                    time.sleep(0.002)  # ~500 Hz poll, lighter than select
                    continue
                except OSError:
                    break
                offset = 0
                while offset + _EVENT_SIZE <= len(data):
                    _sec, _usec, ev_type, code, value = struct.unpack_from(
                        _EVENT_FMT, data, offset
                    )
                    offset += _EVENT_SIZE
                    if ev_type != EV_KEY:
                        continue
                    name = EVDEV_TO_NAME.get(code)
                    if name is None or name not in self.profile_keys:
                        continue
                    now = time.monotonic()
                    with self.lock:
                        if value == KEY_DOWN:
                            self.state[name] = {
                                "down_t": now,
                                "up_t": None,
                                "held": True,
                            }
                            self.press_count[name] = (
                                self.press_count.get(name, 0) + 1
                            )
                            self.recent_presses.append((now, name))
                            # trim old presses (keep last 200)
                            if len(self.recent_presses) > 200:
                                self.recent_presses = self.recent_presses[-200:]
                        elif value == KEY_UP:
                            s = self.state.get(name)
                            if s and s["held"]:
                                s["up_t"] = now
                                s["held"] = False
        finally:
            os.close(self._fd)

    def snapshot(self):
        """Return a copy of the current state dict, plus recent_presses and
        press_count, under the lock."""
        with self.lock:
            return (
                dict(self.state),
                list(self.recent_presses),
                dict(self.press_count),
            )


# --------------------------------------------------------- distance util ---
def _key_dist(geom, name_a, name_b):
    """Grid-distance between two keys (Chebyshev on col/row would be 1 for
    neighbors, but we use Euclidean on the normalized geometry for a
    smooth radial falloff)."""
    ax, ay = geom[name_a][0], geom[name_a][1]
    bx, by = geom[name_b][0], geom[name_b][1]
    return math.hypot(ax - bx, ay - by)


def _col_row_dist(keys_tuples, name_a, name_b):
    """Chebyshev (grid) distance between two keys — 1 for any neighbor
    (including diagonals). Used when the effect wants a crisp '1 key radius'."""
    a = b = None
    for n, c, r in keys_tuples:
        if n == name_a:
            a = (c, r)
        if n == name_b:
            b = (c, r)
    if a is None or b is None:
        return 99.0
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


# ------------------------------------------------------------- effects ---

def _center_falloff(d, radius):
    """Gaussian falloff that strongly favors the center key.

    The pressed key itself (d ≈ 0) gets full brightness; immediate neighbors
    (d = 1) get a soft glow (~20%); anything further is a faint halo.
    This gives the visceral feel of *pressing a button* — the center pops
    and the surroundings are ambient."""
    if d < 0.5:
        return 1.0  # the center key: always full brightness
    # gaussian: sigma chosen so d=1 ≈ 0.20, d=1.5 ≈ 0.04
    sigma = 0.45 * radius
    return math.exp(-(d * d) / (2.0 * sigma * sigma))


def ease_out_exp(x, tau=0.3):
    """Exponential decay with time constant tau (in the 0..1 domain)."""
    return max(0.0, math.exp(-x / tau))


# --- splash (the core reactive effect) ---
def render_splash(k, geom, keys_tuples, state, now, o):
    """Bright disc on press, fades after release. Keys within `radius` grid
    cells of the pressed key light up; brightness falls off with distance."""
    fade = o.fade
    radius = o.radius
    for dst_name, dst_col, dst_row in keys_tuples:
        r_tot, g_tot, b_tot = 0.0, 0.0, 0.0
        for src_name, s in state.items():
            d = _col_row_dist(keys_tuples, src_name, dst_name)
            if d > radius:
                continue
            # time since press
            age = now - s["down_t"]
            if s["held"]:
                # while held: full brightness for center, falloff with dist
                bright = 1.0
            else:
                # after release: fade out
                release_age = now - s["up_t"]
                bright = ease_out_exp(release_age, fade)
            if bright < 0.01:
                continue
            # distance attenuation: center key pops, neighbors are a soft glow
            dist_atten = _center_falloff(d, radius)
            val = bright * dist_atten
            if o.mode == "colorful":
                # hue based on which key was pressed (column position)
                src_col = None
                for n, c, _r in keys_tuples:
                    if n == src_name:
                        src_col = c
                        break
                hue = (src_col or 0) / k.p.cols
                cr, cg, cb = palette_at(hue - age * o.scroll, v=val)
            else:
                cr = int(o.base_color[0] * val)
                cg = int(o.base_color[1] * val)
                cb = int(o.base_color[2] * val)
            r_tot += cr
            g_tot += cg
            b_tot += cb
        k.set_key(
            dst_name,
            min(255, int(r_tot)),
            min(255, int(g_tot)),
            min(255, int(b_tot)),
        )


# --- ripple: expanding ring from pressed key ---
def render_ripple(k, geom, keys_tuples, state, now, o):
    """A thin ring expands outward from the pressed key at ripple_speed, fading
    as it grows. Multiple keypresses stack their rings additively."""
    fade = o.fade
    speed = o.ripple_speed
    ring_width = o.ripple_width
    for dst_name, dst_col, dst_row in keys_tuples:
        r_tot, g_tot, b_tot = 0.0, 0.0, 0.0
        for src_name, s in state.items():
            age = now - s["down_t"]
            if age > fade * 3:
                continue  # too old, skip
            d = _col_row_dist(keys_tuples, src_name, dst_name)
            # --- center flash: the pressed key itself flashes bright on impact
            if d < 0.5:
                center_bright = ease_out_exp(age, fade * 0.4)  # fast decay
                val = center_bright
            else:
                # --- expanding ring
                # current ring radius (in grid units)
                ring_r = age * speed
                # how close is this key to the ring front?
                ring_dist = abs(d - ring_r)
                if ring_dist > ring_width:
                    continue
                # ring brightness: gaussian around the ring front, decaying over time
                ring_val = math.exp(-(ring_dist ** 2) / (2 * (ring_width * 0.5) ** 2))
                time_decay = ease_out_exp(age, fade)
                val = ring_val * time_decay
            if val < 0.01:
                continue
            if o.mode == "colorful":
                src_col = None
                for n, c, _r in keys_tuples:
                    if n == src_name:
                        src_col = c
                        break
                hue = (src_col or 0) / k.p.cols + age * 0.5
                cr, cg, cb = palette_at(hue, v=val)
            else:
                cr = int(o.base_color[0] * val)
                cg = int(o.base_color[1] * val)
                cb = int(o.base_color[2] * val)
            r_tot += cr
            g_tot += cg
            b_tot += cb
        k.set_key(
            dst_name,
            min(255, int(r_tot)),
            min(255, int(g_tot)),
            min(255, int(b_tot)),
        )


# --- trail: typing paints a gradient wake ---
def render_trail(k, geom, keys_tuples, recent_presses, now, o):
    """Each recently-pressed key glows, and the hue shifts smoothly along the
    sequence of presses — so typing a word paints a gradient trail across the
    keys you touched, fading over time."""
    fade = o.fade
    radius = o.radius
    trail_len = min(o.trail_length, len(recent_presses))
    if trail_len == 0:
        for name, _, _ in keys_tuples:
            k.set_key(name, 0, 0, 0)
        return
    # take the last trail_len presses
    trail = recent_presses[-trail_len:]
    for dst_name, dst_col, dst_row in keys_tuples:
        r_tot, g_tot, b_tot = 0.0, 0.0, 0.0
        for idx, (press_t, src_name) in enumerate(trail):
            age = now - press_t
            if age > fade * 2.5:
                continue
            d = _col_row_dist(keys_tuples, src_name, dst_name)
            if d > radius:
                continue
            dist_atten = _center_falloff(d, radius)
            time_decay = ease_out_exp(age, fade)
            val = dist_atten * time_decay
            if val < 0.01:
                continue
            # hue walks along the trail: each successive press shifts hue
            hue = idx / max(1, trail_len) + now * o.scroll * 0.1
            if o.mode == "colorful":
                cr, cg, cb = palette_at(hue, v=val)
            else:
                cr = int(o.base_color[0] * val)
                cg = int(o.base_color[1] * val)
                cb = int(o.base_color[2] * val)
            r_tot += cr
            g_tot += cg
            b_tot += cb
        k.set_key(
            dst_name,
            min(255, int(r_tot)),
            min(255, int(g_tot)),
            min(255, int(b_tot)),
        )


# --- heatmap: keys accumulate heat with each press ---
def render_heatmap(k, geom, keys_tuples, state, press_count, now, o):
    """Keys that are pressed more often glow hotter (blue→cyan→green→yellow→red).
    Heat decays slowly over time, so the board cools down when you stop typing,
    but frequently-used keys stay warm longer. Nearby keys get a faint bleed."""
    max_count = max(press_count.values()) if press_count else 1
    max_count = max(max_count, 1)
    decay_rate = o.heat_decay
    radius = max(1.0, o.radius * 0.6)  # smaller bleed radius for heatmap
    for dst_name, dst_col, dst_row in keys_tuples:
        heat = 0.0
        for src_name, count in press_count.items():
            d = _col_row_dist(keys_tuples, src_name, dst_name)
            if d > radius + 0.5:
                continue
            # base heat from press count
            src_heat = count / max_count
            # if key was recently pressed, boost
            s = state.get(src_name)
            if s:
                age = now - s["down_t"]
                recency_boost = ease_out_exp(age, decay_rate) * 0.4
                src_heat = min(1.0, src_heat + recency_boost)
            # distance falloff
            heat += src_heat * _center_falloff(d, radius)
        heat = min(1.0, heat)
        # color: cold(blue) → warm(red) via the heatmap spectrum
        # hue: 0.66 (blue) → 0.5 (cyan) → 0.33 (green) → 0.16 (yellow) → 0.0 (red)
        hue = 0.66 * (1.0 - heat)
        r, g, b = hsv(hue, s=0.9, v=heat)
        k.set_key(dst_name, r, g, b)


# --- raindrops: random-colored splashes ---
# Each press gets a random hue assigned (stored in this dict, keyed by
# (press_time, key_name) to allow the same key pressed twice to get
# different colors).
_raindrop_hues = {}


def render_raindrops(k, geom, keys_tuples, state, recent_presses, now, o):
    """Each keypress drops a random-colored splash. Splashes stack additively
    so rapid typing creates a watercolor layering effect."""
    fade = o.fade * 1.5  # raindrops linger a bit longer
    radius = o.radius
    # assign random hues to new presses
    import random
    for press_t, name in recent_presses:
        key = (press_t, name)
        if key not in _raindrop_hues:
            _raindrop_hues[key] = random.random()
    # prune old hues
    cutoff = now - fade * 3
    to_del = [k for k in _raindrop_hues if k[0] < cutoff]
    for k2 in to_del:
        del _raindrop_hues[k2]

    for dst_name, dst_col, dst_row in keys_tuples:
        r_tot, g_tot, b_tot = 0.0, 0.0, 0.0
        for (press_t, src_name), hue in _raindrop_hues.items():
            age = now - press_t
            if age > fade * 2.5:
                continue
            d = _col_row_dist(keys_tuples, src_name, dst_name)
            if d > radius:
                continue
            dist_atten = _center_falloff(d, radius)
            time_decay = ease_out_exp(age, fade)
            val = dist_atten * time_decay
            if val < 0.01:
                continue
            cr, cg, cb = hsv(hue, s=0.85, v=val)
            r_tot += cr
            g_tot += cg
            b_tot += cb
        k.set_key(
            dst_name,
            min(255, int(r_tot)),
            min(255, int(g_tot)),
            min(255, int(b_tot)),
        )


# --- sonar: ring that bounces off edges ---
def render_sonar(k, geom, keys_tuples, state, now, o):
    """A thin bright ring pings outward from the pressed key. When it reaches
    the board edge it reflects back inward, creating a sonar-pulse feel.
    Multiple pings from different keys interleave."""
    fade = o.fade * 2.0
    speed = o.ripple_speed * 0.8
    ring_width = o.ripple_width * 0.7  # thinner ring for sonar
    max_bounces = 3
    # board extents (in grid units)
    max_dist = max(k.p.cols, k.p.rows)
    for dst_name, dst_col, dst_row in keys_tuples:
        r_tot, g_tot, b_tot = 0.0, 0.0, 0.0
        for src_name, s in state.items():
            age = now - s["down_t"]
            if age > fade * 2:
                continue
            d = _col_row_dist(keys_tuples, src_name, dst_name)
            # --- center flash: the pressed key itself flashes bright on impact
            if d < 0.5:
                val = ease_out_exp(age, fade * 0.4)  # fast decay
            else:
                # --- bouncing ring
                raw_ring_r = age * speed
                # bounce: fold the ring radius back at max_dist boundaries
                # like a triangle wave with period 2*max_dist
                period = 2 * max_dist
                phase = raw_ring_r % period
                ring_r = phase if phase <= max_dist else period - phase
                ring_dist = abs(d - ring_r)
                if ring_dist > ring_width:
                    continue
                ring_val = math.exp(
                    -(ring_dist ** 2) / (2 * (ring_width * 0.4) ** 2)
                )
                time_decay = ease_out_exp(age, fade)
                val = ring_val * time_decay
            if val < 0.01:
                continue
            # sonar green-cyan color scheme with slight hue shift per bounce
            bounce_num = int(raw_ring_r / max_dist)
            hue = 0.45 + bounce_num * 0.08  # cyan → green shifts
            if o.mode == "colorful":
                cr, cg, cb = palette_at(hue + age * 0.1, v=val)
            else:
                cr, cg, cb = hsv(hue, s=0.7, v=val)
            r_tot += cr
            g_tot += cg
            b_tot += cb
        k.set_key(
            dst_name,
            min(255, int(r_tot)),
            min(255, int(g_tot)),
            min(255, int(b_tot)),
        )


# --- matrix: digital rain down the column ---
def render_matrix(k, geom, keys_tuples, state, now, o):
    """Digital rain: pressing a key drops a glowing green trail down its column."""
    speed = 15.0  # rows per sec
    tail_len = 3.0
    coords = {n: (c, r) for n, c, r in keys_tuples}
    for dst_name, dst_col, dst_row in keys_tuples:
        r_tot, g_tot, b_tot = 0.0, 0.0, 0.0
        for src_name, s in state.items():
            src_col, src_row = coords[src_name]
            if dst_col != src_col:
                continue
            age = now - s["down_t"]
            head_row = src_row + age * speed
            d_row = head_row - dst_row
            # d_row >= 0 means head is at or below the key (key is in the tail)
            if 0 <= d_row < tail_len:
                # brightest at head (d_row=0), fading up the tail
                val = 1.0 - (d_row / tail_len)
                # fade out the whole column over time
                val *= ease_out_exp(age, o.fade * 1.5)
                
                # Matrix green! (or custom color)
                if o.mode == "colorful":
                    cr, cg, cb = 0, int(255 * val), 0
                else:
                    cr = int(o.base_color[0] * val)
                    cg = int(o.base_color[1] * val)
                    cb = int(o.base_color[2] * val)
                
                r_tot += cr; g_tot += cg; b_tot += cb
        k.set_key(dst_name, min(255, int(r_tot)), min(255, int(g_tot)), min(255, int(b_tot)))


# --- crosshair: laser beams along row and column ---
def render_crosshair(k, geom, keys_tuples, state, now, o):
    """Laser beams shoot outward along the row and column of the pressed key."""
    speed = 40.0  # cells per sec (very fast!)
    coords = {n: (c, r) for n, c, r in keys_tuples}
    for dst_name, dst_col, dst_row in keys_tuples:
        r_tot, g_tot, b_tot = 0.0, 0.0, 0.0
        for src_name, s in state.items():
            src_col, src_row = coords[src_name]
            dx = abs(src_col - dst_col)
            dy = abs(src_row - dst_row)
            
            # must be on the same row or column
            if dx > 0 and dy > 0:
                continue
            
            dist = dx if dy == 0 else dy
            age = now - s["down_t"]
            front = age * speed
            
            # Beam hasn't reached here yet
            if front < dist:
                continue
            
            # How long ago did the beam pass this key?
            time_since_pass = (front - dist) / speed
            val = ease_out_exp(time_since_pass, o.fade * 0.4)
            
            # center flash
            if dist == 0:
                val = max(val, ease_out_exp(age, o.fade * 0.3))
            
            if val < 0.01: continue
            
            if o.mode == "colorful":
                cr, cg, cb = palette_at((src_col / k.p.cols) + age * 0.4, v=val)
            else:
                cr = int(o.base_color[0] * val)
                cg = int(o.base_color[1] * val)
                cb = int(o.base_color[2] * val)
            
            r_tot += cr; g_tot += cg; b_tot += cb
            
        k.set_key(dst_name, min(255, int(r_tot)), min(255, int(g_tot)), min(255, int(b_tot)))


# --- sparkle: fairy dust twinkling ---
def render_sparkle(k, geom, keys_tuples, state, now, o):
    """Fairy dust: random LEDs twinkle brightly in a wide radius around the pressed key."""
    radius = o.radius * 1.8 # wider area
    coords = {n: (c, r) for n, c, r in keys_tuples}
    for dst_name, dst_col, dst_row in keys_tuples:
        r_tot, g_tot, b_tot = 0.0, 0.0, 0.0
        for src_name, s in state.items():
            src_col, src_row = coords[src_name]
            dx = abs(src_col - dst_col)
            dy = abs(src_row - dst_row)
            d = max(dx, dy)
            if d > radius:
                continue
            
            age = now - s["down_t"]
            if age > o.fade * 2:
                continue
            
            # Twinkle logic: slice time into 40ms chunks so blinks hold briefly
            time_slice = int(now * 25)
            # pseudo-random float 0..1 for this specific key and time slice
            seed = (hash(dst_name) + hash(src_name) + time_slice) % 1000 / 1000.0
            
            # Only ~15% of keys should be lit at any given slice
            if seed > 0.15 and d > 0:
                continue
            
            dist_atten = _center_falloff(d, radius) if d > 0 else 1.0
            time_decay = ease_out_exp(age, o.fade)
            twinkle = seed / 0.15 if d > 0 else 1.0
            
            val = dist_atten * time_decay * twinkle
            if val < 0.01: continue
            
            if o.mode == "colorful":
                # random hue per sparkle!
                hue = (hash(dst_name) + time_slice) % 100 / 100.0
                cr, cg, cb = hsv(hue, s=0.8, v=val)
            else:
                cr = int(o.base_color[0] * val)
                cg = int(o.base_color[1] * val)
                cb = int(o.base_color[2] * val)
                
            r_tot += cr; g_tot += cg; b_tot += cb
            
        k.set_key(dst_name, min(255, int(r_tot)), min(255, int(g_tot)), min(255, int(b_tot)))


# --- erase: pressed keys go dark over an ambient base effect ---
def render_erase(k, keys_tuples, state, now, t, o):
    """The inverse of splash: the whole board runs an ambient base effect
    (--base, or the solid --color in single mode) and each pressed key punches a
    dark hole in it. The pressed key goes fully dark and keys within --radius
    dim with distance. The hole holds while the key is held and its color fades
    back after release; overlapping holes take the darkest."""
    ncols = k.p.cols
    mask = erase_mask(keys_tuples, state, now, o.radius, o.fade)
    for name, col, row in keys_tuples:
        if o.mode == "colorful":
            rgb = idle_color(o.base, col, row, ncols, t)
        else:
            rgb = o.base_color
        k.set_key(name, *apply_erase(rgb, mask.get(name, 0.0)))


def erase_mask(keys_tuples, state, now, radius, fade):
    """Darkness [0..1] per key name for the erase effect, from the listener
    state. Only keys with some darkness are in the dict. The pressed key is fully
    dark, keys within `radius` (Chebyshev grid cells) darken with distance, held
    keys stay dark and released ones recover with time constant `fade`.
    Shared by the reactive erase effect and the audio --erase overlay."""
    # wider than _center_falloff so neighbors read as switched off, not dimmed
    sigma = 0.7 * radius
    coords = {n: (c, r) for n, c, r in keys_tuples}
    mask = {}
    for src_name, s in state.items():
        if s["held"]:
            bright = 1.0
        else:
            # clamp: a release that lands between the caller reading `now`
            # and taking the snapshot gives a negative age, so darkness > 1
            bright = ease_out_exp(max(0.0, now - s["up_t"]), fade)
        if bright < 0.01 or src_name not in coords:
            continue  # fully recovered, skip the distance search
        src_col, src_row = coords[src_name]
        for name, col, row in keys_tuples:
            d = max(abs(col - src_col), abs(row - src_row))
            if d > radius:
                continue
            dark = bright
            if d >= 0.5:
                dark *= math.exp(-(d * d) / (2.0 * sigma * sigma))
            if dark > mask.get(name, 0.0):
                mask[name] = dark
    return mask


def apply_erase(rgb, dark):
    """Scale an (r, g, b) by the remaining brightness 1 - dark."""
    if dark <= 0.0:
        return rgb
    keep = 1.0 - dark
    return (int(rgb[0] * keep), int(rgb[1] * keep), int(rgb[2] * keep))


# ----------------------------------------------------------- main loop ---
REACTIVE_EFFECTS = ("splash", "ripple", "trail", "heatmap", "raindrops", "sonar", "matrix", "crosshair", "sparkle", "erase")


def run_reactive(k, argv):
    """Reactive lighting: the keyboard responds to keypresses with localized
    light effects that fade out over time. Runs until Ctrl-C."""
    p = argparse.ArgumentParser(
        prog="keyboardrgb.py reactive",
        description="reactive keypress lighting effects",
    )
    p.add_argument(
        "--effect",
        choices=REACTIVE_EFFECTS,
        default="splash",
        help="splash = bright disc fades after release (default); "
        "ripple = expanding ring from each press; "
        "trail = typing paints a hue-shifting wake; "
        "heatmap = frequently-pressed keys glow hotter; "
        "raindrops = random-colored splashes that layer; "
        "sonar = ring that bounces off board edges; "
        "matrix = digital rain falls down the column; "
        "crosshair = laser beams shoot along row and column; "
        "sparkle = fairy dust twinkles in a wide radius; "
        "erase = pressed keys go dark over an ambient base effect",
    )
    p.add_argument(
        "--base",
        choices=["gradient", "breathe", "wave"],
        default="gradient",
        help="erase: ambient effect on the rest of the board in colorful mode "
        "(default gradient); single mode uses a solid --color instead",
    )
    p.add_argument(
        "--mode",
        choices=["colorful", "single"],
        default="colorful",
        help="colorful = palette-based hues; single = one color (default colorful)",
    )
    p.add_argument(
        "--color",
        default="009bde",
        help="base color for single mode (default 009bde)",
    )
    p.add_argument(
        "--radius",
        type=float,
        default=1.5,
        help="light radius around the pressed key in grid cells (default 1.5; "
        "1.0 = immediate neighbors only)",
    )
    p.add_argument(
        "--fade",
        type=float,
        default=0.5,
        help="fade-out time constant in seconds (default 0.5)",
    )
    p.add_argument(
        "--scroll",
        type=float,
        default=0.15,
        help="hue scroll speed for colorful mode (default 0.15)",
    )
    p.add_argument(
        "--ripple-speed",
        dest="ripple_speed",
        type=float,
        default=6.0,
        help="ripple/sonar: ring expansion speed in grid cells/sec (default 6.0)",
    )
    p.add_argument(
        "--ripple-width",
        dest="ripple_width",
        type=float,
        default=1.5,
        help="ripple/sonar: ring thickness in grid cells (default 1.5)",
    )
    p.add_argument(
        "--trail-length",
        dest="trail_length",
        type=int,
        default=20,
        help="trail: how many recent presses to show (default 20)",
    )
    p.add_argument(
        "--heat-decay",
        dest="heat_decay",
        type=float,
        default=5.0,
        help="heatmap: seconds for recent-press boost to decay (default 5.0)",
    )
    p.add_argument("--fps", type=float, default=60.0, help="render frame rate")
    p.add_argument(
        "--input",
        default=None,
        help="evdev input device (default: auto-detect the keyboard)",
    )
    p.add_argument(
        "--duration", type=float, default=None, help="stop after N seconds"
    )
    p.add_argument("--debug", action="store_true")
    o = p.parse_args(argv)

    o.base_color = parse_hex(o.color)
    input_dev = _find_keyboard(o.input)
    print(f"reactive: effect={o.effect} mode={o.mode} radius={o.radius:g} "
          f"fade={o.fade:g}s fps={o.fps:g} input={input_dev}")

    # build lookup structures
    geom = k.p.geom
    keys_tuples = k.p.keys_tuples
    profile_keys = {name for name, _, _ in keys_tuples}

    # start the input listener
    listener = KeyListener(input_dev, profile_keys)
    listener.start()

    frame_dt = 1.0 / o.fps
    t0 = time.monotonic()
    frames = 0

    # pre-clean old state periodically
    last_gc = t0

    try:
        while o.duration is None or time.monotonic() - t0 < o.duration:
            tstart = time.monotonic()
            now = tstart
            state, recent_presses, press_count = listener.snapshot()

            # garbage-collect old state entries (> 10s after release)
            if now - last_gc > 2.0:
                last_gc = now
                cutoff = now - max(o.fade * 4, 10.0)
                to_del = []
                for name, s in state.items():
                    if not s["held"] and s["up_t"] is not None and s["up_t"] < cutoff:
                        to_del.append(name)
                for name in to_del:
                    with listener.lock:
                        listener.state.pop(name, None)

            k.clear()
            if o.effect == "splash":
                render_splash(k, geom, keys_tuples, state, now, o)
            elif o.effect == "ripple":
                render_ripple(k, geom, keys_tuples, state, now, o)
            elif o.effect == "trail":
                render_trail(k, geom, keys_tuples, recent_presses, now, o)
            elif o.effect == "heatmap":
                render_heatmap(k, geom, keys_tuples, state, press_count, now, o)
            elif o.effect == "raindrops":
                render_raindrops(k, geom, keys_tuples, state, recent_presses, now, o)
            elif o.effect == "sonar":
                render_sonar(k, geom, keys_tuples, state, now, o)
            elif o.effect == "matrix":
                render_matrix(k, geom, keys_tuples, state, now, o)
            elif o.effect == "crosshair":
                render_crosshair(k, geom, keys_tuples, state, now, o)
            elif o.effect == "sparkle":
                render_sparkle(k, geom, keys_tuples, state, now, o)
            elif o.effect == "erase":
                render_erase(k, keys_tuples, state, now, now - t0, o)

            _flush(k)
            frames += 1
            if o.debug and frames % int(o.fps) == 0:
                active = sum(1 for s in state.values()
                             if s["held"] or (s.get("up_t") and now - s["up_t"] < o.fade * 2))
                print(
                    f"frame {frames}: active_keys={active} "
                    f"total_presses={sum(press_count.values())} "
                    f"dt={(time.monotonic() - tstart) * 1000:.1f}ms"
                )
            time.sleep(max(0.0, frame_dt - (time.monotonic() - tstart)))
    except KeyboardInterrupt:
        pass
    finally:
        try:
            k.clear()
            k.flush()
        except OSError:
            pass
    print(f"{frames} frames in {time.monotonic() - t0:.1f}s")
