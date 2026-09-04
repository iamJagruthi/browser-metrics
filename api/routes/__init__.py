"""API route modules."""

from api.routes.health import router as health_router
from api.routes.validation import router as validation_router

__all__ = [
    "health_router",
    "validation_router",
]
