"""API route modules."""

from api.routes.agent_ws import router as agent_ws_router
from api.routes.browser_metrics import router as browser_metrics_router
from api.routes.excel_validation import router as excel_validation_router
from api.routes.health import router as health_router
from api.routes.runs import router as runs_router
from api.routes.validation import router as validation_router
from api.routes.agent_jobs import router as agent_jobs_router

__all__ = [
    "agent_ws_router",
    "browser_metrics_router",
    "excel_validation_router",
    "health_router",
    "runs_router",
    "validation_router",
    "agent_jobs_router",
]
