import logging
import random
from playwright.async_api import Page
import uuid

from automation.browser import capture_dashboard_snapshot, wait_for_dashboard
from services.table_exporter import export_table_visuals
from services.visual_data_exporter import extract_visual_data
# NOTE: do NOT import DashboardValidator at module level here — validator.py
# imports SlicerEngine at module level too, so a top-level import in both
# directions is a circular import. Import it lazily inside the method instead.

logger = logging.getLogger("automation.slicer")

_validator = None


def _get_validator():
    """Lazily create (and cache) a DashboardValidator instance.

    Imported here rather than at module scope to avoid a circular import
    with automation.validator, which imports SlicerEngine at module level.
    """
    global _validator
    if _validator is None:
        from automation.validator import DashboardValidator
        _validator = DashboardValidator()
    return _validator


class SlicerEngine:
    def __init__(self, page: Page):
        self.page = page

    async def count_slicers(self) -> int:
        """Counts filter header titles in DOM."""
        try:
            count = await self.page.locator(".slicer-header-text").count()
            return count
        except Exception as e:
            logger.error(f"Error counting slicer elements: {e}")
            return 0

    async def extract_filters_from_dom(self) -> list[str]:
        """Extracts visible filter title strings using .slicer-header-text."""
        filter_names = []
        try:
            headers = self.page.locator(".slicer-header-text")
            count = await headers.count()
            for i in range(count):
                txt = await headers.nth(i).text_content()
                clean = txt.strip() if txt else ""
                if clean and clean not in filter_names:
                    filter_names.append(clean)
            return filter_names
        except Exception as e:
            logger.error(f"Error extracting DOM filter titles: {e}")
            return filter_names

    async def _close_any_open_popups(self):
        """Guarantees all floating dropdown overlays are closed and hidden."""
        try:
            popup = self.page.locator(".slicer-dropdown-popup")
            if await popup.count() > 0:
                # Press Escape twice to ensure multi-level popups close
                await self.page.keyboard.press("Escape")
                await self.page.keyboard.press("Escape")
                # Wait until the popup is detached or hidden from DOM
                await popup.first.wait_for(state="hidden", timeout=1500)
        except Exception:
            # Fallback: click neutral background area to close overlays
            try:
                await self.page.mouse.click(10, 10)
                await self.page.wait_for_timeout(300)
            except Exception:
                pass

    async def get_filter_options(self, filter_name: str) -> list[str]:
        logger.info(f"Reading options for filter: '{filter_name}'")
        options = []
        try:
            await self._close_any_open_popups()

            # 1. Locate visual container for this slicer
            slicer_visual = self.page.locator(
                f"visual-container:has(.slicer-header-text:text-is('{filter_name}'))"
            ).first
            if await slicer_visual.count() == 0:
                slicer_visual = self.page.locator(
                    f"visual-container:has(.slicer-header-text:has-text('{filter_name}'))"
                ).first

            if await slicer_visual.count() == 0:
                logger.warning(f"Slicer visual '{filter_name}' not found in DOM.")
                return options

            # 2. Determine if it's a Dropdown vs On-Canvas visual (Checkboxes/Radio/Tiles)
            dropdown_btn = slicer_visual.locator(
                ".slicer-dropdown-menu, .slicer-rest-item, [role='combobox']"
            ).first

            container = slicer_visual

            if await dropdown_btn.count() > 0:
                await dropdown_btn.click(force=True)
                popup = self.page.locator(".slicer-dropdown-popup:visible").first
                try:
                    await popup.wait_for(state="visible", timeout=3000)
                    container = popup
                except Exception:
                    logger.warning(f"Dropdown popup failed to open for '{filter_name}'.")
                    return options

            # 3. Comprehensive Selector: Catches Checkboxes, Radio Buttons, Tiles, and Lists
            items = container.locator(
                ".slicerItemContainer .slicerText, "
                "[role='checkbox'], "
                "[role='radio'], "
                "[role='option'], "
                "[role='treeitem'], "
                ".slicer-checkbox, "
                ".slicerText"
            )

            try:
                # Wait up to 3 seconds for options to render
                await items.first.wait_for(state="visible", timeout=3000)
            except Exception:
                logger.warning(f"No option items rendered for filter '{filter_name}'.")
                await self._close_any_open_popups()
                return options

            count = await items.count()
            for i in range(min(count, 15)):
                txt = await items.nth(i).text_content()
                clean = txt.strip() if txt else ""
                if clean and clean not in options:
                    options.append(clean)

            await self._close_any_open_popups()
            logger.info(f"✅ Discovered options for '{filter_name}': {options}")
            return options

        except Exception as e:
            logger.error(f"Error reading options for '{filter_name}': {e}")
            await self._close_any_open_popups()
            return options

         
    
    async def apply_filter(self, filter_name: str, option_value: str) -> bool:
        logger.info(f"Applying filter: [{filter_name} = '{option_value}']")
        try:
            await self._close_any_open_popups()

            slicer_visual = self.page.locator(
                f"visual-container:has(.slicer-header-text:text-is('{filter_name}'))"
            ).first
            if await slicer_visual.count() == 0:
                slicer_visual = self.page.locator(
                    f"visual-container:has(.slicer-header-text:has-text('{filter_name}'))"
                ).first

            if await slicer_visual.count() == 0:
                logger.warning(f"Slicer visual '{filter_name}' not found.")
                return False

            dropdown_btn = slicer_visual.locator(
                ".slicer-dropdown-menu, .slicer-rest-item, [role='combobox']"
            ).first

            container = slicer_visual

            if await dropdown_btn.count() > 0:
                await dropdown_btn.click(force=True)
                popup = self.page.locator(".slicer-dropdown-popup:visible").first
                try:
                    await popup.wait_for(state="visible", timeout=3000)
                    container = popup
                except Exception:
                    logger.warning(f"Popup failed to open for '{filter_name}'.")
                    return False

            target_el = container.locator(
                f".slicerText:text-is('{option_value}'), "
                f"[role='checkbox']:has-text('{option_value}'), "
                f"[role='radio']:has-text('{option_value}'), "
                f".slicerItemContainer:has-text('{option_value}')"
            ).first

            if await target_el.count() == 0:
                target_el = container.locator(
                    f".slicerText:has-text('{option_value}')"
                ).first

            success = False
            if await target_el.count() > 0:
                await target_el.scroll_into_view_if_needed()
                await target_el.click(force=True)
                logger.info(f"✅ Successfully clicked option '{option_value}' under '{filter_name}'.")
                success = True
            else:
                logger.warning(f"Option '{option_value}' not found in '{filter_name}'.")

            await self.page.keyboard.press("Escape")
            await self.page.wait_for_timeout(3000)
            return success

        except Exception as e:
            logger.error(f"Error applying filter '{filter_name}' = '{option_value}': {e}")
            await self._close_any_open_popups()
            return False

    async def extract_kpi_cards(self, max_retries: int = 2) -> dict:
        """Extracts KPI card values, retrying automatically if visuals return empty or N/A."""
        logger.info("Extracting KPI metrics from report visuals...")
        
        for attempt in range(max_retries + 1):
            kpis = {}
            try:
                visuals = self.page.locator("visual-container")
                count = await visuals.count()
                
                for i in range(count):
                    text = await visuals.nth(i).inner_text()
                    lines = [line.strip() for line in text.split("\n") if line.strip()]
                    if len(lines) >= 2:
                        label, value = lines[0], lines[1]
                        if len(label) < 40 and len(value) < 25 and value.lower() != "n/a":
                            kpis[label] = value

                if len(kpis) > 0:
                    logger.info(f"✅ Extracted {len(kpis)} KPI metric(s): {kpis}")
                    return kpis
                
                if attempt < max_retries:
                    logger.warning(f"Visuals returned empty/N/A on attempt {attempt + 1}. Bumping wait time by 3.0s...")
                    await self.page.wait_for_timeout(3000)

            except Exception as e:
                logger.error(f"Error extracting KPI cards (attempt {attempt + 1}): {e}")
                
        return kpis

    async def apply_random_valid_option(self, filter_name: str) -> str:
        """Fetches options, filters out 'All', picks a random one, and applies it."""
        options = await self.get_filter_options(filter_name)
        
        # Filter out UI noise and reset options
        valid_options = [
            opt for opt in options 
            if opt.strip().lower() not in {"select all", "all", "(blank)", ""}
        ]
        print(f"Valid options for '{filter_name}': {valid_options}")

        if not valid_options:
            logger.warning(f"No valid random options found for '{filter_name}'.")
            return None

        # Pick a random option
        selected_option = random.choice(valid_options)
        
        # Apply it
        await self.apply_filter(filter_name, selected_option)
        return selected_option

    async def process_dashboard_page(
            self,
            dashboard,
            page,
            response,
            page_name,
            predetermined_filters=None,
        ):
            """..."""

            validator = _get_validator()

            executions = []
            applied_selection = {}

            logger.info("Waiting for visual containers to stay stable before extraction")
            await wait_for_dashboard(page)

            default_visual_data = await extract_visual_data(page, attempt_export=False)
            default_tables = await export_table_visuals(
                page,
                default_visual_data.get("table_visuals", []),
                dashboard["name"],
            )
            default_metrics = await validator._capture_metrics(
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

            if predetermined_filters:
                filters_to_apply = list(predetermined_filters.items())
                logger.info(
                    "Replaying source's filter selections on target | page=%s | filters=%s",
                    page_name,
                    filters_to_apply,
                )
            else:
                detected_filters = await self.extract_filters_from_dom()
                if detected_filters:
                    logger.info(f"Detected filters on page '{page_name}': {detected_filters}")
                filters_to_apply = [(f_name, None) for f_name in detected_filters[:2]]

            for f_name, predetermined_value in filters_to_apply:
                previous_snapshot = await capture_dashboard_snapshot(page)

                if predetermined_value is not None:
                    logger.info(f"Reproducing filter on target: {f_name} = '{predetermined_value}'")
                    success = await self.apply_filter(f_name, predetermined_value)

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
                    applied_option = await self.apply_random_valid_option(f_name)

                    if not applied_option:
                        continue

                applied_selection[f_name] = applied_option
                filter_label = f"{f_name} = '{applied_option}'"
                logger.info(
                    "Filter applied | filter=%s | value=%s",
                    f_name,
                    applied_option,
                )
                validator.timer.start("filter_dashboard_render")
                logger.info("Waiting for Power BI visuals to recalculate...")
                await wait_for_dashboard(page, previous_snapshot=previous_snapshot)
                validator.timer.stop("filter_dashboard_render")

                filtered_visual_data = await extract_visual_data(page, attempt_export=False)
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
                    "tables": filtered_tables,
                    "metrics": await validator._capture_metrics(
                        dashboard,
                        page,
                        response,
                        page_name=page_name,
                    ),
                    "_page": page,
                })

            return executions, applied_selection