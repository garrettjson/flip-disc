# How the Current Implementation Works

A walkthrough of what the code does today, traced from the source. It describes behavior as it is, including the rough edges; `CLAUDE.md` holds the design goals, and `docs/hardware.md` holds the panel facts.

File references are to `flipdisc/`.

---

## 1. Processes and threads

One Python process runs three things:

| Where | What | Code |
|---|---|---|
| asyncio event loop (main thread) | FastAPI/uvicorn request handlers, the **presenter** task, the preview consumer task, the weather fetch loop | `web/api_server.py`, `engine/pipeline.py` |
| `GeneratorThread` (daemon thread) | The **generator**: owns the animation object and produces frames | `engine/pipeline.py` `_generator_loop` |
| aioserial's executor | Blocking serial writes, awaited by the presenter | `hardware/serial.py` |

The animation object is created, configured, stepped, and rendered **only on the generator thread**. The event loop never touches it; it communicates through the frame queue and a request queue (§4).

## 2. Startup

`python -m flipdisc run-server` → `cli.py` → `FlipDiscApplication.start` (`app.py`):

1. `load_config(path)` reads the TOML into a `DisplayConfig`. With no `--config`, it looks for `./config.toml`, then `./flipdisc.toml`, then falls back to built-in defaults. Only `[display]` and `[serial]` are read.
2. `DisplayPipeline(cfg)` builds the serial transport (mock unless `serial.mock = false`), the `ProtocolEncoder`, and the frame queue with capacity `max(1, int(refresh_rate * buffer_duration))` — 20 frames with the defaults (20 fps × 1 s).
3. `pipeline.start("bouncing_dot")` connects serial, queues the initial animation as the generator's first request, starts the generator thread, and starts the presenter task. **Nothing is displayed yet**: the generator waits until `play()` is called, which happens on the first `POST /anim/{name}`.
4. uvicorn serves the API.

`--reload` takes a different path: uvicorn imports `flipdisc.app:create_asgi_app` as a factory and manages the pipeline through a lifespan hook. The factory is called with no arguments, so in reload mode `--config` and `--log-level` are not passed through (config is discovered from the working directory).

## 3. The life of a frame

```
generator thread                                   event loop
────────────────                                   ──────────
anim.step(1/refresh_rate)
anim.render_gray()        float32 (H, W) in [0,1]
apply_processing_pipeline bool (H, W), or float32 0/1 if steps=None
queue.put(frame) ───────► queue.Queue(maxsize=20) ───────► presenter tick (every 1/refresh_rate s)
  blocks while full                                        frame == last written?  ── yes ─► skip write
                                                           split_canvas_bits_to_panels   list of (7, panel_w)
                                                           ProtocolEncoder.encode_batch  bytes
                                                           serial.write_frames
                                                           _last_frame = frame; frames_presented += 1
                                                           preview queue ◄── frame copy (changed or not)
```

### Generator loop (`_generator_loop`)

Each iteration, in order:

1. Apply every pending control request, in the order they were made (§4).
2. If not playing, wait up to 50 ms and retry.
3. If there is no animation (none has been built successfully, or the last one failed while running), wait 50 ms and retry.
4. `anim.step(frame_interval)`, then `anim.render_gray()`. The step is one display interval (`1 / refresh_rate`), read each iteration so `set_refresh_rate` takes effect immediately.
5. `apply_processing_pipeline(gray, anim.processing_steps)` (`gfx/postprocessing.py`): each named step in order. The default is `("binarize",)`, a strict `> 0.5` threshold producing a bool array. `None` skips processing — `ClipAnimation` and every `ComposedAnimation` (including `weather`) put **float32** 0/1 frames on the queue.
6. `queue.put(frame, timeout=0.05)`, retried until there is room or the pipeline stops.

Animation code can raise anything, so the thread has two crash barriers, both of which log the traceback and record a message for `get_status().last_error`:

- **Applying a request.** A failed switch or configure leaves the running animation untouched (a switch only drains the frame queue after the replacement has been built and configured).
- **Stepping and rendering.** The broken animation is dropped; the thread idles and the display holds its last frame until a switch succeeds.

