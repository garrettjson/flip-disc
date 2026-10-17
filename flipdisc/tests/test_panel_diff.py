"""The presenter sends only the panels that changed since they were last sent."""

import asyncio
from collections.abc import Iterable

import numpy as np

from flipdisc.config import DisplayConfig
from flipdisc.engine.pipeline import DisplayPipeline
from flipdisc.hardware.serial import SerialTransport

FLUSH = bytes([0x80, 0x82, 0x8F])


class _Recorder(SerialTransport):
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    async def write_frames(self, frames: Iterable[bytes]) -> None:
        self.writes.append(b"".join(frames))


def _addresses(batch: bytes) -> list[int]:
    """Addresses of the panel messages in a batch (28x7: 32 bytes each)."""
    body = batch.removesuffix(FLUSH)
    assert len(body) % 32 == 0
    return [body[i + 2] for i in range(0, len(body), 32)]


async def _pipeline() -> tuple[DisplayPipeline, _Recorder]:
    pipeline = DisplayPipeline(DisplayConfig())  # 28x28: four 28x7 strips
    recorder = _Recorder()
    pipeline.serial = recorder
    await recorder.connect()
    return pipeline, recorder


def _frame() -> np.ndarray:
    return np.zeros((28, 28), dtype=bool)


def test_first_frame_sends_every_panel():
    async def run():
        pipeline, rec = await _pipeline()
        await pipeline._write_frame(_frame())
        assert _addresses(rec.writes[-1]) == [1, 2, 3, 4]
        assert rec.writes[-1].endswith(FLUSH)

    asyncio.run(run())


def test_only_changed_panels_are_sent():
    async def run():
        pipeline, rec = await _pipeline()
        frame = _frame()
        await pipeline._write_frame(frame)

        frame = frame.copy()
        frame[10, 5] = True  # row 10 is in the second strip
        await pipeline._write_frame(frame)
        assert _addresses(rec.writes[-1]) == [2]
        assert rec.writes[-1].endswith(FLUSH)

        frame = frame.copy()
        frame[0, 0] = True
        frame[27, 27] = True
        await pipeline._write_frame(frame)
        assert _addresses(rec.writes[-1]) == [1, 4]
        assert pipeline.get_last_frame_bits()[27, 27]

    asyncio.run(run())


def test_identical_frame_writes_nothing():
    async def run():
        pipeline, rec = await _pipeline()
        await pipeline._write_frame(_frame())
        await pipeline._write_frame(_frame())
        assert len(rec.writes) == 1
        assert pipeline.get_status().frames_presented == 1

    asyncio.run(run())


def test_reconnect_resends_every_panel():
    async def run():
        pipeline, rec = await _pipeline()
        await pipeline._write_frame(_frame())
        await pipeline.reconnect_serial()
        await pipeline._write_frame(_frame())
        assert _addresses(rec.writes[-1]) == [1, 2, 3, 4]

    asyncio.run(run())
