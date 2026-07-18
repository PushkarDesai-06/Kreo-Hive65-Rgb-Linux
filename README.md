# Kreo Hive 65 - RGB Control for Linux (with an audio visualizer!)

Control your Kreo Hive 65 keyboard's RGB from Linux, no Windows software
needed. Set any color per key, paint gradients, and run an audio-reactive
mode that turns the whole board into a live soundwave for whatever your PC
happens to be playing. And when the sound stops, it quietly drifts into an
ambient gradient on its own.

It works with the wired 65% keyboard that shows up on USB as `258a:010c`
"BY Tech Gaming Keyboard" (that's the Kreo Hive 65)

## What you need

- Any modern Linux (Arch, Ubuntu, Fedora, Mint, take your pick) with
  PipeWire or PulseAudio. Every mainstream distro from the last few years
  ships one of them.
- Python 3, which is already there on most distros. No pip packages to
  install.
- The keyboard plugged in with its USB cable, in wired mode. Bluetooth and
  the 2.4 GHz dongle won't cut it, since the RGB channel only exists over
  the cable.

## Setup (one time, about 2 minutes)

**1. Grab the files.** Drop `keyboardrgb.py` and `60-keyboardrgb.rules` into
a folder, say `~/kbd-re`, and open a terminal there.

**2. Give yourself permission to talk to the keyboard.** Out of the box
Linux only lets root touch the keyboard's control channel. This installs a
rule that basically says "whoever is sitting at this computer may control
this specific keyboard". It's scoped to this one device and trivial to undo
later (just delete the file):

```bash
sudo cp 60-keyboardrgb.rules /etc/udev/rules.d/
sudo udevadm control --reload
```

Now unplug the keyboard's USB cable and plug it back in so the rule takes
effect.

> The `60-` at the front of the filename actually matters. udev applies the
> access tag in a step numbered 73, so the rule has to sort before it. Don't
> rename it to something like `99-whatever`, or it'll silently do nothing.

**3. Try it out:**

```bash
python3 keyboardrgb.py color ff0000     # whole board red (Ctrl-C to stop)
python3 keyboardrgb.py rainbow          # rainbow across the keys
python3 keyboardrgb.py off              # everything off
```

If the board turned red, you're done. If you got `Permission denied`, jump
to Troubleshooting below.

> Heads up: `color`, `rainbow`, `gradient`, `key`, and `wave` keep running
> and hold their colors until you press Ctrl-C. That's deliberate. The
> keyboard snaps back to its own built-in lighting the moment the program
> stops, so the tool has to stay alive to hold your colors in place. If
> you'd rather set a color and have the command exit right away (from a
> startup script, say), add `--once`:
> `python3 keyboardrgb.py color ff0000 --once`.

## Audio-reactive mode


https://github.com/user-attachments/assets/8e475d93-be6e-4a3d-a416-4831388860dd

The order of effect is wave -> bars -> wave

```bash
python3 keyboardrgb.py audio
```

That's the whole thing. Play some music and the keyboard becomes a
16-column spectrum wave: bass on the left, treble on the right, rippling out
from the middle row. It grabs whatever your system is outputting (Spotify,
YouTube, games, anything at all), no matter whether it's headed to speakers
or headphones. Press Ctrl-C to stop.

### Effects (`--effect`)

Pick the visual style you want. They all react to your audio in real time:

| Effect             | Looks like                                                                                 | Reacts to                                                                                                                                                                 |
| ------------------ | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `wave` _(default)_ | a spectrum that swells out from the home row                                               | each column is one frequency band                                                                                                                                         |
| `bars`             | a classic equalizer — grows bottom-up by default; `--direction` picks the edge it grows from | column (or row) height tracks band loudness                                                                                                                             |
| `split`            | bass glowing in from the left edge and treble from the right, fading to dark in the middle  | the left half brightens with bass, the right half with treble, so beats push in from the sides                                                                            |
| `flow`             | a bass "waterfall" — the left column tracks the bass and each punch then travels across to the right     | only the leftmost column samples the bass; that reading scrolls rightward every frame, so a beat enters at the left and glides to the right edge (speed set by `--flow-speed`) |
| `vortex`           | a black hole, with a dark void in the middle and a color accretion ring swirling around it | the colors spin faster the louder it gets, each frequency lights its own slice of the ring, and bass swells the hole and shoves the ring outward so beats give it a pulse |
| `ripple`           | concentric rings breathing out from the middle                                             | bass hits push the rings outward, and overall loudness sets the brightness                                                                                                |

```bash
python3 keyboardrgb.py audio --effect vortex
python3 keyboardrgb.py audio --effect ripple
python3 keyboardrgb.py audio --effect bars
python3 keyboardrgb.py audio --effect split
python3 keyboardrgb.py audio --effect flow
```

#### Bar direction (`--direction`)

`bars` grows bottom-up by default. `--direction` (only meaningful for `bars`)
changes which edge the bars grow from. `bottom`/`top` are vertical (one band per
column); `left`/`right`/`sides` are horizontal (one band per row).

