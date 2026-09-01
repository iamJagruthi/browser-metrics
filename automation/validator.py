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
    save_inventory_snapshot,
    save_pages_snapshot,
)
from services.excel_exporter import export_validation_workbook
from services.mismatch_service import build_mismatch_payload, save_mismatch_snapshot
from services.filter_service import build_filters_api_payload, save_filters_snapshot
from services.visual_data_exporter import extract_visual_data
from services.table_exporter import export_table_visuals
from utils.config import DASHBOARD_CONFIG, OUTPUT_DIR, PAGE_TIMEOUT, SCREENSHOT_DIR
# commenting the below import as we are going ahead without ai
# from ai.Text_Extraction import extract_dashboard_json
from services.visual_data_exporter import extract_visual_data
from automation.SlicerEngine import SlicerEngine


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
        """Run one dashboard in a supplied authenticated Edge tab when available.

        `filter_selections`, if provided, is a {page_name: {filter_name: value}}
        map captured from an earlier (source) dashboard run. When present,
        each report page replays exactly those filter/value pairs instead of
        picking new random ones, so the two dashboards end up compared in the
        same filtered state. Returns a 4th value: a {page_name: {filter_name:
        value}} map of whatever this dashboard actually applied, so a later
        (target) dashboard can replay it. This is empty for the single-page
        path, since no page-level filter randomization happens there.
        """
        extraction = {"status": "not_used", "data": None, "error": None}
        visual_data = {"status": "failed", "filters": [], "visuals": [], "errors": []}
        response = None

        try:
            clear()
            self.timer.reset()
            self.timer.start("total_execution")

            # Compare runs launch Edge in run_links, then pass in `page`.
            # Time that launch there and inject it here, otherwise this
            # timer never starts and browser_launch_seconds stays 0.
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

            # ============================================================
            # Arun - Multi Page Dashboard Processing
            # ============================================================

            pages = await self.get_dashboard_pages(page)

            # Only use the new multi-page flow when the dashboard
            # actually contains more than one report page.
            if len(pages) > 1:
                executions = []
                page_filter_selections = {}

                for page_info in pages:
                    page_name = page_info["name"]

                    logger.info(
                        "Processing dashboard page | dashboard=%s | page=%s",
                        dashboard.get("name"),
                        page_name,
                    )

                    if not page_info["selected"]:
                        await self.navigate_to_page(
                            page,
                            page_name,
                        )

                    predetermined = (filter_selections or {}).get(page_name)

                    execution, applied = await self.process_dashboard_page(
                        dashboard=dashboard,
                        page=page,
                        response=response,
                        page_name=page_name,
                        predetermined_filters=predetermined,
                    )

                    executions.extend(execution)
                    page_filter_selections[page_name] = applied

                try:
                    self.timer.stop("total_execution")
                except Exception:
                    pass

                return playwright, context, executions, page_filter_selections

            # ============================================================
            # Existing single-page processing
            # ============================================================

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

            # Independent of Gemini: sees the live signed-in browser and filters.
            visual_data = await extract_visual_data(
                page,
                download_directory=OUTPUT_DIR / "visual_exports",
                attempt_export=True,
            )

            self.timer.start("visual_extraction")

            try:
                visual_data = await extract_visual_data(
                    page,
                    attempt_export=False,
                )

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
        """
        Build the comparison payload entirely from DOM-extracted data.
        """
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
        """Build the metrics dict that the API returns to the frontend."""
        
        # Safe retrieval of page title and URL
        title = "Unknown / Page Closed"
        final_url = ""
        
        if page and not page.is_closed():
            try:
                title = await page.title()
                final_url = page.url
            except Exception as e:
                self.logger.warning(f"Could not retrieve page title: {e}")
                final_url = getattr(page, "url", "")

        metrics = build_metrics(
            dashboard_name=dashboard["name"],
            dashboard_url=dashboard["url"],
            timers=self.timer.summary(),
            network_summary=summary(),
            network_details=details(),
            page_title=title,
            final_url=final_url,
            http_status=response.status if response else None,
        )
        if page_name:
            metrics["page_name"] = page_name
        if screenshot_path:
            metrics["screenshot_path"] = str(screenshot_path)
        return metrics

    async def run_links(self, links):
        """Validate source/target URLs and return data suitable for the API/frontend."""
        executions = []
        resources = []

        # ============================================================
        # Arun - Multi Page Execution Tracking
        # ============================================================

        executions_by_dashboard = []
        multi_page_mode = False

        # ============================================================
        # Filter replay: the first dashboard picks filters randomly per
        # page; every dashboard after it replays those exact selections
        # instead of randomizing its own, so source and target are always
        # compared in the same filtered state.
        # ============================================================
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
            # A persistent Edge profile can only be launched once at a time.
            # Reuse one authenticated context and open the dashboards in tabs.
            launch_started = time.perf_counter()
            playwright, context, first_page = await launch_browser()
            browser_launch_elapsed = time.perf_counter() - launch_started
            logger.info(
                "Browser launch completed | elapsed=%.3f seconds",
                browser_launch_elapsed,
            )
            resources.append((playwright, context))

            for index, dashboard in enumerate(links):
                # Safe check: context in Playwright Python doesn't have .is_closed()
                is_context_dead = False
                try:
                    _ = context.pages
                except Exception:
                    is_context_dead = True

                if is_context_dead:
                    logger.warning("Browser context died. Relaunching context...")
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
                        logger.error(f"Failed to create new page, recreating context: {page_err}")
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
                        # Whatever the first (source) dashboard actually
                        # applied is what every later dashboard will replay.
                        source_filter_selections = page_filters

                    # ========================================================
                    # Arun - Accept Single or Multiple Page Executions
                    # ========================================================

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
                    logger.exception(
                        "Dashboard run failed | dashboard=%s",
                        dashboard.get("name"),
                    )

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

                    executions.append(
                        failed_execution
                    )

                    executions_by_dashboard.append(
                        [failed_execution]
                    )

        except Exception as exc:
            logger.exception(
                "Unable to launch shared Edge context"
            )

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

            executions_by_dashboard = [
                [execution]
                for execution in executions
            ]

        try:
            # ============================================================
            # Arun - Page-wise Comparison
            # ============================================================

            if multi_page_mode:
                comparison = self._compare_multi_page_executions(
                    executions_by_dashboard
                )

                slicer_scenarios = (
                    await self._run_multi_page_slicer_scenarios(
                        executions_by_dashboard
                    )
                )

                # Reports currently expect one source and one target
                # execution. Use the first matching page pair for the
                # existing report generator while API results contain
                # every page.
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

            # Persist exactly what filter values were applied on the source
            # dashboard (and therefore replayed on every dashboard after it),
            # so the run's filtered state is auditable independent of the
            # comparison/mismatch report.
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

            report_paths = self._export_reports(
                run_id,
                report_executions,
                comparison,
                executions_by_dashboard=executions_by_dashboard,
                multi_page_mode=multi_page_mode,
            )

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
            inventory_payload = build_inventory_api_payload(
                public_executions,
                run_id=run_id,
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

            # ============================================================
            # Arun - Page-aware API response
            # ============================================================

            if multi_page_mode:
                llm_results = [
                    {
                        "dashboard": item["dashboard"].get("name"),
                        "page_name": item["dashboard"].get("page_name"),
                        "extraction": item["visual_data"].get("data"),
                    }
                    for item in executions
                ]

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
        """Apply one common, non-selected slicer value to both dashboards.

        This is intentionally opt-in by available common options only.  It
        never guesses a value, and it preserves a record when the UI cannot
        safely expose a matching slicer option.
        """
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

            logger.info(
                "Running matched slicer scenario | slicer=%s | value=%s",
                slicer_name,
                value,
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

                from services.excel_exporter import (
                    build_visual_data_comparison,
                )

                scenario["visual_comparison"] = (
                    build_visual_data_comparison(
                        {
                            "Source": source_visual,
                            "Target": target_visual,
                        }
                    )["summary"]
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

                # try:
                #     from ai.Text_Extraction import (
                #         extract_dashboard_json,
                #     )

                #     source_analysis, target_analysis = (
                #         await asyncio.gather(
                #             asyncio.to_thread(
                #                 extract_dashboard_json,
                #                 source_image,
                #             ),
                #             asyncio.to_thread(
                #                 extract_dashboard_json,
                #                 target_image,
                #             ),
                #         )
                #     )

                #     scenario["ai_analysis"] = {
                #         "source_kpis": source_analysis.get(
                #             "kpi_cards",
                #             [],
                #         ),
                #         "target_kpis": target_analysis.get(
                #             "kpi_cards",
                #             [],
                #         ),
                #     }

                # except Exception as exc:
                #     logger.exception(
                #         "Slicer screenshot AI analysis failed"
                #     )

                #     scenario["ai_analysis_error"] = str(exc)

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

    def _export_reports(
        self,
        run_id,
        executions,
        comparison,
        executions_by_dashboard=None,
        multi_page_mode=False,
    ):
        if len(executions) < 2:
            return {}

        paths = {}
        page_comparisons = comparison.get("page_comparisons", [])
        public_groups = None
        if executions_by_dashboard:
            public_groups = [
                [
                    {key: value for key, value in item.items() if key != "_page"}
                    for item in group
                ]
                for group in executions_by_dashboard
            ]

        try:
            from services.docx_reporter import (
                generate_validation_document,
            )

            document = generate_validation_document(
                run_id,
                executions,
                comparison,
                OUTPUT_DIR / "reports",
                page_comparisons=page_comparisons if multi_page_mode else None,
                executions_by_dashboard=public_groups,
            )

            paths["document"] = str(document)

        except ModuleNotFoundError as exc:
            if exc.name != "docx":
                raise

            paths["document_error"] = (
                "Word report skipped: install "
                "python-docx from requirements.txt."
            )
        except Exception:
            logger.exception("Word report generation failed | run_id=%s", run_id)
            paths["document_error"] = "Word report generation failed. See server logs."

        try:
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
                [item.get("metrics", {}) for item in executions],
                OUTPUT_DIR / "reports",
                visual_data={
                    "Source": executions[0]["visual_data"],
                    "Target": executions[1]["visual_data"],
                },
                slicer_scenarios=comparison_payload.get("slicer_scenarios", []),
                page_comparisons=page_comparisons if multi_page_mode else None,
                executions_by_dashboard=public_groups,
            )
            paths["excel"] = str(workbook)
        except Exception as exc:
            logger.exception("Excel workbook generation failed | run_id=%s", run_id)
            paths["excel_error"] = f"Excel report failed: {exc}"

        try:
            public_executions = [
                {key: value for key, value in item.items() if key != "_page"}
                for item in executions
            ]
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
            pages_payload = build_pages_showcase_payload(
                public_executions,
                executions_by_dashboard=public_groups,
                run_id=run_id,
            )
            save_pages_snapshot(run_id, pages_payload, OUTPUT_DIR / "reports")
            paths["pages"] = str(OUTPUT_DIR / "reports" / f"{run_id}_pages.json")
            mismatch_payload = build_mismatch_payload(
                comparison,
                visual_data={
                    "Source": executions[0]["visual_data"],
                    "Target": executions[1]["visual_data"],
                },
                metrics=[item.get("metrics", {}) for item in executions],
                run_id=run_id,
            )
            save_mismatch_snapshot(run_id, mismatch_payload, OUTPUT_DIR / "reports")
            paths["mismatches"] = str(OUTPUT_DIR / "reports" / f"{run_id}_mismatches.json")
            paths["mismatches_data"] = mismatch_payload
        except Exception:
            logger.exception("Filter/inventory snapshot save failed | run_id=%s", run_id)

        return paths

    # ============================================================
    # Arun - Process Dashboard Page
    # ============================================================

    async def process_dashboard_page(
        self,
        dashboard,
        page,
        response,
        page_name,
        predetermined_filters=None,
    ):
        """Process one currently selected dashboard page.

        If `predetermined_filters` is None, this dashboard's filters are
        chosen randomly for this page (this is the "source" role); the
        filter/value pairs actually applied are returned so a later
        dashboard can replay them.

        If `predetermined_filters` is a {filter_name: value} dict, this
        dashboard replays exactly those values instead of randomizing (this
        is the "target" role), so it ends up compared against the source in
        the same filtered state. If a value can't be reproduced on this
        dashboard, that's recorded as an explicit failed execution rather
        than silently skipped, so the mismatch report can show *why* a
        filter state is missing here instead of it just looking like an
        unrelated data mismatch.

        Returns (executions, applied_selection) where applied_selection is
        the {filter_name: value} map of whatever was actually applied on
        this page.
        """

        executions = []
        engine = SlicerEngine(page)
        applied_selection = {}

        # ---------------------------------------------------------
        # STEP 1: Process the default (unfiltered) page state
        # ---------------------------------------------------------

        logger.info("Waiting for visual containers to stay stable before extraction")
        await wait_for_dashboard(page)

        default_visual_data = await extract_visual_data(page, attempt_export=False)
        default_tables = await export_table_visuals(
            page,
            default_visual_data.get("table_visuals", []),
            dashboard["name"],
        )
        default_metrics = await self._capture_metrics(
            dashboard,
            page,
            response,
            page_name=page_name,
        )

        executions.append({
            "dashboard": {
                **dashboard,
                "page_name": page_name,
                "filter_applied": "Default View"
            },
            "page_name": page_name,
            "filter_applied": "Default View",
            "extraction": {
                "status": "not_used",
                "data": None,
                "error": None},
            "visual_data": default_visual_data,
            "metrics": default_metrics,
            "tables": default_tables,
            "_page": page,
        })

        # ---------------------------------------------------------
        # STEP 2: Apply filters — random for source, replayed for target
        # ---------------------------------------------------------
        if predetermined_filters:
            filters_to_apply = list(predetermined_filters.items())
            logger.info(
                "Replaying source's filter selections on target | page=%s | filters=%s",
                page_name,
                filters_to_apply,
            )
        else:
            detected_filters = await engine.extract_filters_from_dom()
            if detected_filters:
                logger.info(f"Detected filters on page '{page_name}': {detected_filters}")
            filters_to_apply = [(f_name, None) for f_name in detected_filters[:2]]

        for f_name, predetermined_value in filters_to_apply:
            previous_snapshot = await capture_dashboard_snapshot(page)

            if predetermined_value is not None:
                logger.info(f"Reproducing filter on target: {f_name} = '{predetermined_value}'")
                success = await engine.apply_filter(f_name, predetermined_value)

                if not success:
                    logger.warning(
                        "Target could not reproduce source filter | page=%s filter=%s value=%s",
                        page_name,
                        f_name,
                        predetermined_value,
                    )
                    executions.append({
                        "dashboard": {
                            **dashboard,
                            "page_name": page_name,
                            "filter_applied": (
                                f"{f_name} = '{predetermined_value}' "
                                "(FAILED TO APPLY)"
                            ),
                        },
                        "page_name": page_name,
                        "filter_applied": f"{f_name} = '{predetermined_value}'",
                        "extraction": {"status": "not_used", "data": None, "error": None},
                        "visual_data": {
                            "status": "failed",
                            "kpi_cards": [],
                            "visuals": [],
                            "filters": [],
                            "errors": [
                                f"Could not reproduce source's filter selection "
                                f"'{predetermined_value}' for '{f_name}' on target dashboard."
                            ],
                        },
                        "_page": page,
                    })
                    continue

                applied_option = predetermined_value
            else:
                logger.info(f"Applying random option to filter: {f_name}")
                applied_option = await engine.apply_random_valid_option(f_name)

                if not applied_option:
                    continue

            applied_selection[f_name] = applied_option
            filter_label = f"{f_name} = '{applied_option}'"
            logger.info(
                "Filter applied | filter=%s | value=%s",
                f_name,
                applied_option,
            )
            self.timer.start("filter_dashboard_render")
            logger.info("Waiting for Power BI visuals to recalculate...")
            await wait_for_dashboard(page, previous_snapshot=previous_snapshot)
            self.timer.stop("filter_dashboard_render")

            filtered_screenshot = (
                SCREENSHOT_DIR
                / f"{dashboard['name']}_{page_name}_{f_name}_{uuid.uuid4().hex[:8]}.png"
            )
            await page.screenshot(path=str(filtered_screenshot), full_page=True)

            filtered_visual_data = await extract_visual_data(page, attempt_export=False)
            # as we decided not to go furthur with ai commenting the below line
            # filtered_ai_data = await asyncio.to_thread(extract_dashboard_json, filtered_screenshot)
            filtered_tables = await export_table_visuals(
                page,
                filtered_visual_data.get("table_visuals", []),
                dashboard["name"],
            )

            executions.append({
                "dashboard": {
                    **dashboard,
                    "page_name": page_name,
                    "filter_applied": filter_label
                },
                "page_name": page_name,
                "filter_applied": filter_label,
                "extraction": {"status": "not_used", "data": None, "error": None},
                "visual_data": filtered_visual_data,
                "screenshot": str(filtered_screenshot),
                "tables": filtered_tables,
                "metrics": await self._capture_metrics(
                    dashboard,
                    page,
                    response,
                    page_name=page_name,
                    screenshot_path=filtered_screenshot,
                ),
                "_page": page,
            })

        # Return the list of executions plus what was actually applied, so
        # run_dashboard can hand it off as the next dashboard's replay set.
        return executions, applied_selection

    # ============================================================
    # Arun - Multi Page Dashboard Navigation
    # ============================================================

    async def get_dashboard_pages(self, page):
        """Detect Power BI report pages from the Pages pane."""

        page_elements = page.locator(
            '[role="tab"][aria-label]'
        )

        pages = []

        count = await page_elements.count()

        for index in range(count):
            element = page_elements.nth(index)

            aria_label = await element.get_attribute(
                "aria-label"
            )

            text = (await element.inner_text()).strip()

            if not aria_label:
                continue

            if aria_label.endswith(" Selected"):
                page_name = aria_label[
                    :-len(" Selected")
                ]
                selected = True
            else:
                page_name = aria_label
                selected = False

            pages.append(
                {
                    "name": text or page_name,
                    "selected": selected,
                    "index": index,
                }
            )

        return pages

    async def navigate_to_page(self, page, page_name):
        """Navigate to a Power BI report page and verify the selected page."""
        
        # Early target guard
        if page.is_closed():
            raise RuntimeError(f"Cannot navigate to '{page_name}': target page is closed or crashed.")

        try:
            page_element = page.locator(
                f'[role="tab"][aria-label="{page_name}"]'
            )

            if await page_element.count() == 0:
                raise RuntimeError(
                    f"Dashboard page tab not found: {page_name}"
                )

            await page_element.first.click()
            await wait_for_dashboard(page)

            selected_page = page.locator(
                '[role="tab"][aria-label$=" Selected"]'
            )

            if await selected_page.count() == 0:
                raise RuntimeError(
                    f"Could not verify selected page after navigating to: {page_name}"
                )

            selected_label = await selected_page.first.get_attribute(
                "aria-label"
            )

            expected_label = f"{page_name} Selected"

            if selected_label != expected_label:
                raise RuntimeError(
                    f"Page navigation verification failed. "
                    f"Expected: {expected_label}, "
                    f"Actual: {selected_label}"
                )

            print(
                f"Successfully navigated to page: {page_name}"
            )

        except Exception as exc:
            if page.is_closed():
                logger.error(f"Browser target crashed during page navigation to '{page_name}': {exc}")
                raise RuntimeError(f"Browser crashed while attempting to load page: {page_name}") from exc
            raise

    # ============================================================
    # Arun - Multi Page Comparison Helpers
    # ============================================================

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

    async def run_filter_probe(self, links):
        executions = await self._probe_dashboard_executions(links)
        comparison_filters = []
        if len(executions) >= 2:
            source_data = self._build_comparison_payload(executions[0])
            target_data = self._build_comparison_payload(executions[1])
            if source_data.get("filters") or target_data.get("filters"):
                # from ai.Text_Extraction import compare_filters
                # comparison_filters = compare_filters(source_data, target_data)
                from services.comparison_service import compare_filters
                comparison_filters = compare_filters(
                    source_data.get("filters", []),
                    target_data.get("filters", []),
                )
        return build_filters_api_payload(
            executions,
            run_id=None,
            comparison_filters=comparison_filters,
        )

    async def run_inventory_probe(self, links):
        executions = await self._probe_dashboard_executions(links)
        return build_inventory_api_payload(executions, run_id=None)

    async def run_pages_probe(self, links):
        """Jagruthi — lightweight multi-page showcase (page names, KPIs, visuals, inventory)."""
        executions, executions_by_dashboard = await self._probe_multi_page_dashboard_executions(links)
        return build_pages_showcase_payload(
            executions,
            executions_by_dashboard=executions_by_dashboard,
            run_id=None,
        )

    async def _probe_multi_page_dashboard_executions(self, links):
        """Jagruthi — visit every report page and collect DOM visual inventory."""
        executions = []
        executions_by_dashboard = []
        resources = []
        if not links:
            return executions, executions_by_dashboard
        try:
            playwright, context, first_page = await launch_browser()
            resources.append((playwright, context))
            for index, dashboard in enumerate(links):
                page = first_page if index == 0 else await context.new_page()
                dashboard_executions = []
                try:
                    await page.goto(
                        dashboard["url"],
                        wait_until="domcontentloaded",
                        timeout=PAGE_TIMEOUT,
                    )
                    await wait_for_dashboard(page)
                    pages = await self.get_dashboard_pages(page)
                    page_items = pages if len(pages) > 1 else [{"name": "Default", "selected": True}]
                    for page_info in page_items:
                        page_name = page_info["name"]
                        if not page_info.get("selected"):
                            await self.navigate_to_page(page, page_name)
                        visual_data = await extract_visual_data(
                            page,
                            attempt_export=False,
                        )
                        execution = {
                            "dashboard": {
                                **dashboard,
                                "page_name": page_name,
                            },
                            "visual_data": visual_data,
                            "extraction": {
                                "status": "skipped",
                                "data": None,
                                "error": None,
                            },
                        }
                        dashboard_executions.append(execution)
                        executions.append(execution)
                except Exception as exc:
                    logger.exception(
                        "Multi-page dashboard probe failed | dashboard=%s",
                        dashboard.get("name"),
                    )
                    failed = {
                        "dashboard": dashboard,
                        "visual_data": {
                            "status": "failed",
                            "filters": [],
                            "visuals": [],
                            "errors": [str(exc)],
                        },
                        "extraction": {
                            "status": "failed",
                            "data": None,
                            "error": str(exc),
                        },
                    }
                    dashboard_executions.append(failed)
                    executions.append(failed)
                executions_by_dashboard.append(dashboard_executions)
        except Exception as exc:
            logger.exception("Unable to launch shared Edge context for multi-page probe")
            for dashboard in links:
                failed = {
                    "dashboard": dashboard,
                    "visual_data": {
                        "status": "failed",
                        "filters": [],
                        "errors": [str(exc)],
                    },
                    "extraction": {
                        "status": "failed",
                        "data": None,
                        "error": str(exc),
                    },
                }
                executions.append(failed)
                executions_by_dashboard.append([failed])
        finally:
            for playwright, context in resources:
                try:
                    await context.close()
                    await playwright.stop()
                except Exception:
                    logger.exception(
                        "Failed to close browser resources after multi-page probe"
                    )
        return executions, executions_by_dashboard

    async def _probe_dashboard_executions(self, links):
        executions = []
        resources = []

        if not links:
            return executions

        try:
            playwright, context, first_page = await launch_browser()
            resources.append((playwright, context))

            for index, dashboard in enumerate(links):
                page = (
                    first_page
                    if index == 0
                    else await context.new_page()
                )

                try:
                    await page.goto(
                        dashboard["url"],
                        wait_until="domcontentloaded",
                        timeout=PAGE_TIMEOUT,
                    )

                    await wait_for_dashboard(page)

                    visual_data = await extract_visual_data(
                        page,
                        attempt_export=False,
                    )

                    executions.append({
                        "dashboard": dashboard,
                        "visual_data": visual_data,
                        "extraction": {
                            "status": "skipped",
                            "data": None,
                            "error": None,
                        },
                    })

                except Exception as exc:
                    logger.exception(
                        "Dashboard probe failed | dashboard=%s",
                        dashboard.get("name"),
                    )

                    executions.append({
                        "dashboard": dashboard,
                        "visual_data": {
                            "status": "failed",
                            "visuals": [],
                            "errors": [str(exc)],
                        },
                        "extraction": {
                            "status": "failed",
                            "data": None,
                            "error": str(exc),
                        },
                    })

        except Exception as exc:
            logger.exception(
                "Unable to launch shared Edge context for dashboard probe"
            )

            executions = [
                {
                    "dashboard": dashboard,
                    "visual_data": {
                        "status": "failed",
                        "visuals": [],
                        "errors": [str(exc)],
                    },
                    "extraction": {
                        "status": "failed",
                        "data": None,
                        "error": str(exc),
                    },
                }
                for dashboard in links
            ]

        finally:
            for playwright, context in resources:
                try:
                    await context.close()
                    await playwright.stop()
                except Exception:
                    logger.exception(
                        "Failed to close browser resources "
                        "after dashboard probe"
                    )

        return executions


async def main():
    await DashboardValidator().run_all()


if __name__ == "__main__":
    asyncio.run(main())