#!/usr/bin/env python3
"""RGB control for SinoWealth / BY Tech RGB keyboards on Linux.

Each supported board is described by a JSON *profile* in profiles/ (USB id,
frame format, and key→LED layout); the driver auto-detects the attached board
and every effect reads its geometry from the profile, so the same code drives
different-sized keyboards. Adding a board is a new profiles/<id>.json file — no
code changes. See kbd_profiles.py. The default board is the Kreo Hive 65
(258a:010c): report 6, 520-byte frame, 68 keys, LED index = col*6 + row + 1.

Modules: color (color math), audio (capture + FFT), screen (monitor capture),
device (discovery + Kbd driver), effects (renderers), kbd_profiles (profile
loader). This file is the CLI.

Board selection (any subcommand):
  --profile NAME     force a specific profile (see --list-profiles)
  --device /dev/hidrawN   force the hidraw node
  --vid XXXX --pid XXXX   also match this USB id (test an uninstalled rebrand)
  --list-profiles    list known boards and exit

Usage:
  keyboardrgb.py color <rrggbb>              # whole board one color
  keyboardrgb.py key <keyname> <rrggbb> ...  # per-key colors (pairs), rest off
  keyboardrgb.py gradient <rrggbb> <rrggbb>  # left-to-right gradient
  keyboardrgb.py rainbow                     # rainbow across columns
  keyboardrgb.py wave [seconds] [--speed X]  # animated hue wave (forever if no time)
  keyboardrgb.py flux [options]              # drifting multi-source gradient
      --colors 2|3|4           number of moving color sources (default 3)
      --motion walk|drift      walk = random-walk + edge bounce (organic, unique
                               each run); drift = sum-of-sines (silky, reproducible)
      --hex R,R,...            custom source colors (default: colorful palette)
      --speed FLOAT            motion speed multiplier (1.0)
      --sharp FLOAT            blend sharpness, 2 = soft, higher = tighter (2.0)
      --seed INT               walk only: seed a repeatable wander
      --fps N --duration SEC   runs until Ctrl-C unless --duration is given
  keyboardrgb.py off                         # all LEDs off
  keyboardrgb.py status                      # what is driving the keyboard now
  keyboardrgb.py stop                        # stop whatever is driving it
  keyboardrgb.py raw <hex...>                # send raw feature report
  keyboardrgb.py walk [--delay S] [--start N] [--end N]
      # light one LED slot at a time to map a new board's layout (report-6 only)

  color/key/gradient/rainbow/wave stay on until Ctrl-C: the board reverts to
  its onboard lighting once streaming stops, so the tool holds the frame by
  re-sending it. Add --once to set a single frame and exit (for scripts).
  keyboardrgb.py audio [options]             # audio-reactive spectrum wave
      --mode colorful|single   coloring (default colorful = 4-color gradient)
      --color RRGGBB           color for single mode (default 009bde)
      --palette HEX,HEX,...    colorful-mode gradient colors (default
                               ff4242,7c3aed,06b6d4,eab308)
      --gain FLOAT             amplitude multiplier (default 1.0)
      --smooth FLOAT           smoothness multiplier (default 1.0)
      --scroll FLOAT           colorful gradient scroll speed in hue
                               cycles/sec, left-to-right; 0 = static (0.15)
      --effect NAME            wave  = center-out spectrum (default)
                               bars  = equalizer (see --direction for origin)
                               split = bass grows from the left edge, treble
                                       from the right, fading out in the middle
                               flow  = the left column tracks the bass and
                                       that punch travels left-to-right
                                       (speed set by --flow-speed)
                               vortex= black hole: dark center, rainbow ring
                                       spinning around it (faster when loud)
                               ripple= rings pushed outward by bass
                               (--shape is a backward-compatible alias)
      --direction NAME         bars only: edge the bars grow from —
                               bottom(default)|top|left|right|sides
                               (left/right/sides are horizontal, one band/row)
      --radius FLOAT           vortex event-horizon (hole) size 0..1 (0.18)
      --flow-speed FLOAT       flow only: bass-punch travel speed, cols/sec (8.0)
      --default NAME           non-audio effect shown when music is silent:
                               gradient(default)|breathe|wave|off. After
                               --idle-gap secs of silence it crossfades in;
                               sound returning fades back to audio instantly.
      --idle-gap SEC           silence before switching to --default (5.0)
      --silence-level FLOAT    peak below this = silence (0.004; tune per system)
      --erase                  pressed keys + neighbors go dark over the effect
      --erase-radius FLOAT     erase: darkened area in grid cells (default 1.5)
      --erase-fade FLOAT       erase: fade-back time in seconds (default 0.5)
      --input /dev/input/eventN  erase: evdev device (default: auto-detect)
      --fps N --source NAME --duration SEC --debug
    Captures system sound from the default sink's monitor via parec
    (PipeWire/PulseAudio); override with --source (see: pactl list short
    sources), or --source - to pipe raw s16le mono PCM on stdin.
  keyboardrgb.py screen [options]            # mirror a monitor onto the keys
      --output NAME            monitor to capture (default: the focused one;
                               see hyprctl monitors / wlr-randr)
      --follow / --no-follow   track the focused monitor live (default: follow)
      --res N                  capture height in px, the "144p" working res (144)
      --blur FLOAT             blur radius in px at 144p, 0 = none (2.0)
      --saturation FLOAT       saturation multiplier, 1 = faithful (1.5)
      --gain FLOAT             brightness multiplier (1.1)
      --gamma FLOAT            gamma, <1 brightens mid-tones (1.0)
      --smooth FLOAT           temporal smoothing 0..0.95 (0.5)
      --raw                    faithful colors (disable saturation/gain/gamma)
      --fps N --duration SEC --debug
    Grabs the display with grim (wlroots Wayland) or ffmpeg x11grab (X11),
    downscales to 144p, blurs, and streams it to the keys. Needs ffmpeg (plus
    grim on Wayland). Runs until Ctrl-C.
  keyboardrgb.py reactive [options]          # keypress-reactive lighting
      --effect NAME            splash   = bright disc fades after release (default)
                               ripple   = expanding ring from each press
                               trail    = typing paints a gradient wake
                               heatmap  = frequent keys glow hotter
                               raindrops= random-colored layered splashes
                               sonar    = ring bounces off board edges
                               matrix   = digital rain down the column
                               crosshair= laser beams along row and column
                               sparkle  = fairy dust twinkling in a wide radius
                               erase    = pressed keys go dark over --base
      --base gradient|breathe|wave  erase: ambient effect (default gradient)
    For erase on top of the music visualizer use `audio --erase` instead.
      --mode colorful|single   coloring (default colorful)
      --color RRGGBB           color for single mode (default 009bde)
      --palette HEX,HEX,...    colorful-mode gradient colors (default
                               ff4242,7c3aed,06b6d4,eab308)
      --radius FLOAT           light radius in grid cells (default 1.5)
      --fade FLOAT             fade-out time constant in seconds (default 0.5)
      --scroll FLOAT           hue scroll speed (default 0.15)
      --ripple-speed FLOAT     ring expansion speed, cells/sec (default 6.0)
      --ripple-width FLOAT     ring thickness, cells (default 1.5)
      --trail-length INT       recent presses to show (default 20)
      --heat-decay FLOAT       heatmap recency decay in seconds (default 5.0)
      --input /dev/input/eventN  evdev device (default: auto-detect)
      --fps N --duration SEC --debug
    Reads keyboard input via evdev and lights up keys around where you type.
    Each press creates a localized light effect that fades after release.

Only one process drives the board at a time: starting an effect stops the one
already running (a background runner, another CLI, or the app's live preview).

Device node + profile autodetected from /sys/class/hidraw (USB id + report id).
"""

