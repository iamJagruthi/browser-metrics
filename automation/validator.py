"""Main orchestration for screenshot validation and browser-side visual data.

Jagruthi — features:
- DOM + Gemini merge for filter and KPI comparison payloads
- Target tab focus and DOM-before-screenshot load order
- Partial comparison when Gemini fails (filters from DOM still compared)
- Always attempt Excel export with error logging
- DOM KPI hint merge into extraction results
"""

import asyncio
import json
import logging
import uuid

from .browser import launch_browser, wait_for_dashboard
from .network import clear, details, register, summary
from .performance import PerformanceTimer
from .metrics import build_metrics
from services.dashboard_inventory_service import (
    build_inventory_api_payload,
    save_inventory_snapshot,
)
from services.filter_service import build_filters_api_payload, save_filters_snapshot
from services.visual_data_exporter import apply_slicer_value, extract_filter_data, extract_visual_data
from utils.config import DASHBOARD_CONFIG, OUTPUT_DIR, PAGE_TIMEOUT, SCREENSHOT_DIR


logger = logging.getLogger(__name__)


class DashboardValidator:
    def __init__(self):
        self.timer = PerformanceTimer()

    def load_dashboards(self):
        with open(DASHBOARD_CONFIG, "r", encoding="utf-8") as file:
            return json.load(file)["dashboards"]

    async def run_dashboard(self, dashboard, *, playwright=None, context=None, page=None, validation_run_id=None):
        """Run one dashboard in a supplied authenticated Edge tab when available."""
        extraction = {"status": "failed", "data": None, "error": None}
        visual_data = {"status": "failed", "filters": [], "visuals": [], "errors": []}
        response = None
        try:
            clear()
            self.timer.reset()
            self.timer.start("total_execution")
            if page is None:
                self.timer.start("browser_launch")
                playwright, context, page = await launch_browser()
                self.timer.stop("browser_launch")
            await register(page)
            page.set_default_timeout(PAGE_TIMEOUT)
            await page.bring_to_front()
            self.timer.start("page_load")
            response = await page.goto(
                dashboard["url"],
                wait_until="domcontentloaded",
                timeout=PAGE_TIMEOUT,
            )
            self.timer.stop("page_load")
            self.timer.start("dashboard_render")
            await wait_for_dashboard(page)

            # Collect DOM visuals first so scrolling/waiting finishes before the
            # screenshot Gemini uses.  The target tab is especially prone to
            # capturing loading placeholders when shot too early.
            visual_data = await extract_visual_data(
                page,
                download_directory=OUTPUT_DIR / "visual_exports",
                attempt_export=True,
            )
            await wait_for_dashboard(page)
            self.timer.stop("dashboard_render")

            self.timer.start("screenshot")
            screenshot_path = SCREENSHOT_DIR / f"{dashboard['name']}_{uuid.uuid4().hex[:8]}.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)
            self.timer.stop("screenshot")
            self.timer.start("ocr")
            try:
                # A missing Gemini key must not prevent browser data collection.
                from ai.Text_Extraction import extract_dashboard_json
                extraction["data"] = await asyncio.to_thread(extract_dashboard_json, screenshot_path)
                self._merge_dom_filters(extraction["data"], visual_data)
                self._merge_dom_kpis(extraction["data"], visual_data)
                extraction["status"] = "success"
            except Exception as exc:
                extraction["error"] = str(exc)
            finally:
                self.timer.stop("ocr")
            self.timer.stop("total_execution")
            metrics = build_metrics(
                dashboard_name=dashboard["name"], dashboard_url=dashboard["url"],
                timers=self.timer.summary(), network_summary=summary(),
                network_details=details(),
                page_title=await page.title(),
                final_url=page.url, http_status=response.status if response else None,
                validation_run_id=validation_run_id,
            )
            metrics["screenshot_path"] = str(screenshot_path)
            metrics["extraction_status"] = extraction["status"]
            if extraction.get("error"):
                metrics["extraction_error"] = extraction["error"]
            return playwright, context, {"dashboard": dashboard, "metrics": metrics, "extraction": extraction, "visual_data": visual_data, "_page": page}
        except Exception:
            logger.exception("Dashboard run failed | dashboard=%s", dashboard.get("name"))
            try:
                self.timer.stop("total_execution")
            except Exception:
                pass
            raise

    @staticmethod
    def _merge_dom_filters(extracted_data, visual_data):
        """Prefer live DOM filter state over screenshot inference.

        Gemini remains useful for metadata, but it cannot reliably decide which
        visually styled button is selected.  Browser accessibility attributes
        (``aria-pressed``, ``aria-selected`` and checked inputs) are the source
        of truth whenever they are available.
        """
        if not extracted_data:
            return
        filters = extracted_data.setdefault("filters", [])
        index = {
            " ".join(str(item.get("filter_name", "")).casefold().split()): item
            for item in filters
            if item.get("filter_name")
        }
        for dom_filter in visual_data.get("filters", []):
            key = " ".join(str(dom_filter.get("name", "")).casefold().split())
            if not key:
                continue
            item = index.get(key)
            if item is None:
                item = {"filter_name": dom_filter["name"], "filter_type": dom_filter.get("filter_type", "Buttons"), "selected_values": [], "available_values": []}
                filters.append(item)
                index[key] = item
            if dom_filter.get("selected_values"):
                item["selected_values"] = dom_filter["selected_values"]
            if dom_filter.get("visible_values"):
                item["available_values"] = dom_filter["visible_values"]
            item["filter_type"] = dom_filter.get("filter_type") or item.get("filter_type")
            item["extraction_source"] = "dom"
        logger.info("Merged DOM filter state | filters=%d", len(filters))

    @staticmethod
    def _build_comparison_payload(execution: dict) -> dict:
        """Merge Gemini extraction with live DOM filter state for comparisons."""
        extraction = execution.get("extraction", {})
        visual_data = execution.get("visual_data", {})
        data = dict(extraction.get("data") or {})
        if not data:
            data = {
                "filters": [],
                "kpi_cards": [],
                "charts": [],
                "tables": [],
                "metadata": {},
            }
        DashboardValidator._merge_dom_filters(data, visual_data)
        DashboardValidator._merge_dom_kpis(data, visual_data)
        return data

    @staticmethod
    def _merge_dom_kpis(extracted_data, visual_data):
        """Supplement Gemini KPI cards with DOM card/callout values when present."""
        if not extracted_data:
            return
        existing = {
            " ".join(str(item.get("name", "")).casefold().split())
            for item in extracted_data.get("kpi_cards", [])
            if item.get("name")
        }
        for dom_kpi in visual_data.get("kpi_cards", []):
            key = " ".join(str(dom_kpi.get("name", "")).casefold().split())
            if not key or key in existing:
                continue
            extracted_data.setdefault("kpi_cards", []).append(
                {
                    "name": dom_kpi.get("name"),
                    "value": dom_kpi.get("value"),
                    "previous_value": dom_kpi.get("previous_value"),
                    "variance": dom_kpi.get("variance"),
                    "extraction_source": "dom",
                }
            )
            existing.add(key)
        if visual_data.get("kpi_cards"):
            logger.info(
                "Merged DOM KPI hints | kpi_cards=%d",
                len(extracted_data.get("kpi_cards", [])),
            )

    async def run_links(self, links):
        """Validate source/target URLs and return data suitable for the API/frontend."""
        executions = []
        resources = []
        if not links:
            return {"run_id": uuid.uuid4().hex, "dashboards": [], "metrics": [], "kpis": [], "comparison": {"status": "not_compared", "reason": "Two dashboards are required."}}
        run_id = uuid.uuid4().hex
        try:
            # A persistent Edge profile can only be launched once at a time.
            # Reuse one authenticated context and open the dashboards in tabs.
            playwright, context, first_page = await launch_browser()
            resources.append((playwright, context))
            for index, dashboard in enumerate(links):
                page = first_page if index == 0 else await context.new_page()
                try:
                    await page.bring_to_front()
                    _, _, execution = await self.run_dashboard(
                        dashboard, playwright=playwright, context=context, page=page,
                        validation_run_id=run_id,
                    )
                    executions.append(execution)
                except Exception as exc:
                    logger.exception("Dashboard run failed | dashboard=%s", dashboard.get("name"))
                    executions.append({
                        "dashboard": dashboard, "metrics": None,
                        "extraction": {"status": "failed", "data": None, "error": str(exc)},
                        "visual_data": {"status": "failed", "filters": [], "visuals": [], "errors": [str(exc)]},
                    })
        except Exception as exc:
            logger.exception("Unable to launch shared Edge context")
            executions = [{
                "dashboard": dashboard, "metrics": None,
                "extraction": {"status": "failed", "data": None, "error": str(exc)},
                "visual_data": {"status": "failed", "filters": [], "visuals": [], "errors": [str(exc)]},
            } for dashboard in links]
        try:
            slicer_scenarios = await self._run_slicer_scenarios(executions)
            comparison = self._compare_executions(executions)
            comparison["slicer_scenarios"] = slicer_scenarios
            report_paths = self._export_reports(run_id, executions, comparison)
            public_executions = [{key: value for key, value in item.items() if key != "_page"} for item in executions]
            filters_payload = build_filters_api_payload(
                public_executions,
                run_id=run_id,
                comparison_filters=comparison.get("filters", []),
            )
            inventory_payload = build_inventory_api_payload(
                public_executions,
                run_id=run_id,
            )
            return {
                "run_id": run_id, "dashboards": public_executions,
                "metrics": [item["metrics"] for item in executions],
                "kpis": [(item["extraction"].get("data") or {}).get("kpi_cards", []) for item in executions],
                "comparison": comparison, "report_path": report_paths.get("excel"),
                "document_report_path": report_paths.get("document"),
                "document_report_error": report_paths.get("document_error"),
                "report_downloads": {
                    "excel": f"/api/reports/{run_id}/excel" if report_paths.get("excel") else None,
                    "docx": f"/api/reports/{run_id}/docx" if report_paths.get("document") else None,
                    "filters": f"/api/reports/{run_id}/filters",
                    "inventory": f"/api/reports/{run_id}/inventory",
                },
                "filters": filters_payload,
                "inventory": inventory_payload,
                "llm_results": [
                    {"dashboard": item["dashboard"].get("name"), "extraction": item["extraction"].get("data")}
                    for item in executions
                ],
                "filter_state": {
                    item["dashboard"].get("name"): item["visual_data"].get("filters", [])
                    for item in executions
                },
            }
        finally:
            for playwright, context in resources:
                try:
                    await context.close()
                    await playwright.stop()
                except Exception:
                    logger.exception("Failed to close browser resources")

    async def _run_slicer_scenarios(self, executions):
        """Apply one common, non-selected slicer value to both dashboards.

        This is intentionally opt-in by available common options only.  It
        never guesses a value, and it preserves a record when the UI cannot
        safely expose a matching slicer option.
        """
        if len(executions) < 2 or not all(item.get("_page") for item in executions[:2]):
            return []
        source, target = executions[:2]
        source_filters = {" ".join(str(item.get("name", "")).casefold().split()): item for item in source["visual_data"].get("filters", [])}
        target_filters = {" ".join(str(item.get("name", "")).casefold().split()): item for item in target["visual_data"].get("filters", [])}
        for key in sorted(set(source_filters) & set(target_filters)):
            left, right = source_filters[key], target_filters[key]
            selected = {" ".join(str(value).casefold().split()) for value in left.get("selected_values", []) + right.get("selected_values", [])}
            candidates = [value for value in left.get("visible_values", []) if " ".join(str(value).casefold().split()) in {" ".join(str(item).casefold().split()) for item in right.get("visible_values", [])} and " ".join(str(value).casefold().split()) not in selected and str(value).strip().casefold() not in {"all", "select all"}]
            if not candidates:
                continue
            value = candidates[0]
            slicer_name = left.get("name") or right.get("name")
            logger.info("Running matched slicer scenario | slicer=%s | value=%s", slicer_name, value)
            applied_source = await apply_slicer_value(source["_page"], slicer_name, value)
            applied_target = await apply_slicer_value(target["_page"], slicer_name, value)
            scenario = {"slicer": slicer_name, "value": value, "source_applied": applied_source, "target_applied": applied_target}
            if applied_source and applied_target:
                source_visual = await extract_visual_data(source["_page"], download_directory=OUTPUT_DIR / "visual_exports")
                target_visual = await extract_visual_data(target["_page"], download_directory=OUTPUT_DIR / "visual_exports")
                from services.excel_exporter import build_visual_data_comparison
                scenario["visual_comparison"] = build_visual_data_comparison({"Source": source_visual, "Target": target_visual})["summary"]
                scenario_id = uuid.uuid4().hex[:8]
                source_image = SCREENSHOT_DIR / f"slicer_source_{scenario_id}.png"
                target_image = SCREENSHOT_DIR / f"slicer_target_{scenario_id}.png"
                await source["_page"].screenshot(path=str(source_image), full_page=True)
                await target["_page"].screenshot(path=str(target_image), full_page=True)
                scenario["screenshots"] = {"source": str(source_image), "target": str(target_image)}
                try:
                    from ai.Text_Extraction import extract_dashboard_json
                    source_analysis, target_analysis = await asyncio.gather(
                        asyncio.to_thread(extract_dashboard_json, source_image),
                        asyncio.to_thread(extract_dashboard_json, target_image),
                    )
                    scenario["ai_analysis"] = {
                        "source_kpis": source_analysis.get("kpi_cards", []),
                        "target_kpis": target_analysis.get("kpi_cards", []),
                    }
                except Exception as exc:
                    logger.exception("Slicer screenshot AI analysis failed")
                    scenario["ai_analysis_error"] = str(exc)
            else:
                scenario["status"] = "not_run"
            return [scenario]
        return []

    def _compare_executions(self, executions):
        if len(executions) < 2:
            return {"status": "not_compared", "reason": "Two dashboards are required."}
        source, target = executions[:2]
        source_data = self._build_comparison_payload(source)
        target_data = self._build_comparison_payload(target)
        source_gemini_ok = source["extraction"]["status"] == "success"
        target_gemini_ok = target["extraction"]["status"] == "success"

        if not source_data.get("filters") and not target_data.get("filters"):
            if not source_gemini_ok and not target_gemini_ok:
                return {
                    "status": "not_compared",
                    "reason": "Gemini extraction failed for both dashboards and no DOM filters were captured.",
                }

        from services.comparison_service import compare_dashboard_payloads

        return compare_dashboard_payloads(
            source_data,
            target_data,
            source_gemini_ok=source_gemini_ok,
            target_gemini_ok=target_gemini_ok,
        )

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
        except Exception:
            logger.exception("Word report generation failed | run_id=%s", run_id)
            paths["document_error"] = "Word report generation failed. See server logs."

        # Jagruthi: always attempt Excel export so filter/table data is available
        # even when Gemini KPI extraction is empty or partial.
        try:
            from services.excel_exporter import export_validation_workbook

            comparison_payload = comparison if comparison.get("status") == "success" else {
                "filters": comparison.get("filters", []),
                "kpis": comparison.get("kpis", []),
                "visuals": comparison.get("visuals", []),
                "summary": comparison.get("summary", {
                    "filter_match_percentage": 0.0,
                    "kpi_match_percentage": 0.0,
                    "visual_match_percentage": 0.0,
                    "overall_match_percentage": 0.0,
                }),
                "slicer_scenarios": comparison.get("slicer_scenarios", []),
            }
            source_payload = self._build_comparison_payload(executions[0])
            target_payload = self._build_comparison_payload(executions[1])
            workbook = export_validation_workbook(
                run_id,
                source_payload,
                target_payload,
                comparison_payload.get("filters", []),
                comparison_payload.get("kpis", []),
                comparison_payload.get("visuals", []),
                comparison_payload.get("summary", {}),
                [item["metrics"] for item in executions],
                OUTPUT_DIR / "reports",
                visual_data={
                    "Source": executions[0]["visual_data"],
                    "Target": executions[1]["visual_data"],
                },
                slicer_scenarios=comparison_payload.get("slicer_scenarios", []),
            )
            paths["excel"] = str(workbook)
        except Exception as exc:
            logger.exception("Excel workbook generation failed | run_id=%s", run_id)
            paths["excel_error"] = f"Excel report failed: {exc}"

        # Jagruthi: persist filter snapshot for GET /api/reports/{run_id}/filters.
        try:
            public_executions = [{key: value for key, value in item.items() if key != "_page"} for item in executions]
            filters_payload = build_filters_api_payload(
                public_executions,
                run_id=run_id,
                comparison_filters=comparison.get("filters", []),
            )
            save_filters_snapshot(run_id, filters_payload, OUTPUT_DIR / "reports")
            paths["filters"] = str(OUTPUT_DIR / "reports" / f"{run_id}_filters.json")
            inventory_payload = build_inventory_api_payload(
                public_executions,
                run_id=run_id,
            )
            save_inventory_snapshot(run_id, inventory_payload, OUTPUT_DIR / "reports")
            paths["inventory"] = str(OUTPUT_DIR / "reports" / f"{run_id}_inventory.json")
        except Exception:
            logger.exception("Filter snapshot save failed | run_id=%s", run_id)
        return paths

    async def run_filter_probe(self, links):
        """Open dashboard URLs and return DOM filter state without full validation."""
        executions = await self._probe_dashboard_executions(links)
        comparison_filters = []
        if len(executions) >= 2:
            source_data = self._build_comparison_payload(executions[0])
            target_data = self._build_comparison_payload(executions[1])
            if source_data.get("filters") or target_data.get("filters"):
                from ai.Text_Extraction import compare_filters
                comparison_filters = compare_filters(source_data, target_data)
        return build_filters_api_payload(
            executions,
            run_id=None,
            comparison_filters=comparison_filters,
        )

    async def run_inventory_probe(self, links):
        """Open dashboard URLs and return filters plus visual inventory counts."""
        executions = await self._probe_dashboard_executions(links)
        return build_inventory_api_payload(executions, run_id=None)

    async def _probe_dashboard_executions(self, links):
        executions = []
        resources = []
        if not links:
            return executions
        try:
            playwright, context, first_page = await launch_browser()
            resources.append((playwright, context))
            for index, dashboard in enumerate(links):
                page = first_page if index == 0 else await context.new_page()
                try:
                    await page.bring_to_front()
                    await page.goto(
                        dashboard["url"],
                        wait_until="domcontentloaded",
                        timeout=PAGE_TIMEOUT,
                    )
                    await wait_for_dashboard(page)
                    visual_data = await extract_filter_data(page)
                    executions.append({
                        "dashboard": dashboard,
                        "visual_data": visual_data,
                        "extraction": {"status": "skipped", "data": None, "error": None},
                    })
                except Exception as exc:
                    logger.exception("Dashboard probe failed | dashboard=%s", dashboard.get("name"))
                    executions.append({
                        "dashboard": dashboard,
                        "visual_data": {"status": "failed", "filters": [], "errors": [str(exc)]},
                        "extraction": {"status": "failed", "data": None, "error": str(exc)},
                    })
        except Exception as exc:
            logger.exception("Unable to launch shared Edge context for dashboard probe")
            executions = [{
                "dashboard": dashboard,
                "visual_data": {"status": "failed", "filters": [], "errors": [str(exc)]},
                "extraction": {"status": "failed", "data": None, "error": str(exc)},
            } for dashboard in links]
        finally:
            for playwright, context in resources:
                try:
                    await context.close()
                    await playwright.stop()
                except Exception:
                    logger.exception("Failed to close browser resources after dashboard probe")
        return executions

    async def run_all(self):
        return await self.run_links(self.load_dashboards())


async def main():
    await DashboardValidator().run_all()


if __name__ == "__main__":
    asyncio.run(main())
