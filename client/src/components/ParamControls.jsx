// [r,g,b] floats (0..1) <-> "#rrggbb", for shader color props like Dither's waveColor
const floatsToHex = (a) =>
  "#" + [0, 1, 2].map((i) => Math.round((a?.[i] ?? 0) * 255).toString(16).padStart(2, "0")).join("");
const hexToFloats = (h) => {
  const n = h.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16) / 255);
};

// Generic controls panel: renders a component descriptor's `controls` list
// against the current `params`, calling onChange(key, value) on edits.
export default function ParamControls({ descriptor, params, onChange }) {
  return (
    <div className="controls">
      {descriptor.controls.map((c) => {
        const v = params[c.key];

        if (c.type === "bool") {
          return (
            <label key={c.key} className="control bool">
              <input type="checkbox" checked={!!v} onChange={(e) => onChange(c.key, e.target.checked)} />
              {c.key}
            </label>
          );
        }

        if (c.type === "select") {
          return (
            <div key={c.key} className="control select">
              <span className="clabel">{c.key}</span>
              <div className="segbtns">
                {c.options.map((o) => (
                  <button key={o} className={v === o ? "on" : ""} onClick={() => onChange(c.key, o)}>
                    {o}
                  </button>
                ))}
              </div>
            </div>
          );
        }

        if (c.type === "floatColor") {
          return (
            <label key={c.key} className="control colors">
              <span className="clabel">{c.key}</span>
              <input
                type="color"
                value={floatsToHex(v)}
                onChange={(e) => onChange(c.key, hexToFloats(e.target.value))}
              />
            </label>
          );
        }

        if (c.type === "colors") {
          const arr = Array.isArray(v) ? v : [];
          return (
            <div key={c.key} className="control colors">
              <span className="clabel">{c.key}</span>
              <div className="swatches">
                {Array.from({ length: c.count }, (_, i) => (
                  <input
                    key={i}
                    type="color"
                    value={arr[i] ?? "#000000"}
                    onChange={(e) => {
                      const next = [...arr];
                      while (next.length < c.count) next.push("#000000");
                      next[i] = e.target.value;
                      onChange(c.key, next);
                    }}
                  />
                ))}
              </div>
            </div>
          );
        }

        // range / int
        const step = c.type === "int" ? 1 : c.step ?? 0.01;
        return (
          <label key={c.key} className="control">
            <span className="clabel">{c.key}</span>
            <input
              type="range"
              min={c.min}
              max={c.max}
              step={step}
              value={v}
              onChange={(e) => onChange(c.key, +e.target.value)}
            />
            <b>{c.type === "int" ? v : (+v).toFixed(2)}</b>
          </label>
        );
      })}
    </div>
  );
}
