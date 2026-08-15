"""Main orchestration for screenshot validation and browser-side visual data."""

import asyncio
import json
import uuid

from .browser import launch_browser, wait_for_dashboard
from .network import clear, register, summary
from .performance import PerformanceTimer
from .metrics import build_metrics
from services.visual_data_exporter import extract_visual_data
from utils.config import DASHBOARD_CONFIG, OUTPUT_DIR, PAGE_TIMEOUT, SCREENSHOT_DIR


class DashboardValidator:
    def __init__(self):
        self.timer = PerformanceTimer()

    def load_dashboards(self):
        with open(DASHBOARD_CONFIG, "r", encoding="utf-8") as file:
            return json.load(file)["dashboards"]

    async def run_dashboard(self, dashboard):
        """Run one dashboard while preserving its signed-in browser context."""
        playwright = context = None
        extraction = {"status": "failed", "data": None, "error": None}
        visual_data = {"status": "failed", "filters": [], "visuals": [], "errors": []}
        response = None
        try:
            clear()
            self.timer.reset()
            self.timer.start("total_execution")
            self.timer.start("browser_launch")
            playwright, context, page = await launch_browser()
            self.timer.stop("browser_launch")
            await register(page)
            page.set_default_timeout(PAGE_TIMEOUT)
            self.timer.start("page_load")
            response = await page.goto(dashboard["url"], wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
            self.timer.stop("page_load")
            self.timer.start("dashboard_render")
            await wait_for_dashboard(page)
            self.timer.stop("dashboard_render")
            self.timer.start("screenshot")
            screenshot_path = SCREENSHOT_DIR / f"{dashboard['name']}_{uuid.uuid4().hex[:8]}.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)
            self.timer.stop("screenshot")

            # Independent of Gemini: sees the live signed-in browser and filters.
            visual_data = await extract_visual_data(page, download_directory=OUTPUT_DIR / "visual_exports")
            self.timer.start("ocr")
            try:
                # A missing Gemini key must not prevent browser data collection.
                from ai.Text_Extraction import extract_dashboard_json
                extraction["data"] = await asyncio.to_thread(extract_dashboard_json, screenshot_path)
                extraction["status"] = "success"
            except Exception as exc:
                extraction["error"] = str(exc)
            finally:
                self.timer.stop("ocr")
            self.timer.stop("total_execution")
            metrics = build_metrics(
                dashboard_name=dashboard["name"], dashboard_url=dashboard["url"],
                timers=self.timer.summary(), network_summary=summary(), page_title=await page.title(),
                final_url=page.url, http_status=response.status if response else None,
            )
            metrics["screenshot_path"] = str(screenshot_path)
            metrics["extraction_status"] = extraction["status"]
            return playwright, context, {"dashboard": dashboard, "metrics": metrics, "extraction": extraction, "visual_data": visual_data}
        except Exception:
            try:
                self.timer.stop("total_execution")
            except Exception:
                pass
            raise

    async def run_links(self, links):
        """Validate source/target URLs and return data suitable for the API/frontend."""
        executions = []
        for dashboard in links:
            playwright = context = None
            try:
                playwright, context, execution = await self.run_dashboard(dashboard)
                executions.append(execution)
            except Exception as exc:
                executions.append({
                    "dashboard": dashboard, "metrics": None,
                    "extraction": {"status": "failed", "data": None, "error": str(exc)},
                    "visual_data": {"status": "failed", "filters": [], "visuals": [], "errors": [str(exc)]},
                })
            finally:
                if context:
                    await context.close()
                if playwright:
                    await playwright.stop()
        run_id = uuid.uuid4().hex
        comparison = self._compare_executions(executions)
        report_paths = self._export_reports(run_id, executions, comparison)
        return {
            "run_id": run_id, "dashboards": executions,
            "metrics": [item["metrics"] for item in executions],
            "kpis": [(item["extraction"].get("data") or {}).get("kpi_cards", []) for item in executions],
            "comparison": comparison, "report_path": report_paths.get("excel"),
            "document_report_path": report_paths.get("document"),
            "document_report_error": report_paths.get("document_error"),
        }

    def _compare_executions(self, executions):
        if len(executions) < 2:
            return {"status": "not_compared", "reason": "Two dashboards are required."}
        source, target = executions[:2]
        if source["extraction"]["status"] != "success" or target["extraction"]["status"] != "success":
            return {"status": "not_compared", "reason": "Gemini extraction failed for one or both dashboards; no match percentage was calculated."}
        from ai.Text_Extraction import compare_filters, compare_visuals
        from services.excel_exporter import build_comparison_summary, compare_kpis
        source_data, target_data = source["extraction"]["data"], target["extraction"]["data"]
        filters, kpis, visuals = compare_filters(source_data, target_data), compare_kpis(source_data, target_data), compare_visuals(source_data, target_data)
        summary = build_comparison_summary(filters, kpis, visuals)
        return {
            "status": "success", "filters": filters, "kpis": kpis, "visuals": visuals,
            "summary": summary,
            # Kept for the existing dashboard UI while richer result groups are
            # available above for API consumers.
            "results": kpis,
            "match_percentage": summary["kpi_match_percentage"],
        }

    def _export_reports(self, run_id, executions, comparison):
        if len(executions) < 2:
            return {}
        paths = {}
        try:
            from services.docx_reporter import generate_validation_document
            document = generate_validation_document(run_id, executions, comparison, OUTPUT_DIR / "reports")
            paths["document"] = str(document)
        except ModuleNotFoundError as exc:
            # Word output is an optional enhancement. Keep the validation and
            # Excel workbook usable until its package is installed.
            if exc.name != "docx":
                raise
            paths["document_error"] = "Word report skipped: install python-docx from requirements.txt."
        if comparison.get("status") != "success":
            return paths
        from services.excel_exporter import export_validation_workbook
        workbook = export_validation_workbook(
            run_id, executions[0]["extraction"]["data"], executions[1]["extraction"]["data"],
            comparison["filters"], comparison["kpis"], comparison["visuals"], comparison["summary"],
            [item["metrics"] for item in executions], OUTPUT_DIR / "reports",
            visual_data={
                "Source": executions[0]["visual_data"],
                "Target": executions[1]["visual_data"],
            },
        )
        paths["excel"] = str(workbook)
        return paths

    async def run_all(self):
        return await self.run_links(self.load_dashboards())


async def main():
    await DashboardValidator().run_all()


if __name__ == "__main__":
    asyncio.run(main())
