"""Conway's Game of Life animation."""

from typing import override

import numpy as np
from scipy.ndimage import convolve

from .base import Animation, register_animation

# Kernel that counts the 8 neighbors of each cell (toroidal wrap)
_NEIGHBOR_KERNEL = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]])

# Glow kernel for visual enhancement
_GLOW_KERNEL = np.array(
    [[0.1, 0.2, 0.1], [0.2, 1.0, 0.2], [0.1, 0.2, 0.1]], dtype=np.float32
)


@register_animation("life")
class Life(Animation):
    """Conway's Game of Life cellular automaton with toroidal wrapping."""

    def __init__(self, width: int, height: int):
        super().__init__(width, height, processing_steps=("dither",))

        self.grid = np.zeros((height, width), dtype=bool)
        self.generation = 0
        self.rate = 20.0  # generations per second
        self._generation_timer = 0.0

        self._randomize(density=0.3)

    @override
    def configure(self, **params):
        super().configure(**params)

        if "density" in params:
            self._randomize(float(params["density"]))
        if "pattern" in params:
            self._load_pattern(params["pattern"])
        if "rate" in params:
            self.rate = max(0.0, float(params["rate"]))

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        if self.rate <= 0:
            return

        self._generation_timer += dt
        interval = 1.0 / self.rate
        # Small tolerance so float error doesn't delay a generation by a frame
        while self._generation_timer >= interval - 1e-9:
            self._generation_timer -= interval
            self._update_generation()

    @override
    def render_gray(self) -> np.ndarray:
        frame = self.grid.astype(np.float32)

        if np.any(self.grid):
            frame = convolve(frame, _GLOW_KERNEL, mode="constant")
            np.clip(frame, 0, 1, out=frame)

        return frame

    def _update_generation(self):
        self.generation += 1

        # Count neighbors using convolution with toroidal (wrap) boundary
        neighbors = convolve(self.grid.astype(np.int8), _NEIGHBOR_KERNEL, mode="wrap")

        # Conway's rules:
        # Live cell with 2-3 neighbors survives
        # Dead cell with exactly 3 neighbors becomes alive
        self.grid = (neighbors == 3) | (self.grid & (neighbors == 2))

        # Re-seed if population dies out
        if self.generation % 100 == 0 and np.sum(self.grid) < 5:
            self._randomize(density=0.2)

    def _randomize(self, density: float = 0.3):
        self.grid = np.random.random((self.height, self.width)) < density
        self.generation = 0

    def _place_pattern(
        self, pattern: list[tuple[int, int]], offset_x: int = 0, offset_y: int = 0
    ):
        center_x, center_y = self.width // 2, self.height // 2
        for dx, dy in pattern:
            x, y = center_x + dx + offset_x, center_y + dy + offset_y
            if 0 <= x < self.width and 0 <= y < self.height:
                self.grid[y, x] = True

    def _load_pattern(self, pattern_name: str):
        self.grid.fill(False)
        self.generation = 0

        patterns = {
            "glider": [(1, 0), (2, 1), (0, 2), (1, 2), (2, 2)],
            "blinker": [(-1, 0), (0, 0), (1, 0)],
            "block": [(0, 0), (0, 1), (1, 0), (1, 1)],
            "beacon": [(0, 0), (0, 1), (1, 0), (2, 3), (3, 2), (3, 3)],
        }

        coords = patterns.get(pattern_name)
        if coords is not None:
            offset = (-1, -1) if pattern_name in ("glider", "beacon") else (0, 0)
            self._place_pattern(coords, offset_x=offset[0], offset_y=offset[1])
        else:
            self._randomize()
