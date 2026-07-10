// Typed client for the keyboard WebSocket bridge. Zero dependencies.
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
  private closing = false;
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
      if (!this.closing) setTimeout(() => this.connect(), 1000); };   // auto-reconnect
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
  close() { this.closing = true; this.ws?.close(); }
}

export { KEYS, KEY_COUNT, KEY_INDEX };
