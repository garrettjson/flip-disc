"""Animation module for flip-disc displays."""

# Import all animations to register them
from . import (
    bouncing_dot,
    clip,
    clock,
    composed,
    fluid,
    image,
    life,
    pendulum,
    simplex_noise,
    supersampled,
    text,
    weather,
    wireframe_cube,
)
from .base import Animation, get_animation, list_animations, register_animation
from .supersampled import SupersampledAnimation

__all__ = [
    "Animation",
    "SupersampledAnimation",
    "bouncing_dot",
    "clip",
    "clock",
    "composed",
    "fluid",
    "get_animation",
    "image",
    "life",
    "list_animations",
    "pendulum",
    "register_animation",
    "simplex_noise",
    "supersampled",
    "text",
    "weather",
    "wireframe_cube",
]
