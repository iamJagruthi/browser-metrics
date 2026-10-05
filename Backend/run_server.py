"""
run_server.py

Launches the FastAPI backend (server.py) directly, without going
through the `uvicorn` CLI.

Why this exists:
-----------------
Playwright launches Edge as a subprocess. On supported Windows Python
versions, ``asyncio.run()`` uses the required default Proactor loop.
Keeping the launcher free of an explicit loop class also avoids startup
failures on Python versions where ``asyncio.ProactorEventLoop`` is no
longer exposed as a public attribute.

Usage
-----
    python run_server.py

Note: this does not include uvicorn's --reload auto-restart-on-change
behaviour (that machinery lives outside Server.serve() and isn't
compatible with a custom loop_factory). During development, just
re-run this script after editing backend code. If you want file-watch
auto-restart back, run `pip install watchfiles --break-system-packages`
and wrap this script's call in a `watchfiles.run_process(...)` call.
"""

import asyncio
import logging
import sys

import uvicorn

from api.logging_config import setup_logging
from server import app  # Re-export the FastAPI application as the frontend/backend bridge.


logger = logging.getLogger(__name__)


async def run():
    setup_logging()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
    server = uvicorn.Server(config)
    logger.info("Starting Browser Metrics Validator API on http://127.0.0.1:8000")
    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(run())

    except Exception:
        logger.exception("Failed to start API server")
        raise
