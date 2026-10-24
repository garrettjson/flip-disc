"""Sorting algorithms at work, shown as a row of bars.

Each value is a bar as tall as the value, one bar per column (or several
columns per bar when there are fewer bars than columns). The animation runs
once, in three phases, and then holds the sorted bars:

1. **Shuffle** — the bars start in order and are shuffled by a Fisher–Yates
   pass, one swap at a time, taking about a second.
2. **Sort** — the chosen algorithm sorts them at ``speed`` operations per
   second. An operation is one comparison, with the swap or write it leads
   to; the bars it touched are highlighted.
3. **Sweep** — the bars are highlighted one after another from left to right,
   checking the order, as in the usual sorting videos.

Changing ``algorithm`` or ``bars``, or resetting, starts again from the
shuffle.

Each algorithm is a generator in its own module, registered with
``@sort_algorithm``. It sorts the list it's given in place and yields the
indices to highlight after every operation, so it reads like the textbook
version; the animation plays one yield per operation.

The display has one bit per dot, so a highlight changes a bar's shape
(``highlight``): ``invert`` flips the bar's whole column, ``cap`` leaves only
its top dot, and ``none`` shows the bars alone.
"""

from collections.abc import Callable, Iterator
from typing import override

import numpy as np

from ..base import Animation, register_animation
from ..cadence import Cadence
from ..params import Param

# Indices of the bars an operation touched
type Highlight = tuple[int, ...]
type SortAlgorithm = Callable[[list[int]], Iterator[Highlight]]

_ALGORITHMS: dict[str, SortAlgorithm] = {}

# The shuffle and the sweep each take about this long, whatever the bar count
_PASS_DURATION = 1.0  # s

_HIGHLIGHTS = ("invert", "cap", "none")


def sort_algorithm(name: str) -> Callable[[SortAlgorithm], SortAlgorithm]:
    """Register a sorting generator under ``name`` (an ``algorithm`` choice)."""

    def decorator(algorithm: SortAlgorithm) -> SortAlgorithm:
        _ALGORITHMS[name] = algorithm
        return algorithm

    return decorator


def list_algorithms() -> list[str]:
    return list(_ALGORITHMS)


def _shuffle(values: list[int]) -> Iterator[Highlight]:
    """Fisher–Yates, one swap per operation."""
    for i in range(len(values) - 1, 0, -1):
        j = int(np.random.randint(i + 1))
        values[i], values[j] = values[j], values[i]
        yield (i, j)


def _sweep(count: int) -> Iterator[Highlight]:
    for i in range(1, count + 1):
        yield tuple(range(i))


@register_animation("sort")
class SortAnimation(Animation):
    """Bars shuffled, then sorted by a classic sorting algorithm."""

    PARAMS = (
        # Changing the algorithm or the bar count starts a new shuffle
        Param("algorithm", str, "bubble", choices=list_algorithms),
        Param("speed", float, 20.0, min=1, max=1000, step=1, unit="ops/s"),
        # Unset: one bar per column. More bars than columns are capped at the
        # number of columns.
        Param("bars", int, None, min=1, max=256, nullable=True),
        Param("highlight", str, "invert", choices=_HIGHLIGHTS),
    )

    def __init__(self, width: int, height: int):
        super().__init__(width, height, processing_steps=None)
        self._cadence = Cadence()
        self._restart()

    def _restart(self) -> None:
        count = min(self.params["bars"] or self.width, self.width)
        self._values = list(range(1, count + 1))
        self._highlight: Highlight = ()
        self._completed = False
        self._begin("shuffle")

    def _begin(self, phase: str) -> None:
        self._phase = phase
        self._cadence.reset()
        match phase:
            case "shuffle":
                self._ops = _shuffle(self._values)
            case "sort":
                self._ops = _ALGORITHMS[self.params["algorithm"]](self._values)
            case "sweep":
                self._ops = _sweep(len(self._values))
            case "done":
                self._highlight = ()
                self._completed = True

    def _rate(self) -> float:
        if self._phase == "sort":
            return self.params["speed"]
        return len(self._values) / _PASS_DURATION

    def _next_op(self) -> bool:
        """Play one operation, moving on to the next phase when one runs out.

        Returns False once the sweep has finished.
        """
        highlight = next(self._ops, None)
        while highlight is None:
            match self._phase:
                case "shuffle":
                    self._begin("sort")
                case "sort":
                    self._begin("sweep")
                case "sweep":
                    self._begin("done")
                    return False
            highlight = next(self._ops, None)
        self._highlight = highlight
        return True

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        if self._completed:
            return
        for _ in range(self._cadence.advance(self._rate(), dt)):
            if not self._next_op():
                break

    @override
    def render_gray(self) -> np.ndarray:
        count = len(self._values)
        bar_width = self.width // count
        left = (self.width - bar_width * count) // 2
        bars = slice(left, left + bar_width * count)

        # Heights round up, so with more bars than rows every bar shows
        heights = -(-np.array(self._values) * self.height // count)
        tops = np.full(self.width, self.height)  # empty columns
        tops[bars] = np.repeat(self.height - heights, bar_width)
        rows = np.arange(self.height)[:, np.newaxis]
        frame = rows >= tops

        marked = np.zeros(count, dtype=bool)
        marked[list(self._highlight)] = True
        columns = np.zeros(self.width, dtype=bool)
        columns[bars] = np.repeat(marked, bar_width)
        match self.params["highlight"]:
            case "invert":
                frame[:, columns] = ~frame[:, columns]
            case "cap":
                frame[:, columns] = (rows == tops)[:, columns]
        return frame.astype(np.float32)

    @override
    def on_configure(self, **params):
        if "algorithm" in params or "bars" in params:
            self._restart()

    @override
    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        self._restart()
