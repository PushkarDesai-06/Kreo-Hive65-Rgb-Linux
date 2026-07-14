#!/usr/bin/env python3
"""Color helpers: hex parsing, HSV, and the palette used by 'colorful' effects."""


def parse_hex(s):
    s = s.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def hsv(h, s=1.0, v=1.0):
    i = int(h * 6) % 6
    f = h * 6 - int(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return int(r * 255), int(g * 255), int(b * 255)


# "colorful" mode palette — the Gradient Lab default (red / violet / cyan / amber)
COLORFUL_PALETTE = [
    (0xFF, 0x42, 0x42),
    (0x7C, 0x3A, 0xED),
    (0x06, 0xB6, 0xD4),
    (0xEA, 0xB3, 0x08),
]


def palette_at(u, v=1.0, palette=COLORFUL_PALETTE):
    """Sample a looping gradient of `palette` at position u (wraps), scaled by
    brightness v. Mirrors the web Gradient Lab's palAt so colorful mode matches."""
    n = len(palette)
    x = ((u % 1.0) + 1.0) % 1.0 * n
    i = int(x) % n
    f = x - int(x)
    a, b = palette[i], palette[(i + 1) % n]
    return tuple(int((a[c] + (b[c] - a[c]) * f) * v) for c in range(3))
