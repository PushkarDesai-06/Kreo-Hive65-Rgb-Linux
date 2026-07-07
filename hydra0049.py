#!/usr/bin/env python3
"""Reverse-engineering probe for the Portronics Hydra 10 variant 258a:0049.

Its vendor RGB interface exposes report ID 6 as a 1031-byte FEATURE report
(vs 519 on the 258a:010c board), so the 010c packet format doesn't fit. This
tool only ever writes report 6 (the RGB framebuffer) — never report 5 (the
command/ISP channel) — so it can't touch firmware.

Subcommands:
  writetest              # confirm the device accepts a full-size report-6 write
  white [hdrhex]         # all-0xFF frame with a given header (default 010c-style)
  headers                # cycle candidate headers, all-white, ~3s each
  slot <n> [rrggbb]      # light one slot index (byte offset n*3 in RGB region)
  scan <start> <end>     # sweep-light slots start..end one at a time, ~0.4s each
  off                    # zero frame

RGB region is assumed to start at HDR_LEN (default 8) after the report id.
"""
import sys, os, fcntl, glob, time

def _IOC(d, t, n, s): return (d << 30) | (s << 16) | (ord(t) << 8) | n
def HIDIOCSFEATURE(l): return _IOC(3, "H", 0x06, l)
def HIDIOCGFEATURE(l): return _IOC(3, "H", 0x07, l)

PID = "V0000258AP00000049"
REPORT_LEN = 1032           # report id + 1031 payload
HDR_LEN = 8                 # bytes before RGB data (guess, from 010c)
# 010c header for reference: 06 08 00 00 01 00 7A 01
DEFAULT_HDR = bytes([0x06, 0x08, 0x00, 0x00, 0x01, 0x00, 0xFF, 0x03])  # len=0x03FF

def find_dev():
    for p in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            ue = open(p + "/device/uevent").read().upper()
            desc = open(p + "/device/report_descriptor", "rb").read()
        except OSError:
            continue
        if PID in ue and b"\x85\x06" in desc:
            return "/dev/" + os.path.basename(p)
    raise SystemExit("Hydra 258a:0049 vendor interface not found (wired mode?)")

def send(fd, data):
    buf = bytearray(REPORT_LEN)
    buf[: len(data)] = data
    return fcntl.ioctl(fd, HIDIOCSFEATURE(REPORT_LEN), buf, True)

def frame(header, rgb_fill=None, rgb=None):
    """Build a REPORT_LEN packet: header, then RGB region."""
    pkt = bytearray(REPORT_LEN)
    pkt[: len(header)] = header
    if rgb is not None:
        pkt[HDR_LEN : HDR_LEN + len(rgb)] = rgb
    elif rgb_fill is not None:
        for i in range(HDR_LEN, REPORT_LEN):
            pkt[i] = rgb_fill
    return pkt

