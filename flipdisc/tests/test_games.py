"""The game base class, the input path, and on-demand frames."""

import asyncio
import time
from typing import override

import numpy as np
import pytest
from fastapi.testclient import TestClient

from flipdisc.animations.base import _ANIMATION_REGISTRY
from flipdisc.config import DisplayConfig
from flipdisc.engine.pipeline import DisplayPipeline
from flipdisc.exceptions import AnimationError
from flipdisc.games import Control, Game, game_controls, list_games, validate_input
from flipdisc.web.api_server import ApiServer


class _Cursor(Game):
    """A dot that moves one pixel per press; counts its steps."""

    CONTROLS = (
        Control("left", "Move left", keys=("ArrowLeft",)),
        Control("right", "Move right", keys=("ArrowRight",)),
    )

    def __init__(self, width: int, height: int):
        super().__init__(width, height)
        self.x = width // 2
        self.steps = 0
        self.events: list[tuple[str, str]] = []

    @override
    def on_press(self, action: str) -> None:
        self.events.append(("press", action))
        self.x += 1 if action == "right" else -1
        self.x = max(0, min(self.x, self.width - 1))

    @override
    def on_release(self, action: str) -> None:
        self.events.append(("release", action))

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        self.steps += 1

    @override
    def render_gray(self) -> np.ndarray:
        frame = np.zeros((self.height, self.width), dtype=np.float32)
        frame[0, self.x] = 1.0
        return frame


@pytest.fixture(autouse=True)
def cursor_registered(monkeypatch):
    """Register the test game as "cursor" for every test here."""
    monkeypatch.setitem(_ANIMATION_REGISTRY, "cursor", _Cursor)


# --- Game base class ---------------------------------------------------------


def test_press_and_release_reach_the_game_once_each():
    game = _Cursor(28, 28)
    game.handle_input("right", True)
    game.handle_input("right", True)  # keyboard auto-repeat: still held
    assert game.held == {"right"}
    game.handle_input("right", False)
    game.handle_input("right", False)  # nothing to release
    assert game.events == [("press", "right"), ("release", "right")]
    assert game.held == set()


def test_unknown_action_is_rejected():
    with pytest.raises(AnimationError, match="left, right"):
        _Cursor(28, 28).handle_input("jump", True)


def test_reset_lets_go_of_held_actions():
    game = _Cursor(28, 28)
    game.handle_input("left", True)
    game.reset()
    assert game.held == set()


def test_games_are_listed_with_their_controls():
    assert "cursor" in list_games()
    assert "bouncing_dot" not in list_games()
    assert game_controls()["cursor"][0] == {
        "action": "left",
        "label": "Move left",
        "keys": ["ArrowLeft"],
    }


def test_validate_input():
    validate_input("cursor", "left")
    with pytest.raises(AnimationError, match="not a game"):
        validate_input("bouncing_dot", "left")
    with pytest.raises(AnimationError, match="Unknown action"):
        validate_input("cursor", "jump")


# --- Pipeline ------------------------------------------------------------------


async def _playing(animation: str) -> DisplayPipeline:
    pipeline = DisplayPipeline(DisplayConfig())  # 20 fps
    await pipeline.start(animation=animation)
    await pipeline.play()
    await asyncio.sleep(0.3)
    return pipeline


@pytest.fixture
def switched_to(monkeypatch) -> list:
    """Every animation the generator switches to, newest last (tests only)."""
    seen = []
    original = DisplayPipeline._apply_request

    def apply(self, anim, kind, payload):
        result = original(self, anim, kind, payload)
        if kind == "switch":
            seen.append(result)
        return result

    monkeypatch.setattr(DisplayPipeline, "_apply_request", apply)
    return seen


def test_game_frames_are_made_on_demand(switched_to):
    async def run():
        pipeline = await _playing("cursor")
        game = switched_to[-1]
        start_steps, start_frames = game.steps, pipeline._presented
        await asyncio.sleep(1.0)
        # One step per tick, not a buffer's worth ahead. The cursor doesn't
        # move, so only its first frame is written; count ticks via steps.
        ticks = game.steps - start_steps
        assert 15 <= ticks <= 22
        assert pipeline._frame_queue.qsize() <= 1
        assert pipeline._presented - start_frames <= 1
        await pipeline.stop()

    asyncio.run(run())


def test_input_shows_on_the_next_tick():
    async def run():
        pipeline = await _playing("cursor")
        before = pipeline.get_last_frame_bits().copy()
        sent = time.perf_counter()
        await pipeline.send_input("right", True)
        while np.array_equal(pipeline.get_last_frame_bits(), before):
            assert time.perf_counter() - sent < 0.5, "input never showed"
            await asyncio.sleep(0.002)
        latency = time.perf_counter() - sent
        # At most one tick (50 ms) plus scheduling slack; buffered, it would
        # be a full second
        assert latency < 0.08
        assert pipeline.get_last_frame_bits()[0, 15]
        await pipeline.stop()

    asyncio.run(run())


def test_switching_between_game_and_animation():
    async def run():
        pipeline = await _playing("cursor")
        await pipeline.set_animation("bouncing_dot")
        await asyncio.sleep(0.3)
        assert pipeline.get_status().animation == "bouncing_dot"
        assert not pipeline._on_demand
        before = pipeline._presented
        await asyncio.sleep(0.3)
        assert pipeline._presented > before

        await pipeline.set_animation("cursor")
        await asyncio.sleep(0.3)
        assert pipeline._on_demand
        await pipeline.send_input("left", True)
        await asyncio.sleep(0.15)
        assert pipeline.get_last_frame_bits()[0, 13]
        await pipeline.stop()

    asyncio.run(run())


def test_input_is_rejected_unless_a_game_is_running():
    async def run():
        pipeline = await _playing("bouncing_dot")
        with pytest.raises(AnimationError, match="not a game"):
            await pipeline.send_input("left", True)
        await pipeline.set_animation("cursor")
        with pytest.raises(AnimationError, match="Unknown action"):
            await pipeline.send_input("jump", True)
        await pipeline.stop()

    asyncio.run(run())


# --- API -----------------------------------------------------------------------


def _client() -> TestClient:
    cfg = DisplayConfig()
    return TestClient(ApiServer(cfg, DisplayPipeline(cfg)).app)


def test_api_lists_games_apart_from_animations():
    data = _client().get("/animations").json()
    assert "cursor" in data["games"]
    assert "cursor" not in data["animations"]
    assert "bouncing_dot" in data["animations"]
    assert [c["action"] for c in data["controls"]["cursor"]] == ["left", "right"]
    assert "cursor" in data["params"]


def test_post_input():
    with _client() as client:
        assert client.post("/input", json={"action": "left"}).status_code == 400
        assert client.post("/anim/cursor", json={}).status_code == 200
        res = client.post("/input", json={"action": "left", "pressed": True})
        assert res.status_code == 200
        res = client.post("/input", json={"action": "jump"})
        assert res.status_code == 400
        assert "Unknown action" in res.json()["detail"]


def test_input_websocket_answers_only_bad_messages():
    with _client() as client:
        client.post("/anim/cursor", json={})
        with client.websocket_connect("/ws/input") as ws:
            ws.send_json({"action": "left", "pressed": True})  # no reply
            ws.send_json({"action": "left", "pressed": False})  # no reply
            ws.send_text("not json")
            assert "expected" in ws.receive_json()["error"]
            ws.send_json({"action": "jump", "pressed": True})
            assert "Unknown action" in ws.receive_json()["error"]
