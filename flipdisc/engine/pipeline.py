"""DisplayPipeline: orchestrates a background generator thread and async presenter.

The generator thread runs animations, applies post-processing, and pushes
frames into a queue.Queue. The async presenter pulls frames at refresh_rate,
encodes them, writes to serial, and broadcasts preview frames.

The small frame buffer (queue.Queue(maxsize=N)) smooths compute spikes in the
generator so the presenter always has frames ready to display.

Animations with FRAMES_ON_DEMAND (games) skip the buffer: at each tick the
presenter asks for a frame, and the generator applies pending input, steps
once, and renders it right then, so input shows on the next tick.
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

from flipdisc.animations import Animation, get_animation, validate_params
from flipdisc.config import DisplayConfig
from flipdisc.exceptions import AnimationError, HardwareError, SerialConnectionError
from flipdisc.games import Game, validate_input
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
    animation: str | None = None
    last_error: str | None = None
    # True while frames are made at each tick rather than buffered (games)
    frames_on_demand: bool = False


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

        # Control requests (main thread -> generator thread), applied in order.
        # Each is a (kind, payload) pair; kind is "switch", "configure",
        # "reset" or "input".
        self._requests: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()

        # The animation most recently asked for; params are validated against
        # its schema before a request is queued
        self._requested_animation: str | None = None

        # Written by the generator thread, read by get_status()
        self._current_animation: str | None = None
        self._last_error: tuple[str, str] | None = None

        # On-demand frames: set by the generator when it switches to an
        # animation with FRAMES_ON_DEMAND. The presenter then sets
        # _frame_wanted at each tick and waits for _frame_ready instead of
        # taking whatever is buffered.
        self._on_demand = False
        self._frame_wanted = threading.Event()
        self._frame_ready: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        # Generator thread
        self._gen_thread: threading.Thread | None = None

        # Presenter task
        self._presenter_task: asyncio.Task | None = None
        self._presented = 0
        self._running = False
        self._playing = False

        # Last frame storage + preview queue
        self._last_frame: np.ndarray | None = None
        # What each panel was last sent, in row-major order; None means the
        # panels' state is unknown and the next frame must send all of them
        self._sent_panels: list[np.ndarray] | None = None
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

    def _apply_request(
        self, anim: Animation | None, kind: str, payload: Any
    ) -> Animation | None:
        """Apply one control request and return the animation to keep running."""
        if kind == "switch":
            name, params = payload
            new_anim = get_animation(name, self.cfg.width, self.cfg.height)
            if params:
                new_anim.configure(**params)
            # Only drop queued frames once the replacement is known to work
            self._drain_queue()
            self._current_animation = name
            self._on_demand = new_anim.FRAMES_ON_DEMAND
            self._frame_wanted.clear()
            return new_anim

        if anim is None:
            raise AnimationError(f"No animation is running to {kind}")
        if kind == "configure":
            anim.configure(**payload)
        elif kind == "reset":
            anim.reset()
        elif kind == "input":
            if not isinstance(anim, Game):
                raise AnimationError(f"{self._current_animation} takes no input")
            action, pressed = payload
            anim.handle_input(action, pressed)
        return anim

    def _process_requests(self, anim: Animation | None) -> Animation | None:
        """Apply all pending requests; a failed one leaves the animation as it was."""
        while True:
            try:
                kind, payload = self._requests.get_nowait()
            except queue.Empty:
                return anim

            try:
                anim = self._apply_request(anim, kind, payload)
            except Exception as e:
                # Crash barrier: animation code can raise anything
                logger.exception(f"Animation {kind} request failed")
                self._last_error = (kind, f"{kind} failed: {e}")
                continue

            # A new animation is a clean slate; otherwise a success only
            # clears an earlier failure of the same kind
            if kind == "switch" or (self._last_error and self._last_error[0] == kind):
                self._last_error = None

    def _generator_loop(self) -> None:
        """Background thread: step animation, apply post-processing, enqueue frames."""
        try:
            anim: Animation | None = None

            while not self._stop_event.is_set():
                anim = self._process_requests(anim)

                # Wait for play
                if not self._play_event.is_set():
                    self._play_event.wait(timeout=0.05)
                    continue

                # Nothing to run until a switch request succeeds
                if anim is None:
                    self._stop_event.wait(timeout=0.05)
                    continue

                if self._on_demand:
                    # Wait for the presenter's tick, waking now and then to
                    # apply other requests (a switch away, a configure)
                    if not self._frame_wanted.wait(timeout=0.05):
                        continue
                    self._frame_wanted.clear()
                    # Input that arrived while waiting goes into this frame
                    anim = self._process_requests(anim)
                    if anim is None:
                        continue

                try:
                    # One frame of animation per frame of display time
                    anim.step(self.frame_interval)
                    gray_frame = anim.render_gray()
                    processed = apply_processing_pipeline(
                        gray_frame, anim.processing_steps
                    )
                except Exception as e:
                    # Crash barrier: drop the broken animation, keep the thread
                    logger.exception(
                        f"Animation '{self._current_animation}' failed while running"
                    )
                    self._last_error = ("run", f"{self._current_animation} failed: {e}")
                    self._current_animation = None
                    anim = None
                    continue

                if self._on_demand:
                    self._hand_over(processed)
                else:
                    self._put_frame(processed)
        except Exception:
            logger.exception("Generator thread crashed")

    def _hand_over(self, frame: np.ndarray) -> None:
        """Give the presenter the frame it asked for and wake it.

        Replaces any frame it never collected (one that missed its tick), so
        what it shows next is always the newest.
        """
        self._drain_queue()
        self._frame_queue.put_nowait(frame)
        if self._loop is not None and self._frame_ready is not None:
            # The loop is closed once the pipeline stops
            with contextlib.suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self._frame_ready.set)

    # --- Presenter (async) ------------------------------------------------

    async def _present_loop(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            next_deadline = loop.time()
            while self._running:
                next_deadline += self.frame_interval

                if self._on_demand:
                    frame = await self._request_frame(next_deadline)
                else:
                    try:
                        frame = self._frame_queue.get_nowait()
                    except queue.Empty:
                        frame = None

                if frame is None:
                    sleep_time = max(0.0, next_deadline - loop.time())
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)
                    continue

                await self._write_frame(frame)

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

    async def _request_frame(self, deadline: float) -> np.ndarray | None:
        """Ask the generator for this tick's frame and wait for it.

        Gives up at the tick's deadline; a frame that arrives later is shown
        on the next tick instead of a new one being made.
        """
        assert self._frame_ready is not None
        self._frame_ready.clear()
        with contextlib.suppress(queue.Empty):
            return self._frame_queue.get_nowait()

        self._frame_wanted.set()
        timeout = max(0.0, deadline - asyncio.get_running_loop().time())
        try:
            await asyncio.wait_for(self._frame_ready.wait(), timeout)
        except TimeoutError:
            return None
        try:
            return self._frame_queue.get_nowait()
        except queue.Empty:
            return None

    async def _write_frame(self, frame: np.ndarray) -> None:
        """Send only the panels whose bits differ from what they last got.

        Unchanged panels aren't re-sent (no wire time, no needless disc
        pulses); a frame identical to the last one writes nothing at all.
        """
        panels = split_canvas_bits_to_panels(frame, self.cfg)
        sent = self._sent_panels
        changed = {
            self.cfg.address_base + i: bits
            for i, bits in enumerate(panels)
            if sent is None or not np.array_equal(bits, sent[i])
        }
        if not changed:
            return

        await self.serial.write_frames([self.encoder.encode_panels(changed)])
        self._sent_panels = [bits.copy() for bits in panels]
        self._last_frame = frame.copy()
        self._presented += 1

    # --- Public API -------------------------------------------------------

    async def start(
        self, animation: str = "bouncing_dot", params: dict[str, Any] | None = None
    ) -> None:
        params = validate_params(animation, params or {})
        self._requested_animation = animation
        await self.serial.connect()
        self._sent_panels = None
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._frame_ready = asyncio.Event()
        self._on_demand = False

        # Start generator thread with the initial animation as its first request
        self._stop_event.clear()
        self._requests = queue.SimpleQueue()
        self._requests.put(("switch", (animation, params)))
        self._last_error = None
        self._gen_thread = threading.Thread(
            target=self._generator_loop,
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
        self._requests.put(("reset", None))

    def get_status(self) -> PipelineStatus:
        return PipelineStatus(
            running=self._running,
            playing=self._playing,
            frames_presented=self._presented,
            buffer_capacity=self._buffer_capacity,
            animation=self._current_animation,
            last_error=self._last_error[1] if self._last_error else None,
            frames_on_demand=self._on_demand,
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
        # The panels may have been power-cycled; send all of them next frame
        self._sent_panels = None

    async def set_animation(
        self, name: str, params: dict[str, Any] | None = None
    ) -> None:
        """Switch animation — the generator thread applies it on its next iteration.

        Raises AnimationError for an unknown name or invalid params. A failure
        while building or configuring the new animation keeps the current one
        running and is reported through get_status().last_error.
        """
        params = validate_params(name, params or {})
        self._requested_animation = name
        self._requests.put(("switch", (name, params)))

    async def configure_animation(self, params: dict[str, Any]) -> None:
        """Update params on the running animation without restarting it.

        Raises AnimationError if the params don't fit the schema of the
        animation most recently requested.
        """
        if self._requested_animation is None:
            raise AnimationError("No animation has been started")
        params = validate_params(self._requested_animation, params)
        self._requests.put(("configure", params))

    async def send_input(self, action: str, pressed: bool = True) -> None:
        """Press or release one of the running game's actions.

        Applied before the game's next frame is made. Raises AnimationError
        if the animation most recently requested isn't a game or has no such
        action.
        """
        if self._requested_animation is None:
            raise AnimationError("No game has been started")
        validate_input(self._requested_animation, action)
        self._requests.put(("input", (action, pressed)))
