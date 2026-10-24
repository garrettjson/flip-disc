"""Snake: steer a growing snake to the food without hitting a wall or itself.

The board is the whole display. The game waits on its first frame until a
direction is pressed; when the snake dies it flashes, then the score is shown
until start is pressed.
"""

from collections import deque
from enum import Enum, auto
from typing import override

import numpy as np

from flipdisc.animations.base import register_animation
from flipdisc.animations.cadence import Cadence
from flipdisc.animations.params import Param
from flipdisc.fonts.loader import load_font

from .base import Control, Game

_DIRECTIONS = frozendict(
    {
        "up": (0, -1),
        "down": (0, 1),
        "left": (-1, 0),
        "right": (1, 0),
    }
)

# Turns pressed faster than the snake moves wait their turn, so a quick
# up-then-left squeezes round a corner. More than two would feel laggy.
_MAX_QUEUED_TURNS = 2

# Food blinks off briefly so it stands out from the snake; each blink is two
# flips of one disc
_FOOD_BLINK_PERIOD = 0.5  # s
_FOOD_OFF_TIME = 0.125  # s

# On death the snake flashes this many times before the score shows
_DEATH_FLASHES = 3
_DEATH_FLASH_PERIOD = 0.3  # s


class _State(Enum):
    READY = auto()  # waiting for the first direction
    PLAYING = auto()
    DYING = auto()  # flashing; input ignored
    OVER = auto()  # showing the score until start is pressed


@register_animation("snake")
class Snake(Game):
    """Classic snake on the full display."""

    PARAMS = (
        Param("speed", float, 7.0, min=1, max=20, step=1, unit="cells/s"),
        # False wraps the snake round to the opposite edge
        Param("walls", bool, True),
        # Applies from the next game
        Param("start_length", int, 3, min=1, max=10),
    )

    CONTROLS = (
        Control("up", "Up", keys=("ArrowUp", "KeyW")),
        Control("down", "Down", keys=("ArrowDown", "KeyS")),
        Control("left", "Left", keys=("ArrowLeft", "KeyA")),
        Control("right", "Right", keys=("ArrowRight", "KeyD")),
        Control("start", "Start / new game", keys=("Space", "Enter")),
    )

    def __init__(self, width: int, height: int):
        super().__init__(width, height, processing_steps=None)
        self._font = load_font("standard")
        self._new_game()

    def _new_game(self) -> None:
        self._state = _State.READY
        self._move = Cadence()
        self._state_time = 0.0
        self.score = 0

        length = min(self.params["start_length"], max(1, self.width - 1))
        tail_x = max(0, self.width // 2 - length // 2)
        y = self.height // 2
        # Head first
        self.body: deque[tuple[int, int]] = deque(
            (tail_x + i, y) for i in reversed(range(length))
        )
        self.heading = _DIRECTIONS["right"]
        self._turns: list[tuple[int, int]] = []
        self.food: tuple[int, int] | None = None
        self._place_food()

    def _place_food(self) -> None:
        occupied = set(self.body)
        free = [
            (x, y)
            for y in range(self.height)
            for x in range(self.width)
            if (x, y) not in occupied
        ]
        self.food = free[np.random.randint(len(free))] if free else None

    def _turn(self, direction: tuple[int, int]) -> None:
        """Queue a turn, unless it's no change or a reversal into the body."""
        planned = self._turns[-1] if self._turns else self.heading
        reverse = (-planned[0], -planned[1])
        if direction == planned or (direction == reverse and len(self.body) > 1):
            return
        if len(self._turns) < _MAX_QUEUED_TURNS:
            self._turns.append(direction)

    @override
    def on_press(self, action: str) -> None:
        if action == "start":
            if self._state is _State.OVER:
                self._new_game()
            elif self._state is _State.READY:
                self._state = _State.PLAYING
            return

        direction = _DIRECTIONS[action]
        if self._state is _State.READY:
            self._state = _State.PLAYING
            # Before the first move any direction goes, even straight back
            if direction == (-self.heading[0], -self.heading[1]):
                self.body.reverse()
                self.heading = direction
        if self._state is _State.PLAYING:
            self._turn(direction)

    def _advance(self) -> None:
        """Move one cell: turn, then eat, die, or just move."""
        if self._turns:
            self.heading = self._turns.pop(0)
        x, y = self.body[0]
        head = (x + self.heading[0], y + self.heading[1])

        if self.params["walls"]:
            if not (0 <= head[0] < self.width and 0 <= head[1] < self.height):
                self._die()
                return
        else:
            head = (head[0] % self.width, head[1] % self.height)

        eating = head == self.food
        # The tail moves out of the way this move, unless the snake grows
        body = list(self.body) if eating else list(self.body)[:-1]
        if head in body:
            self._die()
            return

        self.body.appendleft(head)
        if not eating:
            self.body.pop()
            return
        self.score += 1
        self._place_food()
        if self.food is None:  # the snake fills the board
            self._die()

    def _die(self) -> None:
        self._state = _State.DYING
        self._state_time = 0.0

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        self._state_time += dt

        if self._state is _State.PLAYING:
            for _ in range(self._move.advance(self.params["speed"], dt)):
                self._advance()
                if self._state is not _State.PLAYING:
                    break
        elif (
            self._state is _State.DYING
            and self._state_time >= _DEATH_FLASHES * _DEATH_FLASH_PERIOD
        ):
            self._state = _State.OVER

    @override
    def render_gray(self) -> np.ndarray:
        frame = np.zeros((self.height, self.width), dtype=np.float32)
        if self._state is _State.OVER:
            self._draw_score(frame)
            return frame

        flashing_off = (
            self._state is _State.DYING
            and (self._state_time % _DEATH_FLASH_PERIOD) >= _DEATH_FLASH_PERIOD / 2
        )
        if not flashing_off:
            for x, y in self.body:
                frame[y, x] = 1.0

        food_off = (self.current_time % _FOOD_BLINK_PERIOD) < _FOOD_OFF_TIME
        if self.food is not None and not food_off and self._state is not _State.DYING:
            frame[self.food[1], self.food[0]] = 1.0
        return frame

    def _draw_score(self, frame: np.ndarray) -> None:
        text = self._font.render_line(str(self.score))
        h, w = text.shape
        if w > self.width or h > self.height:
            return
        top = (self.height - h) // 2
        left = (self.width - w) // 2
        frame[top : top + h, left : left + w] = text

    @override
    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        self._new_game()
