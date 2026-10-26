# Flip-Disc (Python, single-Pi)

A fast, robust flip-dot display controller written 100% in Python. It runs on a single Raspberry Pi (or any Linux box), exposes a FastAPI HTTP interface, runs animation generation in a background thread, and drives flip-dot panels over RS-485 with a small, protocol-correct encoder.

Highlights
- Async display presenter with deadline-based timing that paces the display (default 20 FPS) and owns serial I/O
- Threaded generator with `queue.Queue` frame buffer for smooth, backpressure-aware animation delivery
- Lightweight animation switching — no process restarts, just a reference swap and queue drain
- Segmented panel writes + proper flush semantics (7x7 immediate refresh; 14x7/28x7 buffered + flush)
- Preview isolation via asyncio queues prevents UI callbacks from blocking the main presenter loop
- Clean separation: engine (pipeline), hardware (protocol/transport), animations (step/render), web (API/UI)


## Quick Start

Requirements
- Python 3.15 (uv installs it from `.python-version`)
- On a Raspberry Pi, 64-bit Raspberry Pi OS: every dependency ships prebuilt 64-bit ARM wheels for 3.15. 32-bit is untested and would likely mean compiling numpy and scipy from source.
- `uv`

Install (dev) with uv:
```bash
# Install dependencies (including dev extras) using the lockfile
uv sync --extra dev
```
 
Run the server (mock serial by default):
```bash
uv run python -m flipdisc run-server --config config.toml --host 0.0.0.0 --port 8000
```

Run with hot reload for development (auto-restarts on file changes):
```bash
uv run python -m flipdisc run-server --reload
```

