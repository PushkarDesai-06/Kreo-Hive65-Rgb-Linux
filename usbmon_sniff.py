#!/usr/bin/env python3
"""Minimal usbmon binary-interface sniffer — no wireshark/dumpcap needed.

Reads /dev/usbmonN (needs read permission), filters to one device address,
decodes control transfers (SET_FEATURE / GET_FEATURE / SET_REPORT etc.)
and interrupt data, prints hexdumps and appends raw events to a log.

Usage: usbmon_sniff.py <bus> <devnum> [logfile]
e.g.:  usbmon_sniff.py 1 7 captures/session1.log
"""
import sys, os, struct, datetime

# struct mon_bin_hdr, 64 bytes (see Documentation/usb/usbmon.rst)
HDR = struct.Struct('=QBBBBHbbqiiii8siiII')
# fields: id type xfer_type epnum devnum busnum flag_setup flag_data
#         ts_sec ts_usec status length len_cap setup interval start_frame
#         xfer_flags ndesc

XFER = {0: 'ISO', 1: 'INTR', 2: 'CTRL', 3: 'BULK'}
REQ = {0x01: 'GET_REPORT', 0x09: 'SET_REPORT', 0x0a: 'SET_IDLE',
       0x06: 'GET_DESCRIPTOR', 0x00: 'GET_STATUS'}
RTYPE = {0x21: 'H2D|class|iface', 0xa1: 'D2H|class|iface',
         0x00: 'H2D|std|dev', 0x80: 'D2H|std|dev', 0x81: 'D2H|std|iface'}

def hexdump(data, indent='    '):
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hexs = ' '.join(f'{b:02x}' for b in chunk)
        asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f'{indent}{i:04x}: {hexs:<48} {asc}')

def main():
    bus, dev = int(sys.argv[1]), int(sys.argv[2])
    logf = open(sys.argv[3], 'ab') if len(sys.argv) > 3 else None
    path = f'/dev/usbmon{bus}'
    fd = os.open(path, os.O_RDONLY)
    print(f'sniffing {path}, filtering devnum={dev} (Ctrl-C to stop)')
    try:
        while True:
            raw = os.read(fd, 64 + 4096)
            if len(raw) < 64:
                continue
            (eid, etype, xfer, epnum, devnum, busnum, flag_setup, flag_data,
             ts_sec, ts_usec, status, length, len_cap, setup, interval,
             start_frame, xfer_flags, ndesc) = HDR.unpack(raw[:64])
            if devnum != dev:
                continue
            data = raw[64:64 + len_cap]
            t = datetime.datetime.fromtimestamp(ts_sec).strftime('%H:%M:%S')
            ev = chr(etype)  # S=submit C=complete E=error
            ep = f'{"IN " if epnum & 0x80 else "OUT"} ep{epnum & 0x7f}'
            desc = f'[{t}.{ts_usec:06d}] {ev} {XFER.get(xfer, xfer)} {ep} len={length}'
            if xfer == 2 and flag_setup == 0:  # control with valid setup
                bm, breq, wval, widx, wlen = struct.unpack('<BBHHH', setup)
                rname = REQ.get(breq, f'req_{breq:02x}')
                tname = RTYPE.get(bm, f'{bm:02x}')
                rtype = {1: 'INPUT', 2: 'OUTPUT', 3: 'FEATURE'}.get(wval >> 8, '?')
                desc += (f' | {tname} {rname} report_type={rtype}'
                         f' report_id=0x{wval & 0xff:02x} iface={widx} wlen={wlen}')
            print(desc)
            if data:
                hexdump(data)
            if logf:
                logf.write(raw[:64 + len_cap] + b'\xff\xfe\xfd\xfc')
                logf.flush()
    except KeyboardInterrupt:
        pass
    finally:
        os.close(fd)

if __name__ == '__main__':
    main()
