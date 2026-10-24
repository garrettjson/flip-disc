"""Animation module for flip-disc displays."""

# Games live in flipdisc/games but share this registry; importing them here
# registers them wherever animations are looked up.
from flipdisc import games  # noqa: F401

# Import all animations to register them
from . import (
    bouncing_balls,
    bouncing_dot,
    clip,
    clock,
    composed,
    fluid,
    image,
    life,
    pendulum,
    point_cloud,
    rain_splash,
    rip,
    sandpile,
    simplex_noise,
    sorting,
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
    "bouncing_balls",
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
    "point_cloud",
    "rain_splash",
    "register_animation",
    "rip",
    "sandpile",
    "simplex_noise",
    "sorting",
    "supersampled",
    "text",
    "validate_params",
    "weather",
    "wireframe_cube",
]
