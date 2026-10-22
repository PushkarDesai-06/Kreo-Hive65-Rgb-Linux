#!/usr/bin/env python3
"""Frame engine shared by the CLI and the GUI.

Effects are `LightingEffect` objects that render one frame at a time into a
`Canvas` (a per-key color buffer that duck-types the bits of `Kbd` effects use:
`.p`, `set_key`, `fill`, `clear`). Two drivers run them:

  drive()     the CLI loop: render, flush to the board, sleep, until Ctrl-C.
              Reproduces the old per-effect loops exactly (byte-identical
              frames; see tests/verify_golden.py).
  LiveEngine  a background thread for the GUI: renders the active effect for
              the on-screen preview, applies parameter changes live, and hands
              frames to an optional DeviceSink that streams them to the board.

Inputs (audio, key presses, screen capture) come from an `Inputs` factory so
the GUI can substitute fallbacks when the system ones are unavailable.
"""
import errno
import queue
import threading
import time

from device import Kbd, _flush
from errors import SetupError


def write_frame(k, colors, bg=None):
    """Put a canvas frame into a Kbd buffer: `bg` (a fill() color) reaches every
    slot, like Kbd.fill; then each key gets its own color."""
    if bg is not None:
        k.fill(*bg)
    else:
        k.clear()
    for (name, _c, _r), rgb in zip(k.p.keys_tuples, colors):
        k.set_key(name, *rgb)


class Canvas:
    """Per-key RGB frame for one profile, in profile.keys_tuples order."""

    def __init__(self, profile):
        self.p = profile
        self.index = {name: i for i, (name, _c, _r) in enumerate(profile.keys_tuples)}
        self.colors = [(0, 0, 0)] * len(self.index)
        self.bg = None  # set by fill(): Kbd.fill also lights the unmapped slots

    def set_key(self, name, r, g, b):
        self.colors[self.index[name]] = (r, g, b)

    def fill(self, r, g, b):
        self.bg = (r, g, b)
        self.colors = [(r, g, b)] * len(self.index)

    def clear(self):
        self.bg = None
        self.colors = [(0, 0, 0)] * len(self.index)

    def to_kbd(self, k):
        write_frame(k, self.colors, self.bg)


class Inputs:
    """Factories for the external inputs effects read. Looked up on the modules
    at call time so tests can monkeypatch effects.AudioTap and friends."""

    def audio(self, source, rate, nsamples):
        import effects

        return effects.AudioTap(source, rate, nsamples)

    def keys(self, input_path, names, aliases=None):
        """Start a key listener; returns (listener, device_path)."""
        import reactive

        dev = reactive._find_keyboard(input_path)
        listener = reactive.KeyListener(dev, names, aliases)
        listener.start()
        return listener, dev

    def screen(self, output, follow, cols, rows, res, blur, fps):
        import screen

        return screen.ScreenTap(output, follow, cols, rows, res=res, blur=blur, fps=fps)


class LightingEffect:
    """One lighting effect. Subclasses set `spec`, open their inputs in start(),
    render into the canvas in step(), and release inputs in stop()."""

    spec = None                 # params.EffectSpec
    needs = frozenset()         # subset of {"audio", "keys", "screen"}
    animated = True             # False: render once, then just hold the frame
    clock = "mono"              # "wall": time.time (the legacy wave loop)
    fixed_sleep = False         # sleep a full frame_dt regardless of render time
    clear_on_exit = True        # CLI: blank the board when the loop ends
    summary = True              # CLI: print "N frames in Ts" at the end

    def __init__(self, profile, o, inputs=None):
        self.p = profile
        self.o = o
        self.inputs = inputs or Inputs()
        self.log = print

    @property
    def frame_dt(self):
        return 1.0 / self.o.fps

    def start(self):
        """Open inputs. Raises SetupError when something is missing."""

    def describe(self):
        """Startup line the CLI prints (after start)."""
        return None

    def step(self, canvas, now, t):
        """Render one frame at monotonic time `now`, `t` seconds since start.
        Returns False when there is nothing new to show this tick."""
        raise NotImplementedError

    def debug_every(self):
        return max(1, int(getattr(self.o, "fps", 60)))

    def debug_line(self, frames, tstart, tflush):
        return None

    def apply(self, changed):
        """Apply changed param values in place. Returns False when one of them
        needs the effect rebuilt (the param is marked live=False)."""
        if self.spec is None:
            return False
        for name in changed:
            prm = self.spec.by_name.get(name)
            if prm is None or not prm.live:
                return False
        for name, v in changed.items():
            setattr(self.o, name, v)
        self.retune()
        return True

    def retune(self):
        """Recompute anything derived from live params."""

    def stop(self):
        """Release inputs."""


