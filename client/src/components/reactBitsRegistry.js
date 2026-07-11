import GradientPlayground from "./GradientPlayground";
import Strands from "./Strands";
import ColorBends from "./ColorBends";
import DarkVeil from "./DarkVeil";
import Dither from "./Dither";

// Each entry surfaces the component's own configurable props as UI controls.
// control types: range (number slider), int (integer slider), bool (checkbox),
// colors (N hex pickers editing a string[]).
const PALETTE = ["#FF4242", "#7C3AED", "#06B6D4", "#EAB308"];

export const REGISTRY = {
  gradient: {
    label: "Gradient Lab",
    Component: GradientPlayground,
    defaults: {
      colors: [...PALETTE], colorCount: 4, effect: "linear", speed: 0.5, angle: 0,
    },
    controls: [
      { key: "colors", type: "colors", count: 4 },
      { key: "colorCount", type: "int", min: 1, max: 4 },
      { key: "effect", type: "select", options: ["linear", "conic", "radial", "aurora"] },
      { key: "speed", type: "range", min: 0, max: 3, step: 0.05 },
      { key: "angle", type: "int", min: 0, max: 360 },
    ],
  },
  strands: {
    label: "Strands",
    Component: Strands,
    defaults: {
      colors: [...PALETTE], count: 3, speed: 0.6, amplitude: 1, waviness: 1,
      thickness: 0.7, glow: 2.6, taper: 3, spread: 1, hueShift: 0,
      intensity: 0.8, saturation: 1.5, scale: 1.5, opacity: 1,
      glass: false, refraction: 1, dispersion: 1, glassSize: 1,
    },
    controls: [
      { key: "colors", type: "colors", count: 4 },
      { key: "count", type: "int", min: 1, max: 12 },
      { key: "speed", type: "range", min: 0, max: 3, step: 0.05 },
      { key: "amplitude", type: "range", min: 0, max: 3, step: 0.05 },
      { key: "waviness", type: "range", min: 0, max: 3, step: 0.05 },
      { key: "thickness", type: "range", min: 0, max: 3, step: 0.05 },
      { key: "glow", type: "range", min: 0, max: 6, step: 0.1 },
      { key: "taper", type: "range", min: 0, max: 8, step: 0.1 },
      { key: "spread", type: "range", min: 0, max: 3, step: 0.05 },
      { key: "hueShift", type: "range", min: 0, max: 1, step: 0.01 },
      { key: "intensity", type: "range", min: 0, max: 1, step: 0.01 },
      { key: "saturation", type: "range", min: 0, max: 3, step: 0.05 },
      { key: "scale", type: "range", min: 0.2, max: 4, step: 0.05 },
      { key: "opacity", type: "range", min: 0, max: 1, step: 0.01 },
      { key: "glass", type: "bool" },
      { key: "refraction", type: "range", min: 0, max: 3, step: 0.05 },
      { key: "dispersion", type: "range", min: 0, max: 3, step: 0.05 },
      { key: "glassSize", type: "range", min: 0.2, max: 2, step: 0.05 },
    ],
  },
  colorbends: {
    label: "Color Bends",
    Component: ColorBends,
    defaults: {
      colors: [...PALETTE], transparent: false, rotation: 90, autoRotate: 8,
      speed: 0.3, scale: 1, frequency: 1, warpStrength: 1, mouseInfluence: 1,
      parallax: 0.5, noise: 0.1, iterations: 3, intensity: 1.5, bandWidth: 6,
    },
    controls: [
      { key: "colors", type: "colors", count: 4 },
      { key: "transparent", type: "bool" },
      { key: "rotation", type: "int", min: 0, max: 360 },
      { key: "autoRotate", type: "range", min: -60, max: 60, step: 1 },
      { key: "speed", type: "range", min: 0, max: 2, step: 0.02 },
      { key: "scale", type: "range", min: 0.2, max: 4, step: 0.05 },
      { key: "frequency", type: "range", min: 0.2, max: 4, step: 0.05 },
      { key: "warpStrength", type: "range", min: 0, max: 2, step: 0.05 },
      { key: "noise", type: "range", min: 0, max: 0.5, step: 0.01 },
      { key: "iterations", type: "int", min: 1, max: 5 },
      { key: "intensity", type: "range", min: 0, max: 3, step: 0.05 },
      { key: "bandWidth", type: "range", min: 1, max: 16, step: 0.5 },
      { key: "parallax", type: "range", min: 0, max: 2, step: 0.05 },
      { key: "mouseInfluence", type: "range", min: 0, max: 2, step: 0.05 },
    ],
  },
  darkveil: {
    label: "Dark Veil",
    Component: DarkVeil,
    defaults: {
      hueShift: 0, noiseIntensity: 0.03, scanlineIntensity: 0, speed: 0.6,
      scanlineFrequency: 0, warpAmount: 1, resolutionScale: 1,
    },
    controls: [
      { key: "hueShift", type: "range", min: 0, max: 360, step: 1 },
      { key: "speed", type: "range", min: 0, max: 3, step: 0.05 },
      { key: "warpAmount", type: "range", min: 0, max: 5, step: 0.05 },
      { key: "noiseIntensity", type: "range", min: 0, max: 0.3, step: 0.01 },
      { key: "scanlineIntensity", type: "range", min: 0, max: 1, step: 0.02 },
      { key: "scanlineFrequency", type: "range", min: 0, max: 5, step: 0.05 },
      { key: "resolutionScale", type: "range", min: 0.3, max: 2, step: 0.05 },
    ],
  },
  dither: {
    label: "Dither",
    Component: Dither,
    defaults: {
      waveSpeed: 0.05, waveFrequency: 3, waveAmplitude: 0.3,
      waveColor: [0.5, 0.4, 0.9], colorNum: 4, pixelSize: 2,
      disableAnimation: false, enableMouseInteraction: false, mouseRadius: 1,
    },
    controls: [
      { key: "waveColor", type: "floatColor" },
      { key: "waveSpeed", type: "range", min: 0, max: 0.3, step: 0.005 },
      { key: "waveFrequency", type: "range", min: 0, max: 10, step: 0.1 },
      { key: "waveAmplitude", type: "range", min: 0, max: 1, step: 0.01 },
      { key: "colorNum", type: "int", min: 2, max: 16 },
      { key: "pixelSize", type: "int", min: 1, max: 16 },
      { key: "mouseRadius", type: "range", min: 0, max: 3, step: 0.05 },
      { key: "disableAnimation", type: "bool" },
      { key: "enableMouseInteraction", type: "bool" },
    ],
  },
};
