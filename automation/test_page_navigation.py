import asyncio
import json

from automation.browser import launch_browser, wait_for_dashboard
from automation.validator import DashboardValidator
from utils.config import DASHBOARD_CONFIG, PAGE_TIMEOUT


async def inspect_page_navigation():
    playwright = None
    context = None

    try:
        # Load first dashboard from existing config
        with open(DASHBOARD_CONFIG, "r", encoding="utf-8") as file:
            dashboard = json.load(file)["dashboards"][0]

        # Use existing browser setup
        playwright, context, page = await launch_browser()

        page.set_default_timeout(PAGE_TIMEOUT)

        print(f"Opening dashboard: {dashboard['name']}")

        await page.goto(
            dashboard["url"],
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT,
        )

        await wait_for_dashboard(page)

        validator = DashboardValidator()

        # ============================================================
        # Detect dashboard pages
        # ============================================================

        pages = await validator.get_dashboard_pages(page)

        print("\nDetected dashboard pages:")

        for page_info in pages:
            selected = " [Selected]" if page_info["selected"] else ""
            print(f"- {page_info['name']}{selected}")

        # ============================================================
        # Arun - Test Multi Page Navigation
        # ============================================================

        print("\nTesting navigation to Turnover...")

        await validator.navigate_to_page(page, "Turnover")

        print("\nTesting navigation to Check-Ins...")

        await validator.navigate_to_page(page, "Check-Ins")

        print("\nMulti-page navigation test completed successfully.")

        # ============================================================
        # Existing inspection
        # ============================================================

        print("\nDashboard loaded.")
        print("URL:", page.url)

        # Inspect possible page navigation elements
        elements = await page.locator(
            '[role="tab"], [role="button"], button'
        ).all()

        print(
            f"\nFound {len(elements)} possible "
            "navigation/button elements.\n"
        )

        for index, element in enumerate(elements):
            try:
                text = (await element.inner_text()).strip()
            except Exception:
                text = ""

            try:
                aria_label = await element.get_attribute("aria-label")
            except Exception:
                aria_label = None

            try:
                title = await element.get_attribute("title")
            except Exception:
                title = None

            if text or aria_label or title:
                print(
                    f"{index}: "
                    f"text={text!r}, "
                    f"aria-label={aria_label!r}, "
                    f"title={title!r}"
                )

        await page.screenshot(
            path="page_navigation_inspection.png",
            full_page=True,
        )

        print(
            "\nScreenshot saved as: "
            "page_navigation_inspection.png"
        )

    finally:
        if context:
            await context.close()

        if playwright:
            await playwright.stop()


if __name__ == "__main__":
    asyncio.run(inspect_page_navigation())