def drive(k, fx, duration=None, debug=False):
    """The CLI frame loop: run `fx` on the board until Ctrl-C or `duration`."""
    clock = time.time if fx.clock == "wall" else time.monotonic
    fx.start()
    line = fx.describe()
    if line:
        print(line)
    canvas = Canvas(k.p)
    t0 = clock()
    frames = 0
    try:
        while duration is None or clock() - t0 < duration:
            tstart = clock()
            if fx.step(canvas, tstart, tstart - t0):
                canvas.to_kbd(k)
                tflush = clock()
                _flush(k)
                frames += 1
                if debug and frames % fx.debug_every() == 0:
                    msg = fx.debug_line(frames, tstart, tflush)
                    if msg:
                        print(msg)
            if fx.fixed_sleep:
                time.sleep(fx.frame_dt)
            else:
                time.sleep(max(0.0, fx.frame_dt - (clock() - tstart)))
    except KeyboardInterrupt:
        pass
    finally:
        fx.stop()
        if fx.clear_on_exit:
            try:
                k.clear()
                k.flush()
            except OSError:
                pass
    if fx.summary:
        print(f"{frames} frames in {clock() - t0:.1f}s")


# --------------------------------------------------------------- GUI side ---
class NullTap:
    """Silent audio source: the visualizer falls back to its idle effect."""

    source = "none"
    eof = False
    drained = 0

    def read(self):
        return None

    def close(self):
        pass


class SafeTap:
    """Wraps an AudioTap so a capture process dying mid-run degrades to
    silence (plus a warning) instead of killing the effect."""

    def __init__(self, tap, warn):
        self.tap, self.warn = tap, warn
        self.source = tap.source
        self.drained = 0

    @property
    def eof(self):
        return self.tap.eof

    def read(self):
        try:
            return self.tap.read()
        except SystemExit as e:
            self.warn("audio", str(e))
            self.tap.close()
            self.tap = NullTap()
            return None

    def close(self):
        self.tap.close()


class PreviewInputs(Inputs):
    """GUI inputs: same sources as the CLI, but a missing source becomes a
    warning plus a fallback (silence, or keys injected from the window)."""

    def __init__(self, on_warning=None):
        self.on_warning = on_warning or (lambda kind, msg: None)
        self.virtual_keys = False

    def audio(self, source, rate, nsamples):
        try:
            return SafeTap(super().audio(source, rate, nsamples), self.on_warning)
        except SystemExit as e:
            self.on_warning("audio", str(e))
            return NullTap()

    def keys(self, input_path, names, aliases=None):
        import reactive

        try:
            listener, dev = super().keys(input_path, names, aliases)
            self.virtual_keys = False
            return listener, dev
        except (SystemExit, OSError) as e:
            self.on_warning("input", str(e))
            self.virtual_keys = True
            listener = reactive.KeyListener(None, names, aliases)
            return listener, "window"


