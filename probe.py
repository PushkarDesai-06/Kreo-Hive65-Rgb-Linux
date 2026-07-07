#!/usr/bin/env python3
"""HID feature-report probe for BY Tech / SinoWealth keyboard (258a:010c).

Pure-python hidraw access via ioctl — no external deps.

Usage:
  probe.py get <dev> <report_id> <length>      # GET_FEATURE, hexdump to stdout
  probe.py snap <dev> <name>                   # snapshot reports 5+6 -> snapshots/<name>.bin
  probe.py diff <a> <b>                        # byte-diff two snapshots
  probe.py set <dev> <hexbytes>                # SET_FEATURE raw hex (first byte = report id)

<dev> is e.g. /dev/hidraw3
"""
import sys, os, fcntl, time

def _IOC(dirn, typ, nr, size):
    return (dirn << 30) | (size << 16) | (ord(typ) << 8) | nr

def HIDIOCGFEATURE(length): return _IOC(3, 'H', 0x07, length)
def HIDIOCSFEATURE(length): return _IOC(3, 'H', 0x06, length)

def get_feature(fd, report_id, length):
    """length = payload bytes NOT including report id"""
    buf = bytearray(length + 1)
    buf[0] = report_id
    rc = fcntl.ioctl(fd, HIDIOCGFEATURE(len(buf)), buf, True)
    return bytes(buf[:rc])

def set_feature(fd, data):
    buf = bytearray(data)
    return fcntl.ioctl(fd, HIDIOCSFEATURE(len(buf)), buf, True)

def hexdump(data, base=0):
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hexs = ' '.join(f'{b:02x}' for b in chunk)
        asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f'{base+i:04x}: {hexs:<48} {asc}')

def cmd_get(dev, rid, length):
    fd = os.open(dev, os.O_RDWR)
    try:
        data = get_feature(fd, rid, length)
        print(f'# GET_FEATURE report 0x{rid:02x} -> {len(data)} bytes')
        hexdump(data)
    finally:
        os.close(fd)

def cmd_snap(dev, name):
    fd = os.open(dev, os.O_RDWR)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'snapshots', name + '.bin')
    try:
        blobs = []
        for rid, ln in ((5, 5), (6, 519)):
            try:
                d = get_feature(fd, rid, ln)
                print(f'report 0x{rid:02x}: read {len(d)} bytes')
            except OSError as e:
                print(f'report 0x{rid:02x}: FAILED ({e})')
                d = b''
            blobs.append(d)
        with open(out, 'wb') as f:
            # simple container: u16 len + blob, per report
            for d in blobs:
                f.write(len(d).to_bytes(2, 'little'))
                f.write(d)
        print(f'saved -> {out}')
    finally:
        os.close(fd)

def read_snap(path):
    blobs = []
    with open(path, 'rb') as f:
        while True:
            lb = f.read(2)
            if len(lb) < 2:
                break
            n = int.from_bytes(lb, 'little')
            blobs.append(f.read(n))
    return blobs

def cmd_diff(a, b):
    A, B = read_snap(a), read_snap(b)
    for idx, (x, y) in enumerate(zip(A, B)):
        rid = x[0] if x else (y[0] if y else 0)
        if x == y:
            print(f'report 0x{rid:02x}: identical ({len(x)} bytes)')
            continue
        print(f'report 0x{rid:02x}: {len(x)} vs {len(y)} bytes, diffs:')
        for i in range(min(len(x), len(y))):
            if x[i] != y[i]:
                print(f'  offset {i:4d} (0x{i:03x}): {x[i]:02x} -> {y[i]:02x}')

def cmd_set(dev, hexstr):
    data = bytes.fromhex(hexstr)
    fd = os.open(dev, os.O_RDWR)
    try:
        rc = set_feature(fd, data)
        print(f'SET_FEATURE report 0x{data[0]:02x}: wrote {rc} bytes')
    finally:
        os.close(fd)

if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        print(__doc__); sys.exit(1)
    cmd = args[0]
    if cmd == 'get':
        cmd_get(args[1], int(args[2], 0), int(args[3], 0))
    elif cmd == 'snap':
        cmd_snap(args[1], args[2])
    elif cmd == 'diff':
        cmd_diff(args[1], args[2])
    elif cmd == 'set':
        cmd_set(args[1], ''.join(args[2:]).replace(' ', ''))
    else:
        print(__doc__); sys.exit(1)
