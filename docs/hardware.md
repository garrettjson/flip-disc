# AlfaZeta XY5 Flip-Dot Panels — Hardware Reference

Everything relevant from the two documents AlfaZeta supplied to the owner, plus how this project uses it. The PDFs are not in the repo.

| Source | Referred to below as |
|---|---|
| *14x28 XY5 / 7x28 XY5 Flipdot Panels — User Manual*, Rev. 9.0, 13 Mar 2017 (12 pages) | **Manual** |
| *Flipdots display control protocols — August 2018* (1 page) | **Protocol** |

Sections marked **Project note** are this project's reading of the documents, not manufacturer statements. Manufacturer support: info@alfazeta.pl (the Manual says "ask for details" in several places — drawings, Ethernet converters, the protocol).

---

## 1. Panel anatomy

- The product is the **XY5** panel, sold as **7x28** and **14x28** (rows × columns in the Manual's naming).
- **A 14x28 panel is two 7x28 panels joined mechanically only.** Each 7x28 area has its own controller board, connected to its dot board by a multi-pin connector. (Manual p.5–6)
- **Each controller needs its own connections**: 24 V DC and RS-485. Two controllers in one 14x28 panel can be daisy-chained for data with a short RJ11 cable if they share one RS-485 line, but power must be wired to each separately. (Manual p.5, p.8)
- The dots are discs turned by magnetic force; they hold position without power. (Manual p.10)

**Project note — naming.** The Manual says "7x28" (rows × columns). The Protocol and this codebase say "28x7" (width × height). They are the same thing: 28 columns wide, 7 dots tall, one controller, one address.

### This display (confirmed by the owner, October 2026)

**Two 14x28 panels stacked vertically, unrotated, forming a 28×28 square.** That is four controllers, each driving a strip 28 dots wide × 7 tall, with the strips running left to right:

```
        28 dots wide
┌────────────────────────────┐
│ strip 1  (28 wide x 7 tall)│  panel A
├ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┤
│ strip 2                    │
├────────────────────────────┤
│ strip 3                    │  panel B
├ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┤
│ strip 4                    │
└────────────────────────────┘
```

So the display has **four addresses**, each taking a 28-byte message (`0x84` buffered, `0x83` immediate), and needs four 24 V feeds and about 2 A in total.

**Project note.** `config.toml` and the built-in defaults describe this as `panel_type = "28x7"`, `columns = 1`, `rows = 4`: addresses `address_base` to `address_base + 3` (1–4 by default), top strip first. `panel_map.py`'s row-major, unrotated assumption fits this layout. Still to confirm on the hardware: which DIP address each strip is actually set to.

---

## 2. Connections (Manual p.6–8)

Every controller needs:

- **24 V DC** (+ and −) on the `VCC` / `GND` screw terminal. Observe polarity.
- **RS-485** (+ and −) through any one of J1, J2, or J3. The three are wired in series (they are the same bus), so J1/J2 can be used to chain modules with short RJ11 cables.

| Connector | Type | Purpose |
|---|---|---|
| 24V DC | screw terminal (`VCC`, `GND`) | power |
| J1 | RJ11 socket | RS-485 data |
| J2 | RJ11 socket | RS-485 data |
| J3 | screw terminal (`+485`, `-485`) | RS-485 data |
| DS#1 | 8-position DIP switch | address, magnetizing time, test mode |
| DS#2 | 3-position DIP switch | baud rate |

The board also has a reset button. The Manual says of every other header on the board: **"PLEASE DISREGARD ALL OTHER CONNECTIONS."**

### RJ11 pinout (J1 and J2, front view, pins 1–6 left to right)

| Pin | Function |
|---|---|
| 1 | N/C |
| 2 | RS485+ |
| 3 | RS485+ |
| 4 | RS485− |
| 5 | RS485− |
| 6 | N/C |

### Connecting a computer

- PCs, Macs, and Arduinos have no RS-485 port: use a **USB-to-RS485** or **Ethernet-to-RS485** converter (Manual p.9–10).
- For large signs AlfaZeta limits each RS-485 line to 10 panels and fans out with Ethernet-to-RS485 converters on a 1 Gb/s LAN (Manual p.9).

---

## 3. DIP switches (Manual p.7)

### DS#2 — baud rate (3 positions)

| Value | Pos 1 | Pos 2 | Pos 3 | Speed |
|---|---|---|---|---|
| 0 | OFF | OFF | OFF | N/A |
| 1 | ON | OFF | OFF | N/A |
| 2 | OFF | ON | OFF | N/A |
| 3 | ON | ON | OFF | 9600 |
| 4 | OFF | OFF | ON | 19200 |
| 5 | ON | OFF | ON | 38400 |
| 6 | OFF | ON | ON | **57600** |
| 7 | ON | ON | ON | 9600 |

57600 is the maximum. Every controller on a line must use the same rate, and `[serial] baudrate` in `config.toml` must match.

**Project note — what baud means here.** Baud is the speed of the serial data link: how many bits per second travel down the RS-485 wire from the computer to the controllers. Each byte costs 10 bits on the wire, so 9600 baud carries about 960 bytes per second and 57600 about 5,760. It sets how quickly a frame *arrives*, not how the dots are driven: the strength and length of the pulse that flips a dot is the magnetizing time (DS#1 position 6, §5). Two consequences:

- **At 9600 the wire, not the dots, is the bottleneck.** A full frame takes about 136 ms to send, so the display can't exceed about 7 fps however fast the dots could flip (§7).
- **A faster link can mean more flips per second**, and therefore more average current, because frames arrive sooner. The 1 A per panel supply guidance in §4 already assumes the panels are driven as fast as they can go.

If the computer's rate doesn't match the switches, the controllers won't read the data correctly. `[serial] baudrate` in `config.toml` is the only place the software sets the rate; to change it, set the DS#2 switches on every controller to the matching row of the table above, then edit `config.toml`. Whether this display's switches match `config.toml` has not been checked.

### DS#1 — address, magnetizing time, test mode (8 positions)

The Manual numbers the positions 0–7; the physical switch is printed 1–8.

| Position (Manual) | Meaning |
|---|---|
| 0–5 | Controller address, natural binary (6 bits: 0–63) |
| 6 | Magnetizing time: **OFF = 500 µs (default)**, ON = 450 µs — see §5 |
| 7 | Test mode: ON = test mode, OFF = normal operation |

**Project note.** The Manual doesn't say which address position is the least significant bit, or what test mode displays. Each controller needs a unique address; this project assigns `address_base + index` in row-major order (top-left first), with `address_base = 1` by default, so the switches must be set to match.

---

## 4. Power (Manual p.8–9)

Measured by AlfaZeta while flipping one complete 14x28 panel from white to black:

| Quantity | Value |
|---|---|
| Nominal voltage | 24 V DC |
| Maximum voltage | 25 V DC |
| Max current while flipping | 680 mA per 14x28 panel |
| Idle current | 40 mA |
| Energy to swap one complete panel | 160 ms × 680 mA |
| Suggested supply | **1 A per 14x28 panel at 24 V** |

- These figures assume "2C configuration" (the Manual does not define the term) and driving the panels as fast as possible.
- Power scales with drive speed: "If you drive panels 2x slower, you can use 2x smaller power supplies."

**Project note.** This display is two 14x28 panels, so it wants about 2 A at 24 V.

---

## 5. Refresh rate and magnetizing time (Manual p.9)

- **10 fps is the guaranteed minimum**, calculated for the worst case where **every dot changes state** each frame, provided:
  - at most 10 panels (20 controllers) share one RS-485 line, and
  - the supply can deliver 1 A per panel.
- **About 25 fps is the effective rate for real video**, because in real animations only a fraction of the dots change per frame.
- **Magnetizing time** (DS#1 position 6) can be shortened from 500 µs to 450 µs to refresh faster, at the risk of too little magnetic energy reaching the dots, which "may lead to problem with stability for some animations and setup." The Manual says experimenting is safe: "you can always return back to the default value."

**Project note — what this implies for software** (inference, not manufacturer statements):

- The frame rate the hardware can sustain depends on **how many dots change**, not just on how many frames are sent. Content that flips a large share of the display every frame (full-screen noise, inversions) is limited to about 10 fps; sparse motion can go much faster.
- The numbers are consistent with a controller pulsing dots one after another: 196 dots (one 7x28 controller) × 500 µs = 98 ms ≈ 10 fps. The Manual does not describe the sequencing, so treat this as a model, not a fact.
- "Only a fraction of dots are being changed" strongly suggests the controller pulses only dots whose state differs, but the Manual does not say so outright. Whether resending an identical panel causes any pulses is still untested on this display.
- The serial link is a separate, hard limit — see §7.

---

## 6. Serial protocol (Protocol, whole document)

### Frame

```
0x80  <command>  <address>  <data ...>  0x8F
```

### Commands

| Command | Data bytes | Refresh? | Panel (width × height) |
|---|---|---|---|
| `0x82` | 0 | YES | Refresh all connected displays. The whole message is `0x80 0x82 0x8F` (no address byte). |
| `0x83` | 28 | YES | 28x7 |
| `0x84` | 28 | NO | 28x7 |
| `0x87` | 7 | YES | 7x7 |
| `0x92` | 14 | YES | 14x7 |
| `0x93` | 14 | NO | 14x7 |

- **Address** — the controller's address. `0xFF` (255) is broadcast: every device accepts the message.
- **Data** — the display contents, one byte per column ("strip") of 7 dots. **Bit 0 (LSB) is the top dot; bit 6 is the bottom dot. Bit 7 is ignored and should be 0.** (The original says "most significant byte (8th)"; it means bit.) The number of data bytes equals the panel's width in columns.
- **Refresh = YES** — the data is shown as soon as it is received.
- **Refresh = NO** — the data is stored in the controller's memory and shown when the `0x80 0x82 0x8F` sequence arrives. This lets many panels change at the same instant. **Not supported by 7x7 displays.**

The protocol is write-only as documented: there is no acknowledgement, checksum, or way to read state back.

**Project note — not specified by either document:** serial framing (this project uses pyserial's defaults, 8 data bits, no parity, 1 stop bit), any required gap between messages, and bus termination.

---

## 7. How this project drives the hardware

- **One frame = one buffered message per changed panel + one flush.** `ProtocolEncoder.encode_panels` (`flipdisc/hardware/protocol.py`) sends `0x93` (14x7) or `0x84` (28x7) to each address, then `0x80 0x82 0x8F`, so all panels flip together. 7x7 panels can't buffer, so they get `0x87` and no flush.
- **Bit packing** is in `flipdisc/hardware/formats.py` (`np.packbits(..., bitorder="little")` down each column), covered by `flipdisc/tests/test_formats.py`.
- **Addresses** are `address_base + panel_index`.
- **Only changed panels are sent.** The presenter compares each panel with what it was last sent and writes just the ones that differ, then the flush. The first frame after connecting or reconnecting sends every panel.

**Project note — unverified on the hardware.** Sending a subset relies on two things the Protocol implies but doesn't state: a controller that receives no new data keeps its stored image across a flush (the flush "refreshes all connected displays", including ones that weren't sent anything), and re-showing that unchanged image doesn't disturb it. If strips that didn't change go blank or glitch when another strip updates, this is the cause; restoring full-frame sends is a one-line change in `DisplayPipeline._write_frame`.

### Wire time per full frame

A message is 4 framing bytes plus the data; a serial byte is 10 bits on the wire (8N1).

| Layout | Bytes per frame | 9600 | 19200 | 38400 | 57600 |
|---|---|---|---|---|---|
| 8 × 14x7 (for comparison) | 8 × 18 + 3 = 147 | 153 ms | 77 ms | 38 ms | 26 ms |
| 4 × 28x7 (this display, current config) | 4 × 32 + 3 = 131 | 136 ms | 68 ms | 34 ms | 23 ms |
| One changed 28x7 strip + flush | 32 + 3 = 35 | 36 ms | 18 ms | 9 ms | 6 ms |

At 9600 a full-frame stream is capped at about 7 fps, below even the Manual's 10 fps worst case. From 38400 up (about 29 fps at 38400, 44 fps at 57600) the link is faster than the default 20 fps refresh rate, so the dots, not the link, become the limit. The rate in use is whatever `[serial] baudrate` in `config.toml` says (§3).

### Known gaps between the code and the hardware

- `refresh_rate` defaults to 20 fps; the Manual's guarantee for all-dots-changing content is 10 fps.
- Nothing in the code limits how many dots change per frame, staggers flips for power, or runs a maintenance routine.
- The repo holds no record of a run against the physical display (the config defaults to the mock transport), so none of the above is confirmed on real panels.

---

## 8. Handling, environment, and maintenance (Manual p.2–5, p.10–12)

Relevant to software mainly through the flip-flop routine below, but recorded in full because damage here is permanent.

### Safety and handling

- Assembly by qualified personnel only; check connections before installing; follow local electrical safety rules.
- **Always disconnect the power supply before doing anything to the boards.**
- The dot grid is delicate and easy to destroy. Hold panels by the edges; never grip the display face. Never drill holes with boards installed.
- **Don't touch dots with bare fingers** (dirt and grease cause malfunctions); use gloves.
- **Extremely electrostatic-sensitive**: avoid touching dots; ESD protection is strongly advised.
- **Extremely dust-sensitive**, especially to metal chips and particles.
- Before laying a board face-down, turn **all dots white**, and use a flat, clean, hard surface. Store spare boards the same way, or with protective cardboard on the dot side.
- Dots are removable. A dot pressed too hard into its socket can be lifted out with tweezers, its axle straightened, and refitted. Spare dots are supplied.

### Operating conditions

- Temperature: −40 °C to 80 °C. Relative humidity: 5–95 % non-condensing (at 40 °C).
- A ventilated housing is recommended to keep out dust and humidity; without one, regular cleaning is necessary.

### Lazy and blocked dots

- A **lazy/slow** dot turns later or more slowly than its neighbours; a **blocked** dot doesn't turn.
- **After a period without use, some dots becoming lazy or blocked is normal** and doesn't mean they are broken. Running a fast black–white flip-flop program for 15–20 minutes usually fixes it.
- To tell a mechanical block from an electrical fault: nudge the dot by hand while it is being magnetized. If it jumps to the right position, it needs cleaning.

### Routine maintenance

- **Daily: a flip-flop routine** — at least 5 minutes, or 10 minutes after more than 2 days of inactivity.
- **Preventive cleaning** about every 4 weeks, more often if blocked dots increase:
  - Compressed air: clean, dry air, about 3 cm from the dots, about 2 s per 14 dots. Avoid condensation.
  - Then a vacuum cleaner at **minimum** suction, no closer than 5 cm. Too much suction pulls dots out or bends their axles, and those dots must then be replaced.
- **Never use lubricant or grease** — it helps briefly, then blocks the dots completely.
- Damage from improper cleaning is not covered by the guarantee.

### Cleaning a stuck dot, in order of escalation

1. **Axle and socket blocked by hair or dust:** compressed air → vacuum at minimum suction → remove the dot and clear it by hand → replace the dot.
2. **Debris in the housing under the dot:** compressed air → vacuum → remove the dot and clean the housing floor with a cotton swab and a drop of 70 % technical spirit.
3. **Dot sticking to the stator pins** (dust plus humidity forms an adhesive film): clean the contact points with a swab and 70 % spirit; if that fails, replace the dot.

**Project note.** The flip-flop routine is something this software could provide (an all-white/all-black exercise animation, run at startup or on a schedule). It doesn't exist yet.
