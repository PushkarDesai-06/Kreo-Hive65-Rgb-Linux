#!/usr/bin/env python3
"""Keyboard profiles for hydra_rgb — data-driven, stdlib-only.

A *profile* bundles the three things that vary between RGB keyboards:

  identity  — which USB device this is (VID:PID) and how to spot its RGB interface
  protocol  — how to build one RGB frame (report id, header, packet size, order)
  layout    — the key→LED-slot map and grid geometry

Profiles live as ``profiles/<id>.json`` and are discovered at load time, so
adding a same-family keyboard is just dropping in a JSON file — no code changes.
A board whose frame doesn't fit the ``standard`` encoder registers its own
encoder in ``ENCODERS`` and names it in its JSON.

Safety: report 5 on this SinoWealth MCU family is the command/ISP (firmware
flash) channel — a blind write there can soft-brick the board. Profiles may only
target report 6 (the RGB framebuffer); this is enforced both at load and in every
encoder, so no profile or tool built on them can reach report 5. See PROTOCOL.md.
"""
import collections
import glob
import json
import math
import os

Key = collections.namedtuple("Key", "name col row slot")

PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")

# report 5 is the SinoWealth ISP/command channel; never build a frame for it.
FORBIDDEN_REPORT = 5


def _norm_usb(s):
    """'258A:010C' / '258a:010c' -> 'vvvv:pppp' lowercase."""
    vid, pid = s.strip().lower().split(":")
    return f"{int(vid, 16):04x}:{int(pid, 16):04x}"


def usb_marker(usb_id):
    """USB id -> the token that appears in an (uppercased) hidraw uevent MODALIAS.
    '258a:010c' -> 'V0000258AP0000010C'."""
    vid, pid = usb_id.split(":")
    return f"V0000{vid}P0000{pid}".upper()


def reorder(order, r, g, b):
    """Permute an (r,g,b) triple into a board's wire byte order, e.g. 'grb'."""
    ch = {"r": r, "g": g, "b": b}
    return tuple(ch[c] for c in order)


def _eval_slot(formula, col, row):
    """Evaluate a layout slot_formula like 'col*6 + row + 1' with no builtins."""
    return int(eval(formula, {"__builtins__": {}}, {"col": col, "row": row}))


def standard_encode(profile, rgb):
    """Build the SET_FEATURE packet: header at offset 0, RGB at payload_offset,
    zero-padded to pkt_len. Covers the SinoWealth 'header + contiguous RGB' family."""
    if profile.report_id == FORBIDDEN_REPORT:
        raise ValueError("refusing to encode a report-5 frame (ISP/flash channel)")
    pkt = bytearray(profile.pkt_len)
    pkt[: len(profile.header)] = profile.header
    off = profile.payload_offset
    pkt[off : off + len(rgb)] = rgb
    return bytes(pkt)


# Frame-encoder registry. Exotic boards add an entry and set "encoder" in JSON.
ENCODERS = {"standard": standard_encode}


def _build_geom(rows, cols, override, keys):
    """Per-key (nx, ny, radius, angle) for 2D field effects, normalized so the
    grid roughly fills [-1,1]. Center/normalization default to the grid middle
    and are overridable per profile (some boards are visually off-center)."""
    maxcol = cols - 1
    cx = override.get("center_col", maxcol / 2.0)
    cy = override.get("center_row", (rows - 1) / 2.0)
    xn = override.get("x_norm", maxcol / 2.0 + 0.5) or 1.0
    yn = override.get("y_norm", (rows - 1) / 2.0 + 0.5) or 1.0
    geom = {}
    for k in keys:
        nx = (k.col - cx) / xn
        ny = (k.row - cy) / yn
        geom[k.name] = (nx, ny, math.hypot(nx, ny), math.atan2(ny, nx))
    return geom


class Profile:
    """A loaded keyboard profile. Built from the JSON dict; derives slot map and
    geometry at construction so effects can read them directly."""

    def __init__(self, d):
        self.id = d["id"]
        self.name = d.get("name", self.id)

        ident = d["identity"]
        self.usb_ids = [_norm_usb(x) for x in ident["usb_ids"]]
        self.report_id = ident.get("report_id", 6)

        proto = d["protocol"]
        self.encoder = proto.get("encoder", "standard")
        self.header = bytes.fromhex(proto["header"])
        self.payload_offset = proto.get("payload_offset", len(self.header))
        self.pkt_len = proto["pkt_len"]
        self.num_slots = proto["num_slots"]
        self.color_order = proto.get("color_order", "rgb").lower()
        self.keepalive_hz = proto.get("keepalive_hz", 1.0)

        lay = d["layout"]
        self.rows = lay["rows"]
        self.cols = lay["cols"]
        formula = lay.get("slot_formula")
        self.keys = []
        for kd in lay["keys"]:
            slot = kd.get("slot")
            if slot is None:
                if not formula:
                    raise ValueError(
                        f"{self.id}: key {kd['name']!r} needs a slot or a slot_formula"
                    )
                slot = _eval_slot(formula, kd["col"], kd["row"])
            self.keys.append(Key(kd["name"], kd["col"], kd["row"], slot))

        self.slot = {k.name: k.slot for k in self.keys}
        self.keys_tuples = [(k.name, k.col, k.row) for k in self.keys]
        self.geom = _build_geom(self.rows, self.cols, lay.get("geometry", {}), self.keys)

        # validate
        if self.report_id == FORBIDDEN_REPORT:
            raise ValueError(
                f"{self.id}: report_id 5 is the ISP/flash channel and is forbidden"
            )
        if self.encoder not in ENCODERS:
            raise ValueError(f"{self.id}: unknown encoder {self.encoder!r}")
        if set(self.color_order) != set("rgb"):
            raise ValueError(f"{self.id}: color_order must be a permutation of r,g,b")

    # --- convenience ---------------------------------------------------------
    def slot_bytes(self):
        return self.num_slots * 3

    def key_count(self):
        return len(self.keys)

    def desc_marker(self):
        """HID report-descriptor bytes that must be present on the RGB interface
        (a Report ID <report_id> main item), e.g. b'\\x85\\x06'."""
        return bytes([0x85, self.report_id])

    def matches_uevent(self, uevent_upper):
        return any(usb_marker(u) in uevent_upper for u in self.usb_ids)

    def encode(self, rgb):
        return ENCODERS[self.encoder](self, rgb)

    def __repr__(self):
        return f"<Profile {self.id} {self.name!r} {self.key_count()}keys>"


def load_profile(path):
    with open(path) as f:
        return Profile(json.load(f))


def load_all(directory=None):
    """Discover every profiles/*.json; return {id: Profile}. Raises on a bad file."""
    directory = directory or PROFILES_DIR
    out = {}
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        prof = load_profile(path)
        if prof.id in out:
            raise ValueError(f"duplicate profile id {prof.id!r} ({path})")
        out[prof.id] = prof
    return out


if __name__ == "__main__":  # quick self-check: python3 kbd_profiles.py
    for pid, prof in load_all().items():
        print(f"{pid:12s} {prof.name}  ({prof.key_count()} keys, "
              f"{prof.cols}x{prof.rows}, {prof.pkt_len}B, usb={prof.usb_ids})")
