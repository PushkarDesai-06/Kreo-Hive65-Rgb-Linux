import { useEffect, useRef, useState } from "react";
import { useKeyboard } from "./hooks/useKeyboard";
import { KEYS, KEY_COUNT, GRID } from "./hooks/keyboardLayout";
import "./App.css";

const EFFECTS = ["rainbow", "wave", "plasma", "solid", "off"];

// --- small color helpers ---------------------------------------------------
function hsv(h, s, v) {
  const i = Math.floor(h * 6) % 6;
  const f = h * 6 - Math.floor(h * 6);
  const p = v * (1 - s), q = v * (1 - f * s), t = v * (1 - (1 - f) * s);
  const [r, g, b] = [[v, t, p], [q, v, p], [p, v, t], [p, q, v], [t, p, v], [v, p, q]][i];
  return [(r * 255) | 0, (g * 255) | 0, (b * 255) | 0];
}
function hex2rgb(h) {
  const n = h.replace("#", "");
  return [parseInt(n.slice(0, 2), 16), parseInt(n.slice(2, 4), 16), parseInt(n.slice(4, 6), 16)];
}

// per-key color for the current effect at time t
function colorFor(effect, k, t, base) {
  if (effect === "off") return [0, 0, 0];
  if (effect === "solid") return base;
  if (effect === "rainbow") return hsv((k.col / GRID.cols + t * 0.1) % 1, 1, 1);
  if (effect === "wave") {
    const w = Math.max(0, (Math.sin(k.col * 0.5 - t * 3) + 1) * 127.5);
    return [0, (w * 0.8) | 0, w | 0];
  }
  // plasma
  const v = 0.5 + 0.5 * Math.sin(k.col * 0.6 + t * 2) * Math.cos(k.row * 0.9 - t * 1.3)
                + 0.25 * Math.sin((k.col + k.row) * 0.4 + t * 1.7);
  return hsv((v * 0.5 + t * 0.05) % 1, 0.9, Math.min(1, Math.abs(v)));
}

export default function App() {
  const { ready, schema, error, sendFrame } = useKeyboard();
  const [effect, setEffect] = useState("rainbow");
  const [color, setColor] = useState("#009bde");
  const [speed, setSpeed] = useState(60);
  const [brightness, setBrightness] = useState(100);
  const [maxFps, setMaxFps] = useState(30);
  const [sendRate, setSendRate] = useState(0);

  // live params the animation loop reads without re-subscribing
  const params = useRef({});
  params.current = { effect, color, speed, brightness, maxFps };
  const cellRefs = useRef({});
  const emaRef = useRef(0);

  // one animation loop for the lifetime of a connection
  useEffect(() => {
    if (!ready) return;
    const buf = new Uint8Array(KEY_COUNT * 3);
    let raf = 0, t = 0, last = performance.now(), lastSend = 0;
    const tick = () => {
      const now = performance.now();
      const dt = (now - last) / 1000; last = now;
      const p = params.current;
      t += dt * (p.speed / 60);
      const bri = p.brightness / 100;
      const base = hex2rgb(p.color);
      for (const k of KEYS) {
        let [r, g, b] = colorFor(p.effect, k, t, base);
        r = (r * bri) | 0; g = (g * bri) | 0; b = (b * bri) | 0;
        const bi = k.index * 3;
        buf[bi] = r; buf[bi + 1] = g; buf[bi + 2] = b;
        const el = cellRefs.current[k.index];
        if (el) {
          el.style.background = `rgb(${r},${g},${b})`;
          el.style.boxShadow = r + g + b > 40 ? `0 0 8px rgb(${r},${g},${b})` : "none";
        }
      }
      // throttle the actual keyboard sends (board tops out ~60 fps; preview is full-rate)
      if (now - lastSend >= 1000 / p.maxFps) {
        sendFrame(buf);
        emaRef.current = emaRef.current * 0.9 + (1000 / (now - lastSend)) * 0.1;
        lastSend = now;
      }
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [ready, sendFrame]);

  // update the send-rate readout a few times a second (not every frame)
  useEffect(() => {
    const id = setInterval(() => setSendRate(Math.round(emaRef.current)), 300);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="app">
      <header>
        <h1>⌨️ Keyboard RGB Studio</h1>
        <div className={"status " + (ready ? "ok" : "")}>
          <span className="dot" />
          {ready ? (schema?.device ?? "connected") : "waiting for server…"}
        </div>
      </header>

      {error && <div className="error">server: {error}</div>}

      <section className="panel">
        <div className="effects">
          {EFFECTS.map((e) => (
            <button key={e} className={effect === e ? "on" : ""} onClick={() => setEffect(e)}>
              {e}
            </button>
          ))}
        </div>
        <div className="sliders">
          <label>
            Color
            <input type="color" value={color} onChange={(e) => setColor(e.target.value)} />
          </label>
          <label>
            Speed <input type="range" min="0" max="200" value={speed} onChange={(e) => setSpeed(+e.target.value)} />
          </label>
          <label>
            Brightness <input type="range" min="0" max="100" value={brightness} onChange={(e) => setBrightness(+e.target.value)} />
          </label>
          <label>
            Max FPS <input type="range" min="5" max="60" value={maxFps} onChange={(e) => setMaxFps(+e.target.value)} />
            <b>{maxFps}</b>
          </label>
        </div>
      </section>

      <section className="board-wrap">
        <div className="board" style={{ gridTemplateColumns: `repeat(${GRID.cols}, 1fr)` }}>
          {KEYS.map((k) => (
            <div
              key={k.index}
              className="key"
              style={{ gridColumn: k.col + 1, gridRow: k.row + 1 }}
              ref={(el) => { cellRefs.current[k.index] = el; }}
            >
              {k.name.length > 5 ? k.name.slice(0, 4) : k.name}
            </div>
          ))}
        </div>
        <footer>
          <span>{KEY_COUNT} keys</span>
          <span>send: <b>{sendRate}</b> fps</span>
          <span>effect: <b>{effect}</b></span>
        </footer>
      </section>
    </div>
  );
}