Endpoints @`http://localhost:8000`:
- [Status](http://localhost:8000/status): `/status`
- [API Docs](http://localhost:8000/docs): `/docs`
- [List animations](http://localhost:8000/animations): `/animations`
- [Start animation](http://localhost:8000/anim/bouncing_dot): `/anim/bouncing_dot`(POST)
- [Set refresh rate](http://localhost:8000/fps?new_fps=15): `/fps?new_fps=15` (POST)
- [Web UI](http://localhost:8000/ui): `/ui` (static page served by FastAPI)



## Configuration (config.toml)

Minimum example (works with mock serial):
```toml
[display]
# Panel grid (each controller drives a 28x7 strip); default canvas = 28x28
panel_type = "28x7"     # "7x7", "14x7", or "28x7"
columns = 1              # horizontal panel count (28*1 = 28)
rows = 4                 # vertical panel count (7*4 = 28)
refresh_rate = 20.0      # frames per second paced by the server
buffer_duration = 1.0    # seconds of frames the buffer can hold
# Optional base address for the first panel (panels are addressed row-major)
address_base = 1

[serial]
# Serial transport. Use mock=true for development.
port = "/dev/ttyUSB0"
baudrate = 38400        # must match the panels' DS#2 switches (docs/hardware.md §3)
timeout = 1.0
mock = true
```

Notes
- Width = panel_w * columns, height = panel_h * rows. With 28x7 x 1x4 -> 28x28.
- 7x7 panels do not support buffered refresh; the controller sends immediate-refresh messages without a flush.
- 14x7 and 28x7 are sent as buffered messages, then a broadcast flush is issued.
- address_base sets the starting panel address and increments per panel in row-major order.


## Fonts

A font is a family of bitmap sizes, each drawn on the dot grid, listed in `assets/text/fonts.toml`:

- **`spleen`** (the default, `DEFAULT_FAMILY` in `flipdisc/fonts/loader.py`): [Spleen](https://github.com/fcambus/spleen) from 5×8 to 32×64 (BSD licence, `assets/text/spleen/LICENSE`), and below that a 3×5 hand-drawn for this display.
- **`x11`**: the X Window System's "fixed" fonts, 4×6 to 10×20 (public domain).

Text asks for a height (`size`, in dots on a 28-dot display) and gets the drawn size nearest that height scaled to the display; past a family's largest size, that size is enlarged by a whole number. Where text has to fit (a static line, a clock, a score), it drops to smaller sizes until it does.

```python
from flipdisc.fonts.loader import load_family

font = load_family("spleen").nearest(8)   # Spleen 5×8
font.render_line("HELLO")                  # float32 array, 8 × 24
```

Sizes are [BDF](https://en.wikipedia.org/wiki/Glyph_Bitmap_Distribution_Format) files, editable in a text editor or a pixel-font editor such as FontForge or Bits'N'Picas. To add one, copy it in with the importer (it keeps the printable ASCII characters), then list it under a family in `fonts.toml`:

```bash
uv run python -m flipdisc.fonts.importer ~/Downloads/7x14.bdf assets/text/x11/7x14.bdf
```

Every drawn size, at the same dot size:

![Every size of each font family](assets/text/font_sizes.png)

The clock and a page of text as each family sets them on 28, 56 and 126 dot displays. Each display is drawn the same width, so a 56 display's dots look half the size of a 28's:

![The clock and text in each family on three display sizes](assets/text/font_specimen.png)

Both images are drawn by the code from the real animations. After changing a font or how text is set, regenerate them (a test fails until you do):

```bash
uv run python -m flipdisc.tools.font_images
```


## Project Layout

```
flip-disc/
├─ config.toml                # Example configuration (TOML)
├─ pyproject.toml             # Package + tooling (ruff, pytest)
├─ CLAUDE.md                  # Context for coding agents (orientation, gotchas)
├─ docs/
│  ├─ architecture.md         # How the implementation works, end to end
│  └─ hardware.md             # AlfaZeta panel reference (wiring, DIP switches, protocol)
├─ assets/
│  ├─ text/                   # Bitmap fonts (BDF), one folder per family, fonts.toml, reference PNGs
│  ├─ images/weather/         # Weather icon BMPs
│  └─ clips/clips.toml        # Clip manifest (GIF frame sequences)
└─ flipdisc/
   ├─ app.py                  # Application orchestrator (wires pipeline + API)
   ├─ cli.py                  # CLI: run-server, preview
   ├─ config.py               # Config loading + validation (TOML)
   ├─ exceptions.py           # Project-wide exception hierarchy
   ├─ engine/pipeline.py      # DisplayPipeline: generator thread + async presenter
   ├─ animations/             # Animation classes + registry
   │  ├─ base.py              # Animation ABC, registry, factory
   │  ├─ viewport.py          # Viewport: an animation's box on a display
   │  ├─ scaling.py           # DisplayScale: how sizes grow with the display
   │  ├─ composed.py          # Layered compositions
   │  ├─ text.py, clock.py, analog_clock.py
   │  ├─ weather.py, weather_icon.py, precipitation.py
   │  ├─ clip.py, image.py
   │  ├─ bouncing_balls.py, bouncing_dot.py, fluid.py, life.py,
   │  │  pendulum.py, point_cloud.py, rain_splash.py, rip.py,
   │  │  sandpile.py, simplex_noise.py, wireframe_cube.py
   │  └─ sorting/             # `sort`: one module per algorithm
   ├─ fonts/                  # BDF reader, font sizes and families, importer
   ├─ clips/                  # GIF clip loader + importer utilities
   ├─ services/               # Weather fetch (Open-Meteo), moon phase
   ├─ hardware/               # RS-485 protocol + serial transport
   │  ├─ PROTOCOL.md          # Wire protocol reference
   │  ├─ spec.py              # Protocol enums, command map, constants
   │  ├─ formats.py           # Low-level encoder (panel msgs + flush)
   │  ├─ protocol.py          # High-level ProtocolEncoder facade
   │  ├─ panel_map.py         # Slice canvas into per-panel bitmaps
   │  └─ serial.py            # Serial transports (hardware + mock)
   ├─ gfx/
   │  ├─ draw.py              # Crisp 1-bit shapes: line, disc, ring, block
   │  ├─ postprocessing.py    # Binarize, dither, blur, sharpen, threshold, downsample
   │  └─ terminal.py          # Print frames in the terminal for debugging
   ├─ web/                    # FastAPI endpoints, WebSocket preview, web UI
   ├─ tools/                  # Dev tools: font_images draws the font reference PNGs
   └─ tests/                  # pytest tests
```


## Control Flow

```mermaid
sequenceDiagram
    autonumber
    participant API as ApiServer
    participant Pipeline as DisplayPipeline
    participant Gen as Generator Thread
    participant Present as Presenter
    participant Serial as SerialTransport
    participant Panels as Hardware

    API->>Pipeline: POST /anim/{name}
    Pipeline->>Gen: Set animation request

    Note over Present: Presenter ticks @ refresh_rate
    loop Every Frame
        Gen->>Present: Frame (via queue.Queue)
        Present->>Serial: Encode + write batch
        alt panels 7x7
            Serial->>Panels: Immediate refresh per panel
        else 14x7/28x7
            Serial->>Panels: Buffered frames + flush
        end
        Present->>Pipeline: Store last frame for UI preview
    end
```


## Development

Run tests:
```bash
uv run pytest -q
```

Lint + format:
```bash
uv run ruff format
uv run ruff check --fix
```

Dev server with hot reload:
```bash
uv run python -m flipdisc run-server --reload
```

Tips
- Exception handling follows "log at level of knowledge": lower layers raise typed errors with context; top-level decides severity.
- Mock serial is on by default; set `mock=false` to write to real hardware.
- The generator thread uses `queue.Queue(maxsize=N)` for natural backpressure — it blocks when the buffer is full, resumes when the presenter consumes a frame.
- Animation switching is a lightweight reference swap: the main thread sets a request, the generator thread drains the queue and creates the new animation. No thread restart needed.
- NumPy releases the GIL during array operations, so the background thread provides real concurrency for compute-heavy animations.


## API

- GET `/status`: pipeline status (running, playing, frames_presented, buffer_capacity)
- GET `/animations`: animation names plus each one's parameter schema; `/fonts`, `/clips`, `/images`: available names
- POST `/anim/{name}` (JSON body = params) -> start or switch animation (400 if a parameter is unknown or invalid)
- POST `/animations/configure` -> set params on current animation
- POST `/animations/reset`, POST `/animations/stop`
- GET `/fps` -> { refresh_rate }
- POST `/fps?new_fps=20` -> update refresh rate
- POST `/serial/reconnect`
- GET/POST `/weather/config`, POST `/weather/refresh` -> background weather fetch for the `weather` animation
- WS `/ws/preview` -> live frames; GET `/ui` -> web UI