Consequences worth knowing:

- **The generator runs ahead, then idles.** It fills the queue as fast as it can, then produces exactly one frame each time the presenter takes one. Every frame shown was computed up to `buffer_duration` (1 s) earlier.
- **A switch drains the queue; a configure does not.** A live `configure` becomes visible only after the frames already queued have played out.
- **One produced frame = one display interval of animation time.** Animation speeds are therefore in real units per second as long as the generator keeps up; when it can't, the display shows slow motion, not dropped frames.

### Presenter loop (`_present_loop`)

Deadline-paced: `next_deadline += frame_interval` each tick, then:

1. `queue.get_nowait()`. If the queue is empty, sleep to the deadline and try again — the display simply holds its last frame.
2. Compare with `_last_frame` using `np.array_equal`. **If identical, nothing is written to serial.**
3. Otherwise split, encode, `await serial.write_frames([batch])`, store a copy as `_last_frame`, and increment `frames_presented`.
4. Offer a copy to the preview queue (dropped if the queue is full).
5. Sleep until the deadline.

If a tick overruns (a slow write), the deadline is not reset, so the loop runs without sleeping until it catches up. An exception in the loop is re-raised as `HardwareError` inside the task; nothing awaits that task until shutdown, so a serial failure stops the display without an immediate visible error.

### Frame → bytes

- `split_canvas_bits_to_panels` (`hardware/panel_map.py`) reshapes the `(height, width)` canvas into `rows × columns` panels of shape `(7, panel_w)`, **row-major: left to right, then top to bottom**. It assumes identical, unrotated panels and raises `FrameError` on a shape mismatch.
- `encode_batch` (`hardware/protocol.py`) emits one message per panel at address `address_base + index`, then one flush. Panel bits go through `astype(np.uint8)`, so a float frame is truncated (0.99 → 0); only exact 0/1 values survive as intended.
- Each panel message is `0x80, cmd, address, <one byte per column, bit 0 = top dot>, 0x8F`. With the default config (four 28x7 strips) the batch is 4 × 32 + 3 = 131 bytes: `80 84 01 … 8F`, `80 84 02 … 8F`, `80 84 03 … 8F`, `80 84 04 … 8F`, then `80 82 8F`.

Byte-level details and timings are in `docs/hardware.md` §6–7.

### Serial transports (`hardware/serial.py`)

- `MockSerialTransport` — logs at DEBUG and sleeps ~1 ms per write. Used whenever `serial.mock = true` (the default).
- `HardwareSerialTransport` — `aioserial.AioSerial(port, baudrate, timeout)` with pyserial's default 8N1 framing. A short write or any `SerialException`/`OSError` becomes `SerialConnectionError`.

## 4. Control path: API → generator

HTTP handlers run on the event loop and call `DisplayPipeline` methods. None of them touch the animation; they hand a request to the generator, which applies it at the top of its next iteration:

| Pipeline method | Handoff | Applied by generator as |
|---|---|---|
| `set_animation(name, params)` | `_requests` ← `("switch", …)` | construct, configure, then drain the frame queue |
| `configure_animation(params)` | `_requests` ← `("configure", …)` | `anim.configure(**params)` |
| `reset()` | `_requests` ← `("reset", None)` | `anim.reset()` |
| `play()` / `pause()` | `_play_event` | run / idle |

All three request kinds go onto one `queue.SimpleQueue` and are applied in order, so:

- The HTTP response is sent **before** the change is applied. An unknown animation name is caught up front (`AnimationError` → 400); any later failure shows up only in `last_error` on `GET /status`.
- Requests are not lost or reordered: a switch followed immediately by a configure applies both, to the new animation.
- `last_error` is cleared by the next successful switch, or by a later success of the same kind of request.
- `POST /animations/stop` only pauses the generator; the presenter keeps running and plays out whatever is queued.
- `set_refresh_rate` changes the presenter's interval only. The queue capacity was fixed at construction.

## 5. Preview and web UI

