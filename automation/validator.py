"""
validator.py

Main orchestration module for Browser Metrics Validator.
"""

import json
import asyncio

from .browser import (launch_browser, wait_for_dashboard,)
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
    RENDER_WAIT,
    SCREENSHOT_DIR,
)


class DashboardValidator:

    def __init__(self):
        self.timer = PerformanceTimer()

    def load_dashboards(self):

        try:
            with open(DASHBOARD_CONFIG, "r", encoding="utf-8") as file:
                return json.load(file)["dashboards"]

        except Exception as e:
            print(f"Error loading dashboard config: {e}")
            raise

    async def run_dashboard(self, dashboard):

        print(f"\nRunning Dashboard: {dashboard['name']}")

        try:
            clear()

            self.timer.reset()

            # ---------------- Browser ----------------

            self.timer.start("browser_launch")

<<<<<<< Updated upstream
            playwright, context, page = await launch_browser(dashboard["url"])
=======
        playwright, context, page = await launch_browser()
>>>>>>> Stashed changes

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

<<<<<<< Updated upstream
            await page.wait_for_timeout(RENDER_WAIT)
=======
        await wait_for_dashboard(page)
>>>>>>> Stashed changes

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

<<<<<<< Updated upstream
            ocr_results = extract_dashboard_text(screenshot_path)

            kpis = detect_kpis(ocr_results)

            return (
                playwright,
                context,
                metrics,
                screenshot_path,
                kpis
            )

        except Exception as e:
            print(f"Error running dashboard '{dashboard.get('name')}': {e}")
            raise

    async def run_links(self, links):
        """
        Run validation for a dynamically supplied list of dashboards
        (used by the API instead of the JSON config file).

        Parameters
        ----------
        links : list[dict]
            Each item must be {"name": str, "url": str}.

        Returns
        -------
        dict
            JSON-serializable result containing per-dashboard metrics,
            KPIs, and the source-vs-target comparison (if both succeeded).
        """

        headers_initialized = False

        all_metrics = []
        all_kpis = []

        for dashboard in links:

            playwright = None
            context = None

            try:
                (
                    playwright,
                    context,
                    metrics,
                    screenshot_path,
                    kpis
                ) = await self.run_dashboard(dashboard)

                if not headers_initialized:

                    initialize_storage(list(metrics.keys()))
                    headers_initialized = True

                save_metrics(metrics)

                generate_report(metrics)

                metrics_with_screenshot = dict(metrics)
                metrics_with_screenshot["screenshot_path"] = str(screenshot_path)

                all_metrics.append(metrics_with_screenshot)
                all_kpis.append(kpis)

                print("Completed")

            except Exception as e:
                print(f"Skipping dashboard '{dashboard.get('name')}' due to error: {e}")
                all_metrics.append(None)
                all_kpis.append([])

            finally:
                try:
                    if context:
                        await context.close()
                    if playwright:
                        await playwright.stop()
                except Exception as cleanup_error:
                    print(f"Error during browser cleanup: {cleanup_error}")

        comparison = None

        if len(all_kpis) >= 2 and all_metrics[0] and all_metrics[1]:

            try:
                comparison = compare_dashboard_kpis(
                    all_kpis[0],
                    all_kpis[1]
                )

            except Exception as e:
                print(f"Error comparing dashboard KPIs: {e}")

        return {
            "metrics": all_metrics,
            "kpis": [
                [{"name": kpi.name, "value": kpi.value} for kpi in kpi_list]
                for kpi_list in all_kpis
            ],
            "comparison": comparison,
        }
=======
        try:
            dashboard_data = extract_dashboard_text(
                screenshot_path
            )

            print(
                f"Dashboard Title : {dashboard_data['title']}"
            )

            print(
                f"Refresh Date    : {dashboard_data['refresh_date']}"
            )

            kpis = detect_kpis(
                dashboard_data["ocr"]
            )

        except Exception as e:
            print(f"OCR failed: {e}")
            kpis = []
        return (
            playwright,
            context,
            metrics,
            screenshot_path,
            kpis
        )
>>>>>>> Stashed changes

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
                    kpis
                ) = await self.run_dashboard(dashboard)

                if not headers_initialized:

                    initialize_storage(list(metrics.keys()))
                    headers_initialized = True

                save_metrics(metrics)

                generate_report(metrics)

                all_metrics.append(metrics)
                all_kpis.append(kpis)

                print("Completed")

            except Exception as e:
                print(f"Skipping dashboard '{dashboard.get('name')}' due to error: {e}")

            finally:
                try:
                    if context:
                        await context.close()
                    if playwright:
                        await playwright.stop()
                except Exception as cleanup_error:
                    print(f"Error during browser cleanup: {cleanup_error}")

        try:
            comparison = compare_dashboard_kpis(
                all_kpis[0],
                all_kpis[1]
            )

            print("\n" + "=" * 60)
            print("KPI COMPARISON")
            print("=" * 60)

            for result in comparison["results"]:

                print(f"\nKPI      : {result['kpi']}")
                print(f"Source   : {result['source']}")
                print(f"Target   : {result['target']}")
                print(f"Status   : {result['status']}")

            print("\n")
            print(f"Match Percentage : {comparison['match_percentage']} %")

        except Exception as e:
            print(f"Error comparing dashboard KPIs: {e}")


async def main():

    validator = DashboardValidator()

    await validator.run_all()


if __name__ == "__main__":

    asyncio.run(main())