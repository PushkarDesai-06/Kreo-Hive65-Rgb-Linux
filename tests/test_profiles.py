#!/usr/bin/env python3
"""Profile-system tests: loading, encoding, device selection, safety, and that
the kbd_ws_server back-compat surface is intact. No hardware required.

    python3 -m unittest tests.test_profiles     (from repo root)
    ./tests/test_profiles.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import kbd_profiles


def _make_sysfs(usb_modalias, marker=b"\x85\x06"):
    """Build a throwaway /sys/class/hidraw-style tree with one node."""
    root = tempfile.mkdtemp()
    dev = os.path.join(root, "hidraw9", "device")
    os.makedirs(dev)
    with open(os.path.join(dev, "uevent"), "w") as f:
        f.write(f"MODALIAS=hid:b0003g0001{usb_modalias}\n")
    with open(os.path.join(dev, "report_descriptor"), "wb") as f:
        f.write(b"\x05\x01\x09\x06" + marker + b"\x75\x08")
    return root


class TestProfiles(unittest.TestCase):
    def setUp(self):
        self.profiles = kbd_profiles.load_all()

    def test_known_profiles_load(self):
        self.assertIn("hive65", self.profiles)
        self.assertIn("hydra10", self.profiles)

    def test_hive65_shape(self):
        p = self.profiles["hive65"]
        self.assertEqual(p.key_count(), 68)
        self.assertEqual((p.cols, p.rows), (16, 5))
        self.assertEqual(p.pkt_len, 520)
        self.assertEqual(p.num_slots, 126)
        self.assertEqual(p.slot["esc"], 1)          # col0,row0 -> 0*6+0+1
        self.assertEqual(p.slot["space"], 5 * 6 + 4 + 1)

    def test_standard_encoder_hive65(self):
        p = self.profiles["hive65"]
        rgb = bytearray(p.num_slots * 3)
        rgb[3:6] = b"\x11\x22\x33"                  # slot 1
        pkt = p.encode(rgb)
        self.assertEqual(len(pkt), 520)
        self.assertEqual(pkt[:8], bytes.fromhex("0608000001007a01"))
        self.assertEqual(pkt[8 + 3 : 8 + 6], b"\x11\x22\x33")  # payload_offset=8

    def test_standard_encoder_hydra10(self):
        """The second board proves the protocol axis: different frame size/header."""
        p = self.profiles["hydra10"]
        self.assertEqual(p.pkt_len, 1032)
        rgb = bytearray(p.num_slots * 3)
        rgb[30:33] = b"\xaa\xbb\xcc"                # slot 10
        pkt = p.encode(rgb)
        self.assertEqual(len(pkt), 1032)
        self.assertEqual(pkt[:8], bytes.fromhex("060800000100ff03"))
        self.assertEqual(pkt[8 + 30 : 8 + 33], b"\xaa\xbb\xcc")

    def test_color_order_reorder(self):
        self.assertEqual(kbd_profiles.reorder("rgb", 1, 2, 3), (1, 2, 3))
        self.assertEqual(kbd_profiles.reorder("grb", 1, 2, 3), (2, 1, 3))
        self.assertEqual(kbd_profiles.reorder("bgr", 1, 2, 3), (3, 2, 1))

    def test_report5_is_refused(self):
        bad = {
            "id": "danger", "name": "x",
            "identity": {"usb_ids": ["1234:5678"], "report_id": 5},
            "protocol": {"header": "05", "pkt_len": 64, "num_slots": 1},
            "layout": {"rows": 1, "cols": 1, "keys": [{"name": "a", "col": 0, "row": 0, "slot": 0}]},
        }
        with self.assertRaises(ValueError):
            kbd_profiles.Profile(bad)

    def test_find_device_selects_by_usb_id(self):
        import hydra_rgb
        # a Hydra 10 node should select the hydra10 profile, not hive65
        root = _make_sysfs("v0000258Ap00000049")
        dev, prof = hydra_rgb.find_device(
            list(self.profiles.values()), sysfs_root=root
        )
        self.assertEqual(prof.id, "hydra10")
        self.assertEqual(dev, "/dev/hidraw9")
        # a Hive 65 node selects hive65
        root2 = _make_sysfs("v0000258Ap0000010C")
        _, prof2 = hydra_rgb.find_device(list(self.profiles.values()), sysfs_root=root2)
        self.assertEqual(prof2.id, "hive65")

    def test_find_device_none_matches(self):
        import hydra_rgb
        root = _make_sysfs("v00001234p00005678")  # unknown board
        with self.assertRaises(SystemExit):
            hydra_rgb.find_device(list(self.profiles.values()), sysfs_root=root)


class TestWsServerBackCompat(unittest.TestCase):
    """kbd_ws_server reads drv.LAYOUT/SLOT/NUM_SLOTS/MAXCOL/ROWS — these aliases
    must still resolve to the default (Hive 65) profile."""

    def test_aliases_present(self):
        import hydra_rgb as drv
        self.assertEqual(len(drv.LAYOUT), 68)
        self.assertEqual(drv.NUM_SLOTS, 126)
        self.assertEqual(drv.MAXCOL, 15)
        self.assertEqual(drv.ROWS, 5)
        self.assertEqual(drv.SLOT["esc"], 1)

    def test_ws_server_imports_and_builds_schema(self):
        import kbd_ws_server as ws
        schema = ws.build_schema()
        self.assertEqual(schema["keyCount"], 68)
        self.assertEqual(schema["grid"], {"cols": 16, "rows": 5})
        self.assertEqual(len(schema["keys"]), 68)


if __name__ == "__main__":
    unittest.main(verbosity=2)
