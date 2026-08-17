"""Main orchestration for screenshot validation and browser-side visual data."""

import asyncio
import json
import logging
import uuid

from .browser import launch_browser, wait_for_dashboard
from .network import clear, register, summary
from .performance import PerformanceTimer
from .metrics import build_metrics
from services.visual_data_exporter import apply_slicer_value, extract_visual_data
from utils.config import DASHBOARD_CONFIG, OUTPUT_DIR, PAGE_TIMEOUT, SCREENSHOT_DIR


logger = logging.getLogger(__name__)


class DashboardValidator:
    def __init__(self):
        self.timer = PerformanceTimer()

    def load_dashboards(self):
        with open(DASHBOARD_CONFIG, "r", encoding="utf-8") as file:
            return json.load(file)["dashboards"]

    async def run_dashboard(self, dashboard, *, playwright=None, context=None, page=None):
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

                    execution = await self.process_dashboard_page(
                        dashboard=dashboard,
                        page=page,
                        response=response,
                        page_name=page_name,
                    )

                    executions.append(execution)

                try:
                    self.timer.stop("total_execution")
                except Exception:
                    pass

                return playwright, context, executions

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

            self.timer.start("ocr")

            try:
                # A missing Gemini key must not prevent browser data collection.
                from ai.Text_Extraction import extract_dashboard_json

                extraction["data"] = await asyncio.to_thread(
                    extract_dashboard_json,
                    screenshot_path,
                )

                self._merge_dom_filters(
                    extraction["data"],
                    visual_data,
                )

                extraction["status"] = "success"

            except Exception as exc:
                extraction["error"] = str(exc)

            finally:
                self.timer.stop("ocr")

            self.timer.stop("total_execution")

            metrics = build_metrics(
                dashboard_name=dashboard["name"],
                dashboard_url=dashboard["url"],
                timers=self.timer.summary(),
                network_summary=summary(),
                page_title=await page.title(),
                final_url=page.url,
                http_status=response.status if response else None,
            )

            metrics["screenshot_path"] = str(screenshot_path)
            metrics["extraction_status"] = extraction["status"]

            return playwright, context, {
                "dashboard": dashboard,
                "metrics": metrics,
                "extraction": extraction,
                "visual_data": visual_data,
                "_page": page,
            }

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
    def _merge_dom_filters(extracted_data, visual_data):
        """Prefer live DOM filter state over screenshot inference.

        Gemini remains useful for metadata, but it cannot reliably decide which
        visually styled button is selected. Browser accessibility attributes
        (``aria-pressed``, ``aria-selected`` and checked inputs) are the source
        of truth whenever they are available.
        """
        if not extracted_data:
            return

        filters = extracted_data.setdefault("filters", [])

        index = {
            " ".join(
                str(item.get("filter_name", "")).casefold().split()
            ): item
            for item in filters
            if item.get("filter_name")
        }

        for dom_filter in visual_data.get("filters", []):
            key = " ".join(
                str(dom_filter.get("name", "")).casefold().split()
            )

            if not key:
                continue

            item = index.get(key)

            if item is None:
                item = {
                    "filter_name": dom_filter["name"],
                    "filter_type": dom_filter.get(
                        "filter_type",
                        "Buttons",
                    ),
                    "selected_values": [],
                    "available_values": [],
                }

                filters.append(item)
                index[key] = item

            if dom_filter.get("selected_values"):
                item["selected_values"] = dom_filter[
                    "selected_values"
                ]

            if dom_filter.get("visible_values"):
                item["available_values"] = dom_filter[
                    "visible_values"
                ]

            item["filter_type"] = (
                dom_filter.get("filter_type")
                or item.get("filter_type")
            )

            item["extraction_source"] = "dom"

        logger.info(
            "Merged DOM filter state | filters=%d",
            len(filters),
        )

    async def run_links(self, links):
        """Validate source/target URLs and return data suitable for the API/frontend."""
        executions = []
        resources = []

        # ============================================================
        # Arun - Multi Page Execution Tracking
        # ============================================================

        executions_by_dashboard = []
        multi_page_mode = False

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
            playwright, context, first_page = await launch_browser()
            resources.append((playwright, context))

            for index, dashboard in enumerate(links):
                page = (
                    first_page
                    if index == 0
                    else await context.new_page()
                )

                try:
                    _, _, execution = await self.run_dashboard(
                        dashboard,
                        playwright=playwright,
                        context=context,
                        page=page,
                    )

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

            report_paths = self._export_reports(
                run_id,
                report_executions,
                comparison,
            )

            public_executions = [
                {
                    key: value
                    for key, value in item.items()
                    if key != "_page"
                }
                for item in executions
            ]

            # ============================================================
            # Arun - Page-aware API response
            # ============================================================

            if multi_page_mode:
                llm_results = [
                    {
                        "dashboard": item["dashboard"].get("name"),
                        "page_name": item["dashboard"].get("page_name"),
                        "extraction": item["extraction"].get("data"),
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
                llm_results = [
                    {
                        "dashboard": item["dashboard"].get("name"),
                        "extraction": item["extraction"].get("data"),
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
                    item["metrics"]
                    for item in executions
                ],
                "kpis": [
                    (
                        item["extraction"].get("data")
                        or {}
                    ).get("kpi_cards", [])
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
                },
                "llm_results": llm_results,
                "filter_state": filter_state,
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

            applied_source = await apply_slicer_value(
                source["_page"],
                slicer_name,
                value,
            )

            applied_target = await apply_slicer_value(
                target["_page"],
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

                try:
                    from ai.Text_Extraction import (
                        extract_dashboard_json,
                    )

                    source_analysis, target_analysis = (
                        await asyncio.gather(
                            asyncio.to_thread(
                                extract_dashboard_json,
                                source_image,
                            ),
                            asyncio.to_thread(
                                extract_dashboard_json,
                                target_image,
                            ),
                        )
                    )

                    scenario["ai_analysis"] = {
                        "source_kpis": source_analysis.get(
                            "kpi_cards",
                            [],
                        ),
                        "target_kpis": target_analysis.get(
                            "kpi_cards",
                            [],
                        ),
                    }

                except Exception as exc:
                    logger.exception(
                        "Slicer screenshot AI analysis failed"
                    )

                    scenario["ai_analysis_error"] = str(exc)

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

        source, target = executions[:2]

        if (
            source["extraction"]["status"] != "success"
            or target["extraction"]["status"] != "success"
        ):
            return {
                "status": "not_compared",
                "reason": (
                    "Gemini extraction failed for one or both "
                    "dashboards; no match percentage was calculated."
                ),
            }

        from ai.Text_Extraction import (
            compare_filters,
            compare_visuals,
        )

        from services.excel_exporter import (
            build_comparison_summary,
            compare_kpis,
        )

        source_data = source["extraction"]["data"]
        target_data = target["extraction"]["data"]

        filters = compare_filters(
            source_data,
            target_data,
        )

        kpis = compare_kpis(
            source_data,
            target_data,
        )

        visuals = compare_visuals(
            source_data,
            target_data,
        )

        summary = build_comparison_summary(
            filters,
            kpis,
            visuals,
        )

        return {
            "status": "success",
            "filters": filters,
            "kpis": kpis,
            "visuals": visuals,
            "summary": summary,
            # Kept for the existing dashboard UI while richer result groups are
            # available above for API consumers.
            "results": kpis,
            "match_percentage": summary[
                "kpi_match_percentage"
            ],
        }

    def _export_reports(
        self,
        run_id,
        executions,
        comparison,
    ):
        if len(executions) < 2:
            return {}

        paths = {}

        try:
            from services.docx_reporter import (
                generate_validation_document,
            )

            document = generate_validation_document(
                run_id,
                executions,
                comparison,
                OUTPUT_DIR / "reports",
            )

            paths["document"] = str(document)

        except ModuleNotFoundError as exc:
            # Word output is an optional enhancement. Keep the validation and
            # Excel workbook usable until its package is installed.
            if exc.name != "docx":
                raise

            paths["document_error"] = (
                "Word report skipped: install "
                "python-docx from requirements.txt."
            )

        if comparison.get("status") != "success":
            return paths

        from services.excel_exporter import (
            export_validation_workbook,
        )

        workbook = export_validation_workbook(
            run_id,
            executions[0]["extraction"]["data"],
            executions[1]["extraction"]["data"],
            comparison["filters"],
            comparison["kpis"],
            comparison["visuals"],
            comparison["summary"],
            [
                item["metrics"]
                for item in executions
            ],
            OUTPUT_DIR / "reports",
            visual_data={
                "Source": executions[0]["visual_data"],
                "Target": executions[1]["visual_data"],
            },
            slicer_scenarios=comparison.get(
                "slicer_scenarios",
                [],
            ),
        )

        paths["excel"] = str(workbook)

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
    ):
        """Process one currently selected dashboard page."""

        extraction = {
            "status": "failed",
            "data": None,
            "error": None,
        }

        visual_data = {
            "status": "failed",
            "filters": [],
            "visuals": [],
            "errors": [],
        }

        self.timer.reset()
        self.timer.start("total_execution")

        try:
            # Screenshot
            self.timer.start("screenshot")

            screenshot_path = (
                SCREENSHOT_DIR
                / f"{dashboard['name']}_{page_name}_{uuid.uuid4().hex[:8]}.png"
            )

            await page.screenshot(
                path=str(screenshot_path),
                full_page=True,
            )

            self.timer.stop("screenshot")

            # Visual data extraction
            visual_data = await extract_visual_data(
                page,
                download_directory=OUTPUT_DIR / "visual_exports",
                attempt_export=True,
            )

            # AI / text extraction
            self.timer.start("ocr")

            try:
                from ai.Text_Extraction import extract_dashboard_json

                extraction["data"] = await asyncio.to_thread(
                    extract_dashboard_json,
                    screenshot_path,
                )

                self._merge_dom_filters(
                    extraction["data"],
                    visual_data,
                )

                extraction["status"] = "success"

            except Exception as exc:
                extraction["error"] = str(exc)

            finally:
                self.timer.stop("ocr")

            self.timer.stop("total_execution")

            metrics = build_metrics(
                dashboard_name=dashboard["name"],
                dashboard_url=dashboard["url"],
                timers=self.timer.summary(),
                network_summary=summary(),
                page_title=await page.title(),
                final_url=page.url,
                http_status=response.status if response else None,
            )

            metrics["page_name"] = page_name
            metrics["screenshot_path"] = str(screenshot_path)
            metrics["extraction_status"] = extraction["status"]

            return {
                "dashboard": {
                    **dashboard,
                    "page_name": page_name,
                },
                "metrics": metrics,
                "extraction": extraction,
                "visual_data": visual_data,
                "_page": page,
            }

        except Exception as exc:
            logger.exception(
                "Dashboard page processing failed | dashboard=%s | page=%s",
                dashboard.get("name"),
                page_name,
            )

            try:
                self.timer.stop("total_execution")
            except Exception:
                pass

            return {
                "dashboard": {
                    **dashboard,
                    "page_name": page_name,
                },
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
                "_page": page,
            }

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

        page_element = page.locator(
            f'[role="tab"][aria-label="{page_name}"]'
        )

        if await page_element.count() == 0:
            raise RuntimeError(
                f"Dashboard page not found: {page_name}"
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

    async def run_all(self):
        return await self.run_links(
            self.load_dashboards()
        )


async def main():
    await DashboardValidator().run_all()


if __name__ == "__main__":
    asyncio.run(main())