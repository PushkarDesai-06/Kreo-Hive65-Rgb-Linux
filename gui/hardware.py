"""Find connected supported keyboards. Unlike device.find_device, this reports
every profile that could drive a node: boards that share a USB id (the Hive 65
and the Aula F75 are both 258a:010c) cannot be told apart from the bus, so the
user's choice for that id decides."""
import glob
import os

from device import PROFILES


def usable_profiles():
    """Profiles worth offering: ones that actually define keys."""
    return [p for p in PROFILES.values() if p.key_count() > 0]


def scan(sysfs_root="/sys/class/hidraw"):
    """[{"dev", "usb", "profiles": [ids], "writable"}] for each matching node."""
    found = []
    for path in sorted(glob.glob(sysfs_root + "/hidraw*")):
        try:
            with open(path + "/device/uevent") as f:
                uevent = f.read().upper()
            with open(path + "/device/report_descriptor", "rb") as f:
                desc = f.read()
        except OSError:
            continue
        cands = [p for p in usable_profiles()
                 if p.matches_uevent(uevent) and p.desc_marker() in desc]
        if not cands:
            continue
        usb = next(u for u in cands[0].usb_ids
                   if f"V0000{u[:4]}P0000{u[5:]}".upper() in uevent)
        dev = "/dev/" + os.path.basename(path)
        found.append({
            "dev": dev,
            "usb": usb,
            "profiles": [p.id for p in cands],
            "writable": os.access(dev, os.W_OK),
        })
    return found
