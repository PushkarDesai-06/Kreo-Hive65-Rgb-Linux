# Kreo Hive 65 / BY Tech / SinoWealth Gaming Keyboard (258a:010c) — RGB Protocol

Reverse-engineered 2026-07-07 on Linux via HID report-descriptor analysis,
usbmon packet capture, and live hidraw probing on a **Kreo Hive 65**.
Cross-checked against the SignalRGB "Portronics Hydra 10" plugin (same
VID:PID, verified working), a rebrand of the same BY Tech 68-key board.

## Device

- USB `258a:010c` "BY Tech Gaming Keyboard", SinoWealth keyboard MCU family
- Interface 0 (`hidraw2`): standard 6KRO boot keyboard — no vendor traffic
- Interface 1 (`hidraw3`): multi-collection interface, all RGB traffic here
  - Report ID 1: System Control (input)
  - Report ID 2: Consumer Control (input)
  - Report ID 3: vendor page 0xFF00, 3-byte input (hotkey events)
  - Report ID 4: NKRO bitmap (input)
  - Report ID 5: vendor page 0xFF00, **Feature, 5+1 bytes** — command channel
  - Report ID 6: vendor page 0xFF00, **Feature, 519+1 bytes** — bulk data
  - Report ID 7: Mouse (input)

## RGB streaming (fully verified)

One HID SET_FEATURE (control transfer) per frame on **interface 1**:

```
bmRequestType=0x21  bRequest=0x09 (SET_REPORT)
wValue=0x0306 (Feature | report 6)  wIndex=1  wLength=520
```

Packet layout (520 bytes, report ID included):

| offset | value      | meaning                                        |
|--------|------------|------------------------------------------------|
| 0      | `0x06`     | report ID                                      |
| 1      | `0x08`     | command: direct per-LED RGB frame              |
| 2–3    | `00 00`    | constant (likely start offset, little-endian)  |
| 4      | `0x01`     | constant                                       |
| 5      | `0x00`     | constant                                       |
| 6–7    | `7A 01`    | payload length, LE = 0x017A = 378 (126 slots)  |
| 8–385  | RGB data   | `data[slot*3 .. +2] = R, G, B`                 |
| 386–519| `00` pad   | zero padding to 520                            |

- Colors latch immediately; **no init handshake and no apply command**.
- Stream frames at will (60 fps works; the reference plugin paces ~1 ms).
- **The board reverts to its onboard lighting after host traffic stops** (an
  idle timeout of a few seconds), so a single frame does not persist. To hold
  a static color, re-send it on an interval (`keyboardrgb.py` keeps ~1 Hz
  keep-alives for its color/wave modes). Fn hotkeys also override at any time.
- One SET_FEATURE takes ~11.6 ms on the wire (520 bytes over a full-speed
  EP0 = 9 × 64-byte data stages) — ~60 fps is the practical frame ceiling.
- **Firmware reset quirk**: under sustained streaming the MCU occasionally
  resets and re-enumerates (observed once after ~3000 frames: EPROTO on the
  in-flight transfer, then ENODEV, back in ~1 s with a new devnum and
  root-owned hidraw nodes). Long-running drivers must reopen the device;
  `keyboardrgb.py` does this automatically.

### LED slot map (68-key layout)

`slot = column*6 + row + 1` — column-major, 6 slots per physical column,
16 columns (0–15), rows top→bottom 0–4. Examples: Esc = col 0 row 0 → 1,
Space = col 5 row 4 → 35, Right Arrow = col 15 row 4 → 96... (see
`profiles/hive65.json` for the full name→slot layout). Unused slots ignored.

### Readback quirk

GET_FEATURE report 6 after a SET returns: the 8-byte command header echoed,
followed by N bytes (N = header length field) read from device memory — the
window contains firmware tables (USB device/config/HID descriptors are
plainly visible), NOT the RGB buffer. Before any SET since power-on, GET
returns a short all-zero response. Bytes 6–7 govern transfer length in both
directions.

## Command channel (report 5) — NOT mapped

- GET_FEATURE on report 5 stalls (write-only command mailbox).
- Presumably selects onboard effects/profiles (mode/speed/brightness live in
  hardware; Fn hotkeys change them without host traffic).
- **Deliberately not fuzzed**: SinoWealth keyboard MCUs enter their ISP
  (firmware flash) bootloader via a magic feature report on this family;
  blind writes risk soft-bricking. To map it, capture the vendor Windows
  app in a VM with USB passthrough while running
  `reverse-engineering/usbmon_sniff.py` on the host, then diff.

## Tools in this directory

- `keyboardrgb.py` — the CLI. `color/key/gradient/rainbow/wave/off/raw/audio/
  walk` subcommands, auto-detects the hidraw node + profile, no dependencies.
  `audio` is a system-sound visualizer: parec monitor capture -> pure-python
  1024-pt FFT -> N log-spaced bands (one per column, or one per row for
  horizontal bars) with auto-gain, `--mode colorful|single`, `--effect
  wave|bars|split|flow|vortex|ripple` (`bars` takes `--direction
  bottom|top|left|right|sides`; split maps bass->left edge / treble->right edge;
  flow is a bass waterfall — the left column samples the bass and that reading
  scrolls right (speed via --flow-speed), so a punch travels left->right;
  vortex/ripple are 2D field effects using the per-key geometry table),
  `--gain`, `--smooth`, `--scroll`. `--shape` is a back-compat alias for
  `--effect`. It's a thin
  dispatcher over the modules: `device.py` (discovery + the `Kbd` driver),
  `effects.py` (renderers), `audio.py` (capture + FFT), `color.py` (color
  math), and `kbd_profiles.py` + `profiles/*.json` (per-board identity /
  protocol / layout). Adding a keyboard is a new JSON file — no code changes.
- `kbd_ws_server.py` — zero-dep WebSocket bridge (RFC6455 on stdlib) that
  streams RGB frames from any app to the board via a coalescing latest-wins
  writer thread (~12 ms latency). Reuses the `Kbd` driver. Primary frame =
  binary 204 bytes (68 keys × RGB); also JSON keymap/grid/fill. Emits a
  TS client + `useKeyboard` hook + `schema.json` via `emit-client <dir>`
  (see `client/`).
- `reverse-engineering/` — the tools used to derive this protocol; not needed
  to *use* keyboardrgb (see its README):
  - `probe.py` — GET/SET feature-report probe, state snapshot + diff.
  - `usbmon_sniff.py` — dependency-free usbmon binary-interface sniffer
    (decodes SET_REPORT/GET_REPORT control transfers): `usbmon_sniff.py <bus>
    <devnum>`; needs read access to `/dev/usbmon<bus>`.
  - `hydra0049.py` — report-6 probe for the Portronics Hydra 10 (258a:0049).
  - `captures/` — saved usbmon logs from the sessions above.
- `60-keyboardrgb.rules` — udev rule granting the seated user access to the
  keyboard's hidraw nodes (install to `/etc/udev/rules.d/`, then
  `udevadm control --reload && udevadm trigger`).

## Access notes

hidraw nodes are root-owned by default. This session used
`docker run --rm -v /dev:/dev debian:bookworm chown 1000 /dev/hidraw2
/dev/hidraw3 /dev/usbmon1` (docker group ≈ root); ownership resets on
replug/reboot — install the udev rule for a permanent fix.
