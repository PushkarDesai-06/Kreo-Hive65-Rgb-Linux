#!/usr/bin/env python3
"""Effect parameter schema shared by the CLI and the GUI.

Each effect declares its options once as a tuple of `Param`s inside an
`EffectSpec`. The CLI builds its argparse parser from the spec (same flags,
dests, defaults and help text as the hand-written parsers it replaced), and the
GUI builds its controls from the same spec using the label/tooltip/range
fields. `to_argv` turns a GUI value dict back into a CLI command line, so the
background runner and exported scripts run exactly what the preview showed.
"""
import argparse
import re
from dataclasses import dataclass, field

_HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")


@dataclass(frozen=True, eq=False)
class Param:
    name: str                   # argparse dest and value-dict key
    kind: str                   # float | int | bool | color | colors | choice | text
    default: object = None
    flags: tuple = ()           # CLI option strings; () = not on the CLI
    help: str = None            # argparse help, verbatim
    argtype: object = None      # argparse type= (float / int)
    choices: tuple = ()         # allowed values
    labels: tuple = ()          # GUI label per choice, same order
    action: str = None          # "store_true"
    neg_flags: tuple = ()       # store_false twin, e.g. ("--no-follow",)
    neg_help: str = None
    positional: bool = False    # bare CLI argument (color / gradient)
    nargs: str = None
    # --- GUI only ---
    label: str = ""
    tooltip: str = ""
    min: float = None
    max: float = None
    step: float = None
    decimals: int = None
    unit: str = ""
    group: str = "Appearance"   # Appearance | Motion | Audio | Typing | Advanced
    show_if: dict = field(default_factory=dict)  # {param: (values...)}, all must hold
    gui: bool = True
    live: bool = True           # False -> changing it rebuilds the effect
    source: str = None          # dynamic choices: audio_sources | monitors | inputs
    count_from: str = None      # colors: list length follows this param
    auto_label: str = "Automatic"  # text params: what None means

    def coerce(self, v):
        """Bring a stored/GUI value into this param's domain; None if invalid."""
        if v is None:
            return None
        try:
            if self.kind == "bool":
                return bool(v)
            if self.kind == "float":
                v = float(v)
            elif self.kind == "int":
                v = int(round(float(v)))
            elif self.kind == "choice":
                if self.argtype is not None:
                    v = self.argtype(v)
                return v if v in self.choices else None
            elif self.kind == "color":
                v = str(v)
                return v.lstrip("#").lower() if _HEX.match(v) else None
            elif self.kind == "colors":
                parts = [p.strip() for p in str(v).split(",") if p.strip()]
                if not parts or not all(_HEX.match(p) for p in parts):
                    return None
                return ",".join(p.lstrip("#").lower() for p in parts)
            else:
                return str(v) or None
        except (TypeError, ValueError):
            return None
        if self.min is not None:
            v = max(self.min, v)
        if self.max is not None:
            v = min(self.max, v)
        return v


def _fmt(v):
    if isinstance(v, float):
        s = format(v, "g")
        return s if float(s) == v else repr(v)
    return str(v)


class EffectSpec:
    """An effect's CLI name, parser metadata and ordered params."""

    def __init__(self, cli_name, params, prog=None, description=None):
        self.cli_name = cli_name
        self.prog = prog or f"keyboardrgb.py {cli_name}"
        self.description = description
        self.params = tuple(params)
        self.by_name = {p.name: p for p in self.params}

    def build_parser(self):
        p = argparse.ArgumentParser(prog=self.prog, description=self.description)
        for prm in self.params:
            kw = {}
            if prm.help is not None:
                kw["help"] = prm.help
            if prm.positional:
                if prm.argtype is not None:
                    kw["type"] = prm.argtype
                if prm.nargs is not None:
                    kw["nargs"] = prm.nargs
                    kw["default"] = prm.default
                p.add_argument(prm.name, **kw)
                continue
            if not prm.flags:
                continue
            kw["dest"] = prm.name
            kw["default"] = prm.default
            if prm.action:
                kw["action"] = prm.action
            else:
                if prm.argtype is not None:
                    kw["type"] = prm.argtype
                if prm.choices:
                    kw["choices"] = list(prm.choices)
            p.add_argument(*prm.flags, **kw)
            if prm.neg_flags:
                nkw = {"dest": prm.name, "action": "store_false"}
                if prm.neg_help is not None:
                    nkw["help"] = prm.neg_help
                p.add_argument(*prm.neg_flags, **nkw)
        return p

    def parse(self, argv):
        return self.build_parser().parse_args(argv)

    def defaults(self):
        return {p.name: p.default for p in self.params}

    def validate(self, values):
        """Defaults for anything missing or invalid; unknown keys dropped."""
        out = {}
        for prm in self.params:
            if prm.name in values:
                v = prm.coerce(values[prm.name])
                if v is None and values[prm.name] is not None:
                    v = prm.default
                out[prm.name] = v
            else:
                out[prm.name] = prm.default
        return out

    def namespace(self, values):
        return argparse.Namespace(**self.validate(values))

    def to_argv(self, values, force=()):
        """CLI arguments reproducing `values`; params equal to their default are
        omitted unless named in `force`."""
        pos, opts = [], []
        for prm in self.params:
            v = values.get(prm.name, prm.default)
            if prm.positional:
                if v is not None and (prm.nargs is None or v != prm.default
                                      or prm.name in force):
                    pos.append(_fmt(v))
                continue
            if not prm.flags:
                continue
            if v == prm.default and prm.name not in force:
                continue
            if prm.action == "store_true":
                if v:
                    opts.append(prm.flags[0])
                elif prm.neg_flags:
                    opts.append(prm.neg_flags[0])
                continue
            if v is None:
                continue
            opts += [prm.flags[0], _fmt(v)]
        return pos + opts

    def visible(self, prm, values):
        """Whether a param's control should show for the current values."""
        for dep, allowed in prm.show_if.items():
            if values.get(dep, self.by_name[dep].default) not in allowed:
                return False
        return True
