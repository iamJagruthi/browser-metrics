"""
validator.py

Main orchestration module for Browser Metrics Validator.
"""

import json
import asyncio
import logging

from .browser import launch_browser, wait_for_dashboard
from .network import register, summary, clear
from .performance import PerformanceTimer
from .metrics import build_metrics
from .storage import initialize_storage, save_metrics
from .report import generate_report

from services.ocr_service import extract_dashboard_text
from services.kpi_service import detect_kpis
from services.comparison_service import compare_dashboard_kpis

from utils.config import (
    DASHBOARD_CONFIG,
    PAGE_TIMEOUT,
    SCREENSHOT_DIR,
)
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

class DashboardValidator:

    def __init__(self):
        self.timer = PerformanceTimer()

    def load_dashboards(self):
        try:
            with open(DASHBOARD_CONFIG, "r", encoding="utf-8") as file:
                return json.load(file)["dashboards"]

        except Exception as e:
            logger.exception(f"Error loading dashboard config: {e}")
            raise

    async def run_dashboard(self, dashboard):

        logger.info(f"\nRunning Dashboard: {dashboard['name']}")

        playwright = None
        context = None
        page = None

        try:

            clear()
            self.timer.reset()

            # ---------------- Browser ----------------

            self.timer.start("browser_launch")

            playwright, context, page = await launch_browser()

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

            # ---------------- Dashboard Render ----------------

            self.timer.start("dashboard_render")

            await wait_for_dashboard(page)

            self.timer.stop("dashboard_render")

            # ---------------- Screenshot ----------------

            self.timer.start("screenshot")

            screenshot_path = (
                SCREENSHOT_DIR /
                f"{dashboard['name']}.png"
            )

            await page.screenshot(
                path=str(screenshot_path),
                full_page=True,
            )

            self.timer.stop("screenshot")

            # ---------------- Metrics ----------------

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

            # ---------------- OCR ----------------

            dashboard_data = {}
            kpis = []

            try:

                dashboard_data = extract_dashboard_text(
                    screenshot_path
                )

                logger.info(
                    f"Dashboard Title : {dashboard_data.get('title')}"
                )

                logger.info(
                    f"Refresh Date    : {dashboard_data.get('refresh_date')}"
                )

                kpis = detect_kpis(
                    dashboard_data.get("ocr", [])
                )

            except Exception as e:

                logger.exception(f"OCR failed: {e}")
                kpis = []

            return (
                playwright,
                context,
                metrics,
                screenshot_path,
                dashboard_data,
                kpis,
            )

        except Exception as e:

            logger.exception(f"Dashboard execution failed: {e}")
            raise

    async def run_all(self):

        dashboards = self.load_dashboards()

        headers_initialized = False

        all_metrics = []
        all_kpis = []

        for dashboard in dashboards:

            playwright = None
            context = None

            try:

                (
                    playwright,
                    context,
                    metrics,
                    screenshot_path,
                    dashboard_data,
                    kpis,
                ) = await self.run_dashboard(dashboard)

                if not headers_initialized:

                    initialize_storage(list(metrics.keys()))
                    headers_initialized = True

                save_metrics(metrics)

                generate_report(metrics)

                all_metrics.append(metrics)
                all_kpis.append(kpis)

                logger.info("Completed")

            except Exception as e:

                logger.error(
                    f"Skipping dashboard '{dashboard.get('name')}' due to error: {e}"
                )

            finally:

                try:

                    if context:
                        await context.close()

                    if playwright:
                        await playwright.stop()

                except Exception as cleanup_error:

                    logger.exception(
                        f"Error during browser cleanup: {cleanup_error}"
                    )

        # ---------------- KPI Comparison ----------------

        if len(all_kpis) >= 2:

            try:

                comparison = compare_dashboard_kpis(
                    all_kpis[0],
                    all_kpis[1],
                )

                logger.info("\n" + "=" * 60)
                logger.info("KPI COMPARISON")
                logger.info("=" * 60)

                for result in comparison["results"]:

                    print(f"\nKPI      : {result['kpi']}")
                    print(f"Source   : {result['source']}")
                    print(f"Target   : {result['target']}")
                    print(f"Status   : {result['status']}")

                logger.info("\n")
                logger.info(
                    f"Match Percentage : {comparison['match_percentage']} %"
                )

            except Exception as e:

                logger.exception(f"Error comparing dashboard KPIs: {e}")

        else:

            logger.warning(
                "Need at least two dashboards to perform KPI comparison."
            )


async def main():

    validator = DashboardValidator()

    await validator.run_all()


if __name__ == "__main__":

    asyncio.run(main())