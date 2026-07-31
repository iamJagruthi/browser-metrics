"""
validator.py

Main orchestration module for Browser Metrics Validator.
"""

import json
import asyncio

from .browser import launch_browser
from .network import register, summary, clear
from .performance import PerformanceTimer
from .metrics import build_metrics
from .storage import initialize_storage, save_metrics
from .report import generate_report

from utils.config import (
    DASHBOARD_CONFIG,
    PAGE_TIMEOUT,
    RENDER_WAIT,
    SCREENSHOT_DIR,
)


class DashboardValidator:

    def __init__(self):
        self.timer = PerformanceTimer()

    def load_dashboards(self):

        with open(DASHBOARD_CONFIG, "r", encoding="utf-8") as file:
            return json.load(file)["dashboards"]

    async def run_dashboard(self, dashboard):

        print(f"\nRunning Dashboard: {dashboard['name']}")

        clear()

        self.timer.reset()

        # ---------------- Browser ----------------

        self.timer.start("browser_launch")

        playwright, context, page = await launch_browser(dashboard["url"])

        self.timer.stop("browser_launch")

        await register(page)

        page.set_default_timeout(PAGE_TIMEOUT)

        # ---------------- Page Load ----------------

        self.timer.start("page_load")

        response = await page.goto(
            dashboard["url"],
            wait_until="domcontentloaded",
        )

        self.timer.stop("page_load")

        # ---------------- Render ----------------

        self.timer.start("dashboard_render")

        await page.wait_for_timeout(RENDER_WAIT)

        self.timer.stop("dashboard_render")

        # ---------------- Screenshot ----------------

        self.timer.start("screenshot")

        screenshot_path = (
            SCREENSHOT_DIR /
            f"{dashboard['name']}.png"
        )

        await page.screenshot(
            path=str(screenshot_path),
            full_page=True
        )

        self.timer.stop("screenshot")

        # ---------------- Total ----------------

        total_execution = (
            self.timer.get("browser_launch")
            + self.timer.get("page_load")
            + self.timer.get("dashboard_render")
            + self.timer.get("screenshot")
        )

        timers = self.timer.summary()
        timers["total_execution"] = total_execution

        network_summary = summary()

        metrics = build_metrics(
            dashboard_name=dashboard["name"],
            dashboard_url=dashboard["url"],
            timers=timers,
            network_summary=network_summary,
            page_title=await page.title(),
            final_url=page.url,
            http_status=response.status if response else None,
        )

        return playwright, context, metrics

    async def run_all(self):

        dashboards = self.load_dashboards()

        headers_initialized = False

        for dashboard in dashboards:

            playwright, context, metrics = await self.run_dashboard(dashboard)

            if not headers_initialized:

                initialize_storage(list(metrics.keys()))
                headers_initialized = True

            save_metrics(metrics)

            generate_report(metrics)

            await context.close()
            await playwright.stop()

            print("Completed")


async def main():

    validator = DashboardValidator()

    await validator.run_all()


if __name__ == "__main__":

    asyncio.run(main())