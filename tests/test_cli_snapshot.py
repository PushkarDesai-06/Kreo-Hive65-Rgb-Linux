#!/usr/bin/env python3
"""CLI-surface gate: every subcommand's argparse parser (flags, dests, defaults,
types, choices, help text) and the top-level usage text must stay identical
across refactors, so generating parsers from the param schema changes nothing
for existing scripts and keybinds.

    ./tests/test_cli_snapshot.py --save          # snapshot the current CLI
    python3 -m unittest tests.test_cli_snapshot  # assert it is unchanged
"""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SNAPSHOT = os.path.join(HERE, "cli_snapshot.json")
SUBCOMMANDS = ("wave", "flux", "audio", "screen", "reactive", "walk")

# runs in a child so the golden harness's monkeypatches never leak into tests
_PROBE = r"""
import argparse, json, os, sys
sys.path.insert(0, %(here)r)
sys.path.insert(0, %(root)r)
import verify_golden
verify_golden.install()
import keyboardrgb

class _Got(Exception):
    pass

def _type_name(t):
    return None if t is None else getattr(t, "__name__", repr(t))

def _capture(self, args=None, namespace=None):
    acts = []
    for a in self._actions:
        if isinstance(a, argparse._HelpAction):
            continue
        acts.append({
            "options": list(a.option_strings), "dest": a.dest,
            "default": a.default, "type": _type_name(a.type),
            "choices": list(a.choices) if a.choices is not None else None,
            "action": type(a).__name__, "help": a.help, "nargs": a.nargs,
        })
    raise _Got({"prog": self.prog, "help": self.format_help(), "actions": acts})

argparse.ArgumentParser.parse_args = _capture
out = {"usage": keyboardrgb.__doc__}
for cmd in %(cmds)r:
    sys.argv = ["keyboardrgb.py", cmd]
    sys.stdout = open(os.devnull, "w")
    try:
        keyboardrgb.main()
    except _Got as g:
        out[cmd] = g.args[0]
    finally:
        sys.stdout = sys.__stdout__
print(json.dumps(out, sort_keys=True))
"""


def probe():
    env = dict(os.environ, COLUMNS="100", PYTHONHASHSEED="0")
    src = _PROBE % {"here": HERE, "root": ROOT, "cmds": SUBCOMMANDS}
    out = subprocess.check_output([sys.executable, "-c", src], env=env, text=True)
    return json.loads(out)


class TestCliSnapshot(unittest.TestCase):
    def test_cli_unchanged(self):
        with open(SNAPSHOT) as f:
            base = json.load(f)
        cur = probe()
        self.assertEqual(sorted(base), sorted(cur))
        for key in base:
            with self.subTest(cmd=key):
                self.assertEqual(base[key], cur[key])


if __name__ == "__main__":
    if "--save" in sys.argv:
        with open(SNAPSHOT, "w") as f:
            json.dump(probe(), f, indent=1, sort_keys=True)
            f.write("\n")
        print(f"saved {SNAPSHOT}")
    else:
        unittest.main()
