"""Tests for the tetris game."""

import numpy as np
import pytest

from flipdisc.games.tetris import _KINDS, Tetris, _State, fall_speed

DT = 0.05  # 20 fps
_WELL = np.s_[7:27, 1:11]  # where the well's cells are on a 28x28 display


def _tap(game: Tetris, action: str) -> None:
    game.handle_input(action, True)
    game.handle_input(action, False)


def _steps(game: Tetris, seconds: float) -> None:
    for _ in range(round(seconds / DT)):
        game.step(DT)


def _game(kind: str = "T", **params) -> Tetris:
    """A game in play with a ``kind`` piece just spawned."""
    np.random.seed(0)
    game = Tetris(28, 28)
    if params:
        game.configure(**params)
        game.reset()
    game.next = kind
    game._spawn()
    game._state = _State.PLAYING
    return game


def _cells(game: Tetris) -> set[tuple[int, int]]:
    return set(game._cells(game.rotation, game.x, game.y))


def test_waits_with_the_first_piece_at_the_top():
    np.random.seed(0)
    game = Tetris(28, 28)
    start = _cells(game)
    assert min(y for _, y in start) == 0
    _steps(game, 3)
    assert _cells(game) == start
    assert game._state is _State.READY


def test_any_control_starts_and_counts():
    np.random.seed(0)
    game = Tetris(28, 28)
    x = game.x
    _tap(game, "left")
    assert game._state is _State.PLAYING
    assert game.x == x - 1


def test_spawns_centred():
    assert _game("T").x == 3
    assert _game("I").x == 3
    assert _game("O").x == 4


def test_falls_a_row_a_second_at_level_one():
    game = _game()
    assert game.level == 1
    y = game.y
    _steps(game, 3)
    assert game.y == y + 3


def test_speed_curve():
    assert fall_speed(1) == 1
    assert fall_speed(4) == pytest.approx(2.12, abs=0.01)
    assert fall_speed(10) == pytest.approx(15.6, abs=0.1)
    speeds = [fall_speed(level) for level in range(1, 16)]
    assert speeds == sorted(speeds)


def test_start_level_sets_the_speed():
    game = _game("I", start_level=4)
    assert game.level == 4
    y = game.y
    _steps(game, 2)
    assert game.y == y + 4  # 2.12 rows/s plays at 2.22: a row every 9 frames


def test_start_level_applies_before_the_first_move_only():
    np.random.seed(0)
    game = Tetris(28, 28)
    game.configure(start_level=3)
    assert game.level == 3
    _tap(game, "left")
    game.configure(start_level=5)
    assert game.level == 3


def test_falls_at_most_a_row_a_frame():
    game = _game("I", start_level=15)  # 140 rows/s
    y = game.y
    _steps(game, 0.25)
    assert game.y == y + 5


def test_levels_up_every_ten_rows_and_points_scale_with_level():
    game = _game("I")
    for _ in range(4):  # four tetrises: the fourth starts at 12 rows, level 2
        game.board[16:, :] = True
        game.board[16:, 0] = False
        _tap(game, "rotate")  # upright, column 5
        for _ in range(5):
            _tap(game, "left")
        _tap(game, "drop")
        assert game._state is _State.CLEARING
        _steps(game, 1)
        game.next = "I"
        game._spawn()
    assert game.lines == 16
    assert game.level == 2
    assert game.score == 3 * 8 + 8 * 2


def test_moves_stop_at_the_walls():
    game = _game("O")
    for _ in range(10):
        _tap(game, "left")
    assert min(x for x, _ in _cells(game)) == 0
    for _ in range(20):
        _tap(game, "right")
    assert max(x for x, _ in _cells(game)) == 9


def test_holding_a_direction_repeats_after_a_delay():
    game = _game("O")
    x = game.x
    game.handle_input("left", True)
    assert game.x == x - 1  # at once
    _steps(game, 0.15)
    assert game.x == x - 1  # still waiting
    _steps(game, 1)
    assert game.x == 0  # repeated all the way to the wall
    game.handle_input("left", False)
    game.handle_input("right", True)
    _steps(game, 0.15)
    assert game.x == 1


def test_releasing_one_direction_falls_back_to_the_other():
    game = _game("O")
    game.handle_input("left", True)
    game.handle_input("right", True)
    game.handle_input("right", False)
    x = game.x
    _steps(game, 0.5)
    assert game.x < x


def test_rotates_both_ways():
    game = _game("T")
    flat = _cells(game)
    _tap(game, "rotate")
    assert game.rotation == 1
    assert len({x for x, _ in _cells(game)}) == 2  # upright
    _tap(game, "rotate_ccw")
    assert _cells(game) == flat


def test_rotation_kicks_off_the_wall():
    game = _game("I")
    _tap(game, "rotate")  # upright, in the box's third column
    for _ in range(10):
        _tap(game, "right")
    assert max(x for x, _ in _cells(game)) == 9
    _tap(game, "rotate")  # lying flat would stick out of the well
    assert game.rotation == 2
    assert max(x for x, _ in _cells(game)) == 9


def test_o_does_not_rotate():
    game = _game("O")
    cells = _cells(game)
    _tap(game, "rotate")
    assert _cells(game) == cells


