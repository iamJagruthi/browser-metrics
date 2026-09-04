"""Main orchestration for screenshot validation and browser-side visual data."""

import asyncio
import json
import logging
import time
import uuid

from .browser import capture_dashboard_snapshot, launch_browser, wait_for_dashboard
from .network import clear, details, register, summary
from .performance import PerformanceTimer
from .metrics import build_metrics
from services.dashboard_inventory_service import (
    build_inventory_api_payload,
    build_pages_showcase_payload,
)

from services.visual_data_exporter import extract_visual_data
from utils.config import DASHBOARD_CONFIG, OUTPUT_DIR, PAGE_TIMEOUT, SCREENSHOT_DIR
from automation.SlicerEngine import SlicerEngine
from automation.test_page_navigation import get_dashboard_pages, navigate_to_page
from services.comparison_service import (
    build_filters_api_payload,
    build_mismatch_payload,
    compare_dashboard_payloads,
)    

logger = logging.getLogger(__name__)


class DashboardValidator:
    def __init__(self):
        self.timer = PerformanceTimer()

    def load_dashboards(self):
        with open(DASHBOARD_CONFIG, "r", encoding="utf-8") as file:
            return json.load(file)["dashboards"]

    async def run_dashboard(
        self,
        dashboard,
        *,
        playwright=None,
        context=None,
        page=None,
        filter_selections=None,
        browser_launch_elapsed=0.0,
    ):
        """Run one dashboard in a supplied authenticated Edge tab when available."""
        extraction = {"status": "not_used", "data": None, "error": None}
        visual_data = {"status": "failed", "filters": [], "visuals": [], "errors": []}
        response = None
        engine = SlicerEngine(page)

        try:
            clear()
            self.timer.reset()
            self.timer.start("total_execution")

            if page is None:
                self.timer.start("browser_launch")
                playwright, context, page = await launch_browser()
                self.timer.stop("browser_launch")
            elif browser_launch_elapsed:
                self.timer.set_elapsed("browser_launch", browser_launch_elapsed)

            await register(page)
            page.set_default_timeout(PAGE_TIMEOUT)

            self.timer.start("page_load")
            response = await page.goto(
                dashboard["url"],
                wait_until="domcontentloaded",
                timeout=PAGE_TIMEOUT,
            )
            self.timer.stop("page_load")

            self.timer.start("dashboard_render")
            await wait_for_dashboard(page)
            self.timer.stop("dashboard_render")

            pages = await get_dashboard_pages(page)

            if len(pages) > 1:
                executions = []
                page_filter_selections = {}

                for page_info in pages:
                    current_page_name = page_info["name"]

                    if not page_info["selected"]:
                        await navigate_to_page(page, current_page_name)

                    predetermined = (filter_selections or {}).get(current_page_name)

                    execution, applied = await engine.process_dashboard_page(
                        dashboard=dashboard,
                        page=page,
                        response=response,
                        page_name=current_page_name,
                        predetermined_filters=predetermined,
                    )

                    executions.extend(execution)
                    page_filter_selections[current_page_name] = applied

                try:
                    self.timer.stop("total_execution")
                except Exception:
                    pass

                return playwright, context, executions, page_filter_selections

            self.timer.start("screenshot")
            screenshot_path = (
                SCREENSHOT_DIR
                / f"{dashboard['name']}_{uuid.uuid4().hex[:8]}.png"
            )
            await page.screenshot(
                path=str(screenshot_path),
                full_page=True,
            )
            self.timer.stop("screenshot")

            # automation/validator.py

            self.timer.start("visual_extraction")
            try:
                visual_data = await extract_visual_data(
                    page,
                    download_directory=OUTPUT_DIR / "visual_exports",
                    attempt_export=True,
                )
                
                # Guard: Only wait if page is still open and active
                if page and not page.is_closed():
                    await page.wait_for_timeout(1500)
                    
            except Exception as exc:
                logger.exception(
                    "DOM visual extraction failed | dashboard=%s",
                    dashboard.get("name"),
                )
                visual_data = {
                    "status": "failed",
                    "kpi_cards": [],
                    "visuals": [],
                    "filters": [],
                    "errors": [str(exc)],
                }
            finally:
                self.timer.stop("visual_extraction")

            self.timer.stop("total_execution")

            metrics = await self._capture_metrics(
                dashboard,
                page,
                response,
                page_name="Default",
                screenshot_path=screenshot_path,
            )
            metrics["extraction_status"] = extraction["status"]
            if extraction.get("error"):
                metrics["extraction_error"] = extraction["error"]

            return playwright, context, {
                "dashboard": dashboard,
                "metrics": metrics,
                "extraction": extraction,
                "visual_data": visual_data,
                "_page": page,
            }, {}

        except Exception:
            logger.exception(
                "Dashboard run failed | dashboard=%s",
                dashboard.get("name"),
            )

            try:
                self.timer.stop("total_execution")
            except Exception:
                pass

            raise

    @staticmethod
    def _build_comparison_payload(execution: dict) -> dict:
        visual_data = execution.get("visual_data") or {}

        return {
            "filters": visual_data.get("filters", []),
            "kpi_cards": visual_data.get("kpi_cards", []),
            "visuals": visual_data.get("visuals", []),
            "button_groups": visual_data.get("button_groups", []),
            "table_exports": visual_data.get("table_exports", []),
        }

    async def _capture_metrics(
        self,
        dashboard,
        page,
        response,
        *,
        page_name=None,
        screenshot_path=None,
    ) -> dict:
        title = "Unknown / Page Closed"
        final_url = ""

        if page and not page.is_closed():
            try:
                title = await page.title()
                final_url = page.url
            except Exception as e:
                logger.warning(f"Could not retrieve page title: {e}")
                final_url = getattr(page, "url", "")

        metrics = build_metrics(
            dashboard_name=dashboard["name"],
            dashboard_url=dashboard["url"],
            timers=self.timer.summary(),
            network_summary=summary(),
            network_details={},
            page_title=title,
            final_url=final_url,
            http_status=response.status if response else None,
        )
        
        metrics.pop("network_details", None)

        if page_name:
            metrics["page_name"] = page_name
        if screenshot_path:
            metrics["screenshot_path"] = str(screenshot_path)
        return metrics

    async def run_links(self, links):
        executions = []
        resources = []
        executions_by_dashboard = []
        multi_page_mode = False
        source_filter_selections = None

        if not links:
            return {
                "run_id": uuid.uuid4().hex,
                "dashboards": [],
                "metrics": [],
                "kpis": [],
                "comparison": {
                    "status": "not_compared",
                    "reason": "Two dashboards are required.",
                },
            }

        try:
            launch_started = time.perf_counter()
            playwright, context, first_page = await launch_browser()
            browser_launch_elapsed = time.perf_counter() - launch_started
            resources.append((playwright, context))

            for index, dashboard in enumerate(links):
                is_context_dead = False
                try:
                    _ = context.pages
                except Exception:
                    is_context_dead = True

                if is_context_dead:
                    playwright, context, first_page = await launch_browser()
                    resources.append((playwright, context))
                    page = first_page
                else:
                    try:
                        page = (
                            first_page
                            if (index == 0 and not first_page.is_closed())
                            else await context.new_page()
                        )
                    except Exception as page_err:
                        playwright, context, first_page = await launch_browser()
                        resources.append((playwright, context))
                        page = first_page

                try:
                    _, _, execution, page_filters = await self.run_dashboard(
                        dashboard,
                        playwright=playwright,
                        context=context,
                        page=page,
                        filter_selections=source_filter_selections,
                        browser_launch_elapsed=browser_launch_elapsed,
                    )

                    if index == 0:
                        source_filter_selections = page_filters

                    if isinstance(execution, list):
                        multi_page_mode = True
                        dashboard_executions = execution
                        executions.extend(execution)
                    else:
                        dashboard_executions = [execution]
                        executions.append(execution)

                    executions_by_dashboard.append(
                        dashboard_executions
                    )

                except Exception as exc:
                    failed_execution = {
                        "dashboard": dashboard,
                        "metrics": None,
                        "extraction": {
                            "status": "failed",
                            "data": None,
                            "error": str(exc),
                        },
                        "visual_data": {
                            "status": "failed",
                            "filters": [],
                            "visuals": [],
                            "errors": [str(exc)],
                        },
                    }

                    executions.append(failed_execution)
                    executions_by_dashboard.append([failed_execution])

        except Exception as exc:
            executions = [
                {
                    "dashboard": dashboard,
                    "metrics": None,
                    "extraction": {
                        "status": "failed",
                        "data": None,
                        "error": str(exc),
                    },
                    "visual_data": {
                        "status": "failed",
                        "filters": [],
                        "visuals": [],
                        "errors": [str(exc)],
                    },
                }
                for dashboard in links
            ]

            executions_by_dashboard = [[execution] for execution in executions]

        try:
            if multi_page_mode:
                comparison = self._compare_multi_page_executions(
                    executions_by_dashboard
                )

                slicer_scenarios = (
                    await self._run_multi_page_slicer_scenarios(
                        executions_by_dashboard
                    )
                )

                report_executions = (
                    self._get_first_matching_page_pair(
                        executions_by_dashboard
                    )
                )

                if not report_executions:
                    report_executions = executions[:2]

            else:
                slicer_scenarios = await self._run_slicer_scenarios(
                    executions
                )

                comparison = self._compare_executions(
                    executions
                )

                report_executions = executions

            comparison["slicer_scenarios"] = slicer_scenarios

            run_id = uuid.uuid4().hex

            if multi_page_mode and source_filter_selections:
                try:
                    applied_filters_path = (
                        OUTPUT_DIR / "reports" / f"{run_id}_applied_filters.json"
                    )
                    applied_filters_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(applied_filters_path, "w", encoding="utf-8") as f:
                        json.dump(
                            source_filter_selections,
                            f,
                            indent=2,
                            ensure_ascii=False,
                        )
                except Exception:
                    logger.exception(
                        "Failed to save applied filter selections | run_id=%s",
                        run_id,
                    )

            mismatches_payload = build_mismatch_payload(
                comparison, 
                run_id=run_id
            )

            report_paths = {
                "excel": None,
                "document": None,
                "document_error": None,
                "mismatches_data": mismatches_payload,
            }

            public_executions = [
                {
                    key: value
                    for key, value in item.items()
                    if key != "_page"
                }
                for item in executions
            ]

            filters_payload = build_filters_api_payload(
                public_executions,
                run_id=run_id,
                comparison_filters=comparison.get("filters", []),
            )
            
            # Pass comparison dict explicitly to merge top-level tables into dashboard payloads
            inventory_payload = build_inventory_api_payload(
                public_executions,
                run_id=run_id,
                comparison=comparison,
            )
            public_groups = [
                [
                    {
                        key: value
                        for key, value in item.items()
                        if key != "_page"
                    }
                    for item in group
                ]
                for group in executions_by_dashboard
            ]
            pages_payload = build_pages_showcase_payload(
                public_executions,
                executions_by_dashboard=public_groups,
                run_id=run_id,
            )

            if multi_page_mode:
                visual_results = [
                    {
                        "dashboard": item["dashboard"].get("name"),
                        "page_name": item["dashboard"].get("page_name"),
                        "kpi_cards": item["visual_data"].get("kpi_cards", []),
                        "visuals": item["visual_data"].get("visuals", []),
                    }
                    for item in executions
                ]

                filter_state = {
                    (
                        f"{item['dashboard'].get('name')}"
                        f"::{item['dashboard'].get('page_name')}"
                    ): item["visual_data"].get("filters", [])
                    for item in executions
                }
            else:
                visual_results = [
                    {
                        "dashboard": item["dashboard"].get("name"),
                        "kpi_cards": item["visual_data"].get("kpi_cards", []),
                        "visuals": item["visual_data"].get("visuals", []),
                    }
                    for item in executions
                ]

                filter_state = {
                    item["dashboard"].get("name"): item[
                        "visual_data"
                    ].get("filters", [])
                    for item in executions
                }

            return {
                "run_id": run_id,
                "dashboards": public_executions,
                "metrics": [
                    item.get("metrics", {})
                    for item in executions
                ],
                "kpis": [
                    item.get("visual_data", {}).get("kpi_cards", [])
                    for item in executions
                ],
                "comparison": comparison,
                "report_path": report_paths.get("excel"),
                "document_report_path": report_paths.get("document"),
                "document_report_error": report_paths.get(
                    "document_error"
                ),
                "report_downloads": {
                    "excel": (
                        f"/api/reports/{run_id}/excel"
                        if report_paths.get("excel")
                        else None
                    ),
                    "docx": (
                        f"/api/reports/{run_id}/docx"
                        if report_paths.get("document")
                        else None
                    ),
                    "filters": f"/api/reports/{run_id}/filters",
                    "inventory": f"/api/reports/{run_id}/inventory",
                    "pages": f"/api/reports/{run_id}/pages",
                    "mismatches": f"/api/reports/{run_id}/mismatches",
                },
                "filters": filters_payload,
                "inventory": inventory_payload,
                "pages": pages_payload,
                "mismatches": report_paths.get("mismatches_data"),
                "visual_results": visual_results,
                "filter_state": filter_state,
                "applied_filter_selections": source_filter_selections,
            }

        finally:
            for playwright, context in resources:
                try:
                    await context.close()
                    await playwright.stop()
                except Exception:
                    logger.exception(
                        "Failed to close browser resources"
                    )

    async def _run_slicer_scenarios(self, executions):
        if len(executions) < 2 or not all(
            item.get("_page")
            for item in executions[:2]
        ):
            return []

        source, target = executions[:2]

        source_filters = {
            " ".join(
                str(item.get("name", "")).casefold().split()
            ): item
            for item in source["visual_data"].get(
                "filters",
                [],
            )
        }

        target_filters = {
            " ".join(
                str(item.get("name", "")).casefold().split()
            ): item
            for item in target["visual_data"].get(
                "filters",
                [],
            )
        }

        for key in sorted(
            set(source_filters) & set(target_filters)
        ):
            left, right = (
                source_filters[key],
                target_filters[key],
            )

            selected = {
                " ".join(
                    str(value).casefold().split()
                )
                for value in (
                    left.get("selected_values", [])
                    + right.get("selected_values", [])
                )
            }

            candidates = [
                value
                for value in left.get(
                    "visible_values",
                    [],
                )
                if (
                    " ".join(
                        str(value).casefold().split()
                    )
                    in {
                        " ".join(
                            str(item).casefold().split()
                        )
                        for item in right.get(
                            "visible_values",
                            [],
                        )
                    }
                    and
                    " ".join(
                        str(value).casefold().split()
                    ) not in selected
                    and
                    str(value).strip().casefold()
                    not in {"all", "select all"}
                )
            ]

            if not candidates:
                continue

            value = candidates[0]

            slicer_name = (
                left.get("name")
                or right.get("name")
            )

            source_engine = SlicerEngine(source["_page"])
            target_engine = SlicerEngine(target["_page"])

            applied_source = await source_engine.apply_filter(
                slicer_name,
                value,
            )

            applied_target = await target_engine.apply_filter(
                slicer_name,
                value,
            )

            scenario = {
                "slicer": slicer_name,
                "value": value,
                "source_applied": applied_source,
                "target_applied": applied_target,
            }

            if applied_source and applied_target:
                source_visual = await extract_visual_data(
                    source["_page"],
                    download_directory=OUTPUT_DIR / "visual_exports",
                )

                target_visual = await extract_visual_data(
                    target["_page"],
                    download_directory=OUTPUT_DIR / "visual_exports",
                )

                scenario_id = uuid.uuid4().hex[:8]

                source_image = (
                    SCREENSHOT_DIR
                    / f"slicer_source_{scenario_id}.png"
                )

                target_image = (
                    SCREENSHOT_DIR
                    / f"slicer_target_{scenario_id}.png"
                )

                await source["_page"].screenshot(
                    path=str(source_image),
                    full_page=True,
                )

                await target["_page"].screenshot(
                    path=str(target_image),
                    full_page=True,
                )

                scenario["screenshots"] = {
                    "source": str(source_image),
                    "target": str(target_image),
                }

            else:
                scenario["status"] = "not_run"

            return [scenario]

        return []

    def _compare_executions(self, executions):
        if len(executions) < 2:
            return {
                "status": "not_compared",
                "reason": "Two dashboards are required.",
            }

        source = executions[0]
        target = executions[1]

        source_data = self._build_comparison_payload(source)
        target_data = self._build_comparison_payload(target)

        from services.comparison_service import compare_dashboard_payloads

        return compare_dashboard_payloads(
            source_data,
            target_data,
        )

    @staticmethod
    def _get_first_matching_page_pair(
        executions_by_dashboard,
    ):
        if len(executions_by_dashboard) < 2:
            return []

        source_pages = executions_by_dashboard[0]
        target_pages = executions_by_dashboard[1]

        for source in source_pages:
            page_name = source["dashboard"].get(
                "page_name"
            )

            if not page_name:
                continue

            for target in target_pages:
                if (
                    target["dashboard"].get("page_name")
                    == page_name
                ):
                    return [source, target]

        return []

    def _compare_multi_page_executions(
        self,
        executions_by_dashboard,
    ):
        if len(executions_by_dashboard) < 2:
            return {
                "status": "not_compared",
                "reason": "Two dashboards are required.",
                "page_comparisons": [],
            }

        source_pages = executions_by_dashboard[0]
        target_pages = executions_by_dashboard[1]

        target_by_page = {
            item["dashboard"].get("page_name"): item
            for item in target_pages
        }

        page_comparisons = []

        for source in source_pages:
            page_name = source["dashboard"].get(
                "page_name"
            )

            target = target_by_page.get(page_name)

            if not target:
                continue

            page_comparison = self._compare_executions(
                [source, target]
            )

            page_comparison["page_name"] = page_name

            page_comparisons.append(
                page_comparison
            )

        if not page_comparisons:
            return {
                "status": "not_compared",
                "reason": (
                    "No matching page names were found "
                    "between the two dashboards."
                ),
                "page_comparisons": [],
            }

        successful = [
            item
            for item in page_comparisons
            if item.get("status") == "success"
        ]

        first_result = (
            successful[0]
            if successful
            else page_comparisons[0]
        )

        return {
            "status": (
                "success"
                if successful
                else "not_compared"
            ),
            "filters": first_result.get(
                "filters",
                [],
            ),
            "kpis": first_result.get(
                "kpis",
                [],
            ),
            "visuals": first_result.get(
                "visuals",
                [],
            ),
            "summary": first_result.get(
                "summary",
                {},
            ),
            "results": first_result.get(
                "results",
                [],
            ),
            "match_percentage": first_result.get(
                "match_percentage",
                0,
            ),
            "page_comparisons": page_comparisons,
        }

    async def _run_multi_page_slicer_scenarios(
        self,
        executions_by_dashboard,
    ):
        if len(executions_by_dashboard) < 2:
            return []

        source_pages = executions_by_dashboard[0]
        target_pages = executions_by_dashboard[1]

        target_by_page = {
            item["dashboard"].get("page_name"): item
            for item in target_pages
        }

        scenarios = []

        for source in source_pages:
            page_name = source["dashboard"].get(
                "page_name"
            )

            target = target_by_page.get(page_name)

            if not target:
                continue

            page_scenarios = await self._run_slicer_scenarios(
                [source, target]
            )

            for scenario in page_scenarios:
                scenario["page_name"] = page_name

            scenarios.extend(page_scenarios)

        return scenarios

async def main():
    await DashboardValidator().run_all()


if __name__ == "__main__":
    asyncio.run(main())