def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return 1
    dev = find_dev()
    fd = os.open(dev, os.O_RDWR)
    print(f"device: {dev}")
    cmd = a[0]
    if cmd == "writetest":
        for n in (REPORT_LEN, 520, 1024, 65):
            buf = bytearray(n); buf[0] = 6
            try:
                fcntl.ioctl(fd, HIDIOCSFEATURE(n), buf, True)
                print(f"  write {n:5d} bytes: OK")
            except OSError as e:
                print(f"  write {n:5d} bytes: {e}")
    elif cmd == "white":
        hdr = bytes.fromhex(a[1]) if len(a) > 1 else DEFAULT_HDR
        send(fd, frame(hdr, rgb_fill=0xFF))
        print(f"sent all-white, header={hdr.hex()}")
    elif cmd == "off":
        send(fd, frame(bytes([6]), rgb_fill=0x00))
        print("sent zero frame")
    elif cmd == "headers":
        cands = [
            "06080000017a01",      # 010c verbatim (len 0x017A=378)
            "0608000001000004",    # len 0x0400 = 1024
            "060800000100ff03",    # len 0x03FF = 1023
            "0608000000000004",    # byte4=00 variant
            "0601000001000004",    # command byte 0x01
            "06080000000004",      # 7-byte header
        ]
        for h in cands:
            hb = bytes.fromhex(h)
            send(fd, frame(hb, rgb_fill=0xFF))
            print(f"  >>> header {h} — all white, watch the board (3s)")
            time.sleep(3)
        send(fd, frame(bytes([6]), rgb_fill=0x00))
        print("done; board blanked")
    elif cmd == "slot":
        n = int(a[1]); col = bytes.fromhex(a[2]) if len(a) > 2 else b"\xff\xff\xff"
        rgb = bytearray(REPORT_LEN - HDR_LEN)
        rgb[n * 3 : n * 3 + 3] = col
        send(fd, frame(DEFAULT_HDR, rgb=bytes(rgb)))
        print(f"lit slot {n} = {col.hex()} (header {DEFAULT_HDR.hex()})")
    elif cmd == "block":
        # block <offset> <nslots> <rrggbb> [hdrhex] [stride]
        off = int(a[1]); nsl = int(a[2]); col = bytes.fromhex(a[3])
        hdr = bytes.fromhex(a[4]) if len(a) > 4 else DEFAULT_HDR
        stride = int(a[5]) if len(a) > 5 else 3
        pkt = bytearray(REPORT_LEN)
        pkt[: len(hdr)] = hdr
        for s in range(nsl):
            p = off + s * stride
            pkt[p : p + len(col)] = col
        fcntl.ioctl(fd, HIDIOCSFEATURE(REPORT_LEN), pkt, True)
        print(f"block off={off} n={nsl} col={col.hex()} stride={stride} hdr={hdr.hex()}")
    elif cmd == "fill":
        val = int(a[1], 0); hdr = bytes.fromhex(a[2]) if len(a) > 2 else DEFAULT_HDR
        send(fd, frame(hdr, rgb_fill=val))
        print(f"fill 0x{val:02x} from off {HDR_LEN}, hdr={hdr.hex()}")
    elif cmd == "round2":
        hold = float(a[1]) if len(a) > 1 else 5.0
        seq = [
            ("A: WHITE  24 keys @off8 stride3", 8, 24, "ffffff", "0608000001004800", 3),
            ("B: RED    24 keys @off2 stride3", 2, 24, "ff0000", "0608", 3),
            ("C: GREEN  24 keys @off1 stride3", 1, 24, "00ff00", "06", 3),
            ("D: BLUE   24 keys @off8 stride4", 8, 24, "0000ff", "0608000001004800", 4),
            ("E: DIM WHITE whole board @off8 (no 0xFF byte)", 8, 300, "c0c0c0", "060800000100ff03", 3),
            ("F: YELLOW 24 keys @off8 stride3", 8, 24, "ffff00", "0608000001004800", 3),
        ]
        blank = frame(bytes([6]), rgb_fill=0x00)
        for label, off, nsl, colhex, hdrhex, stride in seq:
            col = bytes.fromhex(colhex); hdr = bytes.fromhex(hdrhex)
            pkt = bytearray(REPORT_LEN); pkt[: len(hdr)] = hdr
            for s in range(nsl):
                p = off + s * stride
                pkt[p : p + len(col)] = col
            fcntl.ioctl(fd, HIDIOCSFEATURE(REPORT_LEN), blank, True)  # clear gap
            print(f"  ... (blank)")
            time.sleep(1.3)
            fcntl.ioctl(fd, HIDIOCSFEATURE(REPORT_LEN), pkt, True)
            print(f"  >>> {label}  (hold {hold:g}s)")
            time.sleep(hold)
        fcntl.ioctl(fd, HIDIOCSFEATURE(REPORT_LEN), blank, True)
        print("done; board blanked")
    elif cmd == "scan":
        s, e = int(a[1]), int(a[2])
        for n in range(s, e + 1):
            rgb = bytearray(REPORT_LEN - HDR_LEN)
            rgb[n * 3 : n * 3 + 3] = b"\xff\xff\xff"
            send(fd, frame(DEFAULT_HDR, rgb=bytes(rgb)))
            print(f"  slot {n}")
            time.sleep(0.4)
        send(fd, frame(bytes([6]), rgb_fill=0x00))
    else:
        print(__doc__); return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
