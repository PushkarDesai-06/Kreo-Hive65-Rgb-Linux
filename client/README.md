# Keyboard RGB WebSocket bridge — client guide

Stream RGB frames to the Kreo Hive 65 (`258a:010c`) from a React app (or
anything that speaks WebSocket) with ~12 ms latency.

## 1. Start the server (on the machine with the keyboard)

```bash
python3 kbd_ws_server.py            # ws://127.0.0.1:8787
python3 kbd_ws_server.py --host 0.0.0.0 --port 9000   # expose to LAN / other port
```

Zero dependencies (pure Python stdlib + the `hydra_rgb.py` driver). It reuses
the same udev/permissions setup as the CLI — if you see `waiting for
keyboard...`, grant hidraw access (see the main README's udev rule).

The server holds the last frame with a ~1 Hz keep-alive so colors don't
revert, and auto-reconnects across the board's firmware resets.

## Quick smoke test (no build, no React)

Open **`demo.html`** in a browser while the server is running. It draws to a
16×5 canvas and streams the pixels to the board as binary frames — rainbow,
plasma, gradient, solid, and a click-to-paint mode, plus a live on-screen
mirror of all 68 keys, connection status, and render/send fps. Great for
confirming the socket works before wiring up your own app.

> A **Max FPS** slider throttles the keyboard sends independently of the
> on-screen preview (which animates at your display's full refresh). Default
> is **30**; if you see the board reset (it can be flaky near 60), slide it
> lower. The effective send rate never exceeds the slider value.

## 2. Run the included React app

This folder **is** a Vite + React app, already wired to the bridge:

```bash
bun install      # or npm install
bun run dev      # http://localhost:5173  (start the WS server first)
```

`src/App.jsx` has two tabs:

- **React Bits → Keyboard** — the canvas pipeline. Renders a canvas-producing
  component live, samples its `<canvas>`, downscales it to 16×5, and streams to
  the board. Pick a component (Strands / Color Bends), tweak its own props via
  the generated controls, and watch the on-screen mirror. Adding a component is
  one entry in `src/components/reactBitsRegistry.js` — see "React Bits pipeline"
  below.
- **Built-in Effects** — the hand-written visualizer (rainbow / wave / plasma /
  solid / off) with color, speed, brightness, Max-FPS.

Both cap sends with a **Max FPS** slider (default 30, since the board is flaky
near 60) and show a live mirror of all 68 keys. The hook + client + layout live
in `src/hooks/` (`useKeyboard.ts`, `keyboardClient.ts`, `keyboardLayout.ts`).

### React Bits pipeline (`src/components/`)

`CanvasKeyboardBridge.jsx` is the reusable core: wrap any component that draws a
`<canvas>`, and it downscales that canvas to the board every frame. To add a
React Bits component: drop its file in `src/components/`, and if it's WebGL
(`ogl`/`three`) add `preserveDrawingBuffer: true` to its renderer options — the
pixels are otherwise cleared after compositing and sample as black. Then add a
descriptor (component + default props + control list) to `reactBitsRegistry.js`;
`ParamControls.jsx` renders its controls automatically.

## 3. …or drop the client into your own React app

Copy `src/hooks/keyboardClient.ts`, `useKeyboard.ts`, and `keyboardLayout.ts`
into your project. (`schema.json` is the same data as `keyboardLayout.ts`, for
non-TS consumers.) Then:

```tsx
import { useKeyboard } from "./useKeyboard";
import { KEYS, KEY_COUNT } from "./keyboardLayout";

function Demo() {
  const { ready, sendColors, setKeys, fill, clear } = useKeyboard();

  // animate: rainbow that scrolls, ~60 fps
  useEffect(() => {
    if (!ready) return;
    let raf: number,
      t = 0;
    const tick = () => {
      const colors = KEYS.map((k) => {
        const h = ((k.col / 16 + t) % 1) * 360;
        return `hsl(${h},100%,50%)`; // or an [r,g,b] triplet
      });
      sendColors(hslStringsToRgb(colors)); // sendColors takes RGB or #hex
      t += 0.01;
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [ready, sendColors]);

  return (
    <div>
      keyboard: {ready ? "connected" : "…"}
      <button onClick={() => fill("#ff0000")}>all red</button>
      <button
        onClick={() => setKeys({ w: "#0f0", a: "#0f0", s: "#0f0", d: "#0f0" })}
      >
        WASD
      </button>
      <button onClick={clear}>off</button>
    </div>
  );
}
```

`sendColors` / `setKeys` / `fill` accept `"#rrggbb"`, `"#rgb"`, or `[r,g,b]`.

### Fastest path (build the buffer yourself)

For heavy animation, skip per-call allocation and push the raw 204-byte
buffer — one `[r,g,b]` per key in `KEYS` index order:

```ts
const buf = new Uint8Array(KEY_COUNT * 3);
for (const k of KEYS) {
  buf[k.index * 3] = r;
  buf[k.index * 3 + 1] = g;
  buf[k.index * 3 + 2] = b;
}
sendFrame(buf); // from useKeyboard()
```

## Frame formats (all accepted by the server)

| Send                                  | Meaning                                                            |
| ------------------------------------- | ------------------------------------------------------------------ |
| **Binary, 204 bytes**                 | 68 keys × `R,G,B`, in `KEYS[].index` order. Primary/fastest.       |
| Binary, 378 bytes                     | 126 HID slots × `R,G,B`, raw buffer (advanced; use `keys[].slot`). |
| `{"type":"frame","keys":{...}}`       | key-name → color, on a black board.                                |
| `{"type":"frame","grid":[[...16]×5]}` | 16×5 color grid (unmapped cells ignored).                          |
| `{"type":"frame","rgb":[c0..c67]}`    | flat list of 68 colors in index order.                             |
| `{"type":"fill","color":"#hex"}`      | whole board one color.                                             |
| `{"type":"clear"}`                    | all off.                                                           |
| `{"type":"getSchema"}`                | server replies with the schema message.                            |

On connect the server sends `{"type":"schema", ...}` (device, grid, key list
with names/positions/slots, formats, maxFps). The hook exposes it as `schema`.

## Notes

- **Latency:** a single writer thread coalesces frames _latest-wins_ — sending
  faster than ~60 fps never queues; you always render the freshest frame.
- **Rate:** target ≤ 60 fps. Higher just gets coalesced (harmless).
- Only one keyboard is driven; multiple clients all write to it (last frame wins).
