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
    rain_splash,
    sandpile,
    simplex_noise,
    supersampled,
    text,
    weather,
    wireframe_cube,
)
from .base import (
    Animation,
    animation_schemas,
    get_animation,
    list_animations,
    register_animation,
    validate_params,
)
from .cadence import Cadence
from .params import Param
from .supersampled import SupersampledAnimation

__all__ = [
    "Animation",
    "Cadence",
    "Param",
    "SupersampledAnimation",
    "animation_schemas",
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
    "rain_splash",
    "register_animation",
    "sandpile",
    "simplex_noise",
    "supersampled",
    "text",
    "validate_params",
    "weather",
    "wireframe_cube",
]
