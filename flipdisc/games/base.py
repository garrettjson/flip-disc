"""Base class for interactive games.

A game is an animation that also takes input. It keeps the whole animation
interface (``step``, ``render_gray``, ``PARAMS``, the registry), so the
pipeline, preview, and API run it like any animation, with two differences:

- It declares ``CONTROLS``: the named actions it responds to. Input arrives as
  an action being pressed or released, never as a key, so a keyboard, a phone,
  or a camera can all drive the same game. Each control lists default keys for
  clients that have a keyboard.
- Its frames are made on demand (``FRAMES_ON_DEMAND``): at each presenter tick
  the pipeline applies every input received so far, steps the game once, and
  renders, so a press shows on the very next frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from flipdisc.animations.base import (
    Animation,
    get_animation_class,
    list_animations,
)
from flipdisc.exceptions import AnimationError


@dataclass(frozen=True)
class Control:
    """One action a game responds to."""

    action: str  # what clients send, e.g. "left"
    label: str  # shown to players, e.g. "Move left"
    # Default keyboard keys, as KeyboardEvent.code values ("ArrowLeft", "KeyA")
    keys: tuple[str, ...] = ()

    def to_schema(self) -> dict[str, Any]:
        return {"action": self.action, "label": self.label, "keys": list(self.keys)}


class Game(Animation):
    """Base class for games.

    Subclasses implement ``step``/``render_gray`` like any animation, declare
    ``CONTROLS``, and react to input in ``on_press`` / ``on_release``.
    ``self.held`` is the set of actions currently held down, for anything that
    repeats or continues while held (soft drop, auto-repeat).
    """

    CONTROLS: ClassVar[tuple[Control, ...]] = ()
    FRAMES_ON_DEMAND = True

    def __init__(
        self,
        width: int,
        height: int,
        processing_steps: tuple[str, ...] | None = ("binarize",),
    ):
        super().__init__(width, height, processing_steps=processing_steps)
        self.held: set[str] = set()

    @classmethod
    def validate_action(cls, action: str) -> None:
        actions = [c.action for c in cls.CONTROLS]
        if action not in actions:
            raise AnimationError(
                f"Unknown action for {cls.__name__}: {action!r}. "
                f"Available: {', '.join(actions) or 'none'}"
            )

    @classmethod
    def controls_schema(cls) -> list[dict[str, Any]]:
        return [c.to_schema() for c in cls.CONTROLS]

    def handle_input(self, action: str, pressed: bool) -> None:
        """Apply one press or release. Not meant to be overridden.

        A press of an action already held is ignored (keyboard auto-repeat is
        not a new press), as is a release of one not held.
        """
        self.validate_action(action)
        if pressed:
            if action in self.held:
                return
            self.held.add(action)
            self.on_press(action)
        else:
            if action not in self.held:
                return
            self.held.discard(action)
            self.on_release(action)

    def on_press(self, action: str) -> None:
        """React to an action being pressed."""

    def on_release(self, action: str) -> None:
        """React to an action being released."""

    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        self.held.clear()


def is_game(name: str) -> bool:
    return issubclass(get_animation_class(name), Game)


def list_games() -> list[str]:
    return [name for name in list_animations() if is_game(name)]


def game_controls() -> dict[str, list[dict[str, Any]]]:
    """Controls of every registered game, keyed by name."""
    return {name: get_animation_class(name).controls_schema() for name in list_games()}


def validate_input(name: str, action: str) -> None:
    """Check that ``name`` is a game and ``action`` is one of its controls."""
    cls = get_animation_class(name)
    if not issubclass(cls, Game):
        raise AnimationError(f"{name} is not a game and takes no input")
    cls.validate_action(action)
