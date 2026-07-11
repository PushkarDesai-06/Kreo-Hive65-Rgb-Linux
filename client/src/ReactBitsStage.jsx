import { useEffect, useState } from "react";
import CanvasKeyboardBridge from "./components/CanvasKeyboardBridge";
import ParamControls from "./components/ParamControls";
import { REGISTRY } from "./components/reactBitsRegistry";

// React Bits pipeline: pick a canvas-producing component, tweak its own props,
// and its canvas is sampled + downscaled to the keyboard. Adding a component
// is just another entry in REGISTRY — the pipeline is unchanged.
export default function ReactBitsStage() {
  const ids = Object.keys(REGISTRY);
  const [id, setId] = useState(ids[0]);
  const desc = REGISTRY[id];

  const [params, setParams] = useState(() => ({ ...desc.defaults }));
  // committed = debounced params handed to the component; ColorBends rebuilds
  // its WebGL context on prop change, so we avoid thrashing it on slider drags.
  const [committed, setCommitted] = useState(params);
  useEffect(() => {
    const t = setTimeout(() => setCommitted(params), 160);
    return () => clearTimeout(t);
  }, [params]);

  const switchTo = (k) => {
    setId(k);
    setParams({ ...REGISTRY[k].defaults });
    setCommitted({ ...REGISTRY[k].defaults });
  };

  const Comp = desc.Component;
  return (
    <>
      <section className="panel">
        <div className="tabs">
          {ids.map((k) => (
            <button key={k} className={k === id ? "on" : ""} onClick={() => switchTo(k)}>
              {REGISTRY[k].label}
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <CanvasKeyboardBridge key={id} width={512} height={160}>
          <Comp {...committed} />
        </CanvasKeyboardBridge>
      </section>

      <section className="panel">
        <div className="sub">{desc.label} parameters</div>
        <ParamControls
          descriptor={desc}
          params={params}
          onChange={(k, v) => setParams((p) => ({ ...p, [k]: v }))}
        />
      </section>
    </>
  );
}
