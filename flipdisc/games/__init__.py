"""Interactive games for flip-disc displays.

Games share the animation registry, so importing a game module registers it
under its name like any animation. Import every game module here.
"""

from . import snake
from .base import Control, Game, game_controls, is_game, list_games, validate_input

__all__ = [
    "Control",
    "Game",
    "game_controls",
    "is_game",
    "list_games",
    "snake",
    "validate_input",
]
