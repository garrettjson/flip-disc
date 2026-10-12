"""The generator thread must survive bad requests and broken animations."""

import asyncio
from typing import override

import numpy as np
import pytest
from fastapi.testclient import TestClient

from flipdisc.animations.base import _ANIMATION_REGISTRY, Animation
from flipdisc.config import DisplayConfig
from flipdisc.engine.pipeline import DisplayPipeline
from flipdisc.exceptions import AnimationError
from flipdisc.web.api_server import ApiServer


class _BrokenStep(Animation):
    @override
    def step(self, dt: float) -> None:
        raise RuntimeError("boom")

    @override
    def render_gray(self) -> np.ndarray:
        return np.zeros((self.height, self.width), dtype=np.float32)


async def _started(animation: str = "bouncing_dot") -> DisplayPipeline:
    pipeline = DisplayPipeline(DisplayConfig())
    await pipeline.start(animation=animation)
    await pipeline.play()
    await asyncio.sleep(0.5)
    return pipeline


def _alive(pipeline: DisplayPipeline) -> bool:
    return pipeline._gen_thread is not None and pipeline._gen_thread.is_alive()


async def _frames_advance(pipeline: DisplayPipeline) -> bool:
    before = pipeline.get_status().frames_presented
    await asyncio.sleep(0.5)
    return pipeline.get_status().frames_presented > before


def test_unknown_animation_is_rejected_before_handoff():
    async def run():
        pipeline = await _started()
        with pytest.raises(AnimationError):
            await pipeline.set_animation("does_not_exist")
        assert _alive(pipeline)
        assert pipeline.get_status().animation == "bouncing_dot"
        assert await _frames_advance(pipeline)
        await pipeline.stop()

    asyncio.run(run())


def test_start_with_unknown_animation_raises():
    async def run():
        pipeline = DisplayPipeline(DisplayConfig())
        with pytest.raises(AnimationError):
            await pipeline.start(animation="does_not_exist")
        assert pipeline.get_status().running is False

    asyncio.run(run())


def test_failed_configure_keeps_animation_running():
    async def run():
        pipeline = await _started("clip")
        await pipeline.configure_animation({"name": "no_such_clip"})
        await asyncio.sleep(0.3)
        st = pipeline.get_status()
        assert _alive(pipeline)
        assert st.animation == "clip"
        assert st.last_error is not None
        assert "configure failed" in st.last_error

        # Switching to a new animation starts with a clean slate
        await pipeline.set_animation("life")
        await asyncio.sleep(0.3)
        assert pipeline.get_status().last_error is None
        await pipeline.stop()

    asyncio.run(run())


def test_failed_switch_keeps_previous_animation():
    async def run():
        pipeline = await _started()
        # "clip" is registered, but configuring it with an unknown clip raises
        await pipeline.set_animation("clip", {"name": "no_such_clip"})
        await asyncio.sleep(0.3)
        st = pipeline.get_status()
        assert _alive(pipeline)
        assert st.animation == "bouncing_dot"
        assert "switch failed" in st.last_error
        assert await _frames_advance(pipeline)

        # A later successful switch clears the error
        await pipeline.set_animation("life")
        await asyncio.sleep(0.3)
        st = pipeline.get_status()
        assert st.animation == "life"
        assert st.last_error is None
        await pipeline.stop()

    asyncio.run(run())


def test_animation_that_raises_while_running_is_dropped(monkeypatch):
    monkeypatch.setitem(_ANIMATION_REGISTRY, "broken_step", _BrokenStep)

    async def run():
        pipeline = await _started()
        await pipeline.set_animation("broken_step")
        await asyncio.sleep(0.3)
        st = pipeline.get_status()
        assert _alive(pipeline)
        assert st.animation is None
        assert "boom" in st.last_error

        # The pipeline recovers on the next switch
        await pipeline.set_animation("bouncing_dot")
        await asyncio.sleep(0.3)
        st = pipeline.get_status()
        assert st.animation == "bouncing_dot"
        assert st.last_error is None
        assert await _frames_advance(pipeline)
        await pipeline.stop()

    asyncio.run(run())


def test_requests_are_applied_in_order():
    async def run():
        pipeline = await _started("text")
        # Two configures in quick succession: neither may be lost
        await pipeline.configure_animation({"text": "AB", "mode": "static"})
        await pipeline.configure_animation({"font": "compact"})
        # Frames queued before the configure play out first (buffer_duration)
        await asyncio.sleep(1.0)
        st = pipeline.get_status()
        assert st.last_error is None
        frame = pipeline.get_last_frame_bits()
        assert frame is not None and frame.any()
        await pipeline.stop()

    asyncio.run(run())


def test_api_returns_400_for_unknown_animation():
    cfg = DisplayConfig()
    client = TestClient(ApiServer(cfg, DisplayPipeline(cfg)).app)
    res = client.post("/anim/does_not_exist", json={})
    assert res.status_code == 400
    assert "Unknown animation" in res.json()["detail"]
