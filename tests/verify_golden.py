#!/usr/bin/env python3
"""Byte-identity gate for refactors of the effect code.

Drives keyboardrgb's real CLI (every effect family) with the device, ioctl,
clock, audio/screen capture and key input monkeypatched, and hashes the exact
packets each effect would SET_FEATURE to the board over its first FRAMES frames
plus its exit frame. Run with --save to snapshot the current code as the
baseline; run with no args to assert nothing changed.

    ./tests/verify_golden.py --save    # snapshot baseline (before a refactor)
    ./tests/verify_golden.py           # fail if any effect's frame bytes changed

No hardware, no PulseAudio, fully deterministic: the clock only advances inside
time.sleep, Python's str hash is pinned (sparkle uses hash()), and the global
RNG is reseeded per case (raindrops uses random.random()).
"""
import hashlib
import io
import json
import math
import os
import random
import sys
import tempfile
import threading

if os.environ.get("PYTHONHASHSEED") != "0":  # sparkle hashes key names
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable] + sys.argv)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # import the package modules from repo root
BASELINE = os.path.join(HERE, "golden_frames.json")

FRAMES = 8  # frames captured per case (plus whatever the effect sends on exit)
T0 = 1000.0

# --- a fake hidraw node find_device() will discover ---------------------------
# find_device: USB-id substring in the uppercased uevent + b"\x85\x06" in the
# descriptor. basename "null" makes Kbd open the real /dev/null (a harmless fd).
FAKE_NODE = "/sys/class/hidraw/null"
FAKE_UEVENT = "MODALIAS=hid:b0003g0001v0000258Ap0000010C\n"
FAKE_DESC = b"\x05\x01\x09\x06\x85\x06\x75\x08"  # contains report-id-6 marker 85 06

CAPTURED = []  # packet bytes, in SET_FEATURE order
CLOCK = [T0]   # advanced only by the fake sleep


def _fake_open(path, mode="r", *a, **k):
    if path.endswith("uevent"):
        return io.StringIO(FAKE_UEVENT)
    if path.endswith("report_descriptor"):
        return io.BytesIO(FAKE_DESC)
    return open(path, mode, *a, **k)


def _fake_ioctl(fd, req, arg, mutate=True):
    CAPTURED.append(bytes(arg))
    return 0


def _fake_sleep(x):
    # only the main thread drives frames; listener threads never get here
    if len(CAPTURED) >= FRAMES:
        raise KeyboardInterrupt
    CLOCK[0] += max(0.0, x)


def _audio_window(n, i, silent):
    """Synthetic int16 window whose pitch and loudness drift per read."""
    if silent:
        return (0,) * n
    f1, f2 = 3 + i, 40 + 7 * i
    amp = 6000 + 1500 * i
    return tuple(
        int(amp * math.sin(2 * math.pi * f1 * s / n)
            + 0.4 * amp * math.sin(2 * math.pi * f2 * s / n))
        for s in range(n)
    )


class FakeTap:
    """Stand-in for audio.AudioTap. source 'silent' feeds zeros (idle path)."""

    def __init__(self, source, rate, nsamples):
        self.silent = source == "silent"
        self.source, self.eof, self.drained = source or "fake", False, 0
        self.n, self.i = nsamples, 0

    def read(self):
        self.i += 1
        return _audio_window(self.n, self.i, self.silent)

    def close(self):
        pass


class FakeScreenTap:
    """Stand-in for screen.ScreenTap: a moving synthetic gradient grid."""

    def __init__(self, output, follow, cols, rows, res=144, blur=2.0, fps=24.0):
        self.cols, self.rows = cols, rows
        self.output, self.backend, self.i = output or "FAKE-1", "grim", 0

    def read(self):
        self.i += 1
        return [
            ((c * 16 + self.i * 9) % 256, (r * 40 + self.i * 5) % 256, (c * r * 7) % 256)
            for r in range(self.rows) for c in range(self.cols)
        ]

    def close(self):
        pass


