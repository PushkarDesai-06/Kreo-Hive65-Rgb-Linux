# 🎹 Kreo Hive 65 — RGB Control for Linux (with Audio Visualizer!)

Control your Kreo Hive 65 keyboard's RGB from Linux — no Windows software
needed. Set any color per key, paint gradients, and run an **audio-reactive
mode** that turns the keyboard into a live soundwave for whatever your PC is
playing.

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

**1. Get the files.** Put `hydra_rgb.py` and `60-hydra-rgb.rules` in a
folder, e.g. `~/kbd-re`, and open a terminal there.

**2. Give yourself permission to talk to the keyboard.** Out of the box,
Linux only lets root talk to the keyboard's control channel. This installs
a rule that says "whoever is sitting at this computer may control this
specific keyboard" — it's scoped to this one device and easy to undo
(just delete the file):

```bash
sudo cp 60-hydra-rgb.rules /etc/udev/rules.d/
sudo udevadm control --reload
```

Now **unplug the keyboard's USB cable and plug it back in** so the rule
takes effect.

> The `60-` in the filename matters — udev applies the access tag in a
> step numbered 73, so the rule must sort before it. Don't rename it to
> `99-something`, it will silently do nothing.

**3. Try it:**

```bash
python3 hydra_rgb.py color ff0000     # whole board red
python3 hydra_rgb.py rainbow          # rainbow across the keys
python3 hydra_rgb.py off              # everything off
```

If the board turned red, you're done. If you got `Permission denied`, see
Troubleshooting below.

## 🎵 Audio-reactive mode

```bash
python3 hydra_rgb.py audio
```

That's it — play some music. The keyboard becomes a 16-column spectrum
wave: bass on the left, treble on the right, rippling out from the middle
row. It captures whatever your system is outputting (Spotify, YouTube,
games — anything), regardless of whether it's going to speakers or
headphones. Press **Ctrl-C** to stop.

### Make it yours

| Option | What it does | Default |
|---|---|---|
| `--mode colorful` | rainbow colors across the keyboard | ✔ default |
| `--mode single --color ff2000` | one color of your choice | |
| `--gain 1.5` | wave amplitude multiplier — bigger number = wilder wave. Try `0.5`–`3` | `1.0` |
| `--smooth 2` | smoothness multiplier — bigger = silkier, slower waves; smaller = twitchy and snappy. Try `0.5`–`3` | `1.0` |
| `--scroll 0.3` | how fast the rainbow drifts left-to-right across the keys, in cycles per second. `0` freezes it in place | `0.15` |
| `--shape bars` | bottom-up equalizer bars instead of the center-out wave | `wave` |
| `--fps 60` | frames per second. Default 30 looks smooth and is light on CPU; raise it up to ~60 (the board's ceiling) for silkier motion | `30` |

Examples:

```bash
python3 hydra_rgb.py audio --mode single --color 00ffcc --smooth 2
python3 hydra_rgb.py audio --shape bars --gain 1.5 --smooth 0.6
```

Volume doesn't matter — the visualizer auto-levels to the music's own
dynamics, and `--gain` scales on top of that.

### Other commands

```bash
python3 hydra_rgb.py key w ff0000 a ff0000 s ff0000 d ff0000   # light up WASD
python3 hydra_rgb.py gradient ff00ff 00ffff                    # left→right gradient
python3 hydra_rgb.py wave 30                                   # rainbow animation, 30s
```

Key names: letters/digits as printed, plus `esc tab capslock lshift rshift
lctrl rctrl lwin lalt ralt fn space enter backspace del home pgup pgdn up
down left right minus equal lbracket rbracket backslash semicolon quote
comma period slash`.

## Troubleshooting

**`Permission denied: /dev/hidrawX`** — the udev rule isn't active. Check
that `/etc/udev/rules.d/60-hydra-rgb.rules` exists (with the `60-` name!),
run `sudo udevadm control --reload`, then unplug/replug the keyboard.

**`keyboard vendor interface not found`** — the keyboard isn't connected
by USB cable, or is in wireless mode. Flip it to wired. Verify Linux sees
it: `lsusb | grep 258a` (or `grep -r 258a /sys/bus/usb/devices/*/idVendor`).

**Audio mode runs but nothing moves** — sound is probably going to a
different output than the one being monitored. List your outputs with
`pactl list short sources` and pick the `.monitor` of the device you're
actually listening on:

```bash
python3 hydra_rgb.py audio --source alsa_output.pci-0000_00_1f.3.analog-stereo.monitor
```

**The lights froze / show an old frame** — the visualizer only draws while
it's running; the board holds the last frame forever. Run
`python3 hydra_rgb.py off`, or press your Fn lighting hotkey to hand
control back to the keyboard's built-in effects.

**It says "keyboard dropped off the bus, reconnecting..."** — the board's
firmware reset and re-enumerated; the tool waits for it to come back (~1 s)
and carries on, so it's harmless. The usual cause is **two programs driving
the keyboard at once** (e.g. another `hydra_rgb.py` still running in another
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
- **Don't** use `hydra_rgb.py raw` to experiment with report `0x05` unless
  you know what you're doing — that's the door to the chip's firmware
  bootloader on this hardware family, and wrong bytes could soft-brick the
  board.
