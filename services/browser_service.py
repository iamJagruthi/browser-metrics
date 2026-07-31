"""
browser_service.py

Service layer for browser automation.
"""

from automation.browser import launch_browser


async def capture_dashboard(dashboard_url):
    """
    Launch browser and capture dashboard.
    """

    playwright, context, page = await launch_browser(
        dashboard_url
    )

    return {
        "playwright": playwright,
        "context": context,
        "page": page
    }