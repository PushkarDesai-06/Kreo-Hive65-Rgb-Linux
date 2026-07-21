#!/usr/bin/env python3
"""Screen-sync colour treatment tests (apply_look). Pure math, no hardware,
no capture tools — exercises the punch/gamma/gain that maps a captured pixel
onto the RGB LEDs.

    python3 -m unittest tests.test_screen     (from repo root)
    ./tests/test_screen.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from effects import apply_look


class TestApplyLook(unittest.TestCase):
    def test_identity_is_passthrough(self):
        # sat=gain=gamma=1 leaves the pixel untouched (faithful / --raw)
        for c in [(0, 0, 0), (10, 200, 30), (255, 255, 255)]:
            self.assertEqual(apply_look(c, 1.0, 1.0, 1.0), c)

    def test_gray_is_unchanged_by_saturation(self):
        # a neutral pixel has no colour to push, so saturation is a no-op
        self.assertEqual(apply_look((120, 120, 120), 2.0, 1.0, 1.0), (120, 120, 120))

    def test_saturation_widens_channel_spread(self):
        # a reddish pixel gets redder and its weaker channels drop toward 0
        r, g, b = apply_look((150, 100, 100), 2.0, 1.0, 1.0)
        self.assertGreater(r, 150)
        self.assertLess(g, 100)
        self.assertLess(b, 100)

    def test_gain_and_clamp(self):
        # gain scales brightness and results stay within 0..255
        self.assertEqual(apply_look((200, 200, 200), 1.0, 2.0, 1.0), (255, 255, 255))
        r, g, b = apply_look((50, 50, 50), 1.0, 2.0, 1.0)
        self.assertEqual((r, g, b), (100, 100, 100))

    def test_output_is_ints_in_range(self):
        for c in [(0, 0, 0), (255, 0, 128), (17, 240, 3)]:
            out = apply_look(c, 1.5, 1.1, 0.9)
            self.assertEqual(len(out), 3)
            for v in out:
                self.assertIsInstance(v, int)
                self.assertTrue(0 <= v <= 255)


if __name__ == "__main__":
    unittest.main()
