#!/usr/bin/env python3
"""Typed setup errors. SetupError subclasses SystemExit, so the CLI behaves
exactly as before (an uncaught one prints its message and exits 1), while the
GUI can catch it and use `kind` to pick the right banner and fix-it hint."""

# kinds: device | permission | audio | input | screen | deps
KINDS = ("device", "permission", "audio", "input", "screen", "deps")


class SetupError(SystemExit):
    def __init__(self, kind, msg):
        super().__init__(msg)
        self.kind = kind
        self.msg = msg

    def __str__(self):
        return self.msg
