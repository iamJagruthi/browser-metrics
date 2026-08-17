"""API route modules."""

from api.routes.health import router as health_router
from api.routes.probes import router as probes_router
from api.routes.reports import router as reports_router
from api.routes.validation import router as validation_router

__all__ = [
    "health_router",
    "probes_router",
    "reports_router",
    "validation_router",
]