import json
import os
import signal
import sys
import time

import devlock
import kbd_profiles
from color import parse_hex
from device import Kbd, PROFILES, find_device, _flush, _match_node, hold
from effects import (
    render_gradient,
    render_rainbow,
    run_audio,
    run_flux,
    run_screen,
    run_wave,
)
from reactive import run_reactive


def run_walk(k, argv):
    """Light one LED slot at a time so you can see which physical key each slot
    drives — the way to map a brand-new board's layout. Strictly report-6 (the
    RGB framebuffer), so it can never touch the report-5 flash/ISP channel."""
    import argparse

    p = argparse.ArgumentParser(
        prog="keyboardrgb.py walk",
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


def _terminate(signum, frame):
    """SIGTERM/SIGHUP -> the same cleanup as Ctrl-C (blank the board, exit)."""
    signal.signal(signum, signal.SIG_IGN)  # a second signal mustn't cut cleanup short
    raise KeyboardInterrupt


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
            print(
                f"{pid_:12s} {p.name}  ({p.key_count()} keys, {p.cols}x{p.rows}, "
                f"{p.pkt_len}B, usb={','.join(p.usb_ids)})"
            )
        return 0
    if not a:
        print(__doc__)
        return 1
    # color modes hold the frame until Ctrl-C (the board reverts to onboard
    # lighting when streaming stops); --once sets one frame and exits.
    once = "--once" in a
    a = [x for x in a if x != "--once"]
    cmd = a[0]
    if cmd == "status":
        print(devlock.describe(devlock.owner()))
        return 0
    if cmd == "stop":
        rec = devlock.owner()
        if rec is None:
            print(devlock.describe(None))
            return 0
        ok = devlock.request_release(rec)
        print("stopped" if ok else "could not stop it: " + devlock.describe(rec))
        return 0 if ok else 1
    if "-h" in a or "--help" in a:
        # help never needs the board, so it must not take it from a running effect
        return _help(cmd, a[1:])
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGHUP, _terminate)
    kind = "runner" if os.environ.get("KEYBOARDRGB_RUNNER") else "cli"
    lock = devlock.DeviceLock(kind, mode=cmd, argv=sys.argv[1:])
    if not lock.acquire(takeover=True):
        raise SystemExit("the keyboard is busy: " + devlock.describe(devlock.owner()))
    try:
        return _run(cmd, a, once, profiles, prof_name, dev_override)
    finally:
        lock.release()


