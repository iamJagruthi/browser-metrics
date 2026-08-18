"""
metrics.py

Builds a standardized metrics dictionary for every dashboard execution.
This object is returned by the API and written to the Excel Browser Metrics
worksheet (plus optional network detail sheets).
"""

from datetime import datetime
import logging
import uuid


logger = logging.getLogger(__name__)

_TIMER_FIELD_MAP = {
    "browser_launch": "browser_launch_seconds",
    "page_load": "page_load_seconds",
    "dashboard_render": "dashboard_render_seconds",
    "screenshot": "screenshot_seconds",
    "ocr": "gemini_extraction_seconds",
    "total_execution": "total_execution_seconds",
}


def build_metrics(
    dashboard_name: str,
    dashboard_url: str,
    timers: dict,
    network_summary: dict,
    page_title: str = "",
    final_url: str = "",
    http_status: int | None = None,
    network_details: dict | None = None,
    validation_run_id: str | None = None,
):
    """
    Creates a standardized metrics dictionary.

    Args:
        dashboard_name: Friendly dashboard name.
        dashboard_url: Dashboard URL.
        timers: Dictionary returned from PerformanceTimer.summary().
        network_summary: Dictionary returned from network.summary().
        page_title: Browser page title.
        final_url: Final redirected URL.
        http_status: HTTP status code.
        network_details: Optional detailed network events from network.details().
        validation_run_id: Parent validation run id (when part of a compare run).

    Returns:
        Dictionary containing all browser metrics.
    """

    try:
        metrics = {
            "validation_run_id": validation_run_id,
            "run_id": str(uuid.uuid4()),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "dashboard_name": dashboard_name,
            "dashboard_url": dashboard_url,
            "page_title": page_title,
            "final_url": final_url,
            "http_status": http_status,
            "browser_launch_seconds": timers.get("browser_launch", 0) or 0,
            "page_load_seconds": timers.get("page_load", 0) or 0,
            "dashboard_render_seconds": timers.get("dashboard_render", 0) or 0,
            "screenshot_seconds": timers.get("screenshot", 0) or 0,
            "gemini_extraction_seconds": timers.get("ocr", 0) or 0,
            "total_execution_seconds": timers.get("total_execution", 0) or 0,
            "total_requests": network_summary.get("total_requests", 0),
            "total_responses": network_summary.get("total_responses", 0),
            "failed_requests": network_summary.get("failed_requests", 0),
            "console_messages": network_summary.get("console_messages", 0),
            "page_errors": network_summary.get("page_errors", 0),
        }

        # Include any additional timers without dropping unknown keys.
        for timer_name, elapsed in (timers or {}).items():
            field_name = _TIMER_FIELD_MAP.get(timer_name, f"{timer_name}_seconds")
            if field_name not in metrics:
                metrics[field_name] = elapsed or 0

        if network_details:
            metrics["network_details"] = {
                "failed_requests": network_details.get("failed_requests", []),
                "console_logs": network_details.get("console_logs", []),
                "page_errors": network_details.get("page_errors", []),
            }

        logger.debug(
            "Metrics built | dashboard=%s | page_load=%s",
            dashboard_name,
            metrics.get("page_load_seconds"),
        )
        return metrics

    except Exception:
        logger.exception("Failed to build metrics | dashboard=%s", dashboard_name)
        raise




# changes