import { useEffect, useRef } from "react";

// Our own canvas component (not React Bits): an animated multi-stop gradient
// with several motion modes. Plain 2D canvas — always samplable, we own the
// render loop. Distortion effects are a planned later addition (see NOTE).

const hexToRgb = (h) => {
  let s = h.replace("#", "");
  if (s.length === 3) s = s.split("").map((c) => c + c).join("");
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
};
const lerp = (a, b, f) => a + (b - a) * f;

// wrap-around palette sampling: u in R -> interpolated [r,g,b], loops seamlessly
function palAt(u, cols) {
  const n = cols.length;
  if (n === 1) return cols[0];
  const x = (((u % 1) + 1) % 1) * n;
  const i = Math.floor(x) % n;
  const f = x - Math.floor(x);
  const a = cols[i], b = cols[(i + 1) % n];
  return [lerp(a[0], b[0], f), lerp(a[1], b[1], f), lerp(a[2], b[2], f)];
}
const css = ([r, g, b], a = 1) => `rgba(${r | 0},${g | 0},${b | 0},${a})`;

// build a gradient object's stops by sampling the palette with a scroll phase
function fillStops(grad, cols, phase, steps = 24) {
  for (let s = 0; s <= steps; s++) {
    const u = s / steps;
    grad.addColorStop(u, css(palAt(u + phase, cols)));
  }
}

export default function GradientPlayground({
  colors = ["#FF4242", "#7C3AED", "#06B6D4", "#EAB308"],
  colorCount = 4,
  effect = "linear",
  speed = 0.5,
  angle = 0,
}) {
  const canvasRef = useRef(null);
  const propsRef = useRef({});
  propsRef.current = { colors, colorCount, effect, speed, angle };

  useEffect(() => {
    const canvas = canvasRef.current;
    const parent = canvas.parentElement;
    const ctx = canvas.getContext("2d");

    const resize = () => {
      canvas.width = Math.max(1, parent.clientWidth);
      canvas.height = Math.max(1, parent.clientHeight);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(parent);

    const t0 = performance.now();
    let raf = 0;
    const draw = () => {
      const p = propsRef.current;
      const cols = (p.colors || []).slice(0, Math.max(1, p.colorCount)).map(hexToRgb);
      const t = ((performance.now() - t0) / 1000) * p.speed;
      const W = canvas.width, H = canvas.height;
      ctx.globalCompositeOperation = "source-over";
      ctx.clearRect(0, 0, W, H);

      if (p.effect === "conic" && ctx.createConicGradient) {
        const g = ctx.createConicGradient(t, W / 2, H / 2);
        fillStops(g, cols, 0, 32);
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, W, H);
      } else if (p.effect === "radial") {
        const rMax = Math.hypot(W, H) / 2;
        const r = rMax * (0.7 + 0.3 * Math.sin(t * 1.5));
        const g = ctx.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, r);
        fillStops(g, cols, -t, 28);
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, W, H);
      } else if (p.effect === "aurora") {
        ctx.fillStyle = "#05060a";
        ctx.fillRect(0, 0, W, H);
        ctx.globalCompositeOperation = "lighter";
        const rad = Math.max(W, H) * 0.55;
        cols.forEach((c, i) => {
          const px = W * (0.5 + 0.42 * Math.sin(t * 0.7 + i * 1.9));
          const py = H * (0.5 + 0.42 * Math.cos(t * 0.9 + i * 2.3));
          const g = ctx.createRadialGradient(px, py, 0, px, py, rad);
          g.addColorStop(0, css(c, 0.85));
          g.addColorStop(1, css(c, 0));
          ctx.fillStyle = g;
          ctx.fillRect(0, 0, W, H);
        });
      } else {
        // linear: gradient along `angle`, colors scroll with time
        const rad = (p.angle * Math.PI) / 180;
        const dx = Math.cos(rad), dy = Math.sin(rad);
        const half = (Math.abs(dx) * W + Math.abs(dy) * H) / 2;
        const cx = W / 2, cy = H / 2;
        const g = ctx.createLinearGradient(cx - dx * half, cy - dy * half, cx + dx * half, cy + dy * half);
        fillStops(g, cols, -t, 28);
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, W, H);
      }

      // NOTE: distortion effects (warp/ripple/dither) will post-process here later.
      raf = requestAnimationFrame(draw);
    };
    draw();

    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, []);

  return <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block" }} />;
}
