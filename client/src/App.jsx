import { useState } from "react";
import EffectsStudio from "./EffectsStudio";
import ReactBitsStage from "./ReactBitsStage";
import "./App.css";

const TABS = [
  { id: "reactbits", label: "Canvas → Keyboard" },
  { id: "effects", label: "Built-in Effects" },
];

export default function App() {
  const [tab, setTab] = useState("reactbits");
  return (
    <div className="app">
      <header>
        <h1>⌨️ Keyboard RGB Studio</h1>
        <nav className="tabs">
          {TABS.map((t) => (
            <button key={t.id} className={tab === t.id ? "on" : ""} onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </nav>
      </header>
      {tab === "reactbits" ? <ReactBitsStage /> : <EffectsStudio />}
    </div>
  );
}
