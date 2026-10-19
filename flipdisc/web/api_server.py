"""API server for control and status (FastAPI)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import tomllib
from pathlib import Path
from typing import Annotated

import httpx
import uvicorn
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from flipdisc.animations import animation_schemas
from flipdisc.animations import list_animations as list_animation_names
from flipdisc.clips.loader import _CLIPS_CONFIG, list_clips
from flipdisc.config import DisplayConfig
from flipdisc.engine.pipeline import DisplayPipeline
from flipdisc.exceptions import (
    AnimationError,
    FlipDiscError,
    HardwareError,
    SerialConnectionError,
)
from flipdisc.fonts.loader import list_fonts as list_font_names
from flipdisc.games import game_controls, list_games
from flipdisc.services.weather import WeatherData, fetch_weather

logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).resolve().parent


class ApiServer:
    """FastAPI server for flip-disc control."""

    def __init__(self, config: DisplayConfig, pipeline: DisplayPipeline) -> None:
        self.config = config
        self.pipeline = pipeline

        # Weather background fetch state
        self._weather_lat: float | None = None
        self._weather_lon: float | None = None
        self._weather_unit: str = "F"
        self._weather_interval: float = 900.0
        self._weather_task: asyncio.Task | None = None

        self.app = FastAPI(title="Flip-Disc Controller", version="0.2.0")
        # Mount static assets for UI
        static_dir = _WEB_DIR / "static"
        if static_dir.exists():
            self.app.mount(
                "/static", StaticFiles(directory=str(static_dir)), name="static"
            )
        self._setup_routes()

    def _setup_routes(self) -> None:  # noqa: PLR0915
        @self.app.get("/")
        async def root():
            return {
                "message": "Flip-Disc Controller",
                "version": "0.2.0",
                "status": "running",
            }

        @self.app.get("/status")
        async def status():
            st = self.pipeline.get_status()
            return {
                "pipeline": {
                    "running": st.running,
                    "playing": st.playing,
                    "frames_presented": st.frames_presented,
                    "buffer_capacity": st.buffer_capacity,
                    "frames_on_demand": st.frames_on_demand,
                    "animation": st.animation,
                    "last_error": st.last_error,
                    "serial_connected": self.pipeline.serial.is_connected(),
                },
                "config": {
                    "width": self.config.width,
                    "height": self.config.height,
                    "refresh_rate": self.config.refresh_rate,
                },
            }

        @self.app.get("/animations")
        async def list_animations_route():
            games = list_games()
            return {
                "animations": [n for n in list_animation_names() if n not in games],
                "games": games,
                # name -> list of parameter descriptions (see animations/params.py),
                # for games too
                "params": animation_schemas(),
                # game name -> list of {action, label, keys} (see games/base.py)
                "controls": game_controls(),
            }

        @self.app.get("/fonts")
        async def list_fonts():
            try:
                return {"fonts": list_font_names()}
            except (tomllib.TOMLDecodeError, OSError) as e:
                logger.error(f"Error listing fonts: {e}")
                raise HTTPException(500, f"Failed to list fonts: {e}") from e

        @self.app.get("/clips")
        async def list_clips_route():
            try:
                return {"clips": list_clips(_CLIPS_CONFIG)}
            except (OSError, ValueError) as e:
                logger.error(f"Error listing clips: {e}")
                raise HTTPException(500, f"Failed to list clips: {e}") from e

        @self.app.get("/images")
        async def list_images():
            try:
                images_dir = Path("assets/images")
                names = (
                    [p.stem for p in sorted(images_dir.glob("*.png"))]
                    if images_dir.exists()
                    else []
                )
                return {"images": names}
            except OSError as e:
                logger.error(f"Error listing images: {e}")
                raise HTTPException(500, f"Failed to list images: {e}") from e

        @self.app.post("/animations/configure")
        async def configure_animation(params: dict):
            try:
                # Update params on the running animation without restarting it
                name = params.pop("name", None)
                if not self.pipeline.running:
                    await self.pipeline.start(
                        animation=name or "bouncing_dot", params=params
                    )
                else:
                    await self.pipeline.configure_animation(params)
                return {"message": "Configured animation", "params": params}
            except AnimationError as e:
                logger.error(f"Animation configuration error: {e}")
                raise HTTPException(400, str(e)) from e
            except FlipDiscError as e:
                logger.error(f"Unexpected error configuring animation: {e}")
                raise HTTPException(500, f"Failed to configure animation: {e}") from e

        @self.app.post("/animations/reset")
        async def reset_animation():
            await self.pipeline.reset()
            return {"message": "Animation reset"}

        @self.app.post("/animations/stop")
        async def stop_animation():
            await self.pipeline.pause()
            return {"message": "Animation stopped"}

        @self.app.post("/anim/{name}")
        async def start_animation(
            name: str, params: Annotated[dict | None, Body()] = None
        ):
            try:
                p = params or {}
                if not self.pipeline.running:
                    await self.pipeline.start(animation=name, params=p)
                else:
                    await self.pipeline.set_animation(name, p)
                await self.pipeline.play()
                return {"message": f"Started animation: {name}"}
            except AnimationError as e:
                logger.error(f"Animation error: {e}")
                raise HTTPException(400, str(e)) from e
            except FlipDiscError as e:
                logger.error(f"Unexpected error starting animation: {e}")
                raise HTTPException(500, f"Failed to start animation: {e}") from e

        @self.app.post("/input")
        async def send_input(
            action: Annotated[str, Body()], pressed: Annotated[bool, Body()] = True
        ):
            try:
                await self.pipeline.send_input(action, pressed)
                return {"action": action, "pressed": pressed}
            except AnimationError as e:
                raise HTTPException(400, str(e)) from e

        @self.app.get("/fps")
        async def get_fps():
            return {"refresh_rate": self.config.refresh_rate}

        @self.app.post("/fps")
        async def set_fps(new_fps: float):
            try:
                await self.pipeline.set_refresh_rate(new_fps)
                return {"message": "Refresh rate updated", "refresh_rate": new_fps}
            except (HardwareError, ValueError) as e:
                logger.error(f"Error setting refresh rate: {e}")
                raise HTTPException(400, f"Failed to set refresh rate: {e}") from e

        @self.app.post("/serial/reconnect")
        async def serial_reconnect():
            try:
                await self.pipeline.reconnect_serial()
                return {"message": "Serial reconnected"}
            except (SerialConnectionError, OSError) as e:
                logger.error(f"Error reconnecting serial: {e}")
                raise HTTPException(500, f"Failed to reconnect serial: {e}") from e

        # ------------------------------------------------------------------
        # Weather endpoints
        # ------------------------------------------------------------------

        @self.app.get("/weather/config")
        async def get_weather_config():
            return {
                "latitude": self._weather_lat,
                "longitude": self._weather_lon,
                "unit": self._weather_unit,
                "interval_seconds": self._weather_interval,
                "active": self._weather_task is not None
                and not self._weather_task.done(),
            }

        @self.app.post("/weather/config")
        async def set_weather_config(params: dict):
            try:
                if "latitude" in params:
                    self._weather_lat = float(params["latitude"])
                if "longitude" in params:
                    self._weather_lon = float(params["longitude"])
                if "unit" in params:
                    self._weather_unit = str(params["unit"]).upper()
                if "interval_seconds" in params:
                    self._weather_interval = float(params["interval_seconds"])

                if self._weather_lat is None or self._weather_lon is None:
                    raise HTTPException(
                        400,
                        "latitude and longitude are required to start weather fetch",
                    )
                self._restart_weather_loop()
                return {
                    "message": "Weather config updated, fetch loop started",
                    "latitude": self._weather_lat,
                    "longitude": self._weather_lon,
                    "unit": self._weather_unit,
                    "interval_seconds": self._weather_interval,
                }
            except HTTPException:
                raise
            except (ValueError, TypeError) as e:
                logger.error(f"Error setting weather config: {e}")
                raise HTTPException(500, f"Failed to set weather config: {e}") from e

        @self.app.post("/weather/refresh")
        async def weather_refresh():
            try:
                if self._weather_lat is None or self._weather_lon is None:
                    raise HTTPException(
                        400, "Weather not configured — POST /weather/config first"
                    )
                data = await fetch_weather(
                    self._weather_lat,
                    self._weather_lon,
                    unit=self._weather_unit,
                )
                await self._push_weather(data)
                return {
                    "temp": round(data.temp),
                    "condition": data.condition,
                    "unit": data.unit,
                    "wmo_code": data.wmo_code,
                    "moon_phase": data.moon_phase,
                    "sun_progress": data.sun_progress,
                }
            except HTTPException:
                raise
            except (httpx.HTTPError, KeyError, ValueError, FlipDiscError) as e:
                logger.error(f"Error refreshing weather: {e}")
                raise HTTPException(500, f"Failed to refresh weather: {e}") from e

        # WebSocket preview endpoint
        @self.app.websocket("/ws/preview")
        async def preview_websocket(websocket: WebSocket):
            await websocket.accept()

            frame_available = asyncio.Event()

            def frame_callback(_bits):
                frame_available.set()

            self.pipeline.set_preview_callback(frame_callback)

            receive_task = asyncio.create_task(websocket.receive())
            try:
                while True:
                    frame_task = asyncio.create_task(frame_available.wait())
                    done, _ = await asyncio.wait(
                        {frame_task, receive_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    if receive_task in done:
                        frame_task.cancel()
                        break

                    # Frame arrived — cancel the (already-done) frame task
                    # and send the latest frame.
                    frame_task.cancel()
                    frame_available.clear()

                    bits = self.pipeline.get_last_frame_bits()
                    if bits is not None:
                        rows = bits.astype(int).tolist()
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "width": bits.shape[1],
                                    "height": bits.shape[0],
                                    "bits": rows,
                                }
                            )
                        )

            except WebSocketDisconnect:
                logger.debug("Preview WebSocket client disconnected")
            except (OSError, RuntimeError) as e:
                logger.error(f"Preview WebSocket error: {e}")
            finally:
                receive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect):
                    await receive_task
                self.pipeline.set_preview_callback(None)

        # Game input: {"action": "left", "pressed": true} per message. Invalid
        # messages are answered with {"error": "..."}; valid ones get no reply.
        @self.app.websocket("/ws/input")
        async def input_websocket(websocket: WebSocket):
            await websocket.accept()
            try:
                while True:
                    error = await self._apply_input_message(
                        await websocket.receive_text()
                    )
                    if error:
                        await websocket.send_text(json.dumps({"error": error}))
            except WebSocketDisconnect:
                logger.debug("Input WebSocket client disconnected")

        # UI index
        @self.app.get("/ui")
        async def ui():
            index_file = _WEB_DIR / "index.html"
            if index_file.exists():
                return HTMLResponse(index_file.read_text(encoding="utf-8"))
            raise HTTPException(404, "UI not available")

    async def _apply_input_message(self, text: str) -> str | None:
        """Send one input-socket message to the pipeline; return an error or None."""
        try:
            message = json.loads(text)
            action = message["action"]
            pressed = message.get("pressed", True)
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            return 'expected {"action": str, "pressed": bool}'
        if not isinstance(action, str) or not isinstance(pressed, bool):
            return 'expected {"action": str, "pressed": bool}'
        try:
            await self.pipeline.send_input(action, pressed)
        except AnimationError as e:
            return str(e)
        return None

    # ------------------------------------------------------------------
    # Weather background loop
    # ------------------------------------------------------------------

    async def _push_weather(self, data: WeatherData) -> bool:
        """Send fetched weather to the weather animation, if that's what is showing."""
        if self.pipeline.get_status().animation != "weather":
            return False

        conf = {
            "temp": round(data.temp),
            "condition": data.condition,
            "unit": data.unit,
            "wmo_code": data.wmo_code,
        }
        if data.moon_phase is not None:
            conf["moon_phase"] = data.moon_phase
        if data.sun_progress is not None:
            conf["sun_progress"] = data.sun_progress
        await self.pipeline.configure_animation(conf)
        return True

    async def _weather_loop(self) -> None:
        """Periodically fetch weather and push to the running animation."""
        while True:
            try:
                data: WeatherData = await fetch_weather(
                    self._weather_lat,  # type: ignore[arg-type]
                    self._weather_lon,  # type: ignore[arg-type]
                    unit=self._weather_unit,
                )
                if await self._push_weather(data):
                    logger.info(
                        f"Weather updated: {data.temp}{data.unit} {data.condition}"
                    )
            except (httpx.HTTPError, KeyError, ValueError, FlipDiscError) as e:
                logger.warning(f"Weather fetch failed: {e}")
            await asyncio.sleep(self._weather_interval)

    def _restart_weather_loop(self) -> None:
        """Cancel any existing weather loop task and start a fresh one."""
        if self._weather_task and not self._weather_task.done():
            self._weather_task.cancel()
        self._weather_task = asyncio.create_task(self._weather_loop())

    async def start_server(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        config = uvicorn.Config(self.app, host=host, port=port, log_level="warning")
        server = uvicorn.Server(config)
        logger.info(f"Starting API server on {host}:{port}")
        await server.serve()