# scripted key events relative to T0: (dt, name, down)
KEY_SCRIPT = (
    (-0.30, "f", True), (-0.20, "f", False),
    (-0.05, "j", True),
    (0.010, "space", True), (0.040, "space", False),
    (0.020, "a", True), (0.060, "a", False),
    (0.050, "k", True),
    (0.080, "j", False),
    (0.090, "1", True), (0.100, "1", False),
)


class FakeKeyListener:
    """Stand-in for reactive.KeyListener replaying KEY_SCRIPT against CLOCK."""

    def __init__(self, device_path, profile_keys, aliases=None):
        self.profile_keys = set(profile_keys)
        self.lock = threading.Lock()
        self.state = {}

    def start(self):
        pass

    def snapshot(self):
        now = CLOCK[0]
        state, recent, counts = {}, [], {}
        for dt, name, down in sorted(KEY_SCRIPT, key=lambda e: e[0]):
            t = T0 + dt
            if t > now or name not in self.profile_keys:
                continue
            if down:
                state[name] = {"down_t": t, "up_t": None, "held": True}
                counts[name] = counts.get(name, 0) + 1
                recent.append((t, name))
            elif name in state and state[name]["held"]:
                state[name]["up_t"] = t
                state[name]["held"] = False
        self.state = state
        return dict(state), recent, counts

    def gc(self, cutoff):
        pass

    def stop(self):
        pass


def install():
    """Monkeypatch the modules for deterministic, hardware-free capture."""
    import fcntl
    import glob
    import time

    import device
    import effects
    import reactive
    import screen

    # keep the device lock away from a real running instance
    os.environ["KEYBOARDRGB_RUNTIME_DIR"] = tempfile.mkdtemp(prefix="kbdrgb-test-")
    glob.glob = lambda pat: [FAKE_NODE] if "hidraw" in pat else []
    device.open = _fake_open          # shadows builtin open inside find_device
    fcntl.ioctl = _fake_ioctl
    time.monotonic = lambda: CLOCK[0]
    time.time = lambda: CLOCK[0]
    time.sleep = _fake_sleep
    effects.AudioTap = FakeTap
    screen.ScreenTap = FakeScreenTap
    reactive.KeyListener = FakeKeyListener
    reactive._find_keyboard = lambda path=None: path or "/dev/input/fake"


def run_effect(cli, argv):
    """Run one CLI invocation, return sha256 over every emitted packet."""
    CAPTURED.clear()
    CLOCK[0] = T0
    random.seed(1234)
    sys.argv = ["keyboardrgb.py"] + argv
    try:
        cli.main()
    except KeyboardInterrupt:
        pass
    if not CAPTURED:
        raise SystemExit(f"no frame captured for: {argv}")
    h = hashlib.sha256()
    for pkt in CAPTURED:
        h.update(pkt)
    return f"{len(CAPTURED)}:{h.hexdigest()}"


REACTIVE = ("splash", "ripple", "trail", "heatmap", "raindrops", "sonar",
            "matrix", "crosshair", "sparkle", "erase")
AUDIO = ("wave", "bars", "split", "flow", "vortex", "ripple")

