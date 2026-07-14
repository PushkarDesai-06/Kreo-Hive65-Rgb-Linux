#!/usr/bin/env python3
"""Low-latency WebSocket bridge: stream RGB frames to the BY Tech / Kreo Hive 65
(258a:010c) keyboard from any app (e.g. a React front-end).

Zero dependencies — a minimal RFC6455 server on top of the `Kbd` driver in
device.py. A single writer thread owns the keyboard and coalesces frames
latest-wins, so sending faster than the board's ~60 fps ceiling never builds a
queue — you always render the freshest frame. End-to-end latency ≈ the USB
flush (~12 ms), not the socket.

Wire protocol (client -> server), auto-detected per message:
  * Binary, 204 bytes  = 68 keys x RGB, in schema keys[].index order  (PRIMARY)
  * Binary, 378 bytes  = 126 slots x RGB, raw HID buffer            (advanced)
  * Text JSON:
      {"type":"frame","keys":{"esc":"#ff0000","w":[0,255,0]}}   # black base
      {"type":"frame","grid":[["#f00", ...16], ... 5 rows]}
      {"type":"fill","color":"#00ffaa"}
      {"type":"clear"}
      {"type":"getSchema"}
On connect the server sends {"type":"schema", ...} describing the board.

Usage:
  kbd_ws_server.py [--host 127.0.0.1] [--port 8787]
  kbd_ws_server.py emit-client <dir>     # write schema.json + TS client/hook
"""
import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import threading
import time

import color
import device

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
# the board this bridge serves (the driver's default profile)
P = device.DEFAULT
NKEYS = P.key_count()
RGB_BYTES = P.num_slots * 3
GRID_COLS = P.cols
GRID_ROWS = P.rows
GRID_TO_SLOT = {(col, row): P.slot[name] for name, col, row in P.keys_tuples}


# ---------------------------------------------------------------- schema ----
def build_schema():
    return {
        "type": "schema",
        "device": P.name,
        "grid": {"cols": GRID_COLS, "rows": GRID_ROWS},
        "keyCount": NKEYS,
        "slotCount": P.num_slots,
        "maxFps": 60,
        "primaryFormat": "binary",
        "binaryFrame": {
            "bytes": NKEYS * 3,
            "layout": "R,G,B per key, order = keys[].index",
        },
        "rawFrame": {
            "bytes": RGB_BYTES,
            "layout": "R,G,B per HID slot (%d slots)" % P.num_slots,
        },
        "keys": [
            {"index": i, "name": name, "col": col, "row": row, "slot": P.slot[name]}
            for i, (name, col, row) in enumerate(P.keys_tuples)
        ],
    }


# ------------------------------------------------------- keyboard writer ----
class Writer(threading.Thread):
    """Owns the Kbd; flushes the shared `pending` buffer latest-wins, with a
    ~1 Hz keep-alive so colors don't revert to onboard lighting when idle."""

    KEEPALIVE = 1.0

    def __init__(self):
        super().__init__(daemon=True)
        self.pending = bytearray(RGB_BYTES)
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.running = True
        self.kbd = None
        self.connected = False
        self.flushes = 0
        self.debug = bool(os.environ.get("KBD_WS_DEBUG"))

    def submit(self, rgb):
        with self.lock:
            self.pending[:] = rgb
        self.ready.set()

    def _ensure(self):
        if self.kbd is not None:
            return True
        try:
            self.kbd = device.Kbd()
            print(f"[kbd] connected: {self.kbd.dev}", flush=True)
            self.connected = True
            return True
        except SystemExit:
            if self.connected:
                print("[kbd] waiting for keyboard...", flush=True)
            self.connected = False
            return False

    def run(self):
        while self.running:
            self.ready.wait(timeout=self.KEEPALIVE)
            self.ready.clear()
            if not self._ensure():
                time.sleep(0.5)
                continue
            with self.lock:
                self.kbd.rgb[:] = self.pending
            try:
                self.kbd.flush()
                self.flushes += 1
                if self.debug:
                    print(f"[kbd] flush #{self.flushes} first_key={bytes(self.pending[3:6]).hex()}", flush=True)
            except OSError as e:
                if e.errno in device.Kbd.GONE_ERRNOS:
                    print("[kbd] firmware reset, reconnecting...", flush=True)
                    if not self.kbd.reopen():
                        self.kbd = None
                        self.connected = False
                else:
                    print(f"[kbd] flush error: {e}", flush=True)
                    self.kbd = None


