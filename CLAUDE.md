# Flip-Disc

Python flip-disc display controller for Raspberry Pi. Drives AlfaZeta flip-dot panels over RS-485 via a FastAPI server with a threaded pipeline (Generator thread -> Presenter async task).

## Where to Look

| For | Read |
|---|---|
| Orientation, commands, conventions, gotchas | this file |
| How the code works today, end to end (threads, frame lifecycle, control path) | `docs/architecture.md` |
| The panels: wiring, DIP switches, power, refresh limits, protocol, maintenance | `docs/hardware.md` |
| Writing or changing an animation | `flipdisc/animations/CLAUDE.md` |
| Changing protocol, panel mapping, or serial code | `flipdisc/hardware/CLAUDE.md` |

When behavior or hardware knowledge changes, update the matching doc in the same change.

## What This Project Does

Flip-disc displays are mechanical panels where each pixel is a small magnetic disc — one side painted (visible), one side dark. Flipping a disc requires sending a physical pulse over RS-485 serial. This project controls a grid of those panels from a Raspberry Pi.

The system has three concerns:

1. **Content** — animations produce grayscale frames (NumPy float arrays) that get binarized to 1-bit. They run continuously in a background thread.
2. **Transport** — frames are encoded into RS-485 protocol packets and written to the serial port at the configured refresh rate. In mock mode (default) this is a no-op, so you can develop without hardware.
3. **Control** — a FastAPI server exposes HTTP endpoints, a WebSocket preview, and a small web UI so external systems can start/stop animations and push live updates.

### Display Hardware

The display is **28×28**: two AlfaZeta 14x28 XY5 panels stacked vertically, which is four controllers, each driving a strip 28 dots wide × 7 tall.

- Config: `panel_type = "28x7"`, `columns = 1`, `rows = 4` → addresses 1–4, top strip first (the DIP address of each strip is not yet confirmed on the hardware)
- `refresh_rate = 20.0` fps
- The standard font (5×7px glyphs) renders `"HELLO"` at 29px wide — 1px too wide. Use the **compact font** (3×5px) or keep text short.

### Hardware facts (AlfaZeta XY5 panels)

From the manufacturer's manual and protocol sheet; the full reference is `docs/hardware.md`. Read it before touching `flipdisc/hardware/` or reasoning about frame rates.

- **Refresh rate depends on how many dots change.** AlfaZeta guarantees 10 fps when every dot flips each frame and quotes about 25 fps for typical video, where only a fraction change.
- **Baud is set by a DIP switch on each controller**: 9600, 19200, 38400, or 57600 (maximum). `config.toml` must match it and currently says 9600.
- **The serial link is a hard budget.** A full frame is 131 bytes (4 × 32-byte strip messages + 3-byte flush): ~136 ms at 9600 baud (~7 fps), ~23 ms at 57600.
- **Power:** 24 V; up to 680 mA per 14x28 panel while flipping; 1 A per panel recommended.
- **The protocol is write-only** — no acknowledgement, checksum, or readback, so software can't detect a dot that failed to flip.
- **Verification status is unrecorded.** The repo defaults to the mock transport and holds no record of a run against the physical display, so treat hardware behavior as unconfirmed unless `docs/hardware.md` says otherwise.

## Design Intent

Goals stated by the owner; some are not yet true of the code. Ask before proposing something that contradicts them.

- **The display's frame rate drives the animation.** One presenter tick = one frame requested = the animation advances by one display interval (`step(1 / refresh_rate)`).
- **Plenty of compute headroom.** The target is a Raspberry Pi (model undecided), with heavier simulation-style animations planned. A frame should cost a small fraction of the frame interval (50–100 ms at 10–20 fps), on the Pi, not just on the dev machine (an Intel Mac).

Decisions the owner has made about the refactor (October 2026):

- **Python for everything, for the time being.** A rewrite in another language was considered and set aside.
- **Performance work comes last.** No Numba or other compiled kernels until the structural work is done, even though `fluid` (~100–190 ms per frame) and `simplex_noise` (~27 ms) are too slow today; every other animation costs under 3 ms.
- **Animations will declare their parameters** (type, default, range) so the API can validate them and the web UI can build its controls from the schema. Not built yet.
- **Keep a frame buffer of about one second**, not a single-frame handoff. (`buffer_duration = 1.0`.)
- Don't make other structural changes to `engine/`, `animations/base.py`, or the API boundary without checking what has been agreed.

---

## Commands

Run everything **from the repo root** — fonts, clips, and config are loaded via cwd-relative paths (`assets/...`, `config.toml`).

