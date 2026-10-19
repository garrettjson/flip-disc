# Hardware Layer

Read `docs/hardware.md` first — it is the reference for the AlfaZeta panels (protocol, DIP switches, power, refresh limits) and lists what is still unverified on the physical display.

## What's here

- `spec.py` — protocol constants and the (data size, refresh mode) → command byte table. No I/O.
- `formats.py` — bit packing and single-message encoding.
- `protocol.py` — `ProtocolEncoder`: binds to a `DisplayConfig`, encodes a set of panels by address (`encode_panels`) or a whole frame (`encode_batch`), one message per panel + flush. The presenter sends only changed panels.
- `panel_map.py` — splits the canvas into per-panel arrays.
- `serial.py` — `SerialTransport` ABC, hardware (aioserial) and mock implementations.
- `PROTOCOL.md` — transcription of the manufacturer's protocol sheet.

## Rules

- **The byte format is fixed by the manufacturer.** One byte per column, bit 0 = top dot, bit 7 = 0; start `0x80`, end `0x8F`. `flipdisc/tests/test_formats.py` pins it — keep those tests passing and extend them when adding a panel size or command.
- **Row-major, unrotated panels.** `panel_map.py` assumes identical panels laid out left-to-right then top-to-bottom, addressed `address_base + index`. Rotated or mixed panels need new mapping code, not a config tweak.
- **Panel height is always 7.** Supported widths are 7, 14, and 28. 7-wide panels can't buffer, so they refresh on receipt and get no flush.
- **Hardware behavior is unconfirmed unless `docs/hardware.md` says otherwise** — the repo holds no record of a run against real panels. Don't remove the mock transport path; it is how everything is developed and tested.
- **Every byte costs wire time** (10 bits per byte at the configured baud). When changing what is sent per frame, recompute the budget in `docs/hardware.md` §7.
- **Writes are real-world actions.** Each message can physically flip dots, draw current, and make noise. Avoid changes that send more frames, or flip more dots, than the content requires.
- Raise `SerialConnectionError` / `HardwareError` / `FrameError` with context; don't catch broadly here — the pipeline decides what to do.
