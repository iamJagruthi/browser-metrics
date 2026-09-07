import logging
import random
from playwright.async_api import Page
import uuid

from automation.browser import capture_dashboard_snapshot, wait_for_dashboard
from automation.canvas_diagnostics import measure_canvas, log_delta
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
                _diag_before = await measure_canvas(self.page)
                await dropdown_btn.click(force=True)
                _diag_after = await measure_canvas(self.page)
                log_delta("SlicerEngine.get_filter_options.dropdown_btn_click", filter_name, _diag_before, _diag_after)
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

         
    
    @staticmethod
    def _normalize_value(value) -> str:
        """Whitespace/case-insensitive normalization used only to compare a
        requested option value against selected_values read from the DOM."""
        return " ".join(str(value).strip().casefold().split())

    async def apply_filter(self, filter_name: str, option_value: str) -> bool:
        """Ensures `option_value` ends up selected on `filter_name`, without
        assuming click == select.

        Some Power BI slicers toggle on repeated clicks (first click selects,
        second click deselects), so this reasons in terms of:
            current state -> desired state -> minimum action -> verify
        rather than clicking unconditionally. Reuses get_slicer_state()
        (Task 1) both before acting (to detect "already selected, don't
        touch it") and after acting (to confirm the click actually produced
        the requested state before reporting success).
        """
        logger.info(f"Applying filter: [{filter_name} = '{option_value}']")
        requested_norm = self._normalize_value(option_value)

        try:
            current_state = await self.get_slicer_state(filter_name)
        except Exception as e:
            logger.warning(f"Could not read current state for '{filter_name}' before applying filter: {e}")
            current_state = None

        if current_state and current_state.get("error") == "slicer_not_found":
            logger.warning(f"Slicer visual '{filter_name}' not found.")
            return False

        current_values = {
            self._normalize_value(v)
            for v in (current_state or {}).get("selected_values", []) or []
        }

        if requested_norm in current_values:
            # This is the primary bug being fixed: re-clicking an
            # already-selected value can toggle it OFF on some slicers.
            # The desired state already holds, so do nothing.
            logger.info(
                f"'{option_value}' is already selected on '{filter_name}'; "
                f"skipping click to avoid toggling it off."
            )
            return True

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
                _diag_before = await measure_canvas(self.page)
                await dropdown_btn.click(force=True)
                _diag_after = await measure_canvas(self.page)
                log_delta("SlicerEngine.apply_filter.dropdown_btn_click", filter_name, _diag_before, _diag_after)
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

            if await target_el.count() == 0:
                logger.warning(f"Option '{option_value}' not found in '{filter_name}'.")
                await self.page.keyboard.press("Escape")
                return False

            # Requested value is confirmed absent from selected_values, so a
            # single click here is the minimum action needed to select it —
            # never toggling anything the caller didn't ask to change.
            previous_snapshot = await capture_dashboard_snapshot(self.page)

            _diag_before = await measure_canvas(self.page)
            await target_el.scroll_into_view_if_needed()
            _diag_after = await measure_canvas(self.page)
            log_delta("SlicerEngine.apply_filter.target_el_scroll_into_view_if_needed", f"{filter_name}={option_value}", _diag_before, _diag_after)

            _diag_before = await measure_canvas(self.page)
            await target_el.click(force=True)
            _diag_after = await measure_canvas(self.page)
            log_delta("SlicerEngine.apply_filter.target_el_click", f"{filter_name}={option_value}", _diag_before, _diag_after)

            logger.info(f"Clicked option '{option_value}' under '{filter_name}'; verifying result.")

            await self.page.keyboard.press("Escape")

            try:
                await wait_for_dashboard(self.page, previous_snapshot=previous_snapshot)
            except Exception as e:
                logger.warning(f"Wait for dashboard after clicking '{filter_name}' failed: {e}")

            final_state = await self.get_slicer_state(filter_name)
            final_values = {
                self._normalize_value(v)
                for v in (final_state or {}).get("selected_values", []) or []
            }

            success = requested_norm in final_values

            if success:
                logger.info(f"✅ Verified '{option_value}' selected under '{filter_name}'.")
            else:
                logger.warning(
                    f"Verification failed for '{filter_name}' = '{option_value}': "
                    f"resulting selected_values="
                    f"{final_state.get('selected_values') if final_state else None}. "
                    f"Not reporting success."
                )

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

    # ------------------------------------------------------------------
    # Slicer state model (Task 1A — read-only)
    #
    # Purpose: describe what a slicer currently looks like (selected
    # value(s), whether it can be cleared, single/multi mode, layout
    # orientation) so a later task can decide whether to clear it or
    # preserve its selection. This never clicks an option and never
    # changes a selection. Any dropdown popup opened to inspect state is
    # closed again before returning, mirroring the existing non-destructive
    # open/read/close pattern already used in get_filter_options().
    #
    # Field names reuse the app's existing convention: "name" and
    # "selected_values" are already used for this purpose in
    # visual_data_exporter.py / validator.py. "clear_available",
    # "selection_mode", and "orientation" are new because no existing
    # structure captures them for ordinary (non button-slicer) slicers.
    #
    # Anything that cannot be reliably determined from the DOM is left as
    # None rather than guessed, per design constraint.
    # ------------------------------------------------------------------

    _CLEAR_OR_ALL_TEXT = {"select all", "all", "(all)"}
    _NOISE_TEXT = {"select all", "all", "(all)", "(blank)", ""}

    async def _read_row_selected(self, row) -> bool:
        """Best-effort, non-destructive check of whether a single slicer
        row/item is currently selected. Never clicks anything."""
        try:
            cls = (await row.get_attribute("class")) or ""
            if "selected" in cls.lower():
                return True

            for attr in ("aria-checked", "aria-selected", "aria-pressed"):
                val = await row.get_attribute(attr)
                if val and val.strip().lower() == "true":
                    return True

            input_el = row.locator("input[type='checkbox'], input[type='radio']").first
            if await input_el.count() > 0:
                try:
                    if await input_el.is_checked():
                        return True
                except Exception:
                    pass

            return False
        except Exception:
            return False

    async def _detect_orientation(self, rows) -> str | None:
        """Compares bounding boxes of the first couple of visible rows to
        infer list layout. Returns None (unknown) rather than guessing if
        the layout is ambiguous or can't be measured."""
        try:
            count = await rows.count()
            boxes = []
            for i in range(min(count, 4)):
                box = await rows.nth(i).bounding_box()
                if box:
                    boxes.append(box)
                if len(boxes) >= 2:
                    break

            if len(boxes) < 2:
                return None

            dx = abs(boxes[1]["x"] - boxes[0]["x"])
            dy = abs(boxes[1]["y"] - boxes[0]["y"])

            # Rows clearly stacked left-aligned -> vertical list.
            if dy > 8 and dx < 8:
                return "vertical"
            # Rows clearly side-by-side on the same line -> horizontal list.
            if dx > 8 and dy < 8:
                return "horizontal"
            return None
        except Exception:
            return None

    async def get_slicer_state(self, filter_name: str) -> dict:
        """Reads (without modifying) the current state of a slicer.

        Returns a dict with:
            name, selected_values, clear_available, selection_mode,
            orientation, error

        Fields that cannot be reliably determined are set to None
        (or [] for selected_values) instead of being guessed.
        """
        state = {
            "name": filter_name,
            "selected_values": [],
            "clear_available": None,
            "selection_mode": None,
            "orientation": None,
            "error": None,
        }

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
                state["error"] = "slicer_not_found"
                return state

            # Header-level clear/all affordance (e.g. an "X" / "Clear
            # selections" icon). Scoped to this slicer's own container.
            header_clear_control = slicer_visual.locator(
                ".clearAll, [aria-label*='Clear' i], [title*='Clear' i]"
            ).first
            header_clear_available = await header_clear_control.count() > 0

            dropdown_btn = slicer_visual.locator(
                ".slicer-dropdown-menu, .slicer-rest-item, [role='combobox']"
            ).first

            container = slicer_visual
            opened_popup = False

            if await dropdown_btn.count() > 0:
                _diag_before = await measure_canvas(self.page)
                await dropdown_btn.click(force=True)
                _diag_after = await measure_canvas(self.page)
                log_delta("SlicerEngine.get_slicer_state.dropdown_btn_click", filter_name, _diag_before, _diag_after)
                popup = self.page.locator(".slicer-dropdown-popup:visible").first
                try:
                    await popup.wait_for(state="visible", timeout=3000)
                    container = popup
                    opened_popup = True
                except Exception:
                    # Could not confirm popup contents; fall back to
                    # whatever the closed control shows, if anything.
                    logger.warning(f"Dropdown popup failed to open for '{filter_name}' state read.")
                    restatement = slicer_visual.locator(
                        ".slicer-restatement, .slicerText"
                    ).first
                    if await restatement.count() > 0:
                        txt = (await restatement.text_content() or "").strip()
                        if txt and txt.strip().lower() not in self._CLEAR_OR_ALL_TEXT:
                            state["selected_values"] = [txt]
                    state["clear_available"] = header_clear_available or None
                    return state

            rows = container.locator(
                ".slicerItemContainer, "
                "[role='checkbox'], "
                "[role='radio'], "
                "[role='option'], "
                "[role='treeitem']"
            )

            try:
                await rows.first.wait_for(state="visible", timeout=3000)
            except Exception:
                # No enumerable rows found; nothing more can be reliably read.
                state["clear_available"] = header_clear_available or None
                if opened_popup:
                    await self._close_any_open_popups()
                return state

            row_count = await rows.count()
            selected_values = []
            has_radio = False
            has_checkbox = False
            list_has_select_all_row = False

            for i in range(min(row_count, 200)):
                row = rows.nth(i)

                role = (await row.get_attribute("role")) or ""
                if role.lower() == "radio":
                    has_radio = True
                elif role.lower() == "checkbox":
                    has_checkbox = True

                text = (await row.text_content() or "").strip()
                is_selected = await self._read_row_selected(row)

                if text.strip().lower() in self._CLEAR_OR_ALL_TEXT:
                    list_has_select_all_row = True
                    continue

                if is_selected and text and text.strip().lower() not in self._NOISE_TEXT:
                    if text not in selected_values:
                        selected_values.append(text)

            state["selected_values"] = selected_values

            state["clear_available"] = header_clear_available or list_has_select_all_row

            if has_radio and not has_checkbox:
                state["selection_mode"] = "single"
            elif has_checkbox and not has_radio:
                state["selection_mode"] = "multi"
            elif len(selected_values) > 1:
                state["selection_mode"] = "multi"
            else:
                state["selection_mode"] = None  # not reliably determinable

            state["orientation"] = await self._detect_orientation(rows)

            if opened_popup:
                await self._close_any_open_popups()

            return state

        except Exception as e:
            logger.error(f"Error reading slicer state for '{filter_name}': {e}")
            await self._close_any_open_popups()
            state["error"] = str(e)
            return state

    async def get_all_slicer_states(self) -> list[dict]:
        """Convenience wrapper: reads state for every slicer currently
        detected on the page via extract_filters_from_dom(). Returns an
        empty list for a dashboard with no slicers (a valid state)."""
        filter_names = await self.extract_filters_from_dom()
        states = []
        for name in filter_names:
            states.append(await self.get_slicer_state(name))
        return states

    # ------------------------------------------------------------------
    # Baseline establishment (Task 1)
    #
    # Decides, per dynamically-discovered slicer, whether to clear it or
    # to leave it untouched and preserve its current selection — and does
    # so BEFORE baseline extraction runs. No slicer name, value, or
    # dashboard identifier is ever hardcoded; every slicer acted on here
    # comes from extract_filters_from_dom() at runtime.
    #
    # The "safe to clear" signal used here is intentionally stricter than
    # get_slicer_state()'s `clear_available` field: clicking is only ever
    # attempted against a concretely-located header Clear/All control
    # scoped to that one slicer's own visual container. A "Select All"
    # row inside the option list (which get_slicer_state() also treats as
    # evidence that *some* clear capability exists, for reporting
    # purposes) is never clicked here, since selecting it is a selection
    # action with its own ambiguity, not a confirmed clear control. If no
    # such control can be located, the slicer is treated as non-clearable
    # and its current selection is preserved instead — never guessed,
    # never forced.
    # ------------------------------------------------------------------

    async def _find_clear_control(self, filter_name: str):
        """Returns a Locator for the slicer's own header Clear/All control,
        scoped strictly to that slicer's visual container, or None if no
        such control can be confidently located. Never clicks anything."""
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
                return None

            control = slicer_visual.locator(
                ".clearAll, [aria-label*='Clear' i], [title*='Clear' i]"
            ).first

            if await control.count() > 0:
                return control
            return None
        except Exception as e:
            logger.warning(f"Could not evaluate clear control for '{filter_name}': {e}")
            return None

    async def _click_clear_control(self, control, filter_name: str) -> bool:
        """Clicks a previously-located clear control. Returns whether the
        click itself succeeded (not whether the clear was effective —
        that is verified separately by re-reading state)."""
        try:
            _diag_before = await measure_canvas(self.page)
            await control.scroll_into_view_if_needed()
            _diag_after = await measure_canvas(self.page)
            log_delta("SlicerEngine._click_clear_control.scroll_into_view_if_needed", filter_name, _diag_before, _diag_after)

            _diag_before = await measure_canvas(self.page)
            await control.click(force=True)
            _diag_after = await measure_canvas(self.page)
            log_delta("SlicerEngine._click_clear_control.click", filter_name, _diag_before, _diag_after)

            await self._close_any_open_popups()
            return True
        except Exception as e:
            logger.warning(f"Failed to click clear control for '{filter_name}': {e}")
            await self._close_any_open_popups()
            return False

    async def establish_slicer_baseline(self) -> dict:
        """Reads every slicer currently on the page and, per slicer:

        - if a genuine Clear/All control is found: clicks it, waits for
          Power BI to recalculate, re-reads state, and verifies the
          slicer actually ended up with no selected values. If it can't
          be verified, the attempt is reported as unverified and the
          (whatever it now is) selected values are preserved rather than
          pretending the clear succeeded.
        - if no such control is found: does not click anything and
          preserves the slicer's current selected value(s) as-is.
        - if there are no slicers at all: returns {} and nothing else
          happens, which is a valid, unchanged baseline.

        Returns a dict keyed by discovered slicer name, each value a
        report describing what was found and what (if anything) was done:

            {
                "<slicer name>": {
                    "initial_state": {...},        # get_slicer_state() output
                    "action": "cleared" | "clear_unverified" | "preserved" | "error",
                    "final_state": {...} | None,
                    "preserved_selected_values": [...],
                    "verified": bool | None,
                }
            }

        Never hardcodes a slicer name, dashboard name, or filter value —
        every slicer processed here comes from extract_filters_from_dom().
        """
        baseline: dict = {}

        try:
            slicer_names = await self.extract_filters_from_dom()
        except Exception as e:
            logger.error(f"Could not discover slicers for baseline establishment: {e}")
            return baseline

        if not slicer_names:
            logger.info("No slicers detected; baseline is the unmodified dashboard.")
            return baseline

        for name in slicer_names:
            entry = {
                "initial_state": None,
                "action": "none",
                "final_state": None,
                "preserved_selected_values": [],
                "verified": None,
            }

            try:
                initial_state = await self.get_slicer_state(name)
                entry["initial_state"] = initial_state

                clear_control = await self._find_clear_control(name)

                if clear_control is not None:
                    logger.info(f"Genuine Clear/All control found for slicer '{name}'; clearing.")
                    previous_snapshot = await capture_dashboard_snapshot(self.page)
                    click_ok = await self._click_clear_control(clear_control, name)

                    if click_ok:
                        try:
                            await wait_for_dashboard(self.page, previous_snapshot=previous_snapshot)
                        except Exception as e:
                            logger.warning(f"Wait after clearing '{name}' failed: {e}")

                    final_state = await self.get_slicer_state(name)
                    entry["final_state"] = final_state

                    verified = click_ok and not final_state.get("selected_values")
                    entry["verified"] = verified

                    if verified:
                        entry["action"] = "cleared"
                    else:
                        logger.warning(
                            f"Clear action for slicer '{name}' could not be verified; "
                            f"preserving its current state instead of assuming success."
                        )
                        entry["action"] = "clear_unverified"
                        entry["preserved_selected_values"] = (
                            final_state.get("selected_values")
                            or initial_state.get("selected_values")
                            or []
                        )
                else:
                    logger.info(
                        f"No genuine Clear/All control found for slicer '{name}'; "
                        f"preserving its current selected value(s)."
                    )
                    entry["action"] = "preserved"
                    entry["final_state"] = initial_state
                    entry["preserved_selected_values"] = initial_state.get("selected_values") or []

            except Exception as e:
                logger.error(f"Baseline handling failed for slicer '{name}': {e}")
                entry["action"] = "error"
                entry["error"] = str(e)

            baseline[name] = entry

        return baseline

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
            """Process one report page with tab closure safety."""
            # Guard check: stop gracefully if the page tab was closed
            if not page or page.is_closed():
                logger.error("Cannot process page '%s': Target browser page is closed.", page_name)
                return [], {}

            validator = _get_validator()

            executions = []
            applied_selection = {}

            logger.info("Waiting for visual containers to stay stable before extraction")
            try:
                await wait_for_dashboard(page)
            except Exception as e:
                logger.warning("Wait for dashboard failed on page '%s': %s", page_name, e)

            if page.is_closed():
                logger.warning("Target page closed during initial render on page '%s'. Skipping.", page_name)
                return [], {}

            logger.info("Establishing slicer baseline before extraction on page '%s'", page_name)
            try:
                slicer_baseline = await self.establish_slicer_baseline()
            except Exception as e:
                logger.error("Slicer baseline establishment failed on page '%s': %s", page_name, e)
                slicer_baseline = {}

            if slicer_baseline:
                # At least one slicer was cleared or otherwise touched;
                # let Power BI settle before extracting the baseline.
                try:
                    await wait_for_dashboard(page)
                except Exception as e:
                    logger.warning(
                        "Wait for dashboard after baseline establishment failed on page '%s': %s",
                        page_name, e,
                    )

            if page.is_closed():
                logger.warning(
                    "Target page closed while establishing slicer baseline on page '%s'. Skipping.",
                    page_name,
                )
                return [], {}

            # extract_visual_data(attempt_export=True) already identifies the
            # table/matrix visuals on this page and exports them as part of
            # extraction (see VisualDataExporter.extract_dashboard_data). Reuse
            # that result instead of calling export_table_visuals() a second
            # time, which previously re-triggered a live Export Data action on
            # the same visuals and produced duplicate exports.
            default_visual_data = await extract_visual_data(page, attempt_export=True)
            default_tables = default_visual_data.get("table_exports", [])
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
                "slicer_baseline": slicer_baseline,
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
                filters_to_apply = [(f_name, None) for f_name in (detected_filters or [])[:2]]
            for f_name, predetermined_value in filters_to_apply:
                if page.is_closed():
                    logger.warning("Page closed before applying filter '%s'. Skipping.", f_name)
                    break

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
                                "filter_applied": f"{f_name} = '{predetermined_value}' (FAILED TO APPLY)",
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

                if page.is_closed():
                    break

                # Same reuse as the baseline extraction above: avoid exporting
                # the same filtered table/matrix visuals twice.
                filtered_visual_data = await extract_visual_data(page, attempt_export=True)
                filtered_tables = filtered_visual_data.get("table_exports", [])

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