# -------------------------------------------------- frame parsing helpers ----
def _color(v):
    """Accept '#rrggbb', 'rrggbb', or [r,g,b] -> (r,g,b)."""
    if isinstance(v, str):
        return color.parse_hex(v)
    return int(v[0]) & 255, int(v[1]) & 255, int(v[2]) & 255


def frame_from_binary(data):
    """204 bytes -> per-key; 378 bytes -> raw slot buffer."""
    rgb = bytearray(RGB_BYTES)
    if len(data) == NKEYS * 3:
        for i, (name, _c, _r) in enumerate(P.keys_tuples):
            s = P.slot[name] * 3
            rgb[s : s + 3] = data[i * 3 : i * 3 + 3]
    elif len(data) == RGB_BYTES:
        rgb[:] = data
    else:
        raise ValueError(f"binary frame must be {NKEYS*3} or {RGB_BYTES} bytes, got {len(data)}")
    return rgb


def frame_from_json(msg):
    """Returns (rgb_or_None, reply_or_None). None rgb = control message."""
    t = msg.get("type")
    if t == "getSchema":
        return None, build_schema()
    rgb = bytearray(RGB_BYTES)
    if t == "clear":
        return rgb, None
    if t == "fill":
        r, g, b = _color(msg["color"])
        for name in P.slot:
            s = P.slot[name] * 3
            rgb[s : s + 3] = bytes((r, g, b))
        return rgb, None
    if t == "frame":
        if "keys" in msg:
            for name, v in msg["keys"].items():
                name = name.lower()
                if name in P.slot:
                    s = P.slot[name] * 3
                    rgb[s : s + 3] = bytes(_color(v))
        elif "grid" in msg:
            for row, cols in enumerate(msg["grid"]):
                for col, v in enumerate(cols):
                    slot = GRID_TO_SLOT.get((col, row))
                    if slot is not None:
                        rgb[slot * 3 : slot * 3 + 3] = bytes(_color(v))
        elif "rgb" in msg:  # flat list of 68 colors
            for i, v in enumerate(msg["rgb"][:NKEYS]):
                s = P.slot[P.keys_tuples[i][0]] * 3
                rgb[s : s + 3] = bytes(_color(v))
        return rgb, None
    return None, {"type": "error", "message": f"unknown type {t!r}"}


# ------------------------------------------------------- minimal RFC6455 ----
def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf


def ws_handshake(sock):
    req = b""
    while b"\r\n\r\n" not in req:
        chunk = sock.recv(4096)
        if not chunk:
            return False
        req += chunk
    key = None
    for line in req.split(b"\r\n"):
        if line.lower().startswith(b"sec-websocket-key:"):
            key = line.split(b":", 1)[1].strip()
    if not key:
        return False
    accept = base64.b64encode(hashlib.sha1(key + WS_GUID.encode()).digest())
    sock.sendall(
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n"
    )
    return True


def ws_send(sock, data, opcode):
    b0 = 0x80 | opcode
    n = len(data)
    if n < 126:
        hdr = struct.pack("!BB", b0, n)
    elif n < 65536:
        hdr = struct.pack("!BBH", b0, 126, n)
    else:
        hdr = struct.pack("!BBQ", b0, 127, n)
    sock.sendall(hdr + data)


def ws_send_json(sock, obj):
    ws_send(sock, json.dumps(obj).encode(), 0x1)


def ws_read_message(sock):
    """Returns (opcode, payload). Handles fragmentation and masking."""
    opcode = None
    payload = b""
    while True:
        b0, b1 = recv_exact(sock, 2)
        fin = b0 & 0x80
        op = b0 & 0x0F
        masked = b1 & 0x80
        ln = b1 & 0x7F
        if ln == 126:
            ln = struct.unpack("!H", recv_exact(sock, 2))[0]
        elif ln == 127:
            ln = struct.unpack("!Q", recv_exact(sock, 8))[0]
        mask = recv_exact(sock, 4) if masked else b"\0\0\0\0"
        chunk = bytearray(recv_exact(sock, ln))
        if masked:
            for i in range(ln):
                chunk[i] ^= mask[i & 3]
        if op != 0x0:  # not a continuation
            opcode = op
        payload += bytes(chunk)
        if fin:
            return opcode, payload


