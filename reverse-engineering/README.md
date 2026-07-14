# reverse-engineering/

The scratch tools used to reverse-engineer the keyboards' RGB protocol. **You
don't need any of this to use `keyboardrgb`** — it's kept for the record and for
mapping new boards. Everything here is stdlib-only and standalone (nothing in the
root package imports it).

- `probe.py` — GET/SET HID feature-report probe: snapshot reports 5+6 to
  `snapshots/<name>.bin` and byte-diff two snapshots. How the report-6 frame
  format was pinned down.
- `usbmon_sniff.py` — dependency-free usbmon sniffer that decodes
  SET_REPORT/GET_REPORT control transfers: `usbmon_sniff.py <bus> <devnum>
  [logfile]` (needs read access to `/dev/usbmon<bus>`). Used to capture the
  vendor app's traffic.
- `hydra0049.py` — report-6 probe for the Portronics Hydra 10 (`258a:0049`),
  whose frame is 1032 bytes with a different header. Still in progress; its
  findings seed `profiles/hydra10.json`.
- `captures/` — saved usbmon logs from those sessions.

Safety: these only ever touch **report 6** (the RGB framebuffer), never report 5
(the SinoWealth ISP/flash channel). See `../PROTOCOL.md` for why that matters.

To map a supported board's key layout for a new profile, prefer the safe,
built-in `keyboardrgb.py walk` over poking with these.