CASES = {
    "color":         ["color", "ff8800"],
    "color-once":    ["color", "ff8800", "--once"],
    "off":           ["off"],
    "key":           ["key", "a", "ff0000", "S", "00ff00", "--once"],
    "gradient":      ["gradient", "ff0000", "0000ff"],
    "rainbow":       ["rainbow", "--once"],
    "wave":          ["wave"],
    "wave-dur":      ["wave", "0.05"],
    "flux-walk":     ["flux", "--seed", "7"],
    "flux-walk-4":   ["flux", "--seed", "3", "--colors", "4", "--speed", "2.5", "--sharp", "4"],
    "flux-drift":    ["flux", "--motion", "drift", "--colors", "2"],
    "flux-hex":      ["flux", "--motion", "drift", "--hex", "112233,ffeedd,00ff00", "--fps", "30"],
    "screen":        ["screen"],
    "screen-raw":    ["screen", "--raw", "--smooth", "0"],
    "screen-look":   ["screen", "--sat", "2", "--gain", "0.8", "--gamma", "0.7", "--smooth", "0.9"],
    "audio-bars-top":   ["audio", "--effect", "bars", "--direction", "top"],
    "audio-bars-left":  ["audio", "--effect", "bars", "--direction", "left"],
    "audio-bars-right": ["audio", "--effect", "bars", "--direction", "right"],
    "audio-bars-sides": ["audio", "--effect", "bars", "--direction", "sides"],
    "audio-single":  ["audio", "--mode", "single", "--color", "00ff99", "--gain", "1.7"],
    "audio-smooth":  ["audio", "--effect", "vortex", "--smooth", "0.3", "--radius", "0.3"],
    "audio-flowspd": ["audio", "--effect", "flow", "--flow-speed", "3", "--fps", "60"],
    "audio-erase":   ["audio", "--erase", "--erase-radius", "2", "--erase-fade", "0.2"],
    "audio-idle-gradient": ["audio", "--source", "silent"],
    "audio-idle-breathe":  ["audio", "--source", "silent", "--default", "breathe"],
    "audio-idle-wave":     ["audio", "--source", "silent", "--default", "wave"],
    "audio-idle-off":      ["audio", "--source", "silent", "--default", "off"],
    "audio-palette": ["audio", "--palette", "ff0000,00ff00,0000ff", "--default", "wave"],
    "audio-idle-palette": ["audio", "--source", "silent", "--default", "breathe",
                           "--palette", "112233,ddeeff"],
    "reactive-palette": ["reactive", "--palette", "ff00ff,00ffff,ffff00,ff8800,00ff88"],
    "reactive-erase-palette": ["reactive", "--effect", "erase", "--palette", "330000,ff6600"],
    "reactive-sonar-palette": ["reactive", "--effect", "sonar", "--palette", "00ff00,0000ff"],
    "audio-gap":     ["audio", "--idle-gap", "0", "--silence-level", "0.5"],
    "reactive-single":  ["reactive", "--mode", "single", "--color", "ff00aa"],
    "reactive-erase-breathe": ["reactive", "--effect", "erase", "--base", "breathe"],
    "reactive-erase-single":  ["reactive", "--effect", "erase", "--mode", "single"],
    "reactive-ripple-tuned":  ["reactive", "--effect", "ripple", "--ripple-speed", "12",
                               "--ripple-width", "0.8", "--fade", "0.3"],
    "reactive-trail-short":   ["reactive", "--effect", "trail", "--trail-length", "2"],
    "reactive-heat-decay":    ["reactive", "--effect", "heatmap", "--heat-decay", "0.5",
                               "--radius", "3"],
}
for _fx in AUDIO:
    CASES[f"audio-{_fx}"] = ["audio", "--effect", _fx]
for _fx in REACTIVE:
    CASES[f"reactive-{_fx}"] = ["reactive", "--effect", _fx]
# the same families on the 6-row Aula F75 layout
for _name in ("color", "gradient", "rainbow", "wave", "flux-walk", "screen",
              "audio-wave", "audio-bars", "audio-vortex", "audio-flow",
              "reactive-splash", "reactive-sonar", "reactive-matrix"):
    CASES[f"f75-{_name}"] = ["--profile", "aulaf75"] + CASES[_name]


def main():
    save = "--save" in sys.argv
    install()
    import keyboardrgb
    devnull = open(os.devnull, "w")
    real_stdout = sys.stdout
    hashes = {}
    for name, argv in CASES.items():
        sys.stdout = devnull  # silence the effects' own prints
        try:
            hashes[name] = run_effect(keyboardrgb, argv)
        finally:
            sys.stdout = real_stdout

    if save:
        with open(BASELINE, "w") as f:
            json.dump(hashes, f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"saved baseline: {BASELINE} ({len(hashes)} cases)")
        return 0

    if not os.path.exists(BASELINE):
        raise SystemExit("no baseline; run with --save first")
    with open(BASELINE) as f:
        base = json.load(f)
    ok = True
    for name in sorted(set(base) | set(hashes)):
        b, h = base.get(name), hashes.get(name)
        if b != h:
            ok = False
            print(f"  [DIFF] {name}\n        baseline={b}\n        current ={h}")
    print(f"ALL {len(hashes)} CASES IDENTICAL" if ok
          else "MISMATCH — refactor changed output")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
