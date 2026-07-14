# 🎹 Kreo Hive 65 — RGB Control for Linux (with Audio Visualizer!)

Control your Kreo Hive 65 keyboard's RGB from Linux — no Windows software
needed. Set any color per key, paint gradients, and run an **audio-reactive
mode** that turns the keyboard into a live soundwave for whatever your PC is
playing — and when the sound stops, it drifts into an ambient gradient on
its own.

Works with the wired 65% keyboard that shows up on USB as `258a:010c`
"BY Tech Gaming Keyboard" (the Kreo Hive 65 — and rebrands of the same
board, like the Portronics Hydra 10).

## What you need

- Any modern Linux (Arch, Ubuntu, Fedora, Mint...) with PipeWire or
  PulseAudio — every mainstream distro from the last few years has this.
- Python 3 (preinstalled on most distros). **No pip packages needed.**
- The keyboard plugged in with its **USB cable, in wired mode**. Bluetooth
  and the 2.4 GHz dongle won't work — the RGB channel only exists over the
  cable.

## Setup (one time, ~2 minutes)

**1. Get the files.** Put `keyboardrgb.py` and `60-keyboardrgb.rules` in a
folder, e.g. `~/kbd-re`, and open a terminal there.

**2. Give yourself permission to talk to the keyboard.** Out of the box,
Linux only lets root talk to the keyboard's control channel. This installs
a rule that says "whoever is sitting at this computer may control this
specific keyboard" — it's scoped to this one device and easy to undo
(just delete the file):

```bash
sudo cp 60-keyboardrgb.rules /etc/udev/rules.d/
sudo udevadm control --reload
```

Now **unplug the keyboard's USB cable and plug it back in** so the rule
takes effect.

> The `60-` in the filename matters — udev applies the access tag in a
> step numbered 73, so the rule must sort before it. Don't rename it to
> `99-something`, it will silently do nothing.

**3. Try it:**

```bash
python3 keyboardrgb.py color ff0000     # whole board red (Ctrl-C to stop)
python3 keyboardrgb.py rainbow          # rainbow across the keys
python3 keyboardrgb.py off              # everything off
```

If the board turned red, you're done. If you got `Permission denied`, see
Troubleshooting below.

> **Heads up:** `color`, `rainbow`, `gradient`, `key`, and `wave` keep
> running and hold their colors until you press **Ctrl-C**. That's on
> purpose — the keyboard snaps back to its own built-in lighting the moment
> the program stops, so the tool stays alive to hold your colors in place.
> If you'd rather set a color and have the command exit right away (e.g.
> from a startup script), add `--once`: `python3 keyboardrgb.py color ff0000
> --once`.

## 🎵 Audio-reactive mode

```bash
python3 keyboardrgb.py audio
```

That's it — play some music. The keyboard becomes a 16-column spectrum
wave: bass on the left, treble on the right, rippling out from the middle
row. It captures whatever your system is outputting (Spotify, YouTube,
games — anything), regardless of whether it's going to speakers or
headphones. Press **Ctrl-C** to stop.

### Effects (`--effect`)

Pick the visual style. All four react to your audio in real time:

| Effect | Looks like | Reacts to |
|---|---|---|
| `wave` *(default)* | a spectrum that swells out from the home row | each column = one frequency band |
| `bars` | a classic bottom-up equalizer | column height = band loudness |
| `vortex` | a **black hole** — dark void in the middle with a color accretion ring swirling around it | the colors **spin faster the louder it gets**; each frequency lights its own slice of the ring; **bass swells the hole and shoves the ring outward** so beats pulse it |
| `ripple` | concentric rings breathing out from the middle | bass hits push the rings outward; overall loudness sets the brightness |

```bash
python3 keyboardrgb.py audio --effect vortex
python3 keyboardrgb.py audio --effect ripple
python3 keyboardrgb.py audio --effect bars
```

### Make it yours

These knobs work with every effect:

