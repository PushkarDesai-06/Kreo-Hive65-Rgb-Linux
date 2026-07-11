import { useEffect, useRef, useState } from "react";
import { useKeyboard } from "../hooks/useKeyboard";
import { KEYS, KEY_COUNT, GRID } from "../hooks/keyboardLayout";

/**
 * Generic pipeline: render ANY canvas-producing component as `children`,
 * grab its <canvas>, downscale to the 16x5 keyboard grid, and stream the
 * pixels to the board. Extensible to any component that draws to a canvas.
 *
 * The source component just needs to render a <canvas> somewhere inside.
 */
export default function CanvasKeyboardBridge({
  children,
  width = 512,
  height = 160, // ~3.2:1, matches the 16x5 board aspect so the downscale isn't distorted
  defaultFps = 30,
}) {
  const { ready, schema, sendFrame } = useKeyboard();
  const stageRef = useRef(null);   // wraps the source component; we find its canvas here
  const cellRefs = useRef({});     // on-screen mirror cells
  const [fps, setFps] = useState(defaultFps);
  const [sendRate, setSendRate] = useState(0);
  const [gotCanvas, setGotCanvas] = useState(false);
  const fpsRef = useRef(defaultFps);
  fpsRef.current = fps;
  const emaRef = useRef(0);

  useEffect(() => {
    if (!ready) return;
    // offscreen 16x5 target — the browser box-filters the source down into it
    const down = document.createElement("canvas");
    down.width = GRID.cols;
    down.height = GRID.rows;
    const dctx = down.getContext("2d", { willReadFrequently: true });
    dctx.imageSmoothingEnabled = true;
    dctx.imageSmoothingQuality = "high";

    const buf = new Uint8Array(KEY_COUNT * 3);
    let raf = 0, lastSend = 0, sawCanvas = false;

    const tick = () => {
      raf = requestAnimationFrame(tick);
      const canvas = stageRef.current?.querySelector("canvas");
      if (!canvas || !canvas.width || !canvas.height) return;
      if (!sawCanvas) { sawCanvas = true; setGotCanvas(true); }

      // downscale the whole source canvas into the 16x5 grid
      try {
        dctx.clearRect(0, 0, GRID.cols, GRID.rows);
        dctx.drawImage(canvas, 0, 0, GRID.cols, GRID.rows);
      } catch {
        return; // canvas not yet readable this frame
      }
      const data = dctx.getImageData(0, 0, GRID.cols, GRID.rows).data;

      for (const k of KEYS) {
        const o = (k.row * GRID.cols + k.col) * 4;
        const r = data[o], g = data[o + 1], b = data[o + 2];
        const bi = k.index * 3;
        buf[bi] = r; buf[bi + 1] = g; buf[bi + 2] = b;
        const el = cellRefs.current[k.index];
        if (el) {
          el.style.background = `rgb(${r},${g},${b})`;
          el.style.boxShadow = r + g + b > 40 ? `0 0 8px rgb(${r},${g},${b})` : "none";
        }
      }

      const now = performance.now();
      if (now - lastSend >= 1000 / fpsRef.current) {
        sendFrame(buf);
        emaRef.current = emaRef.current * 0.9 + (1000 / (now - lastSend)) * 0.1;
        lastSend = now;
      }
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [ready, sendFrame]);

  useEffect(() => {
    const id = setInterval(() => setSendRate(Math.round(emaRef.current)), 300);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="bridge">
      <div className="bridge-top">
        <div>
          <div className="sub">Source component (live canvas)</div>
          <div className="stage" ref={stageRef} style={{ width, height }}>
            {children}
          </div>
        </div>
        <div className="bridge-right">
          <div className="sub">Downscaled to the board (16×5)</div>
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
        </div>
      </div>
      <footer>
        <span className={"status " + (ready ? "ok" : "")}>
          <span className="dot" />
          {ready ? (schema?.device ?? "connected") : "waiting for server…"}
        </span>
        <span>canvas: <b>{gotCanvas ? "found" : "…"}</b></span>
        <span>send: <b>{sendRate}</b> fps</span>
        <label className="ctl">Max FPS
          <input type="range" min="5" max="60" value={fps} onChange={(e) => setFps(+e.target.value)} />
          <b>{fps}</b>
        </label>
      </footer>
    </div>
  );
}
