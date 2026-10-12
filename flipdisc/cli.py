"""Simple CLI for running the Flip-Disc server and utilities."""

from __future__ import annotations

import argparse
import asyncio
import signal

import numpy as np

from .app import FlipDiscApplication
from .logging_conf import setup_logging


def _run_server_reload(args: argparse.Namespace) -> int:
    """Run with uvicorn's --reload (restarts process on file changes)."""
    import uvicorn

    setup_logging(args.log_level)
    uvicorn.run(
        "flipdisc.app:create_asgi_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=True,
        reload_dirs=["flipdisc"],
    )
    return 0


async def _run_server(args: argparse.Namespace) -> int:
    setup_logging(args.log_level)

    app = FlipDiscApplication()

    # Ensure clean shutdown on SIGTERM/SIGHUP (not just SIGINT which asyncio handles)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGHUP):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(app.stop()))

    try:
        await app.start(
            config_path=args.config,
            host=args.host,
            port=args.port,
        )
        return 0
    finally:
        await app.stop()


def _render_frame_ascii(frame: np.ndarray) -> str:
    """Convert a binary/grayscale frame to ASCII art."""
    h, w = frame.shape
    is_bool = frame.dtype == np.bool_
    lines = []
    lines.append("┌" + "──" * w + "┐")
    for y in range(h):
        row = "│"
        for x in range(w):
            on = frame[y, x] if is_bool else frame[y, x] > 0.5
            row += "██" if on else "  "
        row += "│"
        lines.append(row)
    lines.append("└" + "──" * w + "┘")
    return "\n".join(lines)


def _preview(args: argparse.Namespace) -> int:
    from .animations import get_animation, list_animations
    from .config import load_config
    from .gfx.postprocessing import apply_processing_pipeline

    if args.list:
        print("Available animations:")
        for name in list_animations():
            print(f"  {name}")
        return 0

    if not args.animation:
        print("Error: --animation is required (or use --list)")
        return 1

    cfg = load_config(args.config)
    anim = get_animation(args.animation, cfg.width, cfg.height)

    if args.seed is not None:
        anim.reset(seed=args.seed)

    # Same step the pipeline uses: one display interval per frame
    dt = 1.0 / (args.fps or cfg.refresh_rate)

    for i in range(args.frames):
        anim.step(dt)

        gray = anim.render_gray()
        processed = apply_processing_pipeline(gray, anim.processing_steps)

        header = (
            f"Frame {i + 1}/{args.frames}  "
            f"t={anim.current_time:.2f}s  "
            f"({cfg.width}x{cfg.height})"
        )
        print(f"\n{header}")
        print(_render_frame_ascii(processed))

        if anim.is_complete():
            print("(animation complete)")
            break

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="flipdisc", description="Flip-Disc controller"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run-server", help="Run the API server")
    p_run.add_argument("--config", help="Path to config TOML")
    p_run.add_argument("--host", default="0.0.0.0", help="API server host")
    p_run.add_argument("--port", type=int, default=8000, help="API server port")
    p_run.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )
    p_run.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload on file changes (dev mode)",
    )

    p_preview = sub.add_parser(
        "preview", help="Render animation frames as ASCII in terminal"
    )
    p_preview.add_argument("--animation", "-a", help="Animation name")
    p_preview.add_argument(
        "--frames", "-n", type=int, default=5, help="Number of frames (default: 5)"
    )
    p_preview.add_argument(
        "--fps", type=float, help="Frames per second (default: config refresh_rate)"
    )
    p_preview.add_argument("--seed", type=int, help="Random seed for determinism")
    p_preview.add_argument("--config", help="Path to config TOML")
    p_preview.add_argument(
        "--list", action="store_true", help="List available animations"
    )

    args = parser.parse_args(argv)

    if args.cmd == "run-server":
        if args.reload:
            return _run_server_reload(args)
        return asyncio.run(_run_server(args))
    if args.cmd == "preview":
        return _preview(args)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
