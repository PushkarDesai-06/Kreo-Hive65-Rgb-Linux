#!/usr/bin/env python3
"""Byte-identity gate for the profile refactor.

Drives keyboardrgb's real CLI effects (color/gradient/rainbow/wave/audio) with the
device, ioctl, clock and audio capture monkeypatched, and hashes the exact packet
each effect would SET_FEATURE to the board. Run with --save to snapshot the
current code as the baseline; run with no args to assert nothing changed.

    ./tests/verify_golden.py --save    # snapshot baseline (before a refactor)
    ./tests/verify_golden.py           # fail if any effect's frame bytes changed

No hardware, no PulseAudio, fully deterministic (clock pinned, synthetic audio).
"""
import hashlib
import io
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # import the package modules from repo root
BASELINE = os.path.join(HERE, "golden_frames.json")

# --- a fake hidraw node both the old and new find_device() will discover ------
# Old find_device: substring "V0000258AP0000010C" in uppercased uevent + b"\x85\x06"
# in the descriptor. New find_device: same USB-id/report-6 checks, per profile.
# basename "null" makes Kbd open the real /dev/null (a harmless fd for ioctl).
FAKE_NODE = "/sys/class/hidraw/null"
FAKE_UEVENT = "MODALIAS=hid:b0003g0001v0000258Ap0000010C\n"
FAKE_DESC = b"\x05\x01\x09\x06\x85\x06\x75\x08"  # contains report-id-6 marker 85 06

# deterministic synthetic audio window (1024 int16 samples, ~5 cycles)
FAKE_SAMPLES = tuple(int(9000 * math.sin(2 * math.pi * 5 * i / 1024)) for i in range(1024))

CAPTURED = []  # list of packet bytes, in SET_FEATURE order


def _fake_open(path, mode="r", *a, **k):
    if path.endswith("uevent"):
        return io.StringIO(FAKE_UEVENT)
    if path.endswith("report_descriptor"):
        return io.BytesIO(FAKE_DESC)
    return open(path, mode, *a, **k)


def _fake_ioctl(fd, req, arg, mutate=True):
    # arg is the mutable packet buffer passed to HIDIOCSFEATURE
    CAPTURED.append(bytes(arg))
    return 0


class _StopClock(Exception):
    pass


def install():
    """Monkeypatch the modules for deterministic, hardware-free capture. Patch
    targets follow the post-split layout: find_device lives in device, AudioTap
    is looked up in effects."""
    import fcntl
    import glob
    import time

    import device
    import effects

    glob.glob = lambda pat: [FAKE_NODE] if "hidraw" in pat else []
    device.open = _fake_open          # shadows builtin open inside find_device
    fcntl.ioctl = _fake_ioctl
    time.monotonic = lambda: 1000.0   # pinned clock -> t == 0 everywhere
    time.time = lambda: 1000.0

    def _sleep(_):                    # first sleep after a frame ends the loop
        raise KeyboardInterrupt
    time.sleep = _sleep

    class FakeTap:
        def __init__(self, source, rate, nsamples):
            self.source, self.eof, self.drained = source or "fake", False, 0

        def read(self):
            return FAKE_SAMPLES

        def close(self):
            pass

    effects.AudioTap = FakeTap


def run_effect(cli, argv):
    """Run one CLI invocation, return sha256 of its first emitted frame."""
    CAPTURED.clear()
    sys.argv = ["keyboardrgb.py"] + argv
    try:
        cli.main()
    except (KeyboardInterrupt, _StopClock):
        pass
    if not CAPTURED:
        raise SystemExit(f"no frame captured for: {argv}")
    return hashlib.sha256(CAPTURED[0]).hexdigest()


CASES = {
    "color":         ["color", "ff8800", "--once"],
    "gradient":      ["gradient", "ff0000", "0000ff", "--once"],
    "rainbow":       ["rainbow", "--once"],
    "wave":          ["wave", "0.001"],  # dur>0 so it renders one frame then stops
    "audio-wave":    ["audio", "--effect", "wave", "--fps", "30"],
    "audio-bars":    ["audio", "--effect", "bars", "--fps", "30"],
    "audio-vortex":  ["audio", "--effect", "vortex", "--fps", "30"],
    "audio-ripple":  ["audio", "--effect", "ripple", "--fps", "30"],
    "audio-single":  ["audio", "--mode", "single", "--color", "00ff99", "--fps", "30"],
}


def main():
    save = "--save" in sys.argv
    install()
    import keyboardrgb
    # silence the effects' own prints
    devnull = open(os.devnull, "w")
    real_stdout = sys.stdout
    hashes = {}
    for name, argv in CASES.items():
        sys.stdout = devnull
        try:
            hashes[name] = run_effect(keyboardrgb, argv)
        finally:
            sys.stdout = real_stdout

    if save:
        os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
        with open(BASELINE, "w") as f:
            json.dump(hashes, f, indent=2, sort_keys=True)
        print(f"saved baseline: {BASELINE}")
        for k, v in sorted(hashes.items()):
            print(f"  {k:16s} {v[:16]}")
        return 0

    if not os.path.exists(BASELINE):
        raise SystemExit("no baseline; run with --save first")
    with open(BASELINE) as f:
        base = json.load(f)
    ok = True
    for name in sorted(set(base) | set(hashes)):
        b, h = base.get(name), hashes.get(name)
        mark = "OK " if b == h else "DIFF"
        if b != h:
            ok = False
        print(f"  [{mark}] {name}")
        if b != h:
            print(f"        baseline={b}\n        current ={h}")
    print("ALL FRAMES IDENTICAL" if ok else "MISMATCH — refactor changed output")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