def test_soft_drop_while_held():
    game = _game()
    y = game.y
    game.handle_input("down", True)
    assert game.y == y + 1  # at once
    _steps(game, 0.5)
    assert game.y == y + 11  # 20 rows/s
    game.handle_input("down", False)
    _steps(game, 0.5)
    assert game.y == y + 11  # back to 1 row/s


def test_soft_drop_does_not_carry_into_the_next_piece():
    game = _game("O")
    game.handle_input("down", True)
    while not game.board.any():  # lands and locks
        game.step(DT)
    y = game.y
    _steps(game, 0.5)
    assert game.y <= y + 1  # held, but not pressed for this piece: 1 row/s


def test_hard_drop_locks_at_the_bottom():
    game = _game("O")
    game.next = "T"
    _tap(game, "drop")
    assert game.board[18:, 4:6].all()
    assert game.board.sum() == 4
    assert game.kind == "T"
    assert game.y == 0
    assert game.score == 0


def test_a_landed_piece_locks_on_its_next_fall():
    game = _game("O")
    while game._try_move(0, 1):
        pass
    _tap(game, "left")  # still slides along the floor
    assert not game.board.any()
    _steps(game, 1)
    assert game.board[18:, 3:5].all()


def test_full_rows_flash_then_clear():
    game = _game("I")
    game.board[19, :] = True
    game.board[19, 3:7] = False  # a gap the I fills
    game.board[18, 0] = True  # a block that falls to the floor
    _tap(game, "drop")
    # The bottom row is full; the one above has the block and nothing else
    assert game._state is _State.CLEARING
    assert game.score == 1
    flashes = []
    while game._state is _State.CLEARING:
        flashes.append(bool(game.render_gray()[_WELL][-1].any()))
        game.step(DT)
    assert True in flashes and False in flashes
    assert flashes[0] is False  # the flash starts at once
    assert game.board.sum() == 1
    assert game.board[19, 0]
    assert game.lines == 1
    assert game.kind is not None


def test_four_rows_at_once_score_eight():
    game = _game("I")
    game.board[16:, :9] = True
    _tap(game, "rotate")  # upright, column 5
    for _ in range(4):
        _tap(game, "right")
    _tap(game, "drop")
    assert game._state is _State.CLEARING
    assert game.score == 8
    _steps(game, 1)
    assert not game.board.any()
    assert game.lines == 4


def test_pieces_come_in_bags_of_all_seven():
    np.random.seed(3)
    game = Tetris(28, 28)
    game._bag = []
    dealt = [game._deal() for _ in range(14)]
    assert sorted(dealt[:7]) == sorted(_KINDS)
    assert sorted(dealt[7:]) == sorted(_KINDS)


def test_no_room_ends_the_game_then_start_restarts():
    game = _game()
    game.board[1:, :] = True
    game.board[1:, 0] = False  # no full rows
    game.score = 12
    _tap(game, "drop")  # locks on top; the next piece has no room
    assert game._state is _State.DYING
    flashes = []
    for _ in range(18):  # 3 flashes of 0.3 s
        game.step(DT)
        flashes.append(bool(game.render_gray()[_WELL].any()))
    assert True in flashes and False in flashes
    assert game._state is _State.OVER

    _tap(game, "drop")  # only start restarts
    assert game._state is _State.OVER
    frame = game.render_gray()
    assert frame.any()  # the score
    assert not frame[0].any() and not frame[:, 0].any()  # centred

    _tap(game, "start")
    assert game._state is _State.READY
    assert game.score == 0
    assert not game.board.any()


def test_layout_border_next_piece_and_stats():
    game = _game("T")
    game.next = "O"
    game.score = 1380
    game.lines = 24
    frame = game.render_gray()
    assert frame[6, :12].all() and frame[27, :12].all()  # top and bottom
    assert frame[6:, 0].all() and frame[6:, 11].all()  # sides
    assert frame[:6, :12].sum() == 16  # O at two dots per cell, above the well
    assert frame[1:5, 4:8].all()  # centred over it
    assert not frame[:, 27].any()  # a dot in from the right edge

    score = frame[1:5, 12:27]  # above the well, beside the next piece
    assert score[:, 0].any() and score[:, -1].any()  # four digits, right-aligned
    assert not frame[7:23, 12:].any()

    stats = frame[23:27]  # level with the bottom of the well
    assert not stats[:, 12].any()  # a dot clear of the border
    assert stats[:, 13:20].any()  # level, "3", by the well
    assert stats[:, 24:27].any()  # rows towards the next level, "4", at the edge
    assert not stats[:, 20:23].any()


@pytest.mark.parametrize(("width", "height"), [(7, 7), (14, 7), (28, 7), (28, 28)])
def test_render_at_other_sizes(width, height):
    np.random.seed(0)
    game = Tetris(width, height)
    for i in range(200):
        _tap(game, ("left", "rotate", "right", "drop")[i % 4])
        game.step(DT)
        frame = game.render_gray()
        assert frame.shape == (height, width)
        assert frame.dtype == np.float32
        assert set(np.unique(frame)) <= {0.0, 1.0}
