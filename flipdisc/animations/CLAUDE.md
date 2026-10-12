# Writing Animations

## Adding a new animation

1. Create `flipdisc/animations/<name>.py`. Subclass `Animation` (or `SupersampledAnimation` for anti-aliased vector-style drawing, or `ComposedAnimation` for layered layouts) and decorate with `@register_animation("<name>")`.
2. **Import the module in `flipdisc/animations/__init__.py`** (both the import tuple and `__all__`). Registration happens at import time; without this the animation doesn't exist.
3. Add `flipdisc/tests/test_<name>.py`. `test_fluid.py` is a good small template: construct, step, assert shape/dtype/value range, check `configure` and `reset`.
4. If it should have controls in the web UI, add an entry to `getAnimationParams()` in `flipdisc/web/static/app.js`.
5. Look at real frames before calling it done: `uv run python -m flipdisc preview -a <name> -n 5`, or `print_animation_frames` for non-default params.

## Rules of the road

- **Never hard-code 28×28.** Use `self.width` / `self.height`. Animations get instantiated at other sizes as layers inside a `ComposedAnimation` (e.g. `TextAnimation(27, 7)`), and the panel grid is configurable.
- **`render_gray()` returns shape `(height, width)`, float32, values in [0, 1].** Row index first. Return a fresh array or one you won't mutate later — frames are queued.
- **`configure()` must not raise on bad input.** It runs on the generator thread; an exception there kills the thread and freezes the display. Validate, fall back to a default, and record the problem (see `TextAnimation._error`). Params arrive as parsed JSON, so coerce types (`float(...)`, `bool(...)`). Always call `super().configure(**params)` so `self.params` stays current.
- **`step(dt)` receives `dt = 1/60`** once per produced frame and should do `self.current_time += dt`. Scale motion by `dt`; don't count frames. Sim time runs slower than wall-clock on the display (see root `CLAUDE.md`), so tune speeds by watching `/ui`, not by arithmetic.
- **`__init__`, `configure`, `step`, `render_gray`, and `reset` all run on the generator thread.** Don't touch asyncio objects or block on I/O in them; load assets once and cache.
- **`processing_steps`** defaults to `("binarize",)`. Pass `None` when the output is already 1-bit or when layers handle their own processing (`ClipAnimation`, `ComposedAnimation`).
- **Finite animations** set `self._completed = True` when done; `is_complete()` reports it.
- Put `@override` on every overridden method.

## Layering

Inside a `ComposedAnimation` subclass, route high-level params to layers with `self._update_layer(layer_id, {...})` in `configure()`, then call `super().configure(**params)` so dotted `layer.<id>.<key>` updates keep working. `weather.py` shows the full pattern, including drawing extra pixels on top of the composed canvas by overriding `render_gray()`.