def handle_client(sock, addr, writer):
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    try:
        if not ws_handshake(sock):
            return
        print(f"[ws] client {addr} connected", flush=True)
        ws_send_json(sock, build_schema())
        while True:
            opcode, data = ws_read_message(sock)
            if opcode == 0x8:  # close
                break
            if opcode == 0x9:  # ping -> pong
                ws_send(sock, data, 0xA)
                continue
            if opcode == 0xA:  # pong
                continue
            try:
                if opcode == 0x2:  # binary
                    writer.submit(frame_from_binary(data))
                elif opcode == 0x1:  # text/json
                    rgb, reply = frame_from_json(json.loads(data.decode()))
                    if rgb is not None:
                        writer.submit(rgb)
                    if reply is not None:
                        ws_send_json(sock, reply)
            except (ValueError, KeyError, IndexError, json.JSONDecodeError) as e:
                ws_send_json(sock, {"type": "error", "message": str(e)})
    except (ConnectionError, OSError):
        pass
    finally:
        sock.close()
        print(f"[ws] client {addr} disconnected", flush=True)


def serve(host, port):
    writer = Writer()
    writer.start()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(8)
    print(f"[ws] listening on ws://{host}:{port}  ({NKEYS} keys)", flush=True)
    try:
        while True:
            sock, addr = srv.accept()
            threading.Thread(
                target=handle_client, args=(sock, addr, writer), daemon=True
            ).start()
    except KeyboardInterrupt:
        print("\n[ws] shutting down", flush=True)
    finally:
        srv.close()


# ---------------------------------------------------------- client emit ----
def emit_client(dest):
    os.makedirs(dest, exist_ok=True)
    schema = build_schema()
    with open(os.path.join(dest, "schema.json"), "w") as f:
        json.dump(schema, f, indent=2)

    keys_ts = ",\n  ".join(
        '{{ index: {i}, name: "{n}", col: {c}, row: {r}, slot: {s} }}'.format(
            i=k["index"], n=k["name"], c=k["col"], r=k["row"], s=k["slot"]
        )
        for k in schema["keys"]
    )
    with open(os.path.join(dest, "keyboardLayout.ts"), "w") as f:
        f.write(
            "// Auto-generated from the keyboard's LED map. Do not edit by hand.\n"
            "export interface KeyDef { index: number; name: string; "
            "col: number; row: number; slot: number; }\n\n"
            f"export const KEY_COUNT = {NKEYS};\n"
            f"export const GRID = {{ cols: {GRID_COLS}, rows: {GRID_ROWS} }} as const;\n\n"
            "export const KEYS: readonly KeyDef[] = [\n  "
            + keys_ts
            + ",\n];\n\n"
            "export const KEY_INDEX: Record<string, number> = "
            "Object.fromEntries(KEYS.map(k => [k.name, k.index]));\n"
        )
    with open(os.path.join(dest, "keyboardClient.ts"), "w") as f:
        f.write(TS_CLIENT)
    with open(os.path.join(dest, "useKeyboard.ts"), "w") as f:
        f.write(TS_HOOK)
    print("wrote schema.json, keyboardLayout.ts, keyboardClient.ts, useKeyboard.ts to", dest)