| `--direction`      | The equalizer bars…                                    |
| ------------------ | ------------------------------------------------------ |
| `bottom` _(def.)_  | grow up from the bottom row                            |
| `top`              | hang down from the top row                             |
| `left`             | grow rightward from the left edge                      |
| `right`            | grow leftward from the right edge                      |
| `sides`            | grow inward from both edges and meet in the middle     |

```bash
python3 keyboardrgb.py audio --effect bars --direction top
python3 keyboardrgb.py audio --effect bars --direction sides
python3 keyboardrgb.py audio --effect bars --direction left --gain 1.5
```

### Make it yours

These knobs work with every effect:

| Option                         | What it does                                                                                                                                 | Default |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `--mode colorful`              | a 4-color gradient (red, violet, cyan, amber) scrolling across the board                                                                     | default |
| `--mode single --color ff2000` | just one color of your choosing                                                                                                              |         |
| `--gain 1.5`                   | amplitude multiplier. Bigger number, wilder reaction. Try somewhere in `0.5` to `3`                                                          | `1.0`   |
| `--smooth 2`                   | smoothness multiplier. Bigger is silkier and slower, smaller is twitchy and snappy. Try `0.5` to `3`                                         | `1.0`   |
| `--scroll 0.3`                 | how fast the gradient drifts across the keys, in cycles per second. `0` freezes it in place (`vortex` ignores this one, it spins on its own) | `0.15`  |
| `--radius 0.45`                | `vortex` only: size of the dark hole in the middle, from `0` to `1`. Bigger means a wider void and the ring pushed further out               | `0.18`  |
| `--flow-speed 5`               | `flow` only: how fast a bass punch travels left-to-right, in columns per second. Lower is a slower, more visible sweep                        | `8.0`   |
| `--fps 60`                     | frames per second. The default 30 looks smooth and stays light on the CPU; push it up toward 60 (the board's ceiling) for silkier motion     | `30`    |

> About the default palette: it's `#FF4242`, `#7C3AED`, `#06B6D4` and
> `#EAB308`, a soft red, violet, cyan and amber. They're deliberately more
> pastel than the harsh, full-saturation RGB the keyboard blasts on its own.
> Easier on the eyes, and honestly just nicer to look at. Miss the loud
> stuff? `--mode single --color <hex>` or the standalone `rainbow` command
> still hand you full-saturation colors.

A few examples:

```bash
python3 keyboardrgb.py audio --effect vortex --radius 0.4         # black hole, wider void
python3 keyboardrgb.py audio --effect ripple --mode single --color 00ffcc
python3 keyboardrgb.py audio --mode single --color 00ffcc --smooth 2
python3 keyboardrgb.py audio --effect bars --gain 1.5 --smooth 0.6
```

Volume doesn't matter, by the way. The visualizer auto-levels to the music's
own dynamics, and `--gain` scales on top of that.

> `--shape` was the old name for `--effect` and it still works, so any older
> commands you've got lying around keep running fine.

### When the music stops (`--default`)

You can leave the visualizer running all day and it won't just sit on a dead
black board during the quiet stretches. After 3 seconds of silence it
smoothly crossfades into an ambient, non-audio effect, and the instant sound
comes back it fades right back to reacting. Both transitions are gentle, no
jarring cuts.

| Option                 | What it does                                                                                                                                                                   | Default    |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------- |
| `--default gradient`   | the idle effect: `gradient` (the scrolling 4-color gradient), `breathe` (the whole board drifting through the palette), `wave` (a rolling brightness wave), or `off` (go dark) | `gradient` |
| `--idle-gap 3`         | seconds of silence before it switches over                                                                                                                                     | `3`        |
| `--silence-level 0.01` | how quiet counts as "silence". Raise it if a noisy line keeps it awake, lower it if quiet passages trip it                                                                     | `0.004`    |

```bash
python3 keyboardrgb.py audio --default breathe            # breathe softly when idle
python3 keyboardrgb.py audio --default off --idle-gap 2   # just go dark after 2s of quiet
```

### Other commands

```bash
python3 keyboardrgb.py key w ff0000 a ff0000 s ff0000 d ff0000   # light up WASD
python3 keyboardrgb.py gradient ff00ff 00ffff                    # left to right gradient
python3 keyboardrgb.py wave                                      # rainbow animation, forever
python3 keyboardrgb.py wave 30                                   # ...or just 30 seconds
```

All of these hold until Ctrl-C (add `--once` to set one frame and exit).
`wave` runs forever unless you hand it a number of seconds.

Key names: letters and digits as printed, plus `esc tab capslock lshift
rshift lctrl rctrl lwin lalt ralt fn space enter backspace del home pgup
pgdn up down left right minus equal lbracket rbracket backslash semicolon
quote comma period slash`.

## Fun commands to try

Copy-paste any of these. Press Ctrl-C to stop.

### Audio-reactive (put some music on first)

```bash
# the black hole, wide dark void, extra punchy
python3 keyboardrgb.py audio --effect vortex --radius 0.4 --gain 1.5

# neon black hole, hot-pink ring, single color instead of the gradient
python3 keyboardrgb.py audio --effect vortex --mode single --color ff0055

# bass ripples breathing out from the center
python3 keyboardrgb.py audio --effect ripple --gain 1.4 --smooth 1.5

# aggressive twitchy equalizer, snaps hard on every beat
python3 keyboardrgb.py audio --effect bars --smooth 0.5 --gain 2

# dreamy chill wave, slow, silky, barely-drifting colors
python3 keyboardrgb.py audio --effect wave --smooth 2.5 --scroll 0.05

# rave mode, fast gradient ripping across the keys
python3 keyboardrgb.py audio --scroll 0.6 --gain 1.5

# cyberpunk cyan rings
python3 keyboardrgb.py audio --effect ripple --mode single --color 00ffcc

# leave it on all day: reacts to music, breathes the gradient when it's quiet
python3 keyboardrgb.py audio --default breathe

# party then chill: punchy bars that melt into a slow gradient after 3s of quiet
python3 keyboardrgb.py audio --effect bars --gain 1.8 --default gradient --idle-gap 3
```

### Ambient (no music needed)

```bash
python3 keyboardrgb.py wave                     # endless flowing rainbow
python3 keyboardrgb.py gradient ff6a00 8a2be2   # sunset: orange to purple
python3 keyboardrgb.py gradient 001b8a 00ffd5   # deep ocean: navy to aqua
python3 keyboardrgb.py color 00ffaa             # solid neon mint
python3 keyboardrgb.py key w ff2200 a ff2200 s ff2200 d ff2200   # gamer WASD
```

### The three knobs worth playing with

- `--gain` is intensity. `0.5` is subtle, `2` and up gets wild.
- `--smooth` is personality. Low (`0.4`) is twitchy and snappy; high (`2.5`)
  is liquid and dreamy.
- `--scroll` is how fast the gradient drifts. `0` freezes it, `0.6` is a
  full-on rave.

Mix them however you like with any `--effect` (`wave`, `bars`, `split`, `flow`,
`vortex`, `ripple`) and `--mode single --color <hex>`. Start with the vortex;
on a bass-heavy track it looks the best.

## Web UI (optional)

There's also a little browser app under `client/`. Its real job is piping
shader and canvas effects to the keyboard: it runs GPU shader components
(React Bits backgrounds like Strands, Color Bends, Dark Veil, plus a
built-in gradient lab), grabs each rendered frame off the `<canvas>`,
downscales it to the 16x5 board, and streams it over a local WebSocket. The
CLI above is all you need day to day; this is just for driving the board
from arbitrary visuals. More on it in [client/README.md](client/README.md).

## Troubleshooting

`Permission denied: /dev/hidrawX` means the udev rule isn't active. Check
that `/etc/udev/rules.d/60-keyboardrgb.rules` exists (with the `60-` name!),
run `sudo udevadm control --reload`, then unplug and replug the keyboard.

`keyboard vendor interface not found` means the keyboard isn't connected by
USB cable, or it's in wireless mode. Flip it to wired. You can confirm Linux
sees it with `lsusb | grep 258a` (or
`grep -r 258a /sys/bus/usb/devices/*/idVendor`).

Audio mode runs but nothing moves? Sound is probably going to a different
output than the one being monitored. List your outputs with `pactl list
short sources` and pick the `.monitor` of the device you're actually
listening on:

```bash
python3 keyboardrgb.py audio --source alsa_output.pci-0000_00_1f.3.analog-stereo.monitor
```

My colors vanished and the keyboard went back to its own lighting? The
program stopped. These modes only persist while the tool is running, because
the keyboard reasserts its built-in lighting the instant streaming stops.
Keep the command running (it holds until Ctrl-C), or add it to your startup
so it relaunches. To go back to the board's own effects on purpose, just
stop the tool or hit your Fn lighting hotkey.

It says "keyboard dropped off the bus, reconnecting..."? The board's
firmware reset and re-enumerated. The tool waits for it to come back (about
a second) and carries on, so it's harmless. Usually the cause is two
programs driving the keyboard at once (another `keyboardrgb.py` still running
in a different terminal, for instance), so make sure only one is streaming.
It can also just happen now and then on its own during long sessions.

## Notes

- Your Fn-key lighting shortcuts still work and will override streamed
  colors; just rerun the tool to take control back.
- Everything runs in userspace over standard HID. No kernel modules, no
  firmware flashing, nothing persistent written to the keyboard.
- Curious how it works? The wire protocol was reverse-engineered from HID
  captures, and the full write-up is in [PROTOCOL.md](PROTOCOL.md). Short
  version: one 520-byte USB "feature report" per frame carries an RGB
  triplet for every key, and the audio mode adds a pure-Python FFT that
  folds system audio into 16 frequency bands, one per keyboard column.
- Don't use `keyboardrgb.py raw` to experiment with report `0x05` unless you
  really know what you're doing. That's the door to the chip's firmware
  bootloader on this hardware family, and the wrong bytes could soft-brick
  the board.
