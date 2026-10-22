"""Live choice lists for params that pick a system resource: audio sources,
monitors and keyboard input devices. Cached briefly; every lookup degrades to
an empty list when the tool behind it is missing."""
import json
import subprocess
import time

_cache = {}
TTL = 15.0


def _cached(key, fn):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]
    try:
        val = fn()
    except Exception:
        val = []
    _cache[key] = (time.monotonic(), val)
    return val


def _audio_sources():
    try:
        out = subprocess.check_output(["pactl", "--format=json", "list", "sources"],
                                      text=True, stderr=subprocess.DEVNULL, timeout=2)
        items = []
        for s in json.loads(out):
            name = s.get("name")
            desc = s.get("description") or name
            if name:
                items.append((name, desc))
        return items
    except (OSError, ValueError, subprocess.SubprocessError):
        out = subprocess.check_output(["pactl", "list", "short", "sources"],
                                      text=True, stderr=subprocess.DEVNULL, timeout=2)
        return [(ln.split("\t")[1],) * 2 for ln in out.splitlines() if "\t" in ln]


def _monitors():
    import screen

    return [(n, n) for n in screen.list_outputs()]


def _inputs():
    with open("/proc/bus/input/devices") as f:
        blocks = f.read().strip().split("\n\n")
    items = []
    for block in blocks:
        name = handlers = ""
        for line in block.split("\n"):
            if line.startswith("N: Name="):
                name = line[8:].strip().strip('"')
            elif line.startswith("H: Handlers="):
                handlers = line[12:]
        low = name.lower()
        if "kbd" not in handlers or "button" in low or "switch" in low:
            continue
        for part in handlers.split():
            if part.startswith("event"):
                items.append((f"/dev/input/{part}", f"{name} ({part})"))
    return items


PROVIDERS = {"audio_sources": _audio_sources, "monitors": _monitors, "inputs": _inputs}


def choices(source):
    """[(value, label)] for a param's `source`."""
    fn = PROVIDERS.get(source)
    return _cached(source, fn) if fn else []
