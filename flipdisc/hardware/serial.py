"""Serial transport implementations (hardware and mock)."""

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable

from aioserial import AioSerial
from serial import SerialException

from flipdisc.config import SerialConfig
from flipdisc.exceptions import SerialConnectionError

logger = logging.getLogger(__name__)


class SerialTransport(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    async def write_frames(self, frames: Iterable[bytes]) -> None: ...


class HardwareSerialTransport(SerialTransport):
    def __init__(self, config: SerialConfig):
        self.config = config
        self._serial: AioSerial | None = None
        self._io_lock = asyncio.Lock()

    async def connect(self) -> None:
        async with self._io_lock:
            try:
                self._serial = AioSerial(
                    port=self.config.port,
                    baudrate=self.config.baudrate,
                    timeout=self.config.timeout,
                )
                await asyncio.sleep(0.1)
                logger.info(f"Connected to hardware serial port {self.config.port}")
            except (SerialException, OSError, ValueError) as e:
                self._serial = None
                raise SerialConnectionError(
                    f"Hardware serial connect failed: {e}"
                ) from e

    async def disconnect(self) -> None:
        async with self._io_lock:
            if self._serial:
                try:
                    self._serial.close()
                    logger.info("Disconnected from hardware serial port")
                except (SerialException, OSError) as e:
                    raise SerialConnectionError(
                        f"Hardware serial disconnect failed: {e}"
                    ) from e
                finally:
                    self._serial = None

    def is_connected(self) -> bool:
        return self._serial is not None

    async def write_frames(self, frames: Iterable[bytes]) -> None:
        if not self._serial:
            raise SerialConnectionError("Not connected to hardware")
        try:
            for frame in frames:
                written = await self._serial.write_async(frame)
                if written != len(frame):
                    raise SerialConnectionError(
                        f"Short write: {written}/{len(frame)} bytes"
                    )
        except SerialConnectionError:
            raise
        except (SerialException, OSError) as e:
            raise SerialConnectionError(f"Hardware write failed: {e}") from e


class MockSerialTransport(SerialTransport):
    def __init__(self, config: SerialConfig):
        self.config = config
        self._connected = False

    async def connect(self) -> None:
        await asyncio.sleep(0.01)
        self._connected = True
        logger.info(f"[MOCK] Connected to serial port {self.config.port}")

    async def disconnect(self) -> None:
        await asyncio.sleep(0.01)
        self._connected = False
        logger.info("[MOCK] Disconnected from serial port")

    def is_connected(self) -> bool:
        return self._connected

    async def write_frames(self, frames: Iterable[bytes]) -> None:
        if not self._connected:
            raise SerialConnectionError("Not connected to mock serial")
        frame_count = 0
        total_bytes = 0
        for frame in frames:
            frame_count += 1
            total_bytes += len(frame)
        logger.debug(f"[MOCK] Wrote {frame_count} frames ({total_bytes} bytes)")
        await asyncio.sleep(0.001 * frame_count)


def create_serial_transport(
    config: SerialConfig, use_hardware: bool | None = None
) -> SerialTransport:
    if use_hardware is None:
        use_hardware = not config.mock
    if use_hardware:
        logger.info("Creating hardware serial transport")
        return HardwareSerialTransport(config)
    logger.info("Creating mock serial transport")
    return MockSerialTransport(config)
