"""FastAPI application factory.

Jagruthi — production layout: routers grouped by domain (health, validation, probes, reports).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.logging_config import setup_logging
from api.routes import health_router, probes_router, reports_router, validation_router


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
    application.include_router(validation_router)
    application.include_router(probes_router)
    application.include_router(reports_router)

    logger.info("FastAPI application initialized")
    return application