| Option | What it does | Default |
|---|---|---|
| `--mode colorful` | a 4-color gradient (red → violet → cyan → amber) scrolling across the board | ✔ default |
| `--mode single --color ff2000` | one color of your choice | |
| `--gain 1.5` | amplitude multiplier — bigger number = wilder reaction. Try `0.5`–`3` | `1.0` |
| `--smooth 2` | smoothness multiplier — bigger = silkier, slower motion; smaller = twitchy and snappy. Try `0.5`–`3` | `1.0` |
| `--scroll 0.3` | how fast the gradient drifts across the keys, in cycles per second. `0` freezes it in place (`vortex` ignores this — it spins on its own) | `0.15` |
| `--radius 0.45` | **`vortex` only** — size of the dark hole in the middle (`0`–`1`). Bigger = wider void, ring pushed further out | `0.18` |
| `--fps 60` | frames per second. Default 30 looks smooth and is light on CPU; raise it up to ~60 (the board's ceiling) for silkier motion | `30` |

> **The default palette** is `#FF4242` · `#7C3AED` · `#06B6D4` · `#EAB308`
> — a soft red, violet, cyan and amber. They're deliberately more **pastel**
> than the harsh, full-saturation RGB the keyboard blasts on its own; the
> result is easier on the eyes and just looks nicer. (Prefer the loud stuff?
> `--mode single --color <hex>` or the standalone `rainbow` command still give
> you full-saturation colors.)

Examples:

```bash
python3 keyboardrgb.py audio --effect vortex --radius 0.4         # black hole, wider void
python3 keyboardrgb.py audio --effect ripple --mode single --color 00ffcc
python3 keyboardrgb.py audio --mode single --color 00ffcc --smooth 2
python3 keyboardrgb.py audio --effect bars --gain 1.5 --smooth 0.6
```

Volume doesn't matter — the visualizer auto-levels to the music's own
dynamics, and `--gain` scales on top of that.

> `--shape` is the old name for `--effect` and still works, so any older
> commands you have keep running.

### When the music stops (`--default`)

Leave the visualizer running all day and it won't sit on a dead black board
during quiet moments. After **5 seconds** of silence it smoothly crossfades
into an ambient, non-audio effect; the instant sound returns it fades right
back to reacting. Both transitions are gentle — no jarring cuts.

| Option | What it does | Default |
|---|---|---|
| `--default gradient` | the idle effect: `gradient` (the scrolling 4-color gradient), `breathe` (whole board drifting through the palette), `wave` (a rolling brightness wave), or `off` (go dark) | `gradient` |
| `--idle-gap 3` | seconds of silence before it switches over | `5` |
| `--silence-level 0.01` | how quiet counts as "silence" — raise it if a noisy line keeps it awake, lower it if quiet passages trip it | `0.004` |

```bash
python3 keyboardrgb.py audio --default breathe            # breathe softly when idle
python3 keyboardrgb.py audio --default off --idle-gap 2   # just go dark after 2s of quiet
```

### Other commands

```bash
python3 keyboardrgb.py key w ff0000 a ff0000 s ff0000 d ff0000   # light up WASD
python3 keyboardrgb.py gradient ff00ff 00ffff                    # left→right gradient
python3 keyboardrgb.py wave                                      # rainbow animation, forever
python3 keyboardrgb.py wave 30                                   # ...or just 30 seconds
```

All of these hold until **Ctrl-C** (add `--once` to set one frame and exit).
`wave` runs forever unless you give it a number of seconds.

Key names: letters/digits as printed, plus `esc tab capslock lshift rshift
lctrl rctrl lwin lalt ralt fn space enter backspace del home pgup pgdn up
down left right minus equal lbracket rbracket backslash semicolon quote
comma period slash`.

## ✨ Fun commands to try

Copy-paste any of these. Press **Ctrl-C** to stop.

### 🎵 Audio-reactive (put some music on first)

```bash
# ⭐ the black hole — wide dark void, extra punchy
python3 keyboardrgb.py audio --effect vortex --radius 0.4 --gain 1.5

# neon black hole — hot-pink ring, single color instead of the gradient
python3 keyboardrgb.py audio --effect vortex --mode single --color ff0055

# bass ripples breathing out from the center
python3 keyboardrgb.py audio --effect ripple --gain 1.4 --smooth 1.5

# aggressive twitchy equalizer — snaps hard on every beat
python3 keyboardrgb.py audio --effect bars --smooth 0.5 --gain 2

# dreamy chill wave — slow, silky, barely-drifting colors
python3 keyboardrgb.py audio --effect wave --smooth 2.5 --scroll 0.05

# rave mode — fast gradient ripping across the keys
python3 keyboardrgb.py audio --scroll 0.6 --gain 1.5

# cyberpunk cyan rings
python3 keyboardrgb.py audio --effect ripple --mode single --color 00ffcc

# leave it on all day — reacts to music, breathes the gradient when it's quiet
python3 keyboardrgb.py audio --default breathe

# party then chill — punchy bars that melt into a slow gradient after 3s of quiet
python3 keyboardrgb.py audio --effect bars --gain 1.8 --default gradient --idle-gap 3
```

### 🌈 Ambient (no music needed)

```bash
python3 keyboardrgb.py wave                     # endless flowing rainbow
python3 keyboardrgb.py gradient ff6a00 8a2be2   # sunset: orange → purple
python3 keyboardrgb.py gradient 001b8a 00ffd5   # deep ocean: navy → aqua
python3 keyboardrgb.py color 00ffaa             # solid neon mint
python3 keyboardrgb.py key w ff2200 a ff2200 s ff2200 d ff2200   # gamer WASD
```

### The three knobs to play with

- **`--gain`** = intensity. `0.5` = subtle, `2`+ = wild.
- **`--smooth`** = personality. Low (`0.4`) = twitchy and snappy; high
  (`2.5`) = liquid and dreamy.
- **`--scroll`** = how fast the gradient drifts. `0` freezes it,
  `0.6` is a full-on rave.

Mix them freely with any `--effect` (`wave`/`bars`/`vortex`/`ripple`) and
`--mode single --color <hex>`. Start with the ⭐ vortex — with a bass-heavy
track it looks the best.

## 🖥️ Web UI (optional)

There's also a small browser app under `client/`. Its real purpose is
**piping shader/canvas effects to the keyboard**: it runs GPU shader
components (React Bits backgrounds like Strands, Color Bends, Dark Veil, plus
a built-in gradient lab), grabs each rendered frame off the `<canvas>`,
downscales it to the 16×5 board, and streams it over a local WebSocket. The
CLI above is all you need day to day — this is just for driving the board
from arbitrary visuals. Details in [client/README.md](client/README.md).

## Troubleshooting

**`Permission denied: /dev/hidrawX`** — the udev rule isn't active. Check
that `/etc/udev/rules.d/60-keyboardrgb.rules` exists (with the `60-` name!),
run `sudo udevadm control --reload`, then unplug/replug the keyboard.

**`keyboard vendor interface not found`** — the keyboard isn't connected
by USB cable, or is in wireless mode. Flip it to wired. Verify Linux sees
it: `lsusb | grep 258a` (or `grep -r 258a /sys/bus/usb/devices/*/idVendor`).

**Audio mode runs but nothing moves** — sound is probably going to a
different output than the one being monitored. List your outputs with
`pactl list short sources` and pick the `.monitor` of the device you're
actually listening on:

```bash
python3 keyboardrgb.py audio --source alsa_output.pci-0000_00_1f.3.analog-stereo.monitor
```

**My colors vanished / the keyboard went back to its own lighting** — the
program stopped. These modes only persist while the tool is running,
because the keyboard reasserts its built-in lighting the instant streaming
stops. Keep the command running (it holds until Ctrl-C), or add it to your
startup so it relaunches. To go back to the board's own effects on purpose,
just stop the tool or press your Fn lighting hotkey.

**It says "keyboard dropped off the bus, reconnecting..."** — the board's
firmware reset and re-enumerated; the tool waits for it to come back (~1 s)
and carries on, so it's harmless. The usual cause is **two programs driving
the keyboard at once** (e.g. another `keyboardrgb.py` still running in another
terminal) — make sure only one is streaming. It can also just happen
occasionally on its own during long sessions.

## Notes

- Your Fn-key lighting shortcuts still work and will override streamed
  colors; just rerun the tool to take control back.
- Everything runs in userspace over standard HID — no kernel modules, no
  firmware flashing, nothing persistent is written to the keyboard.
- Curious how it works? The wire protocol was reverse-engineered from HID
  captures — the full write-up is in [PROTOCOL.md](PROTOCOL.md). Short
  version: one 520-byte USB "feature report" per frame carries an RGB
  triplet for every key; the audio mode adds a pure-Python FFT that folds
  system audio into 16 frequency bands, one per keyboard column.
- **Don't** use `keyboardrgb.py raw` to experiment with report `0x05` unless
  you know what you're doing — that's the door to the chip's firmware
  bootloader on this hardware family, and wrong bytes could soft-brick the
  board.
