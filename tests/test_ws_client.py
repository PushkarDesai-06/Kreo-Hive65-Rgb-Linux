#!/usr/bin/env python3
"""Minimal stdlib WebSocket client to exercise kbd_ws_server.py (no deps).

Manual smoke test: start kbd_ws_server.py first, then run this. It is NOT a
unittest (it needs a live server + keyboard), so its body is guarded under
__main__ to stay import-safe for `unittest discover`."""
import base64, hashlib, json, os, socket, struct, sys, time

def connect(host="127.0.0.1", port=8787):
    s = socket.create_connection((host, port))
    key = base64.b64encode(os.urandom(16))
    s.sendall(
        b"GET / HTTP/1.1\r\nHost: %b:%d\r\nUpgrade: websocket\r\n"
        b"Connection: Upgrade\r\nSec-WebSocket-Key: %b\r\n"
        b"Sec-WebSocket-Version: 13\r\n\r\n" % (host.encode(), port, key)
    )
    resp = b""
    while b"\r\n\r\n" not in resp:
        resp += s.recv(4096)
    assert b"101" in resp, resp[:40]
    return s

def send(s, data, opcode):
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i & 3] for i, b in enumerate(data))
    n = len(data); b0 = 0x80 | opcode
    if n < 126: hdr = struct.pack("!BB", b0, 0x80 | n)
    elif n < 65536: hdr = struct.pack("!BBH", b0, 0x80 | 126, n)
    else: hdr = struct.pack("!BBQ", b0, 0x80 | 127, n)
    s.sendall(hdr + mask + masked)

def recv(s):
    b0, b1 = s.recv(2)
    ln = b1 & 0x7f
    if ln == 126: ln = struct.unpack("!H", s.recv(2))[0]
    elif ln == 127: ln = struct.unpack("!Q", s.recv(8))[0]
    buf = b""
    while len(buf) < ln: buf += s.recv(ln - len(buf))
    return b0 & 0x0f, buf

def main():
    s = connect()
    op, data = recv(s)
    schema = json.loads(data)
    print(f"schema: {schema['device']}, {schema['keyCount']} keys, "
          f"binary={schema['binaryFrame']['bytes']}B")

    # 1) binary 204-byte all-RED frame
    frame = bytes([255, 0, 0] * schema["keyCount"])
    send(s, frame, 0x2)
    print(f"sent binary red frame ({len(frame)}B)")
    time.sleep(0.2)

    # 2) JSON keymap
    send(s, json.dumps({"type": "frame", "keys": {"w": "#00ff00", "esc": [0, 0, 255]}}).encode(), 0x1)
    print("sent JSON keymap (w=green, esc=blue)")
    time.sleep(0.2)

    # 3) JSON fill
    send(s, json.dumps({"type": "fill", "color": "#0000ff"}).encode(), 0x1)
    print("sent JSON fill blue")
    time.sleep(0.2)

    # 4) getSchema round-trip
    send(s, json.dumps({"type": "getSchema"}).encode(), 0x1)
    op, data = recv(s)
    print("getSchema reply type:", json.loads(data)["type"])

    # 5) bad frame -> error reply
    send(s, b"\x00\x01\x02", 0x2)
    op, data = recv(s)
    print("bad binary -> ", json.loads(data))

    # 6) clear
    send(s, json.dumps({"type": "clear"}).encode(), 0x1)
    print("sent clear")
    send(s, b"", 0x8)  # close
    s.close()
    print("done")


if __name__ == "__main__":
    main()
