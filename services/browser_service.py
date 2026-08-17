"""
browser_service.py

Service layer for browser automation.
"""

import logging

from automation.browser import launch_browser


logger = logging.getLogger(__name__)


async def capture_dashboard(dashboard_url: str) -> dict:
    """Launch browser and capture dashboard."""
    try:
        logger.info("Capturing dashboard | url=%s", dashboard_url)
        playwright, context, page = await launch_browser(dashboard_url)
        return {
            "playwright": playwright,
            "context": context,
            "page": page,
        }
    except Exception:
        logger.exception("Failed to capture dashboard | url=%s", dashboard_url)
        raise