- Install: `uv sync --extra dev` (Python 3.11+)
- Test: `uv run pytest -q` (~25s)
- Lint: `uv run ruff check --fix`
- Format: `uv run ruff format`
- Server: `uv run python -m flipdisc run-server --config config.toml` (add `--reload` for hot reload); UI at `http://localhost:8000/ui`, OpenAPI at `/docs`
- Terminal preview: `uv run python -m flipdisc preview -a <name> -n 5` (`--list` for names; default params only; steps at the config's `refresh_rate`, like the display)

Before calling a change done: run the tests, run ruff on the files you touched, and for anything visual look at actual frames (see Debugging below).

---

## Architecture

- `flipdisc/engine/pipeline.py` — `DisplayPipeline`: generator thread + async presenter, connected by `queue.Queue`
- `flipdisc/animations/` — animation classes + decorator-based registry (see `flipdisc/animations/CLAUDE.md` for the authoring checklist)
- `flipdisc/hardware/` — RS-485 encoding (`spec` -> `formats` -> `protocol`), `panel_map` (canvas -> per-panel bits), `serial` (hardware + mock transports)
- `flipdisc/gfx/` — `postprocessing` (binarize, dither, blur, sharpen, threshold, downsample), `terminal` (debug frame printing)
- `flipdisc/web/` — `api_server.py` (FastAPI routes + WebSocket preview + weather fetch loop), `index.html` + `static/` (web UI)
- `flipdisc/services/` — `weather.py` (Open-Meteo fetch via httpx), `moon_phase.py`
- `flipdisc/fonts/`, `flipdisc/clips/` — bitmap font loader; GIF clip loader + importer
- `flipdisc/config.py` — TOML config; `DisplayConfig.width/height` are derived properties (not settable)
- `flipdisc/app.py`, `flipdisc/cli.py` — wiring and `run-server` / `preview` subcommands
- `flipdisc/exceptions.py` — `FlipDiscError` hierarchy
- `flipdisc/tests/` — pytest tests
- `assets/text/` — font sprite sheets + `fonts.toml`; `assets/images/weather/` — weather icon BMPs; `assets/clips/clips.toml` — clip manifest (currently empty)

### Pipeline

- **Generator thread** steps the animation, applies its `processing_steps`, and pushes frames into `queue.Queue(maxsize=refresh_rate * buffer_duration)`. It blocks on `put(timeout=0.05)` when full — natural backpressure.
- **Presenter** (async task) pulls one frame per tick at `refresh_rate`, splits it into panels, encodes, writes to serial, and feeds the preview queue. Frames identical to the last one written are **not** re-sent (no needless disc pulses), and `frames_presented` only counts frames actually written.
- **Cross-thread requests** go through one ordered queue (`_requests`) that the generator empties at the top of each iteration: `switch` (drains the frame queue once the new animation is built), `configure`, and `reset`. So `set_animation` / `configure_animation` / `reset` return before the change is applied; errors raised while applying them are recorded in `get_status().last_error` instead of reaching the caller.

### DisplayPipeline public API

All async except `get_status()`, `get_last_frame_bits()`, `set_preview_callback()`:

- `start(animation, params)` / `stop()` — lifecycle
- `play()` / `pause()` — playback control
- `set_animation(name, params)` — switch animation
- `configure_animation(params)` — update params on the running animation in place
- `reset()` — reset current animation state
- `get_status()` -> `PipelineStatus(running, playing, frames_presented, buffer_capacity, animation, last_error)`
- `get_last_frame_bits()` -> last written frame
- `set_preview_callback(cb)` — single callback, used by the WebSocket preview
- `set_refresh_rate(fps)` / `reconnect_serial()` — runtime config

### HTTP API

- `GET /status`, `/animations`, `/fonts`, `/clips`, `/images`, `/fps`, `/weather/config`
- `POST /anim/{name}` (JSON body = params) — start/switch and play
- `POST /animations/configure` — live param update; `POST /animations/reset`; `POST /animations/stop` (pauses)
- `POST /fps?new_fps=15`, `POST /serial/reconnect`
- `POST /weather/config` `{latitude, longitude, unit, interval_seconds}` — starts the background fetch loop; `POST /weather/refresh`
- `WS /ws/preview` — pushes `{width, height, bits}` JSON per frame; `GET /ui` — web UI

---

## Animations

Registered names: `bouncing_dot`, `clip`, `clock`, `composed`, `fluid`, `image`, `life`, `pendulum`, `simplex_noise`, `text`, `weather`, `wireframe_cube`.

Unregistered building blocks: `SupersampledAnimation` (render at N× and block-average for anti-aliasing), `AnalogClockAnimation` (used by `clock` with `style="analog"`), `WeatherIconAnimation` + `precipitation.py` effects (used by `weather`).

Interface (`flipdisc/animations/base.py`):

- `__init__(width, height)` — call `super().__init__(width, height, processing_steps=(...))`
- `step(dt)` — advance by dt seconds; the pipeline passes one display interval (`1 / refresh_rate`), so rates and speeds are in real units per second
- `render_gray()` -> `np.ndarray` shape `(height, width)`, float32 in [0, 1]
- `configure(**params)` — optional, runtime parameter changes
- `reset(seed=None)` / `is_complete()` — optional

### Composed animations

`ComposedAnimation` stacks independently-animated layers. Subclass it, wire layers in `__init__` with `compose()`, and register it (`flipdisc/animations/weather.py` is the reference example):

```python
@register_animation("weather_dashboard")
class WeatherDashboard(ComposedAnimation):
    def __init__(self, width, height):
        super().__init__(width, height)
        temp = TextAnimation(28, 7)
        temp.configure(text="--", mode="static", font="compact")
        self.compose([(temp, {"id": "temp", "x": 0, "y": 0})])

    @override
    def configure(self, **params):
        if "temp" in params:
            self._update_layer("temp", {"text": f"{params['temp']}F"})
        super().configure(**params)
```

- Layer layout keys: `id` (required), `x`, `y`, `blend` (`"over"` replaces, `"add"` is `np.maximum`), `visible`
- Live-update a layer: `POST /animations/configure {"layer.temp.text": "68F"}` (also `layer.<id>.visible` / `.blend`)
- Ad-hoc from the API: `POST /anim/composed {"layers": [{"id", "type", "x", "y", "width", "height", "params"}]}`
- Each layer's own `processing_steps` run before blitting, so `ComposedAnimation` itself uses `processing_steps=None`

---

## Things That Will Bite You

Verified behaviors that are easy to trip over. Delete an entry when you fix it.

- **Animation errors are reported through `/status`, not the HTTP response.** An unknown animation name is rejected with a 400. Anything that fails later on the generator thread — a `configure()` that raises, a constructor that fails, a `step()` that throws — is logged and recorded in `pipeline.last_error` on `GET /status`, while the request that caused it has already returned 200. A failed switch or configure leaves the current animation running; an animation that raises while running is dropped (`animation` becomes `null`) and the display holds its last frame until the next successful switch.
- **Live `configure` lags by up to `buffer_duration` (1 s).** The generator computes ahead to fill the frame buffer, so a parameter change only shows once the frames already queued have played out. Switching animations is immediate (it drains the buffer).
- **A slow animation plays in slow motion.** Each produced frame advances the animation by exactly one display interval, so if frames take longer than that to compute (`fluid` does today), the display falls behind real time instead of skipping.
- **Clips are GIFs** listed in `assets/clips/clips.toml` (create with `flipdisc/clips/importer.py`). Some docstrings still say `.npz`. No clips are checked in.
- **`[weather]` in `config.toml` is not parsed.** The fetch loop only starts via `POST /weather/config` (the web UI does this when you start `weather`).
- **`GET /images`** globs `assets/images/*.png`; the only images are `assets/images/weather/*.bmp`, so it returns `[]`.
- **`TextAnimation` fails silently in static mode** when text doesn't fit: `_text_image` is `None`, `_error` holds the reason, and the frame is blank.
- **`binarize` is strict `> 0.5`** — a value of exactly 0.5 is off.
- **Web UI param controls are hard-coded** in `getAnimationParams()` in `flipdisc/web/static/app.js`; an animation without an entry there (e.g. `fluid`, `pendulum`) shows "No configurable parameters".

---

## Debugging: Terminal Frame Output

The fastest way to check animation output — no server needed:

```python
from flipdisc.gfx.terminal import print_frame, print_animation_frames
from flipdisc.animations.text import TextAnimation

anim = TextAnimation(28, 28)
anim.configure(text="HI", mode="static", font="compact")
print("error:", anim._error)        # check for silent failures
print("image:", anim._text_image)   # None = nothing will render
print_frame(anim.render_gray())     # █ lit, · dark

print_animation_frames(anim, n=6, dt=0.1)   # step through N frames
```

Run with `uv run python <script>` from the repo root. To see what the server is showing, open `/ui` or read `/ws/preview`.

- Composed animation shows nothing → check each layer: `print_frame(layer.anim.render_gray())` for `layer in anim._layers`
- Clip shows nothing → `ClipAnimation._clip is None` means `configure(name=...)` wasn't called
- Display frozen or unchanged after an API call → check `last_error` and `animation` in `GET /status`, then the server log for the traceback

---

## Conventions

- Ruff for linting and formatting (line-length 88, py311 target)
- Guard clauses and early returns over nested `if`s
- Catch specific exception types, not `except Exception`. Broad catches are acceptable only at thread/task crash barriers, and must log.
- Exception layering: lower layers raise typed `FlipDiscError` subclasses with context; the top level (API routes, loops) decides severity and HTTP status
- `@override` (from `typing`) on every overridden animation method
- Tests live in `flipdisc/tests/test_*.py`; no hardware or network access in tests (mock serial, patched httpx)
