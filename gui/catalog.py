"""The modes shown in the sidebar: friendly names mapped onto the effect specs
the CLI uses, with any sub-effect pinned (e.g. Equalizer Bars = audio with
--effect bars)."""
from dataclasses import dataclass, field

import effects
import reactive

GROUPS = (
    ("static", "Static & Animated"),
    ("music", "Music Visualizer"),
    ("typing", "Typing Effects"),
    ("screen", "Screen Sync"),
)


@dataclass(frozen=True, eq=False)
class Mode:
    id: str
    group: str
    label: str
    icon: str
    description: str
    factory: type
    fixed: dict = field(default_factory=dict)   # params pinned by this mode
    hidden: frozenset = frozenset()            # params with no effect here

    @property
    def spec(self):
        return self.factory.spec

    @property
    def needs(self):
        return self.factory.needs

    def defaults(self):
        return {**self.spec.defaults(), **self.fixed}

    def values(self, stored):
        """Full, validated values for this mode from stored user values."""
        return self.spec.validate({**self.spec.defaults(), **(stored or {}), **self.fixed})

    def user_params(self, values):
        """Params the adjustments panel shows for these values."""
        return [p for p in self.spec.params
                if p.gui and p.name not in self.fixed and p.name not in self.hidden
                and self.spec.visible(p, values)]

    def argv(self, values):
        """CLI arguments (after the global options) that run this mode."""
        return [self.spec.cli_name] + self.spec.to_argv(values, force=tuple(self.fixed))


def _audio(id_, fx, label, icon, desc, hidden=()):
    return Mode(id_, "music", label, icon, desc, effects.AudioVisualizer,
                fixed={"effect": fx}, hidden=frozenset(hidden))


def _typing(fx, label, icon, desc):
    return Mode(f"typing-{fx}", "typing", label, icon, desc, reactive.TypingEffect,
                fixed={"effect": fx})


MODES = (
    Mode("solid", "static", "Solid Color", "solid",
         "Light every key in one color.", effects.SolidColor),
    Mode("gradient", "static", "Gradient", "gradient",
         "A smooth blend between two colors, left to right.", effects.Gradient),
    Mode("rainbow", "static", "Rainbow", "rainbow",
         "A still rainbow spread across the keyboard.", effects.Rainbow),
    Mode("wave", "static", "Rainbow Wave", "wave",
         "A rainbow that rolls continuously across the keys.", effects.RainbowWave),
    Mode("flux", "static", "Color Flux", "flux",
         "Soft color blobs drift around and melt into each other.", effects.Flux),

    _audio("music-wave", "wave", "Spectrum Wave", "music",
           "The music spectrum mirrored around the middle row, like a waveform."),
    _audio("music-bars", "bars", "Equalizer Bars", "bars",
           "Classic equalizer bars that bounce with the music."),
    _audio("music-vortex", "vortex", "Black Hole", "blackhole",
           "A glowing ring spins around a dark center, faster when the music is loud.",
           hidden=("scroll",)),
    _audio("music-ripple", "ripple", "Bass Ripple", "ripple",
           "Rings pulse outward from the center on every bass hit."),
    _audio("music-split", "split", "Bass & Treble", "split",
           "Bass glows in from the left edge and treble from the right."),
    _audio("music-flow", "flow", "Bass Waterfall", "flow",
           "Each bass hit enters on the left and travels across the board."),

    _typing("splash", "Splash", "splash",
            "Each key press lights a bright splash that fades after you let go."),
    _typing("ripple", "Ripple", "radio",
            "A ring of light expands outward from every key you press."),
    _typing("trail", "Typing Trail", "trail",
            "Your typing leaves a colorful trail across the keys."),
    _typing("heatmap", "Heatmap", "flame",
            "The keys you use most glow the hottest."),
    _typing("raindrops", "Raindrops", "drop",
            "Every press drops a random color that blends like paint in water."),
    _typing("sonar", "Sonar", "radar",
            "A thin ping travels outward and bounces off the keyboard edges."),
    _typing("matrix", "Matrix Rain", "matrix",
            "Pressing a key sends digital rain down its column."),
    _typing("crosshair", "Crosshair", "crosshair",
            "Laser beams shoot along the row and column of each press."),
    _typing("sparkle", "Sparkle", "sparkle",
            "Keys around each press twinkle like fairy dust."),
    _typing("erase", "Erase", "eraser",
            "A calm effect runs everywhere and the keys you press go dark."),

    Mode("screen", "screen", "Screen Sync", "monitor",
         "Mirrors your monitor onto the keyboard as ambient lighting.", effects.ScreenSync),
)

BY_ID = {m.id: m for m in MODES}
DEFAULT_MODE = "flux"
