"""
metrics.py

Builds a standardized metrics dictionary for every dashboard execution.
This object can be exported as JSON, uploaded to Google Sheets,
or used by the comparison module.
"""

from datetime import datetime
import uuid


def build_metrics(
    dashboard_name: str,
    dashboard_url: str,
    timers: dict,
    network_summary: dict,
    page_title: str = "",
    final_url: str = "",
    http_status: int | None = None,
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

    Returns:
        Dictionary containing all browser metrics.
    """

    return {

        # ----------------------------
        # Run Information
        # ----------------------------

        "run_id": str(uuid.uuid4()),

        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

        # ----------------------------
        # Dashboard Information
        # ----------------------------

        "dashboard_name": dashboard_name,

        "dashboard_url": dashboard_url,

        "page_title": page_title,

        "final_url": final_url,

        "http_status": http_status,

        # ----------------------------
        # Performance Metrics
        # ----------------------------

        "browser_launch_seconds":
            timers.get("browser_launch", 0),

        "page_load_seconds":
            timers.get("page_load", 0),

        "dashboard_render_seconds":
            timers.get("dashboard_render", 0),

        "screenshot_seconds":
            timers.get("screenshot", 0),

        "total_execution_seconds":
            timers.get("total_execution", 0),

        # ----------------------------
        # Network Metrics
        # ----------------------------

        "total_requests":
            network_summary.get("total_requests", 0),

        "total_responses":
            network_summary.get("total_responses", 0),

        "failed_requests":
            network_summary.get("failed_requests", 0),

        "console_messages":
            network_summary.get("console_messages", 0),

        "page_errors":
            network_summary.get("page_errors", 0)

    }