- `WS /ws/preview` registers a callback with `set_preview_callback`. The presenter drops each frame into an `asyncio.Queue(maxsize=1)`; a consumer task fires the callback, which sets an event; the handler then sends `get_last_frame_bits()` as JSON `{width, height, bits}`.
- **One preview client at a time.** Registering a callback replaces the previous one, and a disconnecting client clears it, which also stops the preview for any other connected client.
- The preview shows `_last_frame`, i.e. the last frame *written to serial*, so it mirrors what the panels were told to show.
- The UI (`web/index.html`, `web/static/app.js`) is static files with no build step. It lists animations from `GET /animations`, but the parameter controls for each animation are a hard-coded table in `getAnimationParams()`.

## 6. Animations

`animations/base.py` defines the `Animation` ABC and a module-level registry filled by `@register_animation(name)` at import time; `animations/__init__.py` imports every module so they register. `get_animation(name, w, h)` instantiates by name.

Three families:

Motion comes in two kinds (`flipdisc/animations/CLAUDE.md`, "Motion"): whole-step motion (text scroll, precipitation, `bouncing_dot`, `life` generations) goes through `Cadence` (`animations/cadence.py`), which snaps the requested rate to an even number of frames per step; continuous motion (`wireframe_cube`, `pendulum`, `fluid`, `simplex_noise`) scales by `dt`.

- **Direct** — subclass `Animation`, draw into a `(height, width)` float array: `bouncing_dot`, `life`, `pendulum`, `simplex_noise`, `text`, `clock`, `image`, `clip`, `fluid`.
- **Supersampled** — subclass `SupersampledAnimation`, draw at N× resolution in `render_hires()`; the base class block-averages down so edges binarize cleanly: `wireframe_cube`, and `AnalogClockAnimation` (used by `clock` when `style="analog"`).
- **Composed** — `ComposedAnimation` holds a list of layers, each an independent animation with a position, blend mode, and visibility. On each render it runs every layer's own processing steps, then blits ("over" replaces, "add" is `np.maximum`). `weather` is the main example: a full-canvas `WeatherIconAnimation` (icon bitmap + precipitation particle effects from `precipitation.py`) plus a `TextAnimation` for the temperature, with the degree symbol drawn on top in an overridden `render_gray()`.

Assets are found by **working-directory-relative paths** (`assets/text/fonts.toml`, `assets/clips/clips.toml`, `assets/images`), except the weather icons, which are resolved relative to the source file. Fonts are bitmap sprite sheets sliced by the parameters in `fonts.toml` (`fonts/loader.py`). Clips are GIFs decoded once and cached in memory (`clips/loader.py`).

## 7. Weather data flow

1. The UI (or any client) starts the `weather` animation, then `POST /weather/config` with latitude/longitude. That stores the settings **in the `ApiServer` instance** (not in config, not persisted) and starts `_weather_loop`.
2. Every `interval_seconds` (default 900), `fetch_weather` (`services/weather.py`) calls the Open-Meteo forecast API with httpx and returns a `WeatherData`: temperature, a condition name mapped from the WMO code, moon phase (`services/moon_phase.py`), and a sunrise/sunset progress value when within the transition window.
3. The loop calls `pipeline.configure_animation({...})` with those values. It does this for **whatever animation is running**, not only `weather`; other animations ignore the unknown keys.
4. Fetch failures are logged as warnings and retried on the next interval.

## 8. Errors

`exceptions.py` defines `FlipDiscError` with `ConfigurationError`, `SerialConnectionError`, `HardwareError`, `AnimationError`, and `FrameError`. Lower layers raise these with context; API routes translate `AnimationError` to 400 and other `FlipDiscError`s to 500. Because animation construction and configuration happen on the generator thread, the routes only see an unknown animation name; later failures are reported through `last_error` — see §3 and §4.

## 9. Tests

`flipdisc/tests/`, run with `uv run pytest -q`. Mostly unit tests on animations, fonts, clips, weather parsing (httpx mocked), moon phase, and the encoder (`test_formats.py`). `test_basic.py` and `test_pacing.py` start a real `DisplayPipeline` on the mock transport and sleep for real time, which is most of the suite's ~20 s. Nothing tests against hardware.
