# Flip-Disc

Python flip-disc display controller for Raspberry Pi. Drives flip-dot panels over RS-485 via a FastAPI server with a threaded pipeline (Generator thread -> Presenter async task).

## What This Project Does

Flip-disc displays are mechanical panels where each pixel is a small magnetic disc — one side painted (visible), one side dark. Flipping a disc requires sending a physical pulse over RS-485 serial. This project controls a grid of those panels from a Raspberry Pi.

The system has three concerns:

1. **Content** — animations produce grayscale frames (NumPy float arrays) that get binarized to 1-bit. They run continuously in a background thread.
2. **Transport** — frames are encoded into RS-485 protocol packets and written to the serial port at the configured refresh rate. In mock mode (default) this is a no-op, so you can develop without hardware.
3. **Control** — a FastAPI server exposes HTTP endpoints, a WebSocket preview, and a small web UI so external systems can start/stop animations and push live updates.

### Display Hardware

The default config (`config.toml`) is a **28×28 display** made from a 2×4 grid of 14×7 panels:

- `panel_type = "14x7"`, `columns = 2`, `rows = 4` → 28px wide × 28px tall
- `refresh_rate = 20.0` fps
- The standard font (5×7px glyphs) renders `"HELLO"` at 29px wide — 1px too wide. Use the **compact font** (3×5px) or keep text short.

Wire protocol reference: `flipdisc/hardware/PROTOCOL.md`.

---

## Commands

Run everything **from the repo root** — fonts, clips, and config are loaded via cwd-relative paths (`assets/...`, `config.toml`).

- Install: `uv sync --extra dev` (Python 3.11+)
- Test: `uv run pytest -q` (~25s)
- Lint: `uv run ruff check --fix`
- Format: `uv run ruff format`
- Server: `uv run python -m flipdisc run-server --config config.toml` (add `--reload` for hot reload); UI at `http://localhost:8000/ui`, OpenAPI at `/docs`
- Terminal preview: `uv run python -m flipdisc preview -a <name> -n 5` (`--list` for names; default params only)

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
- **Cross-thread requests** are plain attribute swaps picked up by the generator on its next iteration: `_anim_request` (switch; drains the queue), `_configure_request`, `_reset_requested`. So `set_animation` / `configure_animation` / `reset` return before the change is applied, and errors raised while applying them never reach the HTTP caller.

### DisplayPipeline public API

All async except `get_status()`, `get_last_frame_bits()`, `set_preview_callback()`:

- `start(animation, params)` / `stop()` — lifecycle
- `play()` / `pause()` — playback control
- `set_animation(name, params)` — switch animation
- `configure_animation(params)` — update params on the running animation in place
- `reset()` — reset current animation state
- `get_status()` -> `PipelineStatus(running, playing, frames_presented, buffer_capacity)`
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
- `step(dt)` — advance simulation by dt seconds
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

- **Exceptions on the generator thread kill it silently.** An unknown animation name, or a `configure()` that raises (e.g. `clip` with an unknown `name` -> `KeyError`), is logged as "Generator thread crashed" and the thread exits; the API has already returned 200 and the display freezes until the server restarts. `configure()` must not raise on bad input.
- **Simulation time is not wall-clock time.** The generator calls `step(1/60)` exactly once per produced frame. At 20 fps the sim advances 1/3 s per real second, so speeds in "units per second" run at 1/3 of nominal on the display (animations that read `datetime.now()`, like `clock`, are unaffected). The `preview` CLI takes 3 steps per printed frame, so it shows motion ~3× faster than the display does.
- **Clip playback** advances `fps / 60` clip frames per presented frame — a clip needs `fps = 60` to show one clip frame per display frame.
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
- Display frozen after an API call → look for "Generator thread crashed" in the server log

---

## Conventions

- Ruff for linting and formatting (line-length 88, py311 target)
- Guard clauses and early returns over nested `if`s
- Catch specific exception types, not `except Exception`. Broad catches are acceptable only at thread/task crash barriers, and must log.
- Exception layering: lower layers raise typed `FlipDiscError` subclasses with context; the top level (API routes, loops) decides severity and HTTP status
- `@override` (from `typing`) on every overridden animation method
- Tests live in `flipdisc/tests/test_*.py`; no hardware or network access in tests (mock serial, patched httpx)
