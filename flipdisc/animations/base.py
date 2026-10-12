"""Base animation interface for flip-disc displays."""

from abc import ABC, abstractmethod
from typing import Any, ClassVar

import numpy as np

from flipdisc.exceptions import AnimationError

from .params import Param


class Animation(ABC):
    """Base class for all flip-disc animations.

    Subclasses implement:
    - step(dt): advance simulation by dt seconds
    - render_gray(): return grayscale frame as (height, width) float32 array [0, 1]

    Subclasses declare their parameters in PARAMS and react to changes in
    on_configure(**params), which only ever receives declared, validated,
    correctly typed values.

    Optional overrides:
    - on_configure(**params): apply changed parameters
    - reset(seed): reset to initial state
    - is_complete(): return True for finite animations
    """

    PARAMS: ClassVar[tuple[Param, ...]] = ()

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
        # Current value of every declared parameter, starting from the defaults
        self.params: dict[str, Any] = {p.name: p.default for p in self.PARAMS}
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

    @classmethod
    def validate_params(cls, params: dict[str, Any]) -> dict[str, Any]:
        """Check and coerce params against PARAMS.

        Returns a new dict with every value converted to its declared type.
        Raises AnimationError for an unknown name or an invalid value. Needs no
        instance, so the API can call it before handing a request to the
        generator thread.
        """
        declared = {p.name: p for p in cls.PARAMS}
        unknown = sorted(set(params) - set(declared))
        if unknown:
            raise AnimationError(
                f"Unknown parameter(s) for {cls.__name__}: {', '.join(unknown)}. "
                f"Available: {', '.join(declared) or 'none'}"
            )
        return {name: declared[name].coerce(value) for name, value in params.items()}

    @classmethod
    def schema(cls) -> list[dict[str, Any]]:
        """JSON-serializable description of PARAMS."""
        return [p.to_schema() for p in cls.PARAMS]

    def configure(self, **params: Any) -> None:
        """Validate params, record them in self.params, and apply them.

        Not meant to be overridden — implement on_configure() instead.
        """
        clean = self.validate_params(params)
        self.params.update(clean)
        self.on_configure(**clean)

    def on_configure(self, **params: Any) -> None:  # noqa: B027
        """Apply changed parameters. Receives only the keys that were passed."""

    def reset(self, seed: int | None = None) -> None:
        """Reset animation to initial state."""
        self.current_time = 0.0
        self._completed = False
        if seed is not None:
            np.random.seed(seed)


# Animation registry for worker processes
_ANIMATION_REGISTRY: dict[str, type[Animation]] = {}


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
    animation_class = get_animation_class(name)
    try:
        return animation_class(width, height)
    except Exception as e:
        raise AnimationError(f"Failed to create animation '{name}': {e}") from e


def list_animations() -> list[str]:
    """Get list of available animation names."""
    return list(_ANIMATION_REGISTRY.keys())


def get_animation_class(name: str) -> type[Animation]:
    """Look up a registered animation class, raising AnimationError if unknown."""
    if name not in _ANIMATION_REGISTRY:
        raise AnimationError(
            f"Unknown animation: {name}. Available: {list(_ANIMATION_REGISTRY.keys())}"
        )
    return _ANIMATION_REGISTRY[name]


def validate_params(name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Validate params for a registered animation without instantiating it."""
    return get_animation_class(name).validate_params(params)


def animation_schemas() -> dict[str, list[dict[str, Any]]]:
    """Parameter schema for every registered animation, keyed by name."""
    return {name: cls.schema() for name, cls in _ANIMATION_REGISTRY.items()}
