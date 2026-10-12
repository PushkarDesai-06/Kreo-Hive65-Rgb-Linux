# keyboardrgb.py manual

This is the full reference for `keyboardrgb.py`, the command-line tool that
drives the RGB lighting on the Kreo Hive 65 (and the Aula F75) from Linux. The
[README](README.md) is the friendly tour; this manual covers every command and
option so you can look things up.

## Contents

1. [Setup](#1-setup)
2. [How commands work](#2-how-commands-work)
3. [Picking your keyboard](#3-picking-your-keyboard)
4. [Static lighting](#4-static-lighting)
5. [Animated lighting](#5-animated-lighting)
6. [Audio-reactive mode](#6-audio-reactive-mode)
7. [Keypress-reactive mode](#7-keypress-reactive-mode)
8. [Screen sync](#8-screen-sync)
9. [Running it in the background](#9-running-it-in-the-background)
10. [Tools for new keyboards](#10-tools-for-new-keyboards)
11. [Troubleshooting](#11-troubleshooting)

## Quick reference

| Command                        | What it does                                                    |
| ------------------------------ | --------------------------------------------------------------- |
| `color <hex>`                  | whole board one color                                           |
| `key <name> <hex> ...`         | color individual keys, everything else off                      |
| `gradient <hex> <hex>`         | left-to-right blend between two colors                          |
| `rainbow`                      | static rainbow across the columns                               |
| `wave [seconds]`               | animated rainbow rolling across the board                       |
| `flux [options]`               | drifting gradient made of moving color blobs                    |
| `audio [options]`              | music visualizer driven by whatever your PC is playing          |
| `reactive [options]`           | lighting that responds to the keys you press                    |
| `screen [options]`             | mirrors your monitor's colors onto the keys                     |
| `off`                          | all LEDs off                                                    |
| `walk [options]`               | lights one LED at a time, for mapping a new board's layout      |
| `raw <hex...>`                 | sends a raw feature report (experts only, see the warning)      |

Every command starts with `python3 keyboardrgb.py`. Press Ctrl-C to stop
anything that keeps running.

## 1. Setup

You need Linux, Python 3 (no extra packages), and the keyboard plugged in by
USB cable in wired mode. Bluetooth and the 2.4 GHz dongle don't carry the RGB
channel.

Out of the box only root can talk to the keyboard's control interface. Install
the udev rule once to let the logged-in user do it:

```bash
sudo cp 60-keyboardrgb.rules /etc/udev/rules.d/
sudo udevadm control --reload
```

Then unplug the keyboard and plug it back in. Keep the `60-` prefix on the
filename, because udev applies the access tag in step 73 and a later number
silently does nothing.

Check that it works:

```bash
python3 keyboardrgb.py color ff0000
```

Some modes need extra programs:

| Mode       | Needs                                                                 |
| ---------- | --------------------------------------------------------------------- |
| `audio`    | PipeWire or PulseAudio (it records with `parec`)                      |
| `reactive` | read access to the keyboard's `/dev/input/eventN` node (see section 7)  |
| `screen`   | `ffmpeg`, plus `grim` on Wayland                                      |

## 2. How commands work

**Colors** are six-digit hex values without the `#`: `ff0000` is red,
`00ffcc` is aqua, `ffffff` is white.

**The tool has to keep running.** The keyboard falls back to its own built-in
lighting the moment the computer stops streaming frames to it. So `color`,
`key`, `gradient`, `rainbow` and every animated mode stay running and keep
re-sending the frame until you press Ctrl-C. When the program exits, the
board goes back to its onboard effect.

**`--once`** sets a single frame and exits straight away. It works with
`color`, `key`, `gradient` and `rainbow`, and is meant for scripts. Expect
the board to fall back to its onboard lighting shortly after.

```bash
python3 keyboardrgb.py color 00ffaa --once
```

**`--duration SEC`** stops an animated mode after that many seconds. It works
with `flux`, `audio`, `reactive` and `screen`. `wave` takes the number of
seconds as a plain argument instead (`wave 30`).

**`--fps N`** sets the frame rate on animated modes. The board tops out around
60.

**Only one copy at a time.** Two programs streaming to the keyboard at once
fight each other and can make its firmware reset. Stop one before starting
another.

## 3. Picking your keyboard

Each supported board has a profile in `profiles/`. The tool reads the USB id
and picks the matching profile on its own. These options override that, and
they can go anywhere on the command line:

| Option                  | What it does                                                   |
| ----------------------- | -------------------------------------------------------------- |
| `--list-profiles`       | list the known boards and exit                                 |
| `--profile NAME`        | force a profile, for example `--profile aulaf75`                 |
| `--device /dev/hidrawN` | use this hidraw node instead of searching for one              |
| `--vid XXXX --pid XXXX` | also match this USB id (useful for testing a rebranded board)  |

Known profiles:

| Profile   | Board                                   | Status                         |
| --------- | --------------------------------------- | ------------------------------ |
| `hive65`  | Kreo Hive 65 (`258a:010c`), the default | working                        |
| `aulaf75` | Aula F75 (`258a:010c`)                  | working, see below             |
| `hydra10` | Portronics Hydra 10 (`258a:0049`)       | provisional                    |
| `artemis` | Cosmic Byte Artemis (`04d9:a1ce`)       | provisional, does not work yet |

**Aula F75 owners:** the F75 reports the same USB id as the Hive 65, so the
tool can't tell them apart and assumes a Hive 65. Add `--profile aulaf75` to
every command, or make an alias:

```bash
alias kbd='python3 ~/kbd-re/keyboardrgb.py --profile aulaf75'          # bash/zsh
alias kbd 'python3 ~/kbd-re/keyboardrgb.py --profile aulaf75'; funcsave kbd   # fish
```

The first line of output names the board in use, for example
`device: /dev/hidraw1 (BY Tech / Kreo Hive 65 (258a:010c))`.

## 4. Static lighting

### color

```bash
python3 keyboardrgb.py color ff2000
```

Sets every key to one color.

### key

```bash
python3 keyboardrgb.py key w ff0000 a ff0000 s ff0000 d ff0000
```

Takes pairs of key name and color. Keys you don't list are switched off.

Key names on the Hive 65: letters and digits as printed, plus `esc tab
capslock lshift rshift lctrl rctrl lwin lalt ralt fn space enter backspace del
home pgup pgdn up down left right minus equal lbracket rbracket backslash
semicolon quote comma period slash`.

The Aula F75 adds `grave` (the `` ` `` key), `f1` to `f12`, `end` and `knob`,
and has no `home` or `ralt`.

### gradient

```bash
python3 keyboardrgb.py gradient ff6a00 8a2be2
```

Blends from the first color on the left edge to the second on the right.

### rainbow

```bash
python3 keyboardrgb.py rainbow
```

A static, fully saturated rainbow across the columns.

### off

```bash
python3 keyboardrgb.py off
```

Turns every LED off.

## 5. Animated lighting

### wave

```bash
python3 keyboardrgb.py wave        # runs until Ctrl-C
python3 keyboardrgb.py wave 30     # runs for 30 seconds
```

A rainbow that keeps rolling across the board.

### flux

```bash
python3 keyboardrgb.py flux
```

A few blobs of color wander around the board, and every key blends between
them, so the whole surface reads as one smooth gradient that keeps morphing.

| Option                 | What it does                                                                                                  | Default          |
| ---------------------- | ------------------------------------------------------------------------------------------------------------- | ---------------- |
| `--colors 2\|3\|4`     | how many moving color sources                                                                                 | `3`              |
| `--motion walk\|drift` | `walk` wanders randomly and bounces off the edges, different every run; `drift` is silky and repeats exactly  | `walk`           |
| `--hex a,b,c`          | your own source colors, comma separated (e.g. `ff4242,7c3aed,06b6d4`)                                         | built-in palette |
| `--speed FLOAT`        | movement speed multiplier                                                                                     | `1.0`            |
| `--sharp FLOAT`        | blend sharpness; `2` is a soft gradient, higher gives tighter patches around each source                       | `2.0`            |
| `--seed INT`           | `walk` only: start the same wander every time                                                                 | random           |
| `--fps N`              | frame rate                                                                                                    | `60`             |
| `--duration SEC`       | stop after this many seconds                                                                                  | forever          |

```bash
python3 keyboardrgb.py flux --colors 4 --motion drift --speed 0.5
python3 keyboardrgb.py flux --hex ff0055,00ffcc --sharp 4
```

## 6. Audio-reactive mode

```bash
python3 keyboardrgb.py audio
```

Turns the board into a live visualizer for whatever your system is playing
(music, videos, games), whether it goes to speakers or headphones. It
auto-levels to the music, so your volume setting doesn't matter. When the
sound stops it fades into a calm idle effect, and fades back the moment sound
returns.

### Effects

Pick one with `--effect`:

| Effect             | Looks like                                                                                                                  |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| `wave` _(default)_ | a spectrum swelling out from the middle row, bass on the left and treble on the right                                       |
| `bars`             | a classic equalizer; `--direction` picks which edge the bars grow from                                                       |
| `split`            | bass glows in from the left edge and treble from the right, dark in the middle                                              |
| `flow`             | the left column follows the bass and each punch travels across to the right                                                 |
| `vortex`           | a black hole: a dark center ringed by a spinning rainbow that speeds up when it's loud, with bass making the hole pulse      |
| `ripple`           | rings pushed outward from the center by bass hits                                                                           |

`--shape` is an old name for `--effect` and still works.

### Options

| Option                     | What it does                                                                                                      | Default    |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------- | ---------- |
| `--mode colorful\|single`  | `colorful` uses a soft red, violet, cyan and amber gradient; `single` uses one color                              | `colorful` |
| `--color HEX`              | the color for `--mode single`                                                                                     | `009bde`   |
| `--gain FLOAT`             | how strongly it reacts; try `0.5` to `3`                                                                          | `1.0`      |
| `--smooth FLOAT`           | higher is calmer and silkier, lower is twitchier; try `0.5` to `3`                                                | `1.0`      |
| `--scroll FLOAT`           | how fast the gradient drifts across the keys, in cycles per second; `0` freezes it (`vortex` ignores this)        | `0.15`     |
| `--direction NAME`         | `bars` only: `bottom`, `top`, `left`, `right` or `sides` (`left`, `right` and `sides` run one band per row)        | `bottom`   |
| `--radius FLOAT`           | `vortex` only: size of the dark hole, `0` to `1`                                                                  | `0.18`     |
| `--flow-speed FLOAT`       | `flow` only: how fast a bass punch travels, in columns per second                                                 | `8.0`      |
| `--default NAME`           | the idle effect for silence: `gradient`, `breathe`, `wave` or `off`                                               | `gradient` |
| `--idle-gap SEC`           | seconds of silence before switching to the idle effect                                                            | `5.0`      |
| `--silence-level FLOAT`    | how quiet counts as silence; raise it if background noise keeps it awake                                          | `0.004`    |
| `--source NAME`            | which audio source to record; `-` reads raw s16le mono PCM from stdin                                             | default output's monitor |
| `--rate N`                 | sample rate                                                                                                       | `48000`    |
| `--fps N`                  | frame rate                                                                                                        | `30`       |
| `--duration SEC`           | stop after this many seconds                                                                                      | forever    |
| `--debug`                  | print levels and timing once a second                                                                             | off        |

### Darkening pressed keys (`--erase`)

Add `--erase` and any key you press goes dark, along with the keys around it,
on top of whatever the visualizer is drawing. It stays dark while you hold the
key and fades back after you let go. The music effect keeps playing on the rest
of the board. This needs the same input access as reactive mode (section 7).

| Option                     | What it does                                                                     | Default     |
| -------------------------- | -------------------------------------------------------------------------------- | ----------- |
| `--erase`                  | turn the overlay on                                                              | off         |
| `--erase-radius FLOAT`     | size of the dark patch in key widths; `1` barely touches neighbors, `2.5` is wide  | `1.5`       |
| `--erase-fade FLOAT`       | seconds for a released key's color to come back                                  | `0.5`       |
| `--input /dev/input/eventN`| which input device to read key presses from                                      | auto-detect |

### Examples

```bash
python3 keyboardrgb.py audio --effect vortex --radius 0.4 --gain 1.5
python3 keyboardrgb.py audio --effect bars --direction sides --smooth 0.6
python3 keyboardrgb.py audio --effect ripple --mode single --color 00ffcc
python3 keyboardrgb.py audio --default breathe --idle-gap 3
python3 keyboardrgb.py audio --effect vortex --erase --erase-radius 2.5
```

### Picking the audio source

By default it listens to the monitor of your default output. If nothing moves,
your sound is probably going somewhere else. List the sources and pick the
`.monitor` of the device you're actually listening on:

```bash
pactl list short sources
python3 keyboardrgb.py audio --source alsa_output.pci-0000_00_1f.3.analog-stereo.monitor
```

## 7. Keypress-reactive mode

```bash
python3 keyboardrgb.py reactive
```

Lights the board in response to your typing. The tool reads key presses from
the keyboard's input device and draws an effect around each one.

### Effects

| Effect                | Looks like                                                                                   |
| --------------------- | -------------------------------------------------------------------------------------------- |
| `splash` _(default)_  | the pressed key lights up with a soft glow around it, fading after release                   |
| `ripple`              | a ring expands outward from each press                                                       |
| `trail`               | typing paints a wake of color that shifts hue along the keys you hit                         |
| `heatmap`             | keys you press often glow hotter, from blue up to red                                        |
| `raindrops`           | each press drops a randomly colored splash, and they layer like paint                        |
| `sonar`               | a thin ring pings outward and bounces off the edges of the board                             |
| `matrix`              | a green digital-rain streak falls down the pressed key's column                              |
| `crosshair`           | laser beams shoot along the pressed key's row and column                                     |
| `sparkle`             | random keys twinkle in a wide area around each press                                         |
| `erase`               | the opposite of `splash`: a background effect fills the board and pressed keys go dark       |

### Options

| Option                       | What it does                                                                         | Default     |
| ---------------------------- | ------------------------------------------------------------------------------------ | ----------- |
| `--effect NAME`              | one of the effects above                                                             | `splash`    |
| `--mode colorful\|single`    | palette colors, or one color                                                         | `colorful`  |
| `--color HEX`                | the color for `--mode single`                                                        | `009bde`    |
| `--radius FLOAT`             | how far the effect spreads around the pressed key, in key widths                     | `1.5`       |
| `--fade FLOAT`               | how quickly things fade after release, in seconds                                    | `0.5`       |
| `--scroll FLOAT`             | how fast colors shift in colorful mode                                               | `0.15`      |
| `--ripple-speed FLOAT`       | `ripple` and `sonar`: ring speed in key widths per second                            | `6.0`       |
| `--ripple-width FLOAT`       | `ripple` and `sonar`: ring thickness in key widths                                   | `1.5`       |
| `--trail-length INT`         | `trail`: how many recent presses stay visible                                        | `20`        |
| `--heat-decay FLOAT`         | `heatmap`: seconds for the extra glow of a fresh press to cool                       | `5.0`       |
| `--base NAME`                | `erase`: the background, `gradient`, `breathe` or `wave`                             | `gradient`  |
| `--input /dev/input/eventN`  | which input device to read                                                           | auto-detect |
| `--fps N`                    | frame rate                                                                           | `60`        |
| `--duration SEC`             | stop after this many seconds                                                         | forever     |
| `--debug`                    | print active keys and frame timing once a second                                     | off         |

Some effects pick their own colors: `heatmap` always uses its blue to red
scale and `raindrops` always uses random hues, so `--mode` and `--color` don't
change them. In `erase`, `--mode single --color HEX` swaps the animated
background for a solid color.

### Examples

```bash
python3 keyboardrgb.py reactive --effect ripple --ripple-speed 10
python3 keyboardrgb.py reactive --effect splash --mode single --color ff0055 --fade 1
python3 keyboardrgb.py reactive --effect heatmap
python3 keyboardrgb.py reactive --effect erase --base breathe --radius 2.5
```

To combine `erase` with the music visualizer, use `audio --erase` (section 6)
instead.

### Input access

Reactive mode and `audio --erase` read `/dev/input/eventN`. The tool looks for
the device named "BY Tech Gaming Keyboard", and if it can't find one it uses
the first keyboard it sees. Check which one it picked on the startup line
(`input=/dev/input/event4`), and pass `--input` if it guessed wrong. To see
your input devices:

```bash
grep -E "^N:|^H:" /proc/bus/input/devices
```

If you get `Permission denied` on the event device, add yourself to the
`input` group and log out and back in:

```bash
sudo usermod -aG input $USER
```

Be aware that membership in `input` lets any program you run read every
keystroke, on every keyboard.

The Fn key is handled inside the keyboard and never reaches Linux, so it
doesn't trigger effects.

## 8. Screen sync

```bash
python3 keyboardrgb.py screen
```

Captures your monitor, shrinks it to a blurry 144p, and paints those colors
onto the keys, so the lighting glows along with games, videos or your
wallpaper. On Hyprland it follows the focused monitor as you move between
screens. On X11 it captures with `ffmpeg`'s `x11grab` and doesn't need `grim`.

| Option                     | What it does                                                                         | Default      |
| -------------------------- | ------------------------------------------------------------------------------------ | ------------ |
| `--output NAME`            | capture this monitor and stop following focus (`hyprctl monitors` or `wlr-randr`)    | focused one  |
| `--follow` / `--no-follow` | track the focused monitor live, or stay on the current one                           | follow       |
| `--res N`                  | capture height in pixels                                                             | `144`        |
| `--blur FLOAT`             | blur radius in pixels at that height; `0` turns it off                               | `2.0`        |
| `--saturation FLOAT`       | color boost; `1` is faithful (`--sat` also works)                                    | `1.5`        |
| `--gain FLOAT`             | brightness multiplier                                                                | `1.1`        |
| `--gamma FLOAT`            | below `1` brightens the mid-tones                                                    | `1.0`        |
| `--smooth FLOAT`           | calms flicker between frames, `0` to `0.95`                                          | `0.5`        |
| `--raw`                    | faithful colors, ignoring saturation, gain and gamma                                 | off          |
| `--fps N`                  | frame rate; lower it to save CPU                                                     | `24`         |
| `--duration SEC`           | stop after this many seconds                                                         | forever      |
| `--debug`                  | print the monitor and frame timing                                                   | off          |

```bash
python3 keyboardrgb.py screen --output HDMI-A-1
python3 keyboardrgb.py screen --raw --smooth 0.7
python3 keyboardrgb.py screen --saturation 2 --gain 1.3
```

## 9. Running it in the background

Because the tool has to stay running, launch it in the background when you
want lighting without a terminal open:

```bash
nohup python3 ~/kbd-re/keyboardrgb.py audio --default breathe >/dev/null 2>&1 &
```

`toggle_audio.sh` in the repo starts audio mode if it isn't running and stops
it if it is, which makes it handy to bind to a hotkey. It remembers the process
in `/tmp/my_script.pid`. Edit the `python3` line inside it to change which
command it starts. On Hyprland, for example:

```
bind = SUPER, K, exec, ~/kbd-re/toggle_audio.sh
```

To have it start with your session, add the same command to your desktop's
autostart (for Hyprland, an `exec-once` line).

## 10. Tools for new keyboards

### walk

```bash
python3 keyboardrgb.py walk --start 60 --end 100
```

Lights one LED slot at a time and prints its number, so you can see which slot
belongs to which key while writing or fixing a profile. When it finishes (or
you press Ctrl-C) it prints a JSON skeleton of the slots it lit, ready to fill
in with key names and grid positions. It only ever writes the RGB report, so
it's safe to run on an unknown board.

| Option         | What it does                  | Default    |
| -------------- | ----------------------------- | ---------- |
| `--delay SEC`  | how long each slot stays lit  | `0.6`      |
| `--color HEX`  | the color to light it with    | `ffffff`   |
| `--start N`    | first slot                    | `0`        |
| `--end N`      | last slot                     | all slots  |

Once you know a key's slot, add `"slot": N` to that key's entry in the
profile JSON to override the profile's formula.

### raw

```bash
python3 keyboardrgb.py raw <hex bytes...>
```

Sends a raw HID feature report. **Never send report `0x05`.** On this chip
family it opens the firmware bootloader, and the wrong bytes can soft-brick
the keyboard. Only use `raw` if you know the protocol (see
[PROTOCOL.md](PROTOCOL.md)).

## 11. Troubleshooting

**`Permission denied: /dev/hidrawX`.** The udev rule isn't active. Make sure
`/etc/udev/rules.d/60-keyboardrgb.rules` exists with the `60-` name, run
`sudo udevadm control --reload`, then unplug and replug the keyboard.

**`keyboard vendor interface not found`.** The keyboard isn't connected by
cable, or it's in wireless mode. Switch it to wired. `lsusb | grep 258a`
shows whether Linux sees it.

**`Permission denied` on `/dev/input/eventN`.** Reactive mode and
`audio --erase` need input access. See [Input access](#input-access).

**Audio mode runs but nothing moves.** It's listening to the wrong output.
See [Picking the audio source](#picking-the-audio-source).

**Colors land on the wrong keys.** The wrong profile is in use. On an Aula
F75, add `--profile aulaf75`.

**My colors vanished and the onboard lighting came back.** The program
stopped. The board only shows your colors while the tool is running.

**"keyboard dropped off the bus (firmware reset), reconnecting..."** The
keyboard's firmware restarted. The tool waits about a second for it and
carries on. The usual cause is two programs streaming at once, so check that
only one copy is running:

```bash
pgrep -af keyboardrgb
```

**Fn lighting shortcuts take over.** The keyboard's own Fn lighting keys still
work and override streamed colors. Restart the command to take control back.
