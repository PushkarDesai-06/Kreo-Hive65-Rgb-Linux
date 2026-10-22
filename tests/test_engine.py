#!/usr/bin/env python3
"""Param schema and frame engine: CLI round trips, canvas bytes, and the GUI's
live engine (live param updates vs rebuilds). No hardware required."""
import os
import random
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import effects
import engine
import kbd_profiles
import reactive
from device import Kbd

SPECS = (effects.SOLID_SPEC, effects.GRADIENT_SPEC, effects.WAVE_SPEC, effects.FLUX_SPEC,
         effects.AUDIO_SPEC, effects.SCREEN_SPEC, reactive.REACTIVE_SPEC)


def _random_value(prm, rng):
    if prm.kind == "bool":
        return rng.random() < 0.5
    if prm.kind == "choice":
        return rng.choice(prm.choices)
    if prm.kind == "color":
        return "%06x" % rng.randrange(1 << 24)
    if prm.kind == "colors":
        return ",".join("%06x" % rng.randrange(1 << 24) for _ in range(3))
    if prm.kind == "text":
        return rng.choice([None, "alsa_output.monitor", "DP-1"])
    lo = prm.min if prm.min is not None else 0
    hi = prm.max if prm.max is not None else 100
    v = rng.uniform(lo, hi)
    return int(round(v)) if prm.kind == "int" else round(v, 3)


def _fake_kbd(profile):
    k = Kbd.__new__(Kbd)
    k.p, k.dev, k.fd = profile, "/dev/null", None
    k.rgb = bytearray(profile.num_slots * 3)
    return k


class TestParams(unittest.TestCase):
    def test_to_argv_round_trips(self):
        rng = random.Random(5)
        for spec in SPECS:
            if any(p.positional for p in spec.params) and spec.cli_name != "wave":
                continue  # color/gradient take bare args in main(), not argparse
            for _ in range(40):
                vals = {p.name: _random_value(p, rng) for p in spec.params if p.gui}
                vals = spec.validate(vals)
                parsed = vars(spec.parse(spec.to_argv(vals)))
                with self.subTest(spec=spec.cli_name, vals=vals):
                    self.assertEqual(parsed, vals)

    def test_defaults_give_empty_argv(self):
        for spec in SPECS:
            if not any(p.positional for p in spec.params):
                self.assertEqual(spec.to_argv(spec.defaults()), [], spec.cli_name)

    def test_force_keeps_fixed_params(self):
        argv = effects.AUDIO_SPEC.to_argv(effects.AUDIO_SPEC.defaults(), force=("effect",))
        self.assertEqual(argv, ["--effect", "wave"])

    def test_validate_clamps_and_drops(self):
        v = effects.FLUX_SPEC.validate({"speed": 99, "colors": 7, "bogus": 1, "hex": "nothex"})
        self.assertEqual(v["speed"], 5.0)
        self.assertEqual(v["colors"], 3)
        self.assertIsNone(v["hex"])
        self.assertNotIn("bogus", v)

    def test_every_gui_param_is_documented(self):
        for spec in SPECS:
            for p in spec.params:
                if not p.gui:
                    continue
                with self.subTest(spec=spec.cli_name, param=p.name):
                    self.assertTrue(p.label and p.tooltip)
                    if p.kind in ("float", "int"):
                        self.assertIsNotNone(p.min)
                        self.assertIsNotNone(p.max)
                    if p.kind == "choice":
                        self.assertEqual(len(p.labels), len(p.choices))


class TestCanvas(unittest.TestCase):
    def setUp(self):
        self.p = kbd_profiles.load_all()["hive65"]

    def test_fill_reaches_every_slot_like_kbd(self):
        direct, via = _fake_kbd(self.p), _fake_kbd(self.p)
        direct.fill(10, 20, 30)
        c = engine.Canvas(self.p)
        c.fill(10, 20, 30)
        c.to_kbd(via)
        self.assertEqual(direct.rgb, via.rgb)

    def test_per_key_matches_kbd(self):
        direct, via = _fake_kbd(self.p), _fake_kbd(self.p)
        c = engine.Canvas(self.p)
        effects.render_rainbow(direct)
        effects.render_rainbow(c)
        c.to_kbd(via)
        self.assertEqual(direct.rgb, via.rgb)


class TestLiveEngine(unittest.TestCase):
    def setUp(self):
        self.p = kbd_profiles.load_all()["hive65"]
        self.events = []
        self.eng = engine.LiveEngine(on_event=self.events.append)
        self.eng.start()

    def tearDown(self):
        self.eng.shutdown()

    def _wait_seq(self, after, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.eng.latest[0] > after:
                return self.eng.latest
            time.sleep(0.01)
        self.fail("engine produced no frame")

    def test_animates_and_applies_live_params(self):
        spec = effects.FLUX_SPEC
        self.eng.set_effect(effects.Flux, spec, spec.defaults(), self.p)
        seq, prof, colors, _bg = self._wait_seq(0)
        self.assertIs(prof, self.p)
        self.assertEqual(len(colors), self.p.key_count())
        fx = self.eng._fx
        self.eng.update(dict(spec.defaults(), speed=3.0))
        self._wait_seq(seq + 2)
        self.assertIs(self.eng._fx, fx)  # live: same effect object
        self.assertEqual(fx.o.speed, 3.0)
        self.eng.update(dict(spec.defaults(), speed=3.0, fps=30.0))
        time.sleep(self.eng.REBUILD_DELAY + 0.2)
        self.assertIsNot(self.eng._fx, fx)  # fps needs a rebuild

    def test_static_renders_once(self):
        spec = effects.SOLID_SPEC
        self.eng.set_effect(effects.SolidColor, spec, {"color": "00ff00"}, self.p)
        seq, _p, colors, bg = self._wait_seq(0)
        self.assertEqual(bg, (0, 255, 0))
        time.sleep(0.2)
        self.assertEqual(self.eng.latest[0], seq)

    def test_typing_falls_back_to_injected_keys(self):
        spec = reactive.REACTIVE_SPEC
        vals = dict(spec.defaults(), input="/nonexistent/event99")
        self.eng.set_effect(reactive.TypingEffect, spec, vals, self.p)
        self._wait_seq(0)
        self.assertTrue(any(e["type"] == "warning" and e["kind"] == "input" for e in self.events))
        self.eng.inject_key("f", True)
        deadline = time.monotonic() + 2
        idx = [n for n, _c, _r in self.p.keys_tuples].index("f")
        while time.monotonic() < deadline and self.eng.latest[2][idx] == (0, 0, 0):
            time.sleep(0.01)
        self.assertNotEqual(self.eng.latest[2][idx], (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
