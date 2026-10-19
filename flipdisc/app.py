"""Main application orchestrator.

Wires together DisplayPipeline and ApiServer.

For hot-reload support, `create_asgi_app()` builds a standalone FastAPI app
with a lifespan that manages the pipeline. Uvicorn can import it by string
reference ("flipdisc.app:create_asgi_app") and restart cleanly on file changes.
"""

import logging
from contextlib import asynccontextmanager

from .config import load_config
from .engine.pipeline import DisplayPipeline
from .logging_conf import setup_logging
from .web.api_server import ApiServer

logger = logging.getLogger(__name__)


class FlipDiscApplication:
    """Main application orchestrator."""

    def __init__(self):
        self.config = None
        self.pipeline: DisplayPipeline | None = None
        self.api_server: ApiServer | None = None
        self.running = False

    async def start(
        self,
        config_path: str | None = None,
        host: str = "0.0.0.0",
        port: int = 8000,
    ):
        """Start all application tasks."""
        try:
            self.config = load_config(config_path)
            logger.info(
                f"Loaded config: {self.config.width}x{self.config.height} display"
            )
            logger.info(
                f"Serial: {self.config.serial.port} (mock={self.config.serial.mock})"
            )

            self.pipeline = DisplayPipeline(self.config)
            self.api_server = ApiServer(self.config, self.pipeline)

            logger.info("Starting pipeline (idle)...")
            await self.pipeline.start(animation="bouncing_dot", params={})

            logger.info("Starting API server...")
            self.running = True

            await self.api_server.start_server(host=host, port=port)

        except Exception:
            await self.stop()
            raise

    async def stop(self):
        """Stop all application tasks."""
        if not self.running:
            return

        logger.info("Shutting down application...")
        self.running = False

        if self.pipeline:
            await self.pipeline.stop()

        logger.info("Application shutdown complete")


def create_asgi_app(config_path: str | None = None):
    """Create a standalone ASGI app for use with uvicorn --reload.

    Uvicorn imports this factory on each reload, so the pipeline and config
    are re-created from scratch every time a file changes.
    """
    setup_logging("INFO")

    config = load_config(config_path)
    pipeline = DisplayPipeline(config)
    server = ApiServer(config, pipeline)

    @asynccontextmanager
    async def lifespan(_app):
        logger.info(
            f"Starting pipeline: {config.width}x{config.height} display "
            f"(mock={config.serial.mock})"
        )
        await pipeline.start(animation="bouncing_dot", params={})
        yield
        await pipeline.stop()

    server.app.router.lifespan_context = lifespan
    return server.app
