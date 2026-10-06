"""FastAPI application factory.

Jagruthi ΓÇö production layout: routers grouped by domain (health, validation).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.logging_config import setup_logging
from api.routes import (
    agent_ws_router,
    browser_metrics_router,
    excel_validation_router,
    health_router,
    runs_router,
    validation_router,
)


logger = logging.getLogger(__name__)

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    setup_logging()
    application = FastAPI(
        title="Browser Metrics Validator API",
        description="Power BI dashboard validation, comparison, and reporting API.",
        version="1.0.0",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=DEFAULT_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(health_router)
    application.include_router(browser_metrics_router)
    application.include_router(excel_validation_router)
    application.include_router(runs_router)
    application.include_router(validation_router)
    application.include_router(agent_ws_router)

    # Serve production React build if present
    try:
        backend_dir = Path(__file__).resolve().parent.parent
        dist_dir = backend_dir.parent / "Frontend" / "dist"
        if dist_dir.exists():
            assets_dir = dist_dir / "assets"
            if assets_dir.exists():
                application.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
            index_file = dist_dir / "index.html"
            if index_file.exists():

                @application.get("/")
                async def serve_index():
                    from fastapi.responses import FileResponse

                    return FileResponse(str(index_file))
    except Exception as e:
        logger.warning(f"Failed to mount static frontend: {e}")

    logger.info("FastAPI application initialized")
    return application
