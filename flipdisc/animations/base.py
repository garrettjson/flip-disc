"""Base animation interface for flip-disc displays."""

from abc import ABC, abstractmethod
from typing import Any

import numpy as np

from flipdisc.exceptions import AnimationError


class Animation(ABC):
    """Base class for all flip-disc animations.

    Subclasses implement:
    - step(dt): advance simulation by dt seconds
    - render_gray(): return grayscale frame as (height, width) float32 array [0, 1]

    Optional overrides:
    - configure(**params): set animation-specific parameters
    - reset(seed): reset to initial state
    - is_complete(): return True for finite animations
    """

    def __init__(
        self,
        width: int,
        height: int,
        processing_steps: tuple[str, ...] | None = ("binarize",),
    ):
        if width <= 0 or height <= 0:
            raise AnimationError(
                f"Animation dimensions must be positive: {width}x{height}"
            )

        self.width = width
        self.height = height
        self.processing_steps = processing_steps
        self.current_time = 0.0
        self.params: dict[str, Any] = {}
        self._completed = False

    @abstractmethod
    def step(self, dt: float) -> None:
        """
        Advance the animation simulation by dt seconds.

        Args:
            dt: Time step in seconds (one display interval, 1 / refresh_rate)
        """

    @abstractmethod
    def render_gray(self) -> np.ndarray:
        """
        Render current animation state to grayscale image.

        Returns:
            Grayscale image as float array (0.0 to 1.0)
            Shape should be (height, width)
        """

    def is_complete(self) -> bool:
        """Check if animation has finished (default: never completes)."""
        return self._completed

    def configure(self, **params: Any) -> None:
        """Configure animation parameters."""
        self.params.update(params)

    def reset(self, seed: int | None = None) -> None:
        """Reset animation to initial state."""
        self.current_time = 0.0
        self._completed = False
        if seed is not None:
            np.random.seed(seed)


# Animation registry for worker processes
_ANIMATION_REGISTRY: dict[str, type] = {}


def register_animation(name: str):
    """Decorator to register an animation class."""

    def decorator(cls):
        if not issubclass(cls, Animation):
            raise AnimationError(f"Registered class must inherit from Animation: {cls}")
        _ANIMATION_REGISTRY[name] = cls
        return cls

    return decorator


def get_animation(name: str, width: int, height: int) -> Animation:
    """
    Factory function to create animation instances.

    Args:
        name: Animation name
        width: Display width
        height: Display height

    Returns:
        Animation instance

    Raises:
        AnimationError: If animation not found
    """
    if name not in _ANIMATION_REGISTRY:
        raise AnimationError(
            f"Unknown animation: {name}. Available: {list(_ANIMATION_REGISTRY.keys())}"
        )

    animation_class = _ANIMATION_REGISTRY[name]
    try:
        return animation_class(width, height)
    except Exception as e:
        raise AnimationError(f"Failed to create animation '{name}': {e}") from e


def list_animations() -> list[str]:
    """Get list of available animation names."""
    return list(_ANIMATION_REGISTRY.keys())
