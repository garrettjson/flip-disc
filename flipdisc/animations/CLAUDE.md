# Writing Animations

## Adding a new animation

1. Create `flipdisc/animations/<name>.py`. Subclass `Animation` (or `SupersampledAnimation` for anti-aliased vector-style drawing, or `ComposedAnimation` for layered layouts) and decorate with `@register_animation("<name>")`.
2. **Import the module in `flipdisc/animations/__init__.py`** (both the import tuple and `__all__`). Registration happens at import time; without this the animation doesn't exist.
   A family of animations sharing most of their code can be a subpackage instead (`sorting/`): import the subpackage here, and have its `__init__.py` import its modules.
3. Add `flipdisc/tests/test_<name>.py`. `test_fluid.py` is a good small template: construct, step, assert shape/dtype/value range, check `configure` and `reset`.
4. Declare its parameters in `PARAMS` (see "Parameters" below). The API validation and the web UI's controls come from that declaration; there is nothing to add in `app.js`.
5. Look at real frames before calling it done: `uv run python -m flipdisc preview -a <name> -n 5`, or `print_animation_frames` for non-default params.

## Rules of the road

- **Never hard-code 28×28.** Use `self.width` / `self.height`. Animations get instantiated at other sizes as layers inside a `ComposedAnimation` (e.g. `TextAnimation(27, 7)`), and the panel grid is configurable.
- **`render_gray()` returns shape `(height, width)`, float32, values in [0, 1].** Row index first. Return a fresh array or one you won't mutate later — frames are queued.
- **Declare every parameter and read defaults from `self.params`.** See "Parameters" below.
- **`step(dt)` receives one display interval** (`1 / refresh_rate`, so 0.05 s at 20 fps) once per produced frame, and should do `self.current_time += dt`. Express rates in real units per second; never advance a fixed amount per call, or the animation's speed will change with the frame rate.
- **Whole-step motion uses `Cadence`; continuous motion scales by `dt`.** See "Motion" below — this is the default pattern, not an optimization.
- **`__init__`, `on_configure`, `step`, `render_gray`, and `reset` all run on the generator thread.** Don't touch asyncio objects or block on I/O in them; load assets once and cache.
- **`processing_steps`** defaults to `("binarize",)`. Pass `None` when the output is already 1-bit or when layers handle their own processing (`ClipAnimation`, `ComposedAnimation`).
- **Finite animations** set `self._completed = True` when done; `is_complete()` reports it.
- Put `@override` on every overridden method.
- **Too slow? Profile, then NumPy.** Most speedups come from replacing Python loops with whole-array NumPy operations (`gfx/noise.py` and `wireframe_cube`'s `_draw_line` are examples). On 28×28 frames, many tiny NumPy calls cost more than their arithmetic, so fewer, larger operations win. Numba isn't a dependency; see "Performance" under Design Intent in the root `CLAUDE.md` before reaching for it.
- Import scipy (or another slow library only your animation needs) with `lazy from scipy.ndimage import convolve`, so server startup and other animations don't pay for it. Never make the import in `__init__.py` lazy: that's what registers the animation.

## Parameters

```python
@register_animation("wireframe_cube")
class WireframeCube(SupersampledAnimation):
    PARAMS = (
        Param("size", float, 0.35, min=0.1, max=0.5, step=0.05),
        Param("rotation_speed", float, 0.35, min=-5, max=5, unit="rad/s"),
    )

    def __init__(self, width, height):
        super().__init__(width, height)
        self.size = self.params["size"]                  # defaults come from PARAMS
        self.rotation_speed = self.params["rotation_speed"]

    @override
    def on_configure(self, **params):
        if "size" in params:
            self.size = params["size"]                   # already a float in range
```

- **`PARAMS` is the only place a default lives.** `Animation.__init__` fills `self.params` from it; read initial values from there instead of repeating literals in `__init__`.
- **Implement `on_configure`, not `configure`.** The base class's `configure` validates and coerces, updates `self.params`, then calls `on_configure` with only the keys that were passed. No `float(...)`, clamping, or "is this a valid mode" checks are needed inside it.
- **Types:** `float`, `int`, `bool`, `str`, `list`. Use `min`/`max` for numbers and `choices` for enumerations; `choices` may be a callable for lists read from disk (`choices=list_fonts`). `strict=False` makes choices suggestions only — use it when an unlisted value has a sensible fallback (weather `condition`) or the list can't be trusted at validation time (clip `name`).
- **`nullable=True` with `default=None`** means "not set / decide automatically". Check `params.get("x") is not None` before using it.
- **`unit`, `label`, `step`** only affect the web UI.
- **Ranges are enforced**, so set them to what the animation can actually handle, not to what looks tidy in a form. A test (`test_params.py`) checks that every animation's defaults satisfy its own declarations.
- **A parameter whose change resets state** (life `density`, fluid `fill_level`, pendulum `initial_angle`) should say so in a comment: the UI sends a single changed key, but API clients may send several.
- What can still go wrong after validation — a file that doesn't exist, text too wide to fit — should not raise from `on_configure` if a fallback exists; record it (see `TextAnimation._error`). An exception there surfaces only as `last_error` in `GET /status`.

## Motion

Every dot that flips is seen and heard, so the *rhythm* of motion matters as much as its speed. There are two kinds of motion, and each has one way to do it:

- **Whole-step motion** — anything that moves in whole pixels or discrete events: scrolling text, falling particles, a dot moving cell to cell, automaton generations, spawn events. **Use `Cadence`** (`flipdisc/animations/cadence.py`):

  ```python
  self._scroll = Cadence()
  ...
  def step(self, dt):
      self._offset += self._scroll.advance(self._speed, dt)   # whole pixels
  ```

  `advance(rate, dt)` returns how many whole steps to take this frame. It snaps the requested rate to the nearest one the frame rate can play evenly (a whole number of frames per step, or of steps per frame) and counts frames, so the gap between moves never varies. The parameter stays in units per second; at 20 fps a requested 7 px/s plays as one pixel every 3 frames (6.67 px/s). `Cadence.snapped_rate(rate, dt)` reports the delivered rate. Call `reset()` when the motion restarts. Don't accumulate `rate * dt` and move when it crosses an integer — that produces an irregular rhythm (3, 3, 3, 2, …) at most rates.

- **Continuous motion** — values that are rasterized rather than stepped: rotation angles, physics positions, noise time. Scale by `dt` directly (`self.angle += self.rotation_speed * dt`). For physics that needs small steps, substep internally with a fixed substep size (see `fluid.py`).

Wall-clock content (`clock`) reads the system time and needs neither.

## Sorting algorithms

`sort` (`sorting/base.py`) plays any algorithm registered with `@sort_algorithm("<name>")`, which becomes an `algorithm` choice. To add one, write a generator in `sorting/<name>.py` that sorts the list it's given in place and yields a tuple of the indices to highlight after every operation (one comparison, with the swap or write it leads to), then import it in `sorting/__init__.py`. `bubble.py` is the template. `test_sort.py` checks every registered algorithm sorts and yields valid indices.

## Layering

Inside a `ComposedAnimation` subclass, declare the high-level params in `PARAMS`, route them to layers with `self._update_layer(layer_id, {...})` in `on_configure()`, then call `super().on_configure(**params)` so dotted `layer.<id>.<key>` updates keep working. `weather.py` shows the full pattern, including reusing another animation's declarations (`ICON_PARAMS`) and drawing extra pixels on top of the composed canvas by overriding `render_gray()`.
