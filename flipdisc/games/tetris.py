"""Tetris: steer falling pieces into full rows, which flash and clear.

The well is the standard 10 cells wide by 20 tall, bordered, at the bottom
left. The next piece and the score show above it, and the level and the rows
cleared towards the next level (0-9) to its right at the bottom. Every ten
rows cleared is a level: pieces fall faster and clears score more. The game
waits with the first piece at the top until any control is pressed; when a
new piece has no room the well flashes, then the score is shown until start
is pressed.

Rotation follows the Super Rotation System (SRS), wall kicks included, and
pieces are dealt from a shuffled bag of all seven, so no kind goes more than
12 pieces without turning up.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import override

import numpy as np

from flipdisc.animations.base import register_animation
from flipdisc.animations.cadence import Cadence
from flipdisc.animations.params import Param
from flipdisc.fonts.loader import load_font

from .base import Control, Game

# The standard well, inside a one-dot border
_WELL_WIDTH = 10
_WELL_HEIGHT = 20

# Each piece's rotation box size and spawn cells (x, y), y down
_SHAPES = {
    "I": (4, ((0, 1), (1, 1), (2, 1), (3, 1))),
    "J": (3, ((0, 0), (0, 1), (1, 1), (2, 1))),
    "L": (3, ((2, 0), (0, 1), (1, 1), (2, 1))),
    "O": (2, ((0, 0), (1, 0), (0, 1), (1, 1))),
    "S": (3, ((1, 0), (2, 0), (0, 1), (1, 1))),
    "T": (3, ((1, 0), (0, 1), (1, 1), (2, 1))),
    "Z": (3, ((0, 0), (1, 0), (1, 1), (2, 1))),
}
_KINDS = tuple(_SHAPES)


def _rotations(size: int, cells: tuple[tuple[int, int], ...]):
    """The four orientations, each a quarter turn clockwise in the box."""
    out = [cells]
    for _ in range(3):
        cells = tuple((size - 1 - y, x) for x, y in cells)
        out.append(cells)
    return tuple(out)


_ROTATIONS = {kind: _rotations(*shape) for kind, shape in _SHAPES.items()}

# SRS wall kicks: the offsets tried in order when turning from one orientation
# to another (0 spawn, 1 right, 2 upside down, 3 left). Written (x, y) with y
# up, as SRS tables usually are. O never needs one.
_KICKS = {
    (0, 1): ((0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)),
    (1, 0): ((0, 0), (1, 0), (1, -1), (0, 2), (1, 2)),
    (1, 2): ((0, 0), (1, 0), (1, -1), (0, 2), (1, 2)),
    (2, 1): ((0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)),
    (2, 3): ((0, 0), (1, 0), (1, 1), (0, -2), (1, -2)),
    (3, 2): ((0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)),
    (3, 0): ((0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)),
    (0, 3): ((0, 0), (1, 0), (1, 1), (0, -2), (1, -2)),
}
_KICKS_I = {
    (0, 1): ((0, 0), (-2, 0), (1, 0), (-2, -1), (1, 2)),
    (1, 0): ((0, 0), (2, 0), (-1, 0), (2, 1), (-1, -2)),
    (1, 2): ((0, 0), (-1, 0), (2, 0), (-1, 2), (2, -1)),
    (2, 1): ((0, 0), (1, 0), (-2, 0), (1, -2), (-2, 1)),
    (2, 3): ((0, 0), (2, 0), (-1, 0), (2, 1), (-1, -2)),
    (3, 2): ((0, 0), (-2, 0), (1, 0), (-2, -1), (1, 2)),
    (3, 0): ((0, 0), (1, 0), (-2, 0), (1, -2), (-2, 1)),
    (0, 3): ((0, 0), (-1, 0), (2, 0), (-1, 2), (2, -1)),
}

# Points for clearing 1, 2, 3, or 4 rows with one piece, times the level: the
# guideline's 100/300/500/800 over 100, so the score fits beside the well
_LINE_POINTS = (0, 1, 3, 5, 8)

# Every ten rows cleared is a level, and each level falls faster
_LINES_PER_LEVEL = 10


def fall_speed(level: int) -> float:
    """Rows per second at a level, on the Tetris Guideline's curve: 1 at level
    1, about 2 at 4, 7 at 8, 16 at 10, and over 50 from 13."""
    return 1 / (0.8 - 0.007 * (level - 1)) ** (level - 1)


# Holding down falls at this speed (or the fall speed, if faster). A piece
# that lands while down is held locks, and the next piece only soft-drops
# once down is pressed again, so a held key doesn't carry into it.
_SOFT_DROP_SPEED = 20.0  # rows/s

# Holding left or right moves once, then repeats after a delay
_SHIFT_DELAY = 0.2  # s
_SHIFT_SPEED = 10.0  # cells/s

# Full rows flash off and on this many times before they clear
_CLEAR_FLASHES = 2
_CLEAR_FLASH_PERIOD = 0.2  # s

# When the game ends the well flashes this many times before the score shows
_OVER_FLASHES = 3
_OVER_FLASH_PERIOD = 0.3  # s

# The next piece is drawn at this many dots per cell
_PREVIEW_SCALE = 2


class _State(Enum):
    READY = auto()  # first piece shown at the top, waiting for any control
    PLAYING = auto()
    CLEARING = auto()  # full rows flashing; no piece in play
    DYING = auto()  # well flashing; input ignored
    OVER = auto()  # showing the score until start is pressed


@register_animation("tetris")
class Tetris(Game):
    """Single-player Tetris with a next-piece preview."""

    # Applies from the next game, or straight away before the first move
    PARAMS = (Param("start_level", int, 1, min=1, max=15),)

    CONTROLS = (
        Control("left", "Move left", keys=("ArrowLeft", "KeyA")),
        Control("right", "Move right", keys=("ArrowRight", "KeyD")),
        Control("down", "Soft drop (hold)", keys=("ArrowDown", "KeyS")),
        Control("rotate", "Rotate clockwise", keys=("ArrowUp", "KeyW", "KeyX")),
        Control("rotate_ccw", "Rotate anticlockwise", keys=("KeyZ",)),
        Control("drop", "Hard drop", keys=("Space",)),
        Control("start", "Start / new game", keys=("Enter",)),
    )

    def __init__(self, width: int, height: int):
        super().__init__(width, height, processing_steps=None)
        self._panel_font = load_font("compact")
        self._score_font = load_font("standard")
        # Border at the left and along the bottom, the next piece above
        self.well_width = max(1, min(_WELL_WIDTH, width - 2))
        self.well_height = max(1, min(_WELL_HEIGHT, height - 2))
        self._well_top = height - self.well_height - 1
        self._new_game()

    def _new_game(self) -> None:
        self._state = _State.READY
        self._state_time = 0.0
        self.score = 0
        self.lines = 0
        self._start_level = self.params["start_level"]
        self.board = np.zeros((self.well_height, self.well_width), dtype=bool)
        self._bag: list[str] = []
        self._fall = Cadence()
        self._soft_drop = False
        self._shift = Cadence()
        self._shift_dir = 0  # -1 left, 1 right, 0 none
        self._shift_time = 0.0
        self._clearing: list[int] = []
        self.next = self._deal()
        self._spawn()

    @property
    def level(self) -> int:
        return self._start_level + self.lines // _LINES_PER_LEVEL

    @override
    def on_configure(self, **params) -> None:
        if "start_level" in params and self._state is _State.READY:
            self._start_level = params["start_level"]

    def _deal(self) -> str:
        if not self._bag:
            self._bag = [_KINDS[i] for i in np.random.permutation(len(_KINDS))]
        return self._bag.pop()

    def _spawn(self) -> None:
        """Bring the next piece in at the top; the game ends if it has no room."""
        self.kind: str | None = self.next
        self.next = self._deal()
        self.rotation = 0
        size, cells = _SHAPES[self.kind]
        self.x = (self.well_width - size) // 2
        self.y = -min(y for _, y in cells)
        self._fall.reset()
        if not self._fits(self.rotation, self.x, self.y):
            self._end()

    # --- Moving the piece ---------------------------------------------------

    def _cells(self, rotation: int, x: int, y: int) -> list[tuple[int, int]]:
        return [(x + cx, y + cy) for cx, cy in _ROTATIONS[self.kind][rotation]]

    def _fits(self, rotation: int, x: int, y: int) -> bool:
        """Whether the piece fits there. Cells above the well are free."""
        for cx, cy in self._cells(rotation, x, y):
            if not 0 <= cx < self.well_width or cy >= self.well_height:
                return False
            if cy >= 0 and self.board[cy, cx]:
                return False
        return True

    def _try_move(self, dx: int, dy: int) -> bool:
        if not self._fits(self.rotation, self.x + dx, self.y + dy):
            return False
        self.x += dx
        self.y += dy
        return True

    def _rotate(self, turn: int) -> None:
        """Turn a quarter clockwise (1) or anticlockwise (-1), kicking if needed."""
        if self.kind == "O":
            return
        to = (self.rotation + turn) % 4
        kicks = _KICKS_I if self.kind == "I" else _KICKS
        for kx, ky in kicks[(self.rotation, to)]:
            x, y = self.x + kx, self.y - ky  # kicks are y up
            if self._fits(to, x, y):
                self.rotation, self.x, self.y = to, x, y
                return

    def _fall_one(self) -> None:
        """Move down a row, or lock if the piece is resting on something."""
        if not self._try_move(0, 1):
            self._lock()

    def _lock(self) -> None:
        """Fix the piece into the well, then clear rows or bring in the next."""
        cells = self._cells(self.rotation, self.x, self.y)
        self.kind = None
        self._soft_drop = False
        for x, y in cells:
            if y >= 0:
                self.board[y, x] = True
        if any(y < 0 for _, y in cells):  # stuck out of the top
            self._end()
            return

        full = [y for y in range(self.well_height) if self.board[y].all()]
        if not full:
            self._spawn()
            return
        self.score += _LINE_POINTS[len(full)] * self.level  # before levelling up
        self.lines += len(full)
        self._clearing = full
        self._state = _State.CLEARING
        self._state_time = 0.0

    def _finish_clearing(self) -> None:
        kept = np.delete(self.board, self._clearing, axis=0)
        empty = np.zeros((len(self._clearing), self.well_width), dtype=bool)
        self.board = np.vstack([empty, kept])
        self._clearing = []
        self._state = _State.PLAYING
        self._spawn()

    def _end(self) -> None:
        self._state = _State.DYING
        self._state_time = 0.0

    # --- Input --------------------------------------------------------------

    @override
    def on_press(self, action: str) -> None:
        if action == "start":
            if self._state is _State.OVER:
                self._new_game()
            elif self._state is _State.READY:
                self._state = _State.PLAYING
            return
        if self._state is _State.READY:
            self._state = _State.PLAYING  # and the press counts

        # Tracked in any state, so a direction held while rows clear keeps
        # repeating on the next piece
        if action in ("left", "right"):
            self._shift_dir = -1 if action == "left" else 1
            self._shift_time = 0.0
            self._shift.reset()
        elif action == "down":
            self._soft_drop = True
            self._fall.reset()

        if self._state is not _State.PLAYING:
            return
        if action in ("left", "right"):
            self._try_move(self._shift_dir, 0)
        elif action == "down":
            self._fall_one()
        elif action == "rotate":
            self._rotate(1)
        elif action == "rotate_ccw":
            self._rotate(-1)
        elif action == "drop":
            while self._try_move(0, 1):
                pass
            self._lock()

    @override
    def on_release(self, action: str) -> None:
        if action == "down":
            if self._soft_drop:
                self._soft_drop = False
                self._fall.reset()
            return
        if action not in ("left", "right"):
            return
        if self._shift_dir != (-1 if action == "left" else 1):
            return
        # Fall back to the other direction if it is still held
        other = "right" if action == "left" else "left"
        self._shift_dir = -self._shift_dir if other in self.held else 0
        self._shift_time = 0.0
        self._shift.reset()

    # --- Time ---------------------------------------------------------------

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        self._state_time += dt

        if self._state is _State.PLAYING:
            self._step_shift(dt)
            if self._state is _State.PLAYING:
                self._step_fall(dt)
        elif self._state is _State.CLEARING:
            self._step_shift(dt)
            if self._state_time >= _CLEAR_FLASHES * _CLEAR_FLASH_PERIOD:
                self._finish_clearing()
        elif (
            self._state is _State.DYING
            and self._state_time >= _OVER_FLASHES * _OVER_FLASH_PERIOD
        ):
            self._state = _State.OVER

    def _step_shift(self, dt: float) -> None:
        """Auto-repeat a held direction once the delay has passed."""
        if not self._shift_dir:
            return
        self._shift_time += dt
        if self._shift_time < _SHIFT_DELAY:
            return
        moves = self._shift.advance(_SHIFT_SPEED, dt)
        if self._state is not _State.PLAYING:
            return
        for _ in range(moves):
            if not self._try_move(self._shift_dir, 0):
                break

    def _step_fall(self, dt: float) -> None:
        # No faster than a row per frame, so every row it passes shows
        speed = min(fall_speed(self.level), 1 / dt)
        if self._soft_drop:
            speed = max(speed, _SOFT_DROP_SPEED)
        for _ in range(self._fall.advance(speed, dt)):
            self._fall_one()
            if self.kind is None or self._state is not _State.PLAYING:
                break

    # --- Display ------------------------------------------------------------

    def _flash_off(self, period: float) -> bool:
        """Whether a flash that starts on entering the state is in its off half."""
        return (self._state_time % period) < period / 2

    @override
    def render_gray(self) -> np.ndarray:
        frame = np.zeros((self.height, self.width), dtype=np.float32)
        if self._state is _State.OVER:
            self._draw_final_score(frame)
            return frame

        well = self.board.copy()
        if self.kind is not None:
            for x, y in self._cells(self.rotation, self.x, self.y):
                if y >= 0:
                    well[y, x] = True
        if self._state is _State.CLEARING and self._flash_off(_CLEAR_FLASH_PERIOD):
            well[self._clearing] = False
        if self._state is _State.DYING and self._flash_off(_OVER_FLASH_PERIOD):
            well[:] = False

        top, bottom = self._well_top, self._well_top + self.well_height
        right = self.well_width + 1
        frame[top - 1 : bottom + 1, [0, right]] = 1.0
        frame[[top - 1, bottom], : right + 1] = 1.0
        frame[top:bottom, 1:right] = well

        self._draw_next(frame)
        # Score above the well at the right, level with the next piece. Level
        # and rows towards the next one along the bottom right, unlabelled:
        # with labels they wouldn't fit side by side.
        self._draw_text(frame, str(self.score), top=self._centred(self._well_top - 1))
        bottom = self._well_top + self.well_height
        self._draw_text(frame, str(self.level), bottom=bottom, left=right + 2)
        rows_into_level = self.lines % _LINES_PER_LEVEL
        self._draw_text(frame, str(rows_into_level), bottom=bottom)
        return frame

    def _draw_next(self, frame: np.ndarray) -> None:
        """The next piece, centred above the well; skipped if there's no room."""
        box = 2 * _PREVIEW_SCALE  # every piece is two cells tall but I
        space = self._well_top - 1  # rows above the border
        if space < box:
            return
        cells = _SHAPES[self.next][1]
        xs = [x for x, _ in cells]
        ys = [y for _, y in cells]
        piece = np.zeros((max(ys) - min(ys) + 1, max(xs) - min(xs) + 1))
        for x, y in cells:
            piece[y - min(ys), x - min(xs)] = 1.0
        piece = np.kron(piece, np.ones((_PREVIEW_SCALE, _PREVIEW_SCALE)))
        h, w = piece.shape
        if w > self.well_width:
            return
        top = (space - box) // 2 + (box - h) // 2
        left = 1 + (self.well_width - w) // 2
        frame[top : top + h, left : left + w] = piece

    def _text(self, text: str) -> np.ndarray:
        """``text`` in the small font, without the blank row under the digits."""
        image = self._panel_font.render_line(text)
        return image[: np.flatnonzero(image.any(axis=1)).max() + 1]

    def _centred(self, rows: int) -> int:
        """Top row that centres small-font text in the first ``rows`` rows."""
        return (rows - self._text("0").shape[0]) // 2

    def _draw_text(
        self,
        frame: np.ndarray,
        text: str,
        top: int | None = None,
        bottom: int | None = None,
        left: int | None = None,
    ) -> None:
        """Small-font text at ``top``, or ending above ``bottom``.

        Starts at ``left`` if given; otherwise right-aligned a dot in from the
        display's edge, so the digits stay put as a number grows. Skipped if
        it would run off the display or into the well.
        """
        image = self._text(text)
        h, w = image.shape
        if top is None:
            top = bottom - h
        if left is None:
            left = self.width - 1 - w
        if left <= self.well_width + 1 or left + w > self.width:
            return
        if top < 0 or top + h > self.height:
            return
        frame[top : top + h, left : left + w] = image

    def _draw_final_score(self, frame: np.ndarray) -> None:
        for font in (self._score_font, self._panel_font):
            text = font.render_line(str(self.score))
            h, w = text.shape
            if w > self.width or h > self.height:
                continue
            top = (self.height - h) // 2
            left = (self.width - w) // 2
            frame[top : top + h, left : left + w] = text
            return

    @override
    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        self._new_game()
