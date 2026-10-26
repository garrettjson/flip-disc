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

Imports that are slow and needed by only some code paths are `lazy` (PEP 810), so they load on first use: scipy (blur, dither and sharpen in `gfx/postprocessing.py`, `life`, `fluid`), httpx (the first weather fetch), and in `cli.py` uvicorn and the server stack, which `preview` never touches. The first frame of an animation that uses scipy pays its import (a few hundred ms on the dev machine), which the frame buffer absorbs. The animation and game modules themselves are imported normally: they register when they run, so running with `-X lazy_imports=all` leaves the registry empty.

`--reload` takes a different path: uvicorn imports `flipdisc.app:create_asgi_app` as a factory and manages the pipeline through a lifespan hook. The factory is called with no arguments, so in reload mode `--config` and `--log-level` are not passed through (config is discovered from the working directory).

## 3. The life of a frame

```
generator thread                                   event loop
────────────────                                   ──────────
anim.step(1/refresh_rate)
anim.render_gray()        float32 (H, W) in [0,1]
apply_processing_pipeline bool (H, W), or float32 0/1 if steps=None
queue.put(frame) ───────► queue.Queue(maxsize=20) ───────► presenter tick (every 1/refresh_rate s)
  blocks while full                                        split_canvas_bits_to_panels   list of (7, panel_w)
                                                           panels changed since sent?  ── none ─► skip write
                                                           ProtocolEncoder.encode_panels  changed panels + flush
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

**On-demand frames (games).** When the animation has `FRAMES_ON_DEMAND` (every `Game` does), the switch sets `_on_demand` and the loop changes between steps 3 and 4: it waits on `_frame_wanted`, a `threading.Event` the presenter sets at each tick, waking every 50 ms to apply other requests. When the tick comes it applies all pending requests again (so input received up to that moment is in), then steps and renders as usual. Instead of `put`, `_hand_over` replaces whatever is in the queue with the new frame and sets the presenter's `_frame_ready` (an `asyncio.Event`, via `call_soon_threadsafe`). Nothing is computed ahead, so the buffer is effectively one frame and only exists for the handover.

Animation code can raise anything, so the thread has two crash barriers, both of which log the traceback and record a message for `get_status().last_error`:

- **Applying a request.** A failed switch or configure leaves the running animation untouched (a switch only drains the frame queue after the replacement has been built and configured).
- **Stepping and rendering.** The broken animation is dropped; the thread idles and the display holds its last frame until a switch succeeds.

Consequences worth knowing:

- **The generator runs ahead, then idles.** It fills the queue as fast as it can, then produces exactly one frame each time the presenter takes one. Every frame shown was computed up to `buffer_duration` (1 s) earlier. On-demand animations are the exception: each frame is computed at the tick that shows it.
- **A switch drains the queue; a configure does not.** A live `configure` becomes visible only after the frames already queued have played out (on the next tick for on-demand animations).
- **One produced frame = one display interval of animation time.** Animation speeds are therefore in real units per second as long as the generator keeps up; when it can't, the display shows slow motion, not dropped frames.

### Presenter loop (`_present_loop`)

Deadline-paced: `next_deadline += frame_interval` each tick, then:

1. `queue.get_nowait()`. If the queue is empty, sleep to the deadline and try again — the display simply holds its last frame. For an on-demand animation, `_request_frame` instead sets `_frame_wanted` and awaits `_frame_ready` until the tick's deadline. A frame that misses the deadline stays in the queue and is shown on the next tick without asking for another. Measured with the mock transport, input reaches the written frame 25 ms after it is sent on average and 50 ms at worst (one tick at 20 fps).
2. `_write_frame`: split into panels and compare each with what that panel was last sent (`_sent_panels`). **If none changed, nothing is written to serial.**
3. Otherwise encode only the changed panels plus the flush (`ProtocolEncoder.encode_panels`), `await serial.write_frames([batch])`, record what each panel now shows, store a copy as `_last_frame`, and increment `frames_presented`. `_sent_panels` is cleared by `start` and `reconnect_serial`, so the first frame after either sends every panel.
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
| `send_input(action, pressed)` | `_requests` ← `("input", …)` | `game.handle_input(action, pressed)` |
| `play()` / `pause()` | `_play_event` | run / idle |

All request kinds go onto one `queue.SimpleQueue` and are applied in order, so:

- **Validation happens before handoff.** `send_input` checks that the animation most recently requested is a game with that action (`validate_input`). `set_animation` and `configure_animation` call `validate_params(name, params)`, which checks the request against the animation class's declared `PARAMS` without needing an instance. An unknown animation, unknown parameter, wrong type, or out-of-range value raises `AnimationError`, which the routes return as a 400. `configure_animation` validates against the animation most recently *requested*, since a switch may still be in the queue.
- The HTTP response is sent **before** the change is applied, so anything that fails later (a missing clip or image file, a bad `layer.<id>.<key>` value, an animation bug) shows up only in `last_error` on `GET /status`.
- Requests are not lost or reordered: a switch followed immediately by a configure applies both, to the new animation.
- `last_error` is cleared by the next successful switch, or by a later success of the same kind of request.
- `POST /animations/stop` only pauses the generator; the presenter keeps running and plays out whatever is queued.
- `set_refresh_rate` changes the presenter's interval only. The queue capacity was fixed at construction.

## 5. Preview and web UI

- `WS /ws/preview` registers a callback with `set_preview_callback`. The presenter drops each frame into an `asyncio.Queue(maxsize=1)`; a consumer task fires the callback, which sets an event; the handler then sends `get_last_frame_bits()` as JSON `{width, height, bits}`.
- **One preview client at a time.** Registering a callback replaces the previous one, and a disconnecting client clears it, which also stops the preview for any other connected client.
- The preview shows `_last_frame`, i.e. the last frame *written to serial*, so it mirrors what the panels were told to show.
- `WS /ws/input` and `POST /input` take `{action, pressed}` and call `send_input`. The socket answers only bad messages, with `{"error": …}`.
- The UI (`web/index.html`, `web/static/app.js`) is static files with no build step. `GET /animations` returns the animation names, the game names (`games`), each one's parameter schema under `params`, and each game's controls under `controls`. While a game is playing, the UI lists its controls under the preview and sends the mapped keys over `/ws/input`, ignoring key auto-repeat and keys typed into form fields, and releasing held keys when the window loses focus. The rest of the form works as for animations: it builds its form from the schema (number inputs with min/max/step, checkboxes, selects for `choices`) and shows the server's message when a value is rejected. Changing a control sends just that one parameter to `POST /animations/configure`. The only hard-coded fields are latitude and longitude for the weather fetch loop, which configure the server's data source and are not animation parameters.
- The preview canvas draws each dot as a disc. A dot that changes animates a half-turn about its horizontal axis (`DISC` in `app.js`; the ~60 ms flip time is a visual guess, not measured on the panels). The animation is cosmetic and client-side only: the frames, and what is sent to serial, are unchanged.

## 6. Animations

`animations/base.py` defines the `Animation` ABC and a module-level registry filled by `@register_animation(name)` at import time; `animations/__init__.py` imports every module so they register. `get_animation(name, viewport)` instantiates by name.

Every animation is built for a `Viewport` (`animations/viewport.py`): a box of dots on a display. The pipeline and `preview` pass the whole display, `Viewport(cfg.width, cfg.height)`; a composed animation gives each layer `self.viewport.region(w, h)`, a smaller box on the same display. An animation fills its own box (`self.width`, `self.height`), but its sizes in design dots follow the display, so every layer draws with the same line weight as a full-screen animation would.

Each animation declares its parameters as a `PARAMS` tuple of `Param` (`animations/params.py`). That one declaration provides the defaults (`self.params` starts from it), the validation (`Animation.configure` coerces and range-checks, then calls the subclass's `on_configure` with clean values), and the schema the API serves to the UI. `ComposedAnimation` additionally lets `layer.<id>.<key>` keys through and validates them against the target layer when they are applied.

Three families:

Motion comes in two kinds (`flipdisc/animations/CLAUDE.md`, "Motion"): whole-step motion (text scroll, precipitation, `bouncing_dot`, `life` generations, `rain_splash` drops, `sandpile` pouring and rolling, `sort` operations) goes through `Cadence` (`animations/cadence.py`), which snaps the requested rate to an even number of frames per step; continuous motion (`wireframe_cube`, `pendulum`, `fluid`, `point_cloud`, `black_hole`, `simplex_noise`, `bouncing_balls`, `rip`) scales by `dt`.

- **Direct** — subclass `Animation`, draw into a `(height, width)` float array: `bouncing_dot`, `life`, `pendulum`, `simplex_noise`, `text`, `clock` (including `AnalogClockAnimation` for `style="analog"`), `image`, `clip`, `fluid`, `point_cloud`, `black_hole`, `bouncing_balls`, `rain_splash`, `rip`, `sandpile`, `sort`, `wireframe_cube`.

Sizes are designed on a 28-dot display. `Animation.__init__` gives every animation `self.scale`, a `DisplayScale` (`animations/scaling.py`) built from its viewport that converts them: fractions are of the animation's own box (`short_side`), while sizes in design dots follow the display; lengths grow with the display, objects more slowly, and lines slowest, so a bigger display gets finer detail rather than a zoomed-in picture. Lines, discs, rings, and blocks are painted with `gfx/draw.py`, which lights a dot when its centre falls inside the shape and visits only the dots near it, so edges are crisp and a shape costs the same at any display size. `rip` measures its tear against every dot (`draw.pixel_centres`), since a tear spans the whole display, and `bouncing_balls` draws its squashed balls all at once in its own `render_gray`. `sandpile` keeps every grain one dot: a bigger display pours more of them, as a wider stream. Text grows like an object but in a font's drawn sizes, never below its design height, and drops to a smaller size where it has to fit (`text.py`, `clock.py`, `Game.draw_score`).
- **Composed** — `ComposedAnimation` holds a list of layers, each an independent animation with a position, blend mode, and visibility. On each render it runs every layer's own processing steps, then blits ("over" replaces, "add" is `np.maximum`). `weather` is the main example: a full-canvas `WeatherIconAnimation` (icon bitmap + precipitation particle effects from `precipitation.py`) plus a `TextAnimation` for the temperature, with the degree symbol drawn on top in an overridden `render_gray()`.

Assets are found by **working-directory-relative paths** (`assets/text/fonts.toml`, `assets/clips/clips.toml`, `assets/images`), except the weather icons, which are resolved relative to the source file. Fonts are families of BDF bitmap sizes listed in `fonts.toml`, read the first time a family is used and kept (`fonts/loader.py`); text picks the size nearest the height it wants (`fonts/font.py`). Clips are GIFs decoded once and cached in memory (`clips/loader.py`); `ClipAnimation` shrinks one larger than the display to fit it when it is configured, box-averaging each frame, optionally averaging over frames (`smoothing`), and lighting cells more than half covered or the densest `coverage` share of each frame.

## 7. Weather data flow

1. The UI (or any client) starts the `weather` animation, then `POST /weather/config` with latitude/longitude. That stores the settings **in the `ApiServer` instance** (not in config, not persisted) and starts `_weather_loop`.
2. Every `interval_seconds` (default 900), `fetch_weather` (`services/weather.py`) calls the Open-Meteo forecast API with httpx and returns a `WeatherData`: temperature, a condition name mapped from the WMO code, moon phase (`services/moon_phase.py`), and a sunrise/sunset progress value when within the transition window.
3. The loop calls `pipeline.configure_animation({...})` with those values, but only while the `weather` animation is the one running (`_push_weather`); otherwise the fetched data is dropped.
4. Fetch failures are logged as warnings and retried on the next interval.

## 8. Errors

`exceptions.py` defines `FlipDiscError` with `ConfigurationError`, `SerialConnectionError`, `HardwareError`, `AnimationError`, and `FrameError`. Lower layers raise these with context; API routes translate `AnimationError` to 400 and other `FlipDiscError`s to 500. Because animation construction and configuration happen on the generator thread, the routes only see an unknown animation name; later failures are reported through `last_error` — see §3 and §4.

## 9. Tests

`flipdisc/tests/`, run with `uv run pytest -q`. Mostly unit tests on animations, fonts, clips, weather parsing (httpx mocked), moon phase, and the encoder (`test_formats.py`). `test_basic.py` and `test_pacing.py` start a real `DisplayPipeline` on the mock transport and sleep for real time, which is most of the suite's ~20 s. Nothing tests against hardware.

## 10. Measuring frame cost

Python 3.15's sampling profiler (Tachyon) reads a running process's stacks without changing any code, which makes it the tool for measuring frame cost on the Pi:

```
python -m profiling.sampling attach -a --sort tottime -d 10 <server pid>
python -m profiling.sampling run -a --sort tottime -m flipdisc preview -a fluid -n 200
```

`-a` samples every thread; without it only the main thread is sampled, and animations run on the generator thread. `--flamegraph -o out.html` writes a flame graph instead. On macOS both forms need `sudo -E`. On Linux, attaching may need it too, depending on the kernel's ptrace setting; this hasn't been tried on the Pi.
