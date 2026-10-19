# Writing Games

A game is an animation that takes input. Everything in `flipdisc/animations/CLAUDE.md` applies (sizes, `render_gray` shape and range, `PARAMS`, `Cadence`, `@override`, generator-thread rules); this file covers what's different.

## Adding a game

1. Create `flipdisc/games/<name>.py`. Subclass `Game` (`flipdisc/games/base.py`) and decorate with `@register_animation("<name>")`. Games share the animation registry, so the name must not collide with an animation's.
2. **Import the module in `flipdisc/games/__init__.py`.** `flipdisc/animations/__init__.py` imports `flipdisc.games`, so that is all registration needs.
3. Declare `CONTROLS` and implement `on_press` (and `on_release` if anything happens while an action is held).
4. Add `flipdisc/tests/test_<name>.py`. Drive the game by calling `handle_input` and `step` directly and assert on its state; `flipdisc/tests/test_games.py` has a minimal game (`_Cursor`) to copy from.
5. Play it: start the server, pick the game under **Games** in `/ui`, and use the keys listed under the preview.

## Controls

```python
CONTROLS = (
    Control("left", "Move left", keys=("ArrowLeft", "KeyA")),
    Control("rotate", "Rotate", keys=("ArrowUp", "KeyW")),
    Control("drop", "Hard drop", keys=("Space",)),
)
```

- **Actions, not keys.** The server and the game only ever see action names. Keys are defaults for keyboard clients, as `KeyboardEvent.code` values; a phone app or a camera would send the same actions. Name actions for what they do in the game.
- **`on_press(action)` / `on_release(action)`** are called once per press and release. Keyboard auto-repeat never arrives as a new press: the UI drops repeats, and `handle_input` ignores a press of an action already held.
- **`self.held`** is the set of actions held right now. Anything that continues or repeats while held (soft drop, auto-shift) checks it in `step()` and paces itself with `Cadence`, like any whole-step motion.
- Don't override `handle_input`; it validates the action and maintains `held`.
- `reset()` clears `held`; call `super().reset(seed)` if you override it.

## Timing

- **Frames are made on demand** (`FRAMES_ON_DEMAND = True`). At each presenter tick the pipeline applies every input received so far, calls `step(1 / refresh_rate)` once, and renders. A press therefore affects the very next step and frame; there is no buffer to play out.
- **That makes `step` + `render_gray` part of the latency.** Keep them well under a millisecond or two; a game that misses the tick shows its frame a tick late.
- Game time advances in whole ticks at the display's frame rate, like animations. Express speeds in units per second and step them with `Cadence` (a piece falling 2 rows/s, a snake moving 8 cells/s).
- Input between ticks is applied in the order it arrived, all before the step. A game that needs "pressed and released within one tick" to count (a tap) gets both calls before that step, so act in `on_press`, not by checking `held` in `step`.

## Display

- 28×28, one bit per dot, and every change is a physical flip. Prefer whole-cell motion and avoid redrawing what hasn't changed; the pipeline only sends panels whose dots changed.
- Use the compact font (3×5) for scores or messages (`flipdisc/fonts/`).
