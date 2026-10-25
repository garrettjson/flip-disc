"""Tests for the snake game."""

import numpy as np
import pytest

from flipdisc.animations.viewport import Viewport
from flipdisc.games.snake import Snake, _State

DT = 0.05  # 20 fps


def _tap(game: Snake, action: str) -> None:
    game.handle_input(action, True)
    game.handle_input(action, False)


def _move(game: Snake, cells: int = 1) -> None:
    """Step until the snake has moved ``cells`` times."""
    frames_per_move = round(1 / (game.params["speed"] * DT))
    for _ in range(cells * frames_per_move):
        game.step(DT)


def _game(width: int = 28, height: int = 28, **params) -> Snake:
    np.random.seed(0)
    game = Snake(Viewport(width, height))
    if params:
        game.configure(**params)
        game.reset()
    game.food = (0, 0)  # out of the way unless a test places it
    return game


def test_waits_for_the_first_direction():
    game = _game()
    start = list(game.body)
    for _ in range(40):
        game.step(DT)
    assert list(game.body) == start
    assert game._state is _State.READY


def test_moves_at_the_set_speed_once_started():
    game = _game(speed=5)
    head_x, head_y = game.body[0]
    _tap(game, "right")
    for _ in range(20):  # one second at 5 cells/s
        game.step(DT)
    assert game.body[0] == (head_x + 5, head_y)
    assert len(game.body) == 3


def test_first_press_can_go_straight_back():
    game = _game()
    tail = game.body[-1]
    _tap(game, "left")
    _move(game)
    assert game.body[0] == (tail[0] - 1, tail[1])


def test_turns_and_ignores_reversal():
    game = _game()
    _tap(game, "right")
    _move(game)
    _tap(game, "left")  # straight back into its body
    _move(game)
    assert game.heading == (1, 0)
    _tap(game, "down")
    _move(game)
    assert game.heading == (0, 1)


def test_two_quick_turns_apply_on_consecutive_moves():
    game = _game()
    _tap(game, "right")
    _move(game)
    x, y = game.body[0]
    _tap(game, "up")
    _tap(game, "left")  # before the snake has moved: a U-turn
    _move(game)
    assert game.body[0] == (x, y - 1)
    _move(game)
    assert game.body[0] == (x - 1, y - 1)


def test_holding_a_key_is_one_turn():
    game = _game()
    _tap(game, "right")
    _move(game)
    game.handle_input("up", True)
    game.handle_input("up", True)  # keyboard auto-repeat
    _move(game, 2)
    assert game.heading == (0, -1)
    assert game._turns == []


def test_eating_grows_and_scores():
    game = _game()
    _tap(game, "right")
    x, y = game.body[0]
    game.food = (x + 1, y)
    _move(game)
    assert game.score == 1
    assert len(game.body) == 4
    assert game.food not in game.body
    _move(game)
    assert len(game.body) == 4  # grows once per food


def test_wall_ends_the_game():
    game = _game()
    _tap(game, "up")
    rows_above = game.body[0][1]
    _move(game, rows_above)
    assert game._state is _State.PLAYING
    assert game.body[0][1] == 0
    _move(game)  # into the wall
    assert game._state is _State.DYING


def test_wraps_without_walls():
    game = _game(walls=False)
    game.food = (0, 0)
    x, _ = game.body[0]
    _tap(game, "up")
    _move(game, game.height)
    assert game._state is _State.PLAYING
    assert game.body[0] == (x, game.height // 2)  # all the way round


def test_running_into_itself_ends_the_game():
    game = _game(start_length=5)
    _tap(game, "right")
    for turn in ("up", "left", "down"):
        _tap(game, turn)
        _move(game)
    assert game._state is _State.DYING


def test_chasing_its_own_tail_is_allowed():
    game = _game(start_length=4)
    _tap(game, "right")
    # A 2x2 loop: the head always enters the cell the tail is leaving
    for turn in ("up", "left", "down", "right") * 3:
        _tap(game, turn)
        _move(game)
    assert game._state is _State.PLAYING


def test_death_flashes_then_shows_the_score_until_start():
    game = _game()
    game.score = 7
    game._die()
    flashes = []
    for _ in range(18):  # 3 flashes of 0.3 s
        game.step(DT)
        flashes.append(game.render_gray().any())
    assert True in flashes and False in flashes
    assert game._state is _State.OVER

    _tap(game, "left")  # directions don't restart
    assert game._state is _State.OVER
    frame = game.render_gray()
    assert frame.any()  # the score
    assert not frame[0].any() and not frame[:, 0].any()  # centred

    _tap(game, "start")
    assert game._state is _State.READY
    assert game.score == 0


def test_food_blinks():
    game = _game()
    game.food = (1, 1)
    seen = set()
    for _ in range(20):
        game.step(DT)
        seen.add(bool(game.render_gray()[1, 1]))
    assert seen == {True, False}


def test_new_food_never_lands_on_the_snake():
    np.random.seed(1)
    game = Snake(Viewport(5, 5))
    game.configure(start_length=4)
    game.reset()
    for _ in range(200):
        game._place_food()
        assert game.food not in game.body


def test_filling_the_board_ends_the_game():
    game = _game(3, 1, start_length=2)
    _tap(game, "right")
    game.food = (2, 0)
    _move(game)
    assert game.food is None
    assert game._state is _State.DYING


@pytest.mark.parametrize(("width", "height"), [(7, 7), (14, 7), (28, 7), (28, 28)])
def test_render_at_other_sizes(width, height):
    game = _game(width, height)
    _tap(game, "down")
    for _ in range(60):
        game.step(DT)
        frame = game.render_gray()
        assert frame.shape == (height, width)
        assert frame.dtype == np.float32
        assert set(np.unique(frame)) <= {0.0, 1.0}
