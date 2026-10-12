"""DisplayPipeline: orchestrates a background generator thread and async presenter.

The generator thread runs animations, applies post-processing, and pushes
frames into a queue.Queue. The async presenter pulls frames at refresh_rate,
encodes them, writes to serial, and broadcasts preview frames.

The small frame buffer (queue.Queue(maxsize=N)) smooths compute spikes in the
generator so the presenter always has frames ready to display.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from flipdisc.animations import get_animation
from flipdisc.config import DisplayConfig
from flipdisc.exceptions import HardwareError, SerialConnectionError
from flipdisc.gfx.postprocessing import apply_processing_pipeline
from flipdisc.hardware.panel_map import split_canvas_bits_to_panels
from flipdisc.hardware.protocol import ProtocolEncoder
from flipdisc.hardware.serial import SerialTransport, create_serial_transport

logger = logging.getLogger(__name__)


@dataclass
class PipelineStatus:
    running: bool
    playing: bool
    frames_presented: int
    buffer_capacity: int


class DisplayPipeline:
    def __init__(self, cfg: DisplayConfig) -> None:
        self.cfg = cfg
        self.frame_interval = 1.0 / cfg.refresh_rate
        self.serial: SerialTransport = create_serial_transport(cfg.serial)
        self.encoder = ProtocolEncoder(cfg)

        # Frame buffer
        self._buffer_capacity = max(1, int(cfg.refresh_rate * cfg.buffer_duration))
        self._frame_queue: queue.Queue[np.ndarray] = queue.Queue(
            maxsize=self._buffer_capacity
        )

        # Threading events
        self._stop_event = threading.Event()
        self._play_event = threading.Event()

        # Animation switch / configure requests (main thread -> generator thread)
        self._anim_request: tuple[str, dict[str, Any]] | None = None
        self._configure_request: dict[str, Any] | None = None
        self._reset_requested = False

        # Generator thread
        self._gen_thread: threading.Thread | None = None

        # Presenter task
        self._presenter_task: asyncio.Task | None = None
        self._presented = 0
        self._running = False
        self._playing = False

        # Last frame storage + preview queue
        self._last_frame: np.ndarray | None = None
        self._preview_queue: asyncio.Queue[np.ndarray] | None = None
        self._preview_task: asyncio.Task | None = None

    def set_preview_callback(self, cb: Callable[[np.ndarray], None] | None) -> None:
        # Cancel any existing preview task before replacing
        if self._preview_task is not None:
            self._preview_task.cancel()
            self._preview_task = None
        self._preview_queue = None

        if cb is not None:
            self._preview_queue = asyncio.Queue(maxsize=1)
            self._preview_task = asyncio.create_task(self._preview_consumer(cb))

    async def _preview_consumer(self, callback: Callable[[np.ndarray], None]) -> None:
        while self._preview_queue is not None:
            try:
                frame = await self._preview_queue.get()
                callback(frame)
            except Exception:
                self._preview_queue = None
                break

    @property
    def running(self) -> bool:
        return self._running

    @property
    def playing(self) -> bool:
        return self._playing

    # --- Generator thread -------------------------------------------------

    def _drain_queue(self) -> None:
        """Drain all frames from the queue (called from generator thread)."""
        while True:
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break

    def _put_frame(self, frame: np.ndarray) -> None:
        """Put a frame into the queue, respecting stop_event."""
        while not self._stop_event.is_set():
            try:
                self._frame_queue.put(frame, timeout=0.05)
                return
            except queue.Full:
                continue

    def _generator_loop(self, animation_name: str, params: dict[str, Any]) -> None:
        """Background thread: step animation, apply post-processing, enqueue frames."""
        try:
            anim = get_animation(animation_name, self.cfg.width, self.cfg.height)
            if params:
                anim.configure(**params)

            sim_dt = 1.0 / 60.0

            while not self._stop_event.is_set():
                # Wait for play
                if not self._play_event.is_set():
                    self._play_event.wait(timeout=0.05)
                    continue

                # Check animation switch request
                req = self._anim_request
                if req is not None:
                    self._anim_request = None
                    name, new_params = req
                    self._drain_queue()
                    anim = get_animation(name, self.cfg.width, self.cfg.height)
                    if new_params:
                        anim.configure(**new_params)

                # Check configure request (update params in place)
                cfg_req = self._configure_request
                if cfg_req is not None:
                    self._configure_request = None
                    anim.configure(**cfg_req)

                # Check reset request
                if self._reset_requested:
                    self._reset_requested = False
                    anim.reset()

                # Step simulation
                anim.step(sim_dt)
                gray_frame = anim.render_gray()

                # Apply processing pipeline
                processed = apply_processing_pipeline(gray_frame, anim.processing_steps)

                self._put_frame(processed)
        except Exception:
            logger.exception("Generator thread crashed")

    # --- Presenter (async) ------------------------------------------------

    async def _present_loop(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            next_deadline = loop.time()
            while self._running:
                next_deadline += self.frame_interval

                # Try to get a frame (non-blocking)
                try:
                    frame = self._frame_queue.get_nowait()
                except queue.Empty:
                    frame = None

                if frame is None:
                    sleep_time = max(0.0, next_deadline - loop.time())
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)
                    continue

                # Skip serial write if the frame is identical to the last
                # one sent — avoids pulsing the mechanical display needlessly.
                changed = self._last_frame is None or not np.array_equal(
                    frame, self._last_frame
                )

                if changed:
                    panel_bits_list = split_canvas_bits_to_panels(
                        frame, self.cfg
                    )
                    addr_base = self.cfg.address_base
                    batch = self.encoder.encode_batch(
                        panel_bits_list, addr_base
                    )
                    await self.serial.write_frames([batch])
                    self._last_frame = frame.copy()
                    self._presented += 1

                if self._preview_queue is not None:
                    with contextlib.suppress(asyncio.QueueFull):
                        self._preview_queue.put_nowait(frame.copy())

                # Sleep until next deadline
                sleep_time = max(0.0, next_deadline - loop.time())
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            raise HardwareError(f"Presenter failed: {e}") from e

    # --- Public API -------------------------------------------------------

    async def start(
        self, animation: str = "bouncing_dot", params: dict[str, Any] | None = None
    ) -> None:
        if params is None:
            params = {}
        await self.serial.connect()
        self._running = True

        # Start generator thread
        self._stop_event.clear()
        self._gen_thread = threading.Thread(
            target=self._generator_loop,
            args=(animation, params),
            name="GeneratorThread",
            daemon=True,
        )
        self._gen_thread.start()

        # Start presenter task
        self._presenter_task = asyncio.create_task(self._present_loop())

    async def stop(self) -> None:
        self._running = False
        self._playing = False

        # Stop generator thread.
        self._stop_event.set()
        self._play_event.set()  # unblock if waiting on play
        if self._gen_thread is not None:
            self._gen_thread.join(timeout=1.0)
            self._gen_thread = None

        # Cancel presenter + preview tasks
        if self._presenter_task:
            self._presenter_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._presenter_task
        if self._preview_task:
            self._preview_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._preview_task

        # Disconnect serial
        with contextlib.suppress(SerialConnectionError, OSError):
            await self.serial.disconnect()

    async def play(self) -> None:
        self._playing = True
        self._play_event.set()

    async def pause(self) -> None:
        self._playing = False
        self._play_event.clear()

    async def reset(self) -> None:
        self._reset_requested = True

    def get_status(self) -> PipelineStatus:
        return PipelineStatus(
            running=self._running,
            playing=self._playing,
            frames_presented=self._presented,
            buffer_capacity=self._buffer_capacity,
        )

    def get_last_frame_bits(self) -> np.ndarray | None:
        return self._last_frame

    async def set_refresh_rate(self, new_fps: float) -> None:
        if new_fps <= 0:
            raise HardwareError("refresh_rate must be positive")
        self.cfg.refresh_rate = new_fps
        self.frame_interval = 1.0 / new_fps

    async def reconnect_serial(self) -> None:
        with contextlib.suppress(SerialConnectionError, OSError):
            await self.serial.disconnect()
        await self.serial.connect()

    async def set_animation(
        self, name: str, params: dict[str, Any] | None = None
    ) -> None:
        """Switch animation — generator thread picks up the request atomically."""
        if params is None:
            params = {}
        self._anim_request = (name, params)

    async def configure_animation(self, params: dict[str, Any]) -> None:
        """Update params on the running animation without restarting it."""
        self._configure_request = params