def _help(cmd, argv):
    import effects
    import reactive

    specs = {"wave": effects.WAVE_SPEC, "flux": effects.FLUX_SPEC, "audio": effects.AUDIO_SPEC,
             "screen": effects.SCREEN_SPEC, "reactive": reactive.REACTIVE_SPEC}
    if cmd in specs:
        specs[cmd].parse(argv)  # argparse prints the help and exits
    elif cmd == "walk":
        run_walk(None, argv)
    else:
        print(__doc__)
    return 0


def _run(cmd, a, once, profiles, prof_name, dev_override):
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
        render_gradient(k, parse_hex(a[1]), parse_hex(a[2]))
        k.flush()
        if not once:
            hold(k, "gradient")
    elif cmd == "rainbow":
        render_rainbow(k)
        k.flush()
        if not once:
            hold(k, "rainbow")
    elif cmd == "wave":
        run_wave(k, a[1:])
    elif cmd == "flux":
        run_flux(k, a[1:])
    elif cmd == "audio":
        run_audio(k, a[1:])
    elif cmd == "screen":
        run_screen(k, a[1:])
    elif cmd == "reactive":
        run_reactive(k, a[1:])
    elif cmd == "walk":
        run_walk(k, a[1:])
    elif cmd == "raw":
        n = k.send_raw(bytes.fromhex("".join(a[1:])))
        print(f"sent {n} bytes")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