class LiveEngine(threading.Thread):
    """Runs one effect at a time for the GUI. All public methods are
    thread-safe: they queue a command that the engine thread applies.

    The newest frame is published as `latest = (seq, profile, colors, bg)` with
    a single reference assignment, so the UI can poll it without locking.
    Events go to `on_event(dict)` from the engine thread."""

    REBUILD_DELAY = 0.15  # debounce for params that need a rebuild

    def __init__(self, on_event=None, inputs=None):
        super().__init__(daemon=True, name="kbd-engine")
        self.on_event = on_event or (lambda ev: None)
        self.inputs = inputs or PreviewInputs(
            lambda kind, msg: self.on_event({"type": "warning", "kind": kind, "msg": msg})
        )
        self.latest = (0, None, None, None)
        self._q = queue.Queue()
        self._running = True
        self._paused = False
        self._want = None       # (factory, spec, values, profile)
        self._fx = None
        self._canvas = None
        self._sink = None
        self._t0 = 0.0
        self._next_t = 0.0
        self._dirty = False
        self._rebuild_at = None
        self._seq = 0

    # -- public API -------------------------------------------------------
    def set_effect(self, factory, spec, values, profile):
        self._q.put(("effect", (factory, spec, dict(values), profile)))

    def update(self, values):
        self._q.put(("update", dict(values)))

    def set_sink(self, sink):
        self._q.put(("sink", sink))

    def pause(self, paused):
        self._q.put(("pause", bool(paused)))

    def inject_key(self, name, down):
        self._q.put(("key", (name, bool(down))))

    def shutdown(self, timeout=2.0):
        self._q.put(("quit", None))
        self.join(timeout)

    # -- engine thread ----------------------------------------------------
    def run(self):
        while self._running:
            now = time.monotonic()
            timeout = 0.5
            if self._fx is not None and not self._paused:
                if self._fx.animated:
                    timeout = max(0.0, self._next_t - now)
                elif self._dirty:
                    timeout = 0.0
            if self._rebuild_at is not None:
                timeout = min(timeout, max(0.0, self._rebuild_at - now))
            try:
                self._handle(*self._q.get(timeout=timeout))
                while True:  # apply everything queued before rendering
                    self._handle(*self._q.get_nowait())
            except queue.Empty:
                pass
            if not self._running:
                break
            now = time.monotonic()
            if self._rebuild_at is not None and now >= self._rebuild_at:
                self._build()
            fx = self._fx
            if fx is None or self._paused:
                continue
            if fx.animated:
                if now >= self._next_t:
                    self._frame(now)
                    self._next_t += fx.frame_dt
                    if self._next_t < now:
                        self._next_t = now + fx.frame_dt
            elif self._dirty:
                self._dirty = False
                self._frame(now)
        self._teardown()
        if self._sink is not None:
            self._sink.stop()

    def _handle(self, cmd, arg):
        if cmd == "effect":
            self._want = arg
            self._build()
        elif cmd == "update":
            self._update(arg)
        elif cmd == "sink":
            self._sink = arg
            if arg is not None and self.latest[2] is not None:
                arg.submit(self.latest[2], self.latest[3])
        elif cmd == "pause":
            if arg == self._paused:
                return
            self._paused = arg
            if arg:
                self._teardown()  # stop parec/grim/listeners while hidden
            elif self._want is not None:
                self._build()
        elif cmd == "key":
            listener = getattr(self._fx, "listener", None)
            if listener is not None and hasattr(listener, "inject"):
                listener.inject(*arg)
        elif cmd == "quit":
            self._running = False

    def _update(self, values):
        if self._want is None:
            return
        factory, spec, old, profile = self._want
        new = spec.validate(values)
        changed = {k: v for k, v in new.items() if old.get(k) != v}
        if not changed:
            return
        self._want = (factory, spec, new, profile)
        if self._fx is not None and self._rebuild_at is None and self._fx.apply(changed):
            self._dirty = True
        elif not self._paused:
            self._rebuild_at = time.monotonic() + self.REBUILD_DELAY

    def _build(self):
        self._rebuild_at = None
        self._teardown()
        if self._paused or self._want is None:
            return
        factory, spec, values, profile = self._want
        fx = factory(profile, spec.namespace(values), self.inputs)
        fx.log = lambda *a, **k: None
        try:
            fx.start()
        except SystemExit as e:
            kind = getattr(e, "kind", "deps")
            self.on_event({"type": "error", "kind": kind, "msg": str(e)})
            self._publish(profile, [(0, 0, 0)] * len(profile.keys_tuples), None)
            return
        except Exception as e:  # a bug in an effect must not kill the engine
            self.on_event({"type": "error", "kind": "effect", "msg": repr(e)})
            return
        self._fx = fx
        self._canvas = Canvas(profile)
        self._t0 = self._next_t = time.monotonic()
        self._dirty = True
        self.on_event({
            "type": "started",
            "virtual_keys": bool(getattr(self.inputs, "virtual_keys", False))
            and "keys" in fx.needs,
        })

    def _teardown(self):
        fx, self._fx = self._fx, None
        if fx is not None:
            try:
                fx.stop()
            except Exception:
                pass

    def _frame(self, now):
        fx, canvas = self._fx, self._canvas
        try:
            shown = fx.step(canvas, now, now - self._t0)
        except SystemExit as e:
            self.on_event({"type": "error", "kind": getattr(e, "kind", "deps"), "msg": str(e)})
            self._teardown()
            return
        except Exception as e:
            self.on_event({"type": "error", "kind": "effect", "msg": repr(e)})
            self._teardown()
            return
        if shown:
            self._publish(fx.p, list(canvas.colors), canvas.bg)

    def _publish(self, profile, colors, bg):
        self._seq += 1
        self.latest = (self._seq, profile, colors, bg)
        if self._sink is not None:
            self._sink.submit(colors, bg)