TS_CLIENT = r'''// Typed client for the keyboard WebSocket bridge. Zero dependencies.
import { KEYS, KEY_COUNT, KEY_INDEX } from "./keyboardLayout";

export type RGB = [number, number, number];
export type Schema = {
  type: "schema"; device: string; grid: { cols: number; rows: number };
  keyCount: number; slotCount: number; maxFps: number;
  keys: { index: number; name: string; col: number; row: number; slot: number }[];
};

function toRGB(c: RGB | string): RGB {
  if (typeof c !== "string") return c;
  const h = c.replace("#", "");
  const n = h.length === 3
    ? h.split("").map(x => x + x).join("")
    : h.padEnd(6, "0");
  return [parseInt(n.slice(0, 2), 16), parseInt(n.slice(2, 4), 16), parseInt(n.slice(4, 6), 16)];
}

export class KeyboardClient {
  private ws: WebSocket | null = null;
  private url: string;
  private buf = new Uint8Array(KEY_COUNT * 3);
  schema: Schema | null = null;
  onSchema?: (s: Schema) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (msg: string) => void;

  constructor(url = "ws://127.0.0.1:8787") { this.url = url; }

  connect() {
    const ws = new WebSocket(this.url);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => this.onOpen?.();
    ws.onclose = () => { this.onClose?.(); this.ws = null;
      setTimeout(() => this.connect(), 1000); };            // auto-reconnect
    ws.onmessage = ev => {
      const m = JSON.parse(ev.data as string);
      if (m.type === "schema") { this.schema = m; this.onSchema?.(m); }
      else if (m.type === "error") this.onError?.(m.message);
    };
    this.ws = ws;
  }

  get ready() { return this.ws?.readyState === WebSocket.OPEN; }

  /** Send the raw 68x3 buffer (fastest path). */
  sendFrame(buf: Uint8Array) { if (this.ready) this.ws!.send(buf); }

  /** Build + send a frame from an array of 68 colors (index order). */
  sendColors(colors: (RGB | string)[]) {
    this.buf.fill(0);
    for (let i = 0; i < Math.min(colors.length, KEY_COUNT); i++) {
      const [r, g, b] = toRGB(colors[i]);
      this.buf[i * 3] = r; this.buf[i * 3 + 1] = g; this.buf[i * 3 + 2] = b;
    }
    this.sendFrame(this.buf);
  }

  /** Set individual keys by name on a black board, then send. */
  setKeys(map: Record<string, RGB | string>) {
    this.buf.fill(0);
    for (const name in map) {
      const idx = KEY_INDEX[name.toLowerCase()];
      if (idx == null) continue;
      const [r, g, b] = toRGB(map[name]);
      this.buf[idx * 3] = r; this.buf[idx * 3 + 1] = g; this.buf[idx * 3 + 2] = b;
    }
    this.sendFrame(this.buf);
  }

  fill(color: RGB | string) { this.sendColors(new Array(KEY_COUNT).fill(color)); }
  clear() { this.buf.fill(0); this.sendFrame(this.buf); }
  close() { this.ws?.close(); }
}

export { KEYS, KEY_COUNT, KEY_INDEX };
'''

TS_HOOK = r'''// React hook wrapping KeyboardClient. Usage:
//   const { ready, sendColors, setKeys, fill, clear } = useKeyboard();
import { useEffect, useRef, useState, useCallback } from "react";
import { KeyboardClient, RGB, Schema } from "./keyboardClient";

export function useKeyboard(url = "ws://127.0.0.1:8787") {
  const ref = useRef<KeyboardClient | null>(null);
  const [ready, setReady] = useState(false);
  const [schema, setSchema] = useState<Schema | null>(null);

  useEffect(() => {
    const c = new KeyboardClient(url);
    c.onOpen = () => setReady(true);
    c.onClose = () => setReady(false);
    c.onSchema = s => setSchema(s);
    c.connect();
    ref.current = c;
    return () => c.close();
  }, [url]);

  const sendFrame = useCallback((buf: Uint8Array) => ref.current?.sendFrame(buf), []);
  const sendColors = useCallback((cs: (RGB | string)[]) => ref.current?.sendColors(cs), []);
  const setKeys = useCallback((m: Record<string, RGB | string>) => ref.current?.setKeys(m), []);
  const fill = useCallback((c: RGB | string) => ref.current?.fill(c), []);
  const clear = useCallback(() => ref.current?.clear(), []);

  return { ready, schema, sendFrame, sendColors, setKeys, fill, clear };
}
'''


def main():
    p = argparse.ArgumentParser(description="Keyboard RGB WebSocket bridge")
    sub = p.add_subparsers(dest="cmd")
    em = sub.add_parser("emit-client", help="write schema.json + TS client files")
    em.add_argument("dir")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    o = p.parse_args()
    if o.cmd == "emit-client":
        emit_client(o.dir)
    else:
        serve(o.host, o.port)


if __name__ == "__main__":
    main()
