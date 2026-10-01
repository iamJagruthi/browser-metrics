"""API route modules."""

from api.routes.browser_metrics import router as browser_metrics_router
from api.routes.excel_validation import router as excel_validation_router
from api.routes.health import router as health_router
from api.routes.runs import router as runs_router
from api.routes.validation import router as validation_router

__all__ = [
    "browser_metrics_router",
    "excel_validation_router",
    "health_router",
    "runs_router",
    "validation_router",
]