class DeviceSink(threading.Thread):
    """Streams frames to the board: latest frame wins, re-sent at the profile's
    keepalive rate so static frames hold, and reconnects after firmware resets.
    Modelled on kbd_ws_server.Writer. Events: connected / reconnecting / lost /
    permission / missing (via on_event)."""

    def __init__(self, profile, dev=None, on_event=None):
        super().__init__(daemon=True, name="kbd-sink")
        self.profile = profile
        self.dev = dev
        self.on_event = on_event or (lambda ev: None)
        self.kbd = None
        self._pending = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._running = True
        self._clear_on_stop = False
        hz = profile.keepalive_hz
        self._keepalive = 1.0 / hz if hz > 0 else 1.0

    def submit(self, colors, bg=None):
        with self._lock:
            self._pending = (colors, bg)
        self._ready.set()

    def stop(self, clear=False, timeout=2.0):
        self._clear_on_stop = clear
        self._running = False
        self._ready.set()
        if self.is_alive() and threading.current_thread() is not self:
            self.join(timeout)

    def _open(self):
        try:
            self.kbd = Kbd(profile=self.profile, dev=self.dev)
        except PermissionError as e:
            self.on_event({"type": "permission", "msg": str(e)})
            return False
        except SetupError as e:
            self.on_event({"type": "missing", "msg": str(e)})
            return False
        except OSError as e:
            self.on_event({"type": "missing", "msg": str(e)})
            return False
        self.on_event({"type": "connected", "dev": self.kbd.dev})
        return True

    def run(self):
        try:
            while self._running:
                self._ready.wait(self._keepalive)
                self._ready.clear()
                if not self._running:
                    break
                if self.kbd is None and not self._open():
                    self._ready.wait(1.0)
                    continue
                with self._lock:
                    frame = self._pending
                if frame is None:
                    continue
                write_frame(self.kbd, *frame)
                try:
                    self.kbd.flush()
                except OSError as e:
                    if e.errno in Kbd.GONE_ERRNOS:
                        self.on_event({"type": "reconnecting"})
                        if self.kbd.reopen(timeout=5.0):
                            self.on_event({"type": "connected", "dev": self.kbd.dev})
                        else:
                            self.kbd = None
                            self.on_event({"type": "lost"})
                    elif e.errno in (errno.EACCES, errno.EPERM):
                        self.kbd = None
                        self.on_event({"type": "permission", "msg": str(e)})
                    else:
                        self.kbd = None
                        self.on_event({"type": "lost", "msg": str(e)})
        finally:
            if self.kbd is not None:
                if self._clear_on_stop:
                    try:
                        self.kbd.clear()
                        self.kbd.flush()
                    except OSError:
                        pass
                self.kbd.close()
                self.kbd = None
