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
from services.run_artifact_store import (
    load_browser_metrics,
    load_run_status,
    load_validation_capture,
    persist_ai_results,
    persist_browser_metrics,
    persist_dom_results,
    persist_validation_capture,
)
from services.ai_validation_service import run_ai_validation
from services.validation_report_service import resolve_dashboard_name
from utils.config import (
    DASHBOARD_CONFIG,
    OUTPUT_DIR,
    PAGE_TIMEOUT,
    SCREENSHOT_DIR,
    dashboard_side_by_title,
    run_screenshot_dir,
    sanitize_filename,
    side_screenshot_dir,
)
from orchestration.slicer_engine import SlicerEngine
from orchestration.page_navigation import get_dashboard_pages, navigate_to_page
from services.comparison_service import (
    build_filters_api_payload,
    build_mismatch_payload,
    compare_dashboard_payloads,
)    

logger = logging.getLogger(__name__)


def _performance_summary(side: str, results: dict, artifacts: dict) -> dict:
    """Trimmed per-side browser metrics surfaced the moment the capture ends.

    Mirror of `build_metrics` fields; used by the status endpoint so the
    frontend can render the "Performance" results immediately after the
    capture step, before `/api/validate` (validation itself carries no
    performance data).
    """
    entry = results.get(side, {}) or {}
    return {
        "browser_launch_seconds": entry.get("browser_launch_seconds", 0.0),
        "page_load_seconds": entry.get("page_load_seconds"),
        "dashboard_render_seconds": entry.get("dashboard_render_seconds", 0.0),
        "filter_dashboard_render_seconds": entry.get("filter_dashboard_render_seconds"),
        "filter_test": entry.get("filter_test"),
        "baseline_stable": bool(entry.get("baseline_stable", False)),
        "screenshot_captured": bool((artifacts.get(side) or {}).get("screenshot")),
    }


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
        screenshot_dir=None,
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

            # Dashboard Load boundary (matches the manual stopwatch): the timer
            # starts only after the browser is ready (browser launch is measured
            # above and never included here) and immediately before navigating
            # to the dashboard URL, then stops once the dashboard reaches the
            # existing stable condition. page_load remains a diagnostic
            # sub-timing covering only the goto attempt until DOMContentLoaded;
            # browser_launch_seconds is reported separately.
            self.timer.start("dashboard_render")
            try:
                self.timer.start("page_load")
                try:
                    response = await page.goto(
                        dashboard["url"],
                        wait_until="domcontentloaded",
                        timeout=PAGE_TIMEOUT,
                    )
                finally:
                    self.timer.stop("page_load")

                await wait_for_dashboard(page)
            finally:
                self.timer.stop("dashboard_render")

            pages = await get_dashboard_pages(page)

            if len(pages) > 1:
                executions = []
                page_filter_selections = {}

                for page_info in pages:
                    current_page_name = page_info["name"]

                    # Guard: Stop multi-page traversal if browser tab was destroyed
                    if page is None or page.is_closed():
                        logger.error(
                            "Browser page is closed. Stopping page traversal at '%s'.",
                            current_page_name
                        )
                        break

                    try:
                        if not page_info["selected"]:
                            await navigate_to_page(page, current_page_name)

                        predetermined = (filter_selections or {}).get(current_page_name)

                        execution, applied = await engine.process_dashboard_page(
                            dashboard=dashboard,
                            page=page,
                            response=response,
                            page_name=current_page_name,
                            predetermined_filters=predetermined,
                            screenshot_dir=screenshot_dir,
                        )

                        if execution:
                            executions.extend(execution)
                        if applied:
                            page_filter_selections[current_page_name] = applied

                    except Exception as page_err:
                        logger.error(
                            "Failed processing page '%s' | error=%s",
                            current_page_name,
                            page_err
                        )
                        break

                try:
                    self.timer.stop("total_execution")
                except Exception:
                    pass

                # These four timers are only ever measured here in
                # validator.py (browser launch, initial page.goto, and
                # wait_for_dashboard all happen once, before the per-page
                # loop). SlicerEngine's own per-page metrics dict does not
                # include them, so without this merge they were captured
                # but never reached the output.
                browser_level_timings = {
                    "browser_launch_seconds": self.timer.get("browser_launch"),
                    "page_load_seconds": self.timer.get("page_load"),
                    "dashboard_render_seconds": self.timer.get("dashboard_render"),
                    "total_execution_seconds": self.timer.get("total_execution"),
                }
                for _execution in executions:
                    _execution.setdefault("metrics", {})
                    for _field, _value in browser_level_timings.items():
                        _execution["metrics"][_field] = _value

                return playwright, context, executions, page_filter_selections

            # Single-page dashboards must receive the same baseline-filter
            # handling as multi-page dashboards. Reuse process_dashboard_page()
            # (which already performs wait_for_dashboard -> reset_dashboard_filters
            # -> baseline extraction -> filter scenarios) instead of extracting
            # visuals directly. This avoids a second, duplicate baseline-reset
            # implementation living in validator.py.
            #
            # process_dashboard_page() captures the default-view screenshot
            # itself (SlicerEngine -> {name}__{page}__default.png) and stores it
            # on the baseline execution's metrics.screenshot_path. No separate
            # screenshot is taken here, otherwise two pixel-identical images
            # (e.g. {name}__fullpage.png) would be persisted per dashboard and
            # risk being fed as distinct captures to a downstream LLM.
            self.timer.start("visual_extraction")
            try:
                predetermined = (filter_selections or {}).get("Default")

                page_executions, _applied = await engine.process_dashboard_page(
                    dashboard=dashboard,
                    page=page,
                    response=response,
                    page_name="Default",
                    predetermined_filters=predetermined,
                    screenshot_dir=screenshot_dir,
                )
            except Exception as exc:
                logger.exception(
                    "DOM visual extraction failed | dashboard=%s",
                    dashboard.get("name"),
                )
                page_executions = []
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

            if not page_executions:
                # process_dashboard_page() produced nothing (e.g. page closed
                # mid-flight, or an exception was caught above). Preserve the
                # existing failure-shaped single-page result contract. The
                # engine captured no screenshot, so take an explicit full-page
                # one here.
                screenshot_path = None
                if screenshot_dir is not None and page and not page.is_closed():
                    screenshot_path = (
                        screenshot_dir
                        / f"{sanitize_filename(dashboard['name'])}__fullpage.png"
                    )
                    try:
                        await page.screenshot(
                            path=str(screenshot_path),
                            full_page=True,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to capture fallback fullpage screenshot | dashboard=%s",
                            dashboard.get("name"),
                        )
                        screenshot_path = None
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

            # Only the baseline (Default View) entry is surfaced here, matching
            # the pre-existing single-page contract: run_dashboard() has always
            # returned one dict for a single-page dashboard, never a list. Any
            # additional filter-scenario entries process_dashboard_page() produced
            # internally are intentionally not forwarded, exactly as before this
            # change (single-page filter-scenario comparison is handled separately
            # by _run_slicer_scenarios() in run_links()).
            baseline_execution = page_executions[0]
            baseline_execution.setdefault("metrics", {})
            # Keep the default-view screenshot the engine already captured and
            # stored on metrics.screenshot_path. Only take an explicit
            # full-page screenshot when the engine could not capture one.
            if (
                not baseline_execution["metrics"].get("screenshot_path")
                and screenshot_dir is not None
                and page
                and not page.is_closed()
            ):
                try:
                    fallback_path = (
                        screenshot_dir
                        / f"{sanitize_filename(dashboard['name'])}__fullpage.png"
                    )
                    await page.screenshot(
                        path=str(fallback_path),
                        full_page=True,
                    )
                    baseline_execution["metrics"]["screenshot_path"] = str(
                        fallback_path
                    )
                except Exception:
                    logger.exception(
                        "Failed to capture fallback fullpage screenshot | dashboard=%s",
                        dashboard.get("name"),
                    )
            baseline_execution["metrics"]["extraction_status"] = extraction["status"]
            if extraction.get("error"):
                baseline_execution["metrics"]["extraction_error"] = extraction["error"]

            # Same gap as the multi-page path above: SlicerEngine's metrics
            # dict for the baseline execution never included the timings
            # measured directly in validator.py, so merge them in here.
            baseline_execution["metrics"]["browser_launch_seconds"] = self.timer.get("browser_launch")
            baseline_execution["metrics"]["page_load_seconds"] = self.timer.get("page_load")
            baseline_execution["metrics"]["dashboard_render_seconds"] = self.timer.get("dashboard_render")
            baseline_execution["metrics"]["total_execution_seconds"] = self.timer.get("total_execution")

            return playwright, context, baseline_execution, {}

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

    async def run_browser_metrics(self, links, run_id=None):
        """Performance-only browser capture for `/api/browser-metrics`.

        THE PERFORMANCE API. Launches the authenticated Edge browser ONCE
        and captures only what browser metrics need, per dashboard:

        navigate -> measure dashboard render -> capture baseline screenshot
        from the supplied URL/bookmark/page state -> run one real filter
        interaction and measure its render.

        It NEVER runs DOM visual extraction, table exports, slicer
        scenarios, comparisons, AI, or DOCX generation. Those belong to the
        Validation API and are intentionally excluded so the performance
        result is available the moment this pass completes -- validation
        browser capture runs separately on ``/api/validate`` when no
        ``validation_capture.json`` exists for the run.

        The supplied state (including hidden/non-default pages) is preserved
        until the filter test begins: the baseline screenshot is taken before
        any interaction, and Reset Filters is never invoked. The baseline
        screenshot is ONLY captured after the existing dashboard stability
        condition (wait_for_dashboard) reports a stable state -- never while
        visuals are still changing. A usable slicer is discovered dynamically
        at runtime (no hardcoded names/values). When no usable slicer exists,
        filter_dashboard_render_seconds is reported as null with an explicit
        filter_test.status, never a fake 0.

        Pages are reused in-place from the context rather than opening new tabs,
        and no new-tab creation is attempted while an existing live page is
        available (source -> target reuse preserved).

        ``run_id`` is optional: when provided (the async route passes the
        already-created run_id so it can be returned immediately), it is used
        verbatim; otherwise a fresh run_id is generated here.

        Persists ``browser_metrics.json`` (metrics + baseline screenshot
        references + dashboard URLs) and returns; the caller
        (``_run_capture_job``) persists the terminal run status. When this
        returns, the browser session is closed and the performance result is
        final -- validation work happens later, independently.
        """
        run_id = run_id or uuid.uuid4().hex
        screenshot_dir = run_screenshot_dir(run_id)
        logger.info(
            "browser_metrics.request_received | run_id=%s | dashboards=%d",
            run_id,
            len(links),
        )

        side_names = ("source", "target")
        results = {}
        artifacts = {}
        resources = []

        # ----------------------------------------------------------
        # Launch once and measure browser_launch once (never twice).
        # ----------------------------------------------------------
        logger.info("browser_metrics.browser_launch.started | run_id=%s", run_id)
        self.timer.reset()
        self.timer.start("browser_launch")
        try:
            playwright, context, first_page = await launch_browser()
        except Exception as exc:
            self.timer.stop("browser_launch")
            logger.exception("browser_metrics.browser_launch.completed | run_id=%s | failed=True", run_id)
            return {
                "status": "failed",
                "run_id": run_id,
                "error": f"browser_launch_failed: {exc}",
                "source": None,
                "target": None,
                "artifacts": {"source": None, "target": None},
            }
        self.timer.stop("browser_launch")
        browser_launch_seconds = self.timer.get("browser_launch")
        resources.append((playwright, context))
        logger.info(
            "browser_metrics.browser_launch.completed | run_id=%s | seconds=%.3f",
            run_id,
            browser_launch_seconds,
        )

        page = None
        resolved_sides = {}
        explicit_side_indices = {}

        try:
            for index, dashboard in enumerate(links):
                side = side_names[index] if index < 2 else f"dashboard_{index}"
                logger.info("browser_metrics.%s.started | run_id=%s | url=%s", side, run_id, dashboard["url"])

                entry = {
                    "browser_launch_seconds": browser_launch_seconds,
                    "page_load_seconds": None,
                    "dashboard_render_seconds": 0.0,
                    "filter_dashboard_render_seconds": None,
                    "status": "failed",
                    "error": None,
                    "filter_test": None,
                }

                try:
                    # Prefer reusing an existing live page: inspect the context's
                    # pages first and navigate in-place to the dashboard URL,
                    # instead of opening a new tab (Target.createTarget can fail
                    # in this environment, e.g. with Edge channel profiles).
                    if page is None or page.is_closed():
                        live_pages = [p for p in context.pages if not p.is_closed()]
                        if live_pages:
                            page = live_pages[0]
                        elif index == 0 and not first_page.is_closed():
                            page = first_page
                        else:
                            page = await context.new_page()

                    await register(page)
                    page.set_default_timeout(PAGE_TIMEOUT)

                    # Dashboard Load boundary (matches the manual stopwatch):
                    # the timer starts only after the browser is ready --
                    # browser launch, profile detection, context creation,
                    # authentication, register()/set_default_timeout and all
                    # other pre-navigation preparation are already complete
                    # and measured separately under browser_launch. The timer
                    # starts IMMEDIATELY before navigating to the dashboard
                    # URL and stops once the existing stable condition reports
                    # the dashboard fully loaded.
                    dashboard_stable = False
                    self.timer.start("dashboard_render")
                    try:
                        self.timer.start("page_load")
                        try:
                            response = await page.goto(
                                dashboard["url"],
                                wait_until="domcontentloaded",
                                timeout=PAGE_TIMEOUT,
                            )
                        finally:
                            self.timer.stop("page_load")
                            entry["page_load_seconds"] = self.timer.get("page_load")
                        logger.info(
                            "browser_metrics.%s.navigation.completed | run_id=%s",
                            side,
                            run_id,
                        )
                        dashboard_stable = await wait_for_dashboard(page)
                    finally:
                        self.timer.stop("dashboard_render")
                    entry["dashboard_render_seconds"] = self.timer.get("dashboard_render")
                    entry["baseline_stable"] = bool(dashboard_stable)
                    logger.info(
                        "browser_metrics.%s.dashboard_render.completed | run_id=%s | seconds=%.3f | stable=%s",
                        side,
                        run_id,
                        entry["dashboard_render_seconds"],
                        dashboard_stable,
                    )

                    # Resolve the ACTUAL side from the loaded page title so the
                    # baseline screenshot and every downstream capture land in
                    # the correct source/target folder regardless of the order
                    # the URLs arrived in. The keyword lists live in the
                    # configuration (SCREENSHOT_SOURCE/TARGET_TITLE_KEYWORDS);
                    # nothing is hardcoded. When no keyword matches this title,
                    # the partner dashboard's keyword verdict decides this one
                    # (exclusive complement); otherwise the request-order
                    # assignment (source_url first) is kept.
                    if index < 2:
                        live_title = None
                        if page and not page.is_closed():
                            try:
                                live_title = await page.title()
                            except Exception:
                                live_title = None
                        resolved = dashboard_side_by_title(live_title)
                        if resolved:
                            side = resolved
                            explicit_side_indices[index] = resolved
                            logger.info(
                                "browser_metrics.%s.identity.resolved | run_id=%s | title=%s",
                                side,
                                run_id,
                                live_title,
                            )
                        elif explicit_side_indices:
                            partner_side = next(iter(explicit_side_indices.values()))
                            side = "target" if partner_side == "source" else "source"
                            logger.info(
                                "browser_metrics.%s.identity.complemented | run_id=%s | title=%s",
                                side,
                                run_id,
                                live_title,
                            )
                        else:
                            side = side_names[index]
                        resolved_sides[index] = side

                    # Preserve the supplied URL/bookmark/page state: capture the baseline
                    # screenshot from the untouched dashboard BEFORE any filter
                    # interaction. Reset Filters is never invoked.
                    #
                    # Stability boundary: the screenshot is ONLY taken when the
                    # existing dashboard stability condition reported a stable
                    # state. No filter clicks, exports, or navigation happen
                    # before this screenshot -- and it is skipped (never a
                    # "dancing" intermediate state) if stability was not
                    # reached.
                    screenshot_path = None
                    if dashboard_stable:
                        try:
                            screenshot_path = (
                                side_screenshot_dir(screenshot_dir, side)
                                / f"{sanitize_filename(dashboard['name'])}__baseline.png"
                            )
                            await page.screenshot(
                                path=str(screenshot_path),
                                full_page=True,
                            )
                            logger.info(
                                "browser_metrics.%s.screenshot.saved | run_id=%s | path=%s",
                                side,
                                run_id,
                                screenshot_path,
                            )
                        except Exception:
                            logger.exception(
                                "browser_metrics.%s.screenshot.saved | run_id=%s | failed=True",
                                side,
                                run_id,
                            )
                            screenshot_path = None
                    else:
                        logger.warning(
                            "browser_metrics.%s.screenshot.skipped_unstable | run_id=%s",
                            side,
                            run_id,
                        )

                    # Measure a REAL filter interaction so that
                    # filter_dashboard_render_seconds is meaningful. A usable
                    # slicer is discovered dynamically from the live DOM and a
                    # valid option (preferring a value different from the current
                    # selection) is applied; the elapsed time until the dashboard
                    # reaches its existing stable/render state is measured via the
                    # shared PerformanceTimer. The result is auditable, and when
                    # no usable slicer exists the value is null -- never a fake 0.
                    engine = SlicerEngine(page)
                    logger.info(
                        "browser_metrics.%s.filter_test.started | run_id=%s",
                        side,
                        run_id,
                    )
                    filter_test = await engine.run_filter_render_test()
                    entry["filter_test"] = filter_test
                    entry["filter_dashboard_render_seconds"] = filter_test.get(
                        "filter_dashboard_render_seconds"
                    )
                    logger.info(
                        "browser_metrics.%s.filter_test.result | run_id=%s | "
                        "slicer=%s | value=%s | status=%s | seconds=%s",
                        side,
                        run_id,
                        filter_test.get("slicer"),
                        filter_test.get("value"),
                        filter_test.get("status"),
                        filter_test.get("filter_dashboard_render_seconds"),
                    )

                    # Explicitly mark this artifact as the baseline/AI screenshot
                    # (kind=baseline) so it can never be confused with
                    # validation/scenario screenshots, plus whether the
                    # dashboard had reached the required stable state before
                    # capture. This reference is written exactly once, BEFORE
                    # any validation interaction, and no later operation
                    # rewrites it.
                    artifacts[side] = {
                        "screenshot": str(screenshot_path) if screenshot_path else None,
                        "kind": "baseline",
                        "stable": bool(entry.get("baseline_stable", False)),
                    }
                    entry["status"] = "completed"
                    entry["error"] = None

                except Exception as exc:
                    entry["error"] = str(exc)
                    logger.exception("browser_metrics.%s.failed | run_id=%s", side, run_id)

                # Do NOT close the page here. The page is intentionally kept
                # open so subsequent dashboards reuse this tab by navigating it
                # to their URL in-place (no new-tab creation). All pages are
                # torn down via context.close() in the outer finally block.

                results[side] = entry
                artifacts.setdefault(
                    side,
                    {"screenshot": None, "kind": "baseline", "stable": False},
                )
                logger.info("browser_metrics.%s.completed | run_id=%s | status=%s", side, run_id, entry["status"])

            statuses = [results.get(side, {}).get("status") for side in side_names]
            if statuses and all(status == "completed" for status in statuses):
                overall_status = "completed"
            elif statuses and any(status == "completed" for status in statuses):
                overall_status = "partial"
            else:
                overall_status = "failed"

            response = {
                "status": overall_status,
                "run_id": run_id,
                "source": _performance_summary("source", results, artifacts),
                "target": _performance_summary("target", results, artifacts),
                "artifacts": artifacts,
            }

            # The Performance API result is final the moment the performance
            # pass finishes: persist the compact artifact and terminal status
            # NOW. DOM visual extraction, table exports, slicer scenarios,
            # AI, and DOCX generation belong to the Validation API, which
            # runs its own validation browser capture on /api/validate when
            # no validation_capture.json exists for the run.
            baseline_refs = {
                side: {
                    "path": artifacts.get(side, {}).get("screenshot"),
                    "stable": bool(artifacts.get(side, {}).get("stable", False)),
                }
                for side in side_names
            }
            try:
                persist_browser_metrics(
                    run_id,
                    {
                        "status": overall_status,
                        "source": results.get("source"),
                        "target": results.get("target"),
                        "screenshots": artifacts,
                        "baseline_screenshots": baseline_refs,
                        "source_url": (
                            links[0].get("url")
                            if links and isinstance(links[0], dict)
                            else None
                        ),
                        "target_url": (
                            links[1].get("url")
                            if len(links) > 1 and isinstance(links[1], dict)
                            else None
                        ),
                    },
                )
                response["persistence_status"] = "saved"
            except Exception:
                logger.exception("artifact_write_failed | run_id=%s", run_id)
                response["persistence_status"] = "failed"

            response["validation_capture_status"] = "pending"

            logger.info(
                "browser_metrics.response_ready | run_id=%s | status=%s | "
                "validation_capture=deferred",
                run_id,
                overall_status,
            )
            return response

        finally:
            for playwright_, context_ in resources:
                try:
                    await context_.close()
                    await playwright_.stop()
                except Exception:
                    logger.exception("Failed to close browser resources | run_id=%s", run_id)

    async def _capture_executions(
        self,
        links,
        *,
        screenshot_dir=None,
        playwright=None,
        context=None,
        first_page=None,
        side_by_index=None,
    ):
        """Browser phase of validation: capture executions + slicer scenarios.

        Launches its own browser session only when none is supplied
        (``owned_browser``); otherwise it reuses the live context/pages of a
        running session (the browser-metrics capture pass), so a second
        browser is never launched for the same run.

        Returns ``(bundle, resources)`` where ``bundle`` carries
        ``executions`` (may hold live ``_page`` references for the slicer
        scenarios), ``executions_by_dashboard``, ``multi_page_mode``,
        ``source_filter_selections``, ``slicer_scenarios``, and
        ``capture_error``; ``resources`` is the list of
        ``(playwright, context)`` tuples CREATED here that the caller must
        close (empty for a shared-session call).
        """
        executions = []
        resources = []
        executions_by_dashboard = []
        multi_page_mode = False
        source_filter_selections = None
        slicer_scenarios = []
        capture_error = None
        owned_browser = playwright is None or context is None
        side_names_capture = ("source", "target")

        if not links:
            return {
                "executions": [],
                "executions_by_dashboard": [],
                "multi_page_mode": False,
                "source_filter_selections": None,
                "slicer_scenarios": [],
                "capture_error": None,
            }, resources

        try:
            browser_launch_elapsed = 0.0
            if owned_browser:
                launch_started = time.perf_counter()
                playwright, context, first_page = await launch_browser()
                browser_launch_elapsed = time.perf_counter() - launch_started
                resources.append((playwright, context))

            page = None

            for index, dashboard in enumerate(links):
                try:
                    # Route this dashboard's screenshots into its side folder
                    # (source/target) so the hosted AI service and the report
                    # can read a stable, per-side layout. Dashboard identity
                    # stays in the filename, so nothing is lost.
                    dashboard_screenshot_dir = None
                    if screenshot_dir is not None:
                        resolved_side = (
                            (side_by_index or {}).get(index)
                            if isinstance(side_by_index, dict)
                            else None
                        )
                        dashboard_side = (
                            resolved_side
                            or (
                                side_names_capture[index]
                                if index < len(side_names_capture)
                                else f"dashboard_{index}"
                            )
                        )
                        dashboard_screenshot_dir = side_screenshot_dir(
                            screenshot_dir, dashboard_side
                        )
                    if owned_browser:
                        # Historical run_links page acquisition: relaunch the
                        # browser if the context died or a new tab could not
                        # be opened (Target.createTarget failures).
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
                            except Exception:
                                playwright, context, first_page = await launch_browser()
                                resources.append((playwright, context))
                                page = first_page
                    else:
                        # Shared session: reuse an existing live page in-place
                        # instead of opening a new tab. Only fall back to
                        # new-page creation when no live page is available at
                        # all (source -> target reuse preserved).
                        if page is None or page.is_closed():
                            live_pages = [
                                p for p in context.pages if not p.is_closed()
                            ]
                            if live_pages:
                                page = live_pages[0]
                            elif (
                                index == 0
                                and first_page is not None
                                and not first_page.is_closed()
                            ):
                                page = first_page
                            else:
                                page = await context.new_page()

                    _, _, execution, page_filters = await self.run_dashboard(
                        dashboard,
                        playwright=playwright,
                        context=context,
                        page=page,
                        filter_selections=source_filter_selections,
                        browser_launch_elapsed=browser_launch_elapsed,
                        screenshot_dir=dashboard_screenshot_dir,
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

            # Slicer scenarios mutate the LIVE dashboard slices and extract
            # the resulting visual data, so they must run here while the
            # _page references are still alive -- never in the pure-compute
            # phase.
            if multi_page_mode:
                slicer_scenarios = await self._run_multi_page_slicer_scenarios(
                    executions_by_dashboard,
                    screenshot_dir=screenshot_dir,
                )
            else:
                slicer_scenarios = await self._run_slicer_scenarios(
                    executions,
                    screenshot_dir=screenshot_dir,
                )

        except Exception as exc:
            # Fatal browser-phase failure: keep the historical run_links
            # contract of returning a failed execution per dashboard instead
            # of raising. The caller decides how to surface capture_error.
            capture_error = str(exc)
            logger.exception(
                "Validation capture failed | dashboards=%d",
                len(links),
            )
            executions = [
                {
                    "dashboard": dashboard,
                    "metrics": None,
                    "extraction": {
                        "status": "failed",
                        "data": None,
                        "error": capture_error,
                    },
                    "visual_data": {
                        "status": "failed",
                        "filters": [],
                        "visuals": [],
                        "errors": [capture_error],
                    },
                }
                for dashboard in links
            ]

            executions_by_dashboard = [[execution] for execution in executions]
            multi_page_mode = False
            source_filter_selections = None
            slicer_scenarios = []

        return {
            "executions": executions,
            "executions_by_dashboard": executions_by_dashboard,
            "multi_page_mode": multi_page_mode,
            "source_filter_selections": source_filter_selections,
            "slicer_scenarios": slicer_scenarios,
            "capture_error": capture_error,
        }, resources

    @staticmethod
    def _resolve_mismatch_executions(
        executions: list,
        executions_by_dashboard: list,
        comparison: dict,
    ) -> tuple[dict | None, dict | None]:
        """Return the source/target execution pair that backs ``comparison``.

        Single-page comparisons compare ``executions[0]`` vs
        ``executions[1]`` directly. Multi-page comparisons surface the first
        successful page pair; its page name selects the matching source/target
        executions from the per-dashboard groups, so the table/cell and
        browser-metric mismatch extraction reads the same visual_data and
        metrics that produced ``comparison``.
        """
        page_comparisons = comparison.get("page_comparisons") or []
        page_name = None
        for page_comparison in page_comparisons:
            if page_comparison.get("status") == "success":
                page_name = page_comparison.get("page_name")
                break
        if page_name is None and page_comparisons:
            page_name = page_comparisons[0].get("page_name")

        if page_name and len(executions_by_dashboard) >= 2:
            source = next(
                (
                    item
                    for item in executions_by_dashboard[0]
                    if (item.get("dashboard") or {}).get("page_name") == page_name
                ),
                None,
            )
            target = next(
                (
                    item
                    for item in executions_by_dashboard[1]
                    if (item.get("dashboard") or {}).get("page_name") == page_name
                ),
                None,
            )
            if source is not None and target is not None:
                return source, target

        source = executions[0] if executions else None
        target = executions[1] if len(executions) >= 2 else None
        return source, target

    def _build_validation_response(
        self,
        *,
        run_id: str,
        executions: list,
        executions_by_dashboard: list,
        multi_page_mode: bool,
        source_filter_selections: dict | None,
        slicer_scenarios: list,
        baseline_screenshots: dict | None = None,
        ai_analysis: dict | None = None,
    ) -> dict:
        """Pure-compute validation report built from captured execution data.

        Shared by the legacy URL-based ``run_links`` (after its browser
        phase) and ``run_validation_from_artifacts`` (which loads a
        persisted ``validation_capture.json``). Never touches a Playwright
        object -- only serializable execution payloads and the comparison /
        report builders.

        ``baseline_screenshots`` (optional) carries the explicitly-marked
        baseline/AI screenshot references captured before validation
        interactions; scenario screenshots are kept separate and never
        replace it.

        ``ai_analysis`` (optional) carries the hosted AI validation result,
        kept separate from DOM data; when absent the response reports a
        not_configured status so consumers always see the channel.
        """
        if multi_page_mode:
            comparison = self._compare_multi_page_executions(
                executions_by_dashboard
            )
        else:
            comparison = self._compare_executions(
                executions
            )
            # Single-page mode compares only the first matched page pair;
            # expose it as a page-level comparison so downstream consumers
            # (e.g. the DOCX report) can map per-page results.
            page_name = (
                (executions[0].get("dashboard") or {}).get("page_name")
                if executions
                else None
            )
            comparison["page_comparisons"] = (
                [{**comparison, "page_name": page_name}]
                if page_name
                else []
            )

        comparison["slicer_scenarios"] = slicer_scenarios

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

        source_execution, target_execution = self._resolve_mismatch_executions(
            executions,
            executions_by_dashboard,
            comparison,
        )

        mismatch_visual_data = None
        mismatch_metrics = None
        if source_execution is not None and target_execution is not None:
            mismatch_visual_data = {
                "Source": self._build_comparison_payload(source_execution),
                "Target": self._build_comparison_payload(target_execution),
            }
            mismatch_metrics = [
                source_execution.get("metrics") or {},
                target_execution.get("metrics") or {},
            ]

        mismatches_payload = build_mismatch_payload(
            comparison,
            run_id=run_id,
            visual_data=mismatch_visual_data,
            metrics=mismatch_metrics,
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

        # Pass comparison dict explicitly to merge top-level tables into
        # dashboard payloads.
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
            "dashboard_name": self._resolve_response_dashboard_name(
                executions_by_dashboard,
                executions,
                ai_analysis,
            ),
            "dashboards": public_executions,
            "baseline_screenshots": baseline_screenshots,
            "ai_analysis": ai_analysis
            or {
                "status": "not_configured",
                "reason": "AI validation not run for this session",
            },
            "metrics": [
                item.get("metrics") or {}
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

    def _resolve_response_dashboard_name(
        self,
        executions_by_dashboard: list,
        executions: list,
        ai_analysis: dict | None = None,
    ) -> str:
        """Resolve the report/dashboard display name for the response.

        Prefers a ``dashboard_name`` actually returned by the hosted AI
        service (it is surfaced only when the service returns that exact
        key). Until one exists, falls back to the deterministic DOM-derived
        name (page-title pass / "Source vs Target").
        """
        ai_name = None
        if isinstance(ai_analysis, dict):
            candidate = ai_analysis.get("dashboard_name")
            if isinstance(candidate, str) and candidate.strip():
                ai_name = candidate.strip()
        if ai_name:
            return ai_name

        groups = executions_by_dashboard or []
        source_name = None
        target_name = None
        if groups and groups[0]:
            source_name = (groups[0][0].get("dashboard") or {}).get("name")
        if len(groups) > 1 and groups[1]:
            target_name = (groups[1][0].get("dashboard") or {}).get("name")
        metrics_list = [item.get("metrics") or {} for item in executions or []]
        return resolve_dashboard_name(source_name, target_name, metrics_list)

    async def run_links(self, links):
        """Full source-vs-target validation using its own browser session.

        Browser phase (capture: executions + slicer scenarios) then
        pure-compute phase (compare + build the report). The response shape
        is the historical run_links contract and is also produced by
        ``run_validation_from_artifacts`` (no browser).
        """
        run_id = uuid.uuid4().hex
        screenshot_dir = run_screenshot_dir(run_id)

        if not links:
            return {
                "run_id": run_id,
                "dashboards": [],
                "metrics": [],
                "kpis": [],
                "comparison": {
                    "status": "not_compared",
                    "reason": "Two dashboards are required.",
                },
            }

        capture_bundle, resources = await self._capture_executions(
            links,
            screenshot_dir=screenshot_dir,
        )

        try:
            return self._build_validation_response(
                run_id=run_id,
                executions=capture_bundle["executions"],
                executions_by_dashboard=capture_bundle["executions_by_dashboard"],
                multi_page_mode=capture_bundle["multi_page_mode"],
                source_filter_selections=capture_bundle["source_filter_selections"],
                slicer_scenarios=capture_bundle["slicer_scenarios"],
            )
        finally:
            for playwright, context in resources:
                try:
                    await context.close()
                    await playwright.stop()
                except Exception:
                    logger.exception(
                        "Failed to close browser resources"
                    )

    async def run_validation_from_artifacts(self, run_id, *, links=None):
        """Pure-compute validation report from a persisted capture.

        Reuses ``validation_capture.json`` when it exists (legacy runs and
        re-validations launch NO browser and NO performance measurement).
        When the capture is missing, the Validation API runs its own
        validation browser capture first (see ``_run_validation_capture``),
        then computes -- performance is never repeated: browser_metrics.json
        and the baseline screenshots from the Performance API are reused
        as-is. Returns None when neither a capture nor runnable dashboard
        URLs exist.
        """
        document = load_validation_capture(run_id)
        if document is None:
            document = await self._run_validation_capture(run_id, links=links)
            if document is None:
                return None

        response = self._build_validation_response(
            run_id=document.get("run_id") or run_id,
            executions=document.get("executions", []),
            executions_by_dashboard=document.get("executions_by_dashboard", []),
            multi_page_mode=bool(document.get("multi_page_mode", False)),
            source_filter_selections=document.get("source_filter_selections"),
            slicer_scenarios=document.get("slicer_scenarios", []),
            baseline_screenshots=document.get("baseline_screenshots"),
            ai_analysis=document.get("ai_analysis"),
        )
        persist_dom_results(run_id, response)
        persist_ai_results(run_id, response.get("ai_analysis"))
        return response

    async def _run_validation_capture(self, run_id, *, links=None):
        """Validation browser capture for the Validation API.

        Independent of the Performance API: verifies the dashboard URLs
        (explicit ``links``, else run_status/browser_metrics metadata),
        launches its own authenticated browser session via
        ``_capture_executions`` (DOM extraction, table exports, per-dashboard
        page groups, source filter selections, slicer scenarios), runs the
        hosted AI validation against the baseline screenshots captured
        earlier by the Performance API, and persists ``validation_capture.json``
        under the same pair-level run_id. Returns the reloaded capture
        document, or None when the dashboard URLs cannot be resolved.
        """
        metrics_doc = load_browser_metrics(run_id) or {}
        screenshot_dir = run_screenshot_dir(run_id)

        if links is None:
            status_doc = load_run_status(run_id) or {}
            details = status_doc.get("details") or {}
            source_url = (
                details.get("source_url") or metrics_doc.get("source_url")
            )
            target_url = (
                details.get("target_url") or metrics_doc.get("target_url")
            )
            if not source_url or not target_url:
                logger.warning(
                    "validation_capture.requires_links | run_id=%s | urls_unavailable=True",
                    run_id,
                )
                return None
            links = [
                {"name": "Dashboard A", "url": source_url},
                {"name": "Dashboard B", "url": target_url},
            ]

        source_name = (
            links[0].get("name")
            if links and isinstance(links[0], dict)
            else None
        )
        target_name = (
            links[1].get("name")
            if len(links) > 1 and isinstance(links[1], dict)
            else None
        )

        baseline_refs = metrics_doc.get("baseline_screenshots") or {}
        if not baseline_refs:
            screenshots = metrics_doc.get("screenshots") or {}
            baseline_refs = {
                side: {
                    "path": (screenshots.get(side) or {}).get("screenshot"),
                    "stable": bool((screenshots.get(side) or {}).get("stable", False)),
                }
                for side in ("source", "target")
            }

        capture_bundle, resources = await self._capture_executions(
            links,
            screenshot_dir=screenshot_dir,
        )
        try:
            # AI validation stays a separate, optional channel: it only runs
            # after the baseline screenshots exist, never writes into the DOM
            # results, and degrades to a structured result when the hosted
            # service is unreachable or unconfigured. A failure here must not
            # abort the persisted validation capture.
            try:
                ai_analysis = await run_ai_validation(
                    run_id,
                    screenshot_dir,
                    source_name=source_name,
                    target_name=target_name,
                )
            except Exception:
                logger.exception(
                    "validation_capture.ai.failed | run_id=%s", run_id
                )
                ai_analysis = {"status": "error", "error": "ai_validation_failed"}

            validation_capture_payload = {
                "baseline_screenshots": baseline_refs,
                "multi_page_mode": capture_bundle["multi_page_mode"],
                "source_filter_selections": capture_bundle[
                    "source_filter_selections"
                ],
                "slicer_scenarios": capture_bundle["slicer_scenarios"],
                "executions": [
                    {
                        key: value
                        for key, value in item.items()
                        if key != "_page"
                    }
                    for item in capture_bundle["executions"]
                ],
                "executions_by_dashboard": [
                    [
                        {
                            key: value
                            for key, value in item.items()
                            if key != "_page"
                        }
                        for item in group
                    ]
                    for group in capture_bundle["executions_by_dashboard"]
                ],
                "ai_analysis": ai_analysis,
                "capture_error": capture_bundle.get("capture_error"),
            }
            try:
                persist_validation_capture(run_id, validation_capture_payload)
            except Exception:
                logger.exception(
                    "validation_capture.persist.failed | run_id=%s", run_id
                )
                raise RuntimeError(
                    f"Failed to persist validation capture for run_id {run_id}."
                ) from None
            logger.info(
                "validation_capture.capture_if_missing.saved | run_id=%s",
                run_id,
            )
        finally:
            for playwright, context in resources:
                try:
                    await context.close()
                    await playwright.stop()
                except Exception:
                    logger.exception(
                        "Failed to close browser resources | run_id=%s",
                        run_id,
                    )

        return load_validation_capture(run_id)

    async def _run_slicer_scenarios(self, executions, screenshot_dir=None):
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
                # Resolved up front: the single-page path produces the
                # scenario without a page_name, and the extraction below needs
                # it to label the tables it finds on the right page.
                "page_name": (
                    (source.get("dashboard") or {}).get("page_name")
                    or "Default"
                ),
            }

            if applied_source and applied_target:
                # apply_filter() already waited for the dashboard's existing
                # stable condition on both pages. Capture the slicer-scenario
                # screenshots NOW, BEFORE extract_visual_data() below runs the
                # blanket table export (which scrolls nested Power BI canvas
                # containers via table_exporter._open_more_options and would
                # displace the canvas in any later screenshot).
                scenario_id = uuid.uuid4().hex[:8]

                scenario_slug = (
                    f"{sanitize_filename(slicer_name)}__"
                    f"{sanitize_filename(value)}"
                )

                screenshot_target_dir = screenshot_dir or SCREENSHOT_DIR

                source_image = (
                    side_screenshot_dir(screenshot_target_dir, "source")
                    / f"slicer__{scenario_slug}__source__{scenario_id}.png"
                )

                target_image = (
                    side_screenshot_dir(screenshot_target_dir, "target")
                    / f"slicer__{scenario_slug}__target__{scenario_id}.png"
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

                logger.info(
                    "slicer_scenario.screenshot.saved | slicer=%s | value=%s | source=%s | target=%s",
                    slicer_name,
                    value,
                    source_image,
                    target_image,
                )

                logger.info(
                    "slicer_scenario.visual_extraction.begin | slicer=%s | value=%s",
                    slicer_name,
                    value,
                )
                source_visual = await extract_visual_data(
                    source["_page"],
                    dashboard_title=str(
                        (source.get("dashboard") or {}).get("name") or ""
                    ) or None,
                    page_name=scenario.get("page_name"),
                )

                target_visual = await extract_visual_data(
                    target["_page"],
                    dashboard_title=str(
                        (target.get("dashboard") or {}).get("name") or ""
                    ) or None,
                    page_name=scenario.get("page_name"),
                )

                # Keep the post-filter extraction. Both dashboards now carry the
                # SAME verified filter applied, so this is the filtered
                # source-vs-target pair the scenario exists to produce; dropping
                # it threw away two full extractions.
                scenario["source_visual_data"] = source_visual
                scenario["target_visual_data"] = target_visual
                logger.info(
                    "slicer_scenario.visual_extraction.completed | slicer=%s | value=%s",
                    slicer_name,
                    value,
                )

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
        screenshot_dir=None,
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
                [source, target],
                screenshot_dir=screenshot_dir,
            )

            for scenario in page_scenarios:
                scenario["page_name"] = page_name

            scenarios.extend(page_scenarios)

        return scenarios

async def main():
    await DashboardValidator().run_all()


if __name__ == "__main__":
    asyncio.run(main())