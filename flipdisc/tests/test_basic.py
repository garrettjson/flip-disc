#!/usr/bin/env python3
"""Basic assertions for the new architecture (no prints)."""

import asyncio

import numpy as np

from flipdisc.animations import get_animation, list_animations
from flipdisc.animations.viewport import Viewport
from flipdisc.config import DisplayConfig
from flipdisc.engine.pipeline import DisplayPipeline


async def _async_test_pipeline_basic():
    config = DisplayConfig()
    pipeline = DisplayPipeline(config)
    await pipeline.start(animation="bouncing_dot")
    await pipeline.play()
    # Allow time for thread startup + frame generation
    await asyncio.sleep(2.0)
    st = pipeline.get_status()
    assert st.running is True
    assert st.frames_presented > 0
    await pipeline.pause()
    await pipeline.stop()


async def _async_test_animations_direct():
    config = DisplayConfig(rows=2)  # 28x14
    names = list_animations()
    assert len(names) > 0
    for name in names:
        anim = get_animation(name, Viewport(config.width, config.height))
        for _ in range(3):
            anim.step(1 / 30)
            gray = anim.render_gray()
            assert gray.shape == (config.height, config.width)
            assert gray.ndim == 2
            assert gray.dtype in (np.float32, np.float64)
            assert np.isfinite(gray).all()
            assert gray.min() >= 0.0 and gray.max() <= 1.0
            await asyncio.sleep(0.05)


async def _async_test_pipeline_integration():
    config = DisplayConfig()
    pipeline = DisplayPipeline(config)
    await pipeline.start(animation="bouncing_dot")
    await pipeline.play()
    await asyncio.sleep(2.0)
    st = pipeline.get_status()
    assert st.frames_presented > 0
    await pipeline.stop()


def test_pipeline_basic():
    asyncio.run(_async_test_pipeline_basic())


def test_animations_direct():
    asyncio.run(_async_test_animations_direct())


def test_pipeline_integration():
    asyncio.run(_async_test_pipeline_integration())


async def _async_test_animation_switch():
    config = DisplayConfig()
    pipeline = DisplayPipeline(config)
    await pipeline.start(animation="bouncing_dot")
    await pipeline.play()
    await asyncio.sleep(1.5)

    before = pipeline.get_status().frames_presented
    assert before > 0

    # Switch animation while playing
    await pipeline.set_animation("life")
    await asyncio.sleep(1.5)

    after = pipeline.get_status().frames_presented
    assert after > before, "No new frames after animation switch"

    # Switch again to verify pipeline stays healthy
    await pipeline.set_animation("simplex_noise")
    await asyncio.sleep(1.5)

    final = pipeline.get_status().frames_presented
    assert final > after, "No new frames after second animation switch"

    await pipeline.stop()


def test_animation_switch():
    asyncio.run(_async_test_animation_switch())
