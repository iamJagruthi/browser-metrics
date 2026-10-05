import logging
import random
import re
from playwright.async_api import Page
import uuid

from orchestration.browser import capture_dashboard_snapshot, wait_for_dashboard
from orchestration.canvas_diagnostics import log_scroll_delta, measure_scroll_chain
from utils.config import sanitize_filename
from services.visual_data_exporter import extract_visual_data
# NOTE: do NOT import DashboardValidator at module level here — validator.py
# imports SlicerEngine at module level too, so a top-level import in both
# directions is a circular import. Import it lazily inside the method instead.

logger = logging.getLogger("orchestration.slicer")

_validator = None

# Word-boundary match for Power BI's selection markers on slicer rows/items.
# Deliberately avoids substring matching so base classes such as
# ``slicerItemContainer`` / ``slicerInteractivity`` are never misread as
# "selected". Mirrors the token set the DOM extraction already uses
# (selected / isSelected / slicer-selected / checked).
_SELECTED_TOKEN_RE = re.compile(
    r"(?:^|\s)(?:is[-_ ]?selected|slicer[-_ ]?selected|selected|checked)(?:\s|$)",
    re.IGNORECASE,
)

# How many selectable options a slicer is scanned up to. Bounded but large
# enough that slicers defaulting to a selected top-N are not starved of
# unselected candidates further down the list.
_MAX_FILTER_OPTIONS = 100

# Option/item nodes within a slicer container (on-canvas lists and open
# dropdown popups). Data-driven; no report-specific selector.
_FILTER_ITEMS_SELECTOR = (
    ".slicerItemContainer .slicerText, "
    "[role='checkbox'], "
    "[role='radio'], "
    "[role='option'], "
    "[role='treeitem'], "
    ".slicer-checkbox, "
    ".slicerText"
)


def _get_validator():
    """Lazily create (and cache) a DashboardValidator instance.

    Imported here rather than at module scope to avoid a circular import
    with orchestration.validator, which imports SlicerEngine at module level.
    """
    global _validator
    if _validator is None:
        from orchestration.validator import DashboardValidator
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

    async def read_filter_state(self, filter_names: list[str]) -> list[dict]:
        """Read the current selection state of each slicer from the live DOM.

        This is the single place that turns on-page slicers into the
        ``{name, selected_values, visible_values}`` records every consumer
        already expects: the filter comparison (``normalize_dom_filter``) and
        the cross-dashboard slicer scenarios both read exactly these keys.
        Slicers that cannot be read are skipped rather than reported as empty,
        so an unreadable slicer is never mistaken for "nothing selected".
        """
        filters: list[dict] = []
        for filter_name in filter_names or []:
            try:
                options = await self.get_filter_options_with_selection(filter_name)
            except Exception as e:
                logger.warning(
                    "Could not read options for slicer '%s': %s", filter_name, e
                )
                continue
            if not options:
                continue

            selected: list[str] = []
            visible: list[str] = []
            for item in options:
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                visible.append(text)
                if item.get("selected"):
                    selected.append(text)

            filters.append(
                {
                    "name": filter_name,
                    "selected_values": selected,
                    "visible_values": visible,
                }
            )
            logger.info(
                "Slicer state read | slicer=%r | selected=%d | visible=%d",
                filter_name,
                len(selected),
                len(visible),
            )

        logger.info(
            "Slicer state summary | readable=%d | requested=%d",
            len(filters),
            len(filter_names or []),
        )
        return filters

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

    async def _locate_slicer_visual(self, filter_name: str):
        """Locate the visual container owning a slicer by its header text."""
        if not self.page or self.page.is_closed():
            return None
        for selector in (
            f"visual-container:has(.slicer-header-text:text-is('{filter_name}'))",
            f"visual-container:has(.slicer-header-text:has-text('{filter_name}'))",
        ):
            try:
                locator = self.page.locator(selector).first
                if await locator.count() > 0:
                    return locator
            except Exception:
                continue
        return None

    async def _open_dropdown_items(self, slicer_visual):
        """Return ``(container, is_dropdown, popup_confirmed)`` for a slicer.

        Dropdown slicers are opened only when their popup is not already
        visible: clicking the trigger again while it is open toggles it
        closed. When the popup cannot be confirmed the visual container
        itself is returned so option-like nodes are still scanned instead of
        silently returning no options.
        """
        dropdown_btn = slicer_visual.locator(
            ".slicer-dropdown-menu, .slicer-rest-item, [role='combobox']"
        ).first
        try:
            if await dropdown_btn.count() == 0:
                return slicer_visual, False, False
        except Exception:
            return slicer_visual, False, False

        popup = self.page.locator(".slicer-dropdown-popup:visible").first
        try:
            if await popup.count() == 0:
                await dropdown_btn.click(force=True)
            await popup.wait_for(state="visible", timeout=3000)
            return popup, True, True
        except Exception:
            logger.warning(
                "Dropdown popup failed to open; scanning the visual "
                "container for option nodes instead."
            )
            return slicer_visual, True, False

    async def _collect_filter_options(
        self,
        filter_name: str,
    ) -> tuple[list[dict], bool]:
        """Discover a slicer's selectable option nodes.

        Returns ``(items, is_dropdown)`` where each item is
        ``{"text": <label>, "selected": <bool>}``. Selection state is read
        per option node from the live DOM so choice logic does not depend on
        a single, sometimes noisy state read. Never hardcodes option counts
        or values.
        """
        logger.info(f"Reading options for filter: '{filter_name}'")
        items: list[dict] = []
        is_dropdown = False
        try:
            await self._close_any_open_popups()

            slicer_visual = await self._locate_slicer_visual(filter_name)
            if slicer_visual is None:
                logger.warning(f"Slicer visual '{filter_name}' not found in DOM.")
                return items, False

            container, is_dropdown = await self._open_dropdown_items(
                slicer_visual
            )

            option_nodes = container.locator(_FILTER_ITEMS_SELECTOR)
            try:
                await option_nodes.first.wait_for(state="visible", timeout=3000)
            except Exception:
                logger.warning(f"No option items rendered for filter '{filter_name}'.")
                await self._close_any_open_popups()
                return items, is_dropdown

            count = await option_nodes.count()
            seen = set()
            for i in range(min(count, _MAX_FILTER_OPTIONS)):
                node = option_nodes.nth(i)
                try:
                    txt = (await node.text_content() or "").strip()
                except Exception:
                    continue
                if not txt:
                    continue
                normalized = self._normalize_value(txt)
                if normalized in seen:
                    continue
                seen.add(normalized)
                try:
                    selected = await self._read_row_selected(node)
                except Exception:
                    selected = False
                items.append({"text": txt, "selected": selected})

        except Exception as e:
            logger.error(f"Error reading options for '{filter_name}': {e}")
        finally:
            try:
                await self._close_any_open_popups()
            except Exception:
                pass

        logger.info(f"Discovered options for '{filter_name}': {items}")
        return items, is_dropdown

    async def get_filter_options(self, filter_name: str) -> list[str]:
        """Return the selectable option labels of a slicer (existing API)."""
        items, _ = await self._collect_filter_options(filter_name)
        return [item["text"] for item in items]

    async def get_filter_options_with_selection(
        self,
        filter_name: str,
    ) -> list[dict]:
        """Return ``[{"text": ..., "selected": ...}, ...]`` for a slicer."""
        items, _ = await self._collect_filter_options(filter_name)
        return items

         
    
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

            if await target_el.count() == 0:
                logger.warning(f"Option '{option_value}' not found in '{filter_name}'.")
                await self.page.keyboard.press("Escape")
                return False

            # Requested value is confirmed absent from selected_values, so a
            # single click here is the minimum action needed to select it —
            # never toggling anything the caller didn't ask to change.
            previous_snapshot = await capture_dashboard_snapshot(self.page)

            _diag_before = await measure_scroll_chain(self.page, target_el)
            await target_el.scroll_into_view_if_needed()
            _diag_after_scroll = await measure_scroll_chain(self.page, target_el)
            log_scroll_delta(
                "slicer.apply_filter.scroll",
                filter_name,
                _diag_before,
                _diag_after_scroll,
                "after_scroll",
            )
            await target_el.click(force=True)
            logger.info(f"Clicked option '{option_value}' under '{filter_name}'; verifying result.")

            await self.page.keyboard.press("Escape")

            try:
                await wait_for_dashboard(self.page, previous_snapshot=previous_snapshot)
            except Exception as e:
                logger.warning(f"Wait for dashboard after clicking '{filter_name}' failed: {e}")

            _diag_after_done = await measure_scroll_chain(self.page)
            log_scroll_delta(
                "slicer.apply_filter.complete",
                filter_name,
                _diag_before,
                _diag_after_done,
                "after_operation",
            )

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
            if _SELECTED_TOKEN_RE.search(cls):
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

            # Some Power BI versions mark selection only on a nested
            # accessibility attribute/checkbox node rather than the row.
            nested = row.locator(
                "[aria-checked='true'], [aria-selected='true'], "
                "[aria-pressed='true']"
            ).first
            if await nested.count() > 0:
                return True

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

            container, is_dropdown, popup_confirmed = await self._open_dropdown_items(
                slicer_visual
            )

            if is_dropdown and not popup_confirmed:
                # Could not confirm popup contents; fall back to whatever
                # the closed control shows, if anything.
                logger.warning(
                    "Dropdown popup failed to open for '%s' state read.",
                    filter_name,
                )
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
                if popup_confirmed:
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

            if popup_confirmed:
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
    # Baseline establishment (Reset Filters)
    #
    # Replaces the old slicer-by-slicer clear mechanism. Power BI reports
    # expose a single dashboard-level "Reset filters, slicers, and other
    # data view changes" action. We locate that action semantically
    # (accessible name / aria-label / title / generic class tokens), click
    # it, wait for the dashboard to re-render, and verify that previously
    # selected slicer values were actually cleared.
    #
    # No coordinates, no nth-child, no report-specific selector, and no
    # hardcoded dashboard/slicer/filter name is ever used.
    # ------------------------------------------------------------------

    _RESET_FILTER_NAME_PATTERN = re.compile(
        r"reset.{0,40}filter|clear.{0,40}filter|remove.{0,40}filter",
        re.IGNORECASE,
    )

    _RESET_FILTER_SELECTORS = (
        # Accessible-name evidence first (resolves buttons, menus, links).
        "button",
        "[role='button']",
        "[role='menuitem']",
        "menuitem",
        # Generic Power BI chrome, never report-specific.
        ".resetFilters",
        ".reset-filters",
        "[data-testid*='reset' i]",
    )

    async def _find_reset_filters_control(self):
        """Locate the dashboard-level Reset Filters action, or None.

        Searches using semantic/accessibility evidence only:
        - ``get_by_role`` with an accessible-name regex matching
          "reset/clear/remove ... filter".
        - aria-label / title attributes mentioning Reset Filters.
        - generic Power BI class tokens (never report-specific).
        Returns the first matching Locator or None.
        """
        for role in self._RESET_FILTER_SELECTORS:
            try:
                candidates = self.page.get_by_role(
                    role,
                    name=self._RESET_FILTER_NAME_PATTERN,
                )
                if await candidates.count() > 0:
                    return candidates.first
            except Exception as e:
                logger.warning(
                    "Reset Filters role probe failed | role=%s | error=%s",
                    role,
                    e,
                )

        # Fall back to aria-label / title attributes.
        for attribute in ("aria-label", "title"):
            try:
                locator = self.page.locator(
                    f"[{attribute}*='reset' i][{attribute}*='filter' i], "
                    f"[{attribute}*='clear' i][{attribute}*='filter' i], "
                    f"[{attribute}*='remove' i][{attribute}*='filter' i]"
                ).first
                if await locator.count() > 0:
                    return locator
            except Exception as e:
                logger.warning(
                    "Reset Filters attribute probe failed | attr=%s | error=%s",
                    attribute,
                    e,
                )

        return None

    async def reset_dashboard_filters(self) -> dict:
        """Reset all dashboard filters via Power BI's dashboard-level
        "Reset filters, slicers, and other data view changes" action.

        Returns a structured result:

            {
                "status": "success" | "not_found" | "verification_failed",
                "action": "reset_filters",
                "verified": bool,
                "error": str | None,
                "before_state": [slicer states before reset],
                "after_state": [slicer states after reset],
            }

        Failure is never silently converted to success.
        """
        result = {
            "status": "not_found",
            "action": "reset_filters",
            "verified": False,
            "error": None,
            "before_state": [],
            "after_state": [],
        }

        # 1. verify page is alive
        if not self.page or self.page.is_closed():
            result["status"] = "not_found"
            result["error"] = "Page is closed; cannot reset filters."
            logger.warning("Reset Filters skipped | page_closed=True")
            return result

        try:
            result["before_state"] = await self.get_all_slicer_states()
        except Exception as e:
            logger.warning(f"Could not read slicer state before reset: {e}")

        # 2. locate dashboard-level Reset Filters action
        control = await self._find_reset_filters_control()

        if control is None:
            result["status"] = "not_found"
            result["error"] = (
                "Dashboard-level 'Reset filters, slicers, and other "
                "data view changes' action not found in the DOM."
            )
            logger.warning(
                "Reset Filters control not found | status=not_found"
            )
            return result

        # 3. click the action
        try:
            previous_snapshot = await capture_dashboard_snapshot(self.page)
            await control.scroll_into_view_if_needed()
            await control.click(force=True)
            clicked = True
        except Exception as e:
            logger.exception("Reset Filters click failed")
            result["status"] = "verification_failed"
            result["error"] = f"Click failed: {e}"
            return result

        # 4. wait for the dashboard to update
        try:
            await wait_for_dashboard(
                self.page,
                previous_snapshot=previous_snapshot,
            )
        except Exception as e:
            logger.warning(f"Wait for dashboard after Reset Filters failed: {e}")

        if self.page.is_closed():
            result["status"] = "verification_failed"
            result["error"] = "Page closed during Reset Filters wait."
            return result

        # 5. verify the reset actually occurred
        try:
            result["after_state"] = await self.get_all_slicer_states()
        except Exception as e:
            logger.warning(f"Could not read slicer state after reset: {e}")

        before_selected = {
            state.get("name"): list(state.get("selected_values") or [])
            for state in result["before_state"]
        }
        after_selected = {
            state.get("name"): list(state.get("selected_values") or [])
            for state in result["after_state"]
        }

        cleared_names = [
            name
            for name, values in before_selected.items()
            if values and not after_selected.get(name)
        ]

        # A successful dashboard-level reset clears every previously
        # selected slicer value. If nothing was selected to begin with
        # (already reset), the click itself plus a re-render is used.
        if cleared_names or (clicked and not any(before_selected.values())):
            result["verified"] = True
            result["status"] = "success"
            logger.info(
                "Reset Filters succeeded | cleared=%s",
                cleared_names,
            )
        else:
            result["status"] = "verification_failed"
            result["error"] = (
                "Reset Filters was clicked but slicer selections were "
                "not cleared; dashboard state preserved as-is."
            )
            logger.warning(
                "Reset Filters verification failed | before=%s | after=%s",
                before_selected,
                after_selected,
            )

        return result

    async def apply_random_valid_option(self, filter_name: str) -> str | None:
        """Choose and apply a runtime-discovered slicer option.

        The selected value is returned only when ``apply_filter`` verifies that
        the value is actually selected. A value counts as "already selected" if
        its own DOM node reports selection OR it appears in the slicer's current
        selected-values state, so no scenario is created from a no-op click.
        """
        items = await self.get_filter_options_with_selection(filter_name)

        valid_options = [
            item for item in items
            if item["text"].strip().casefold() not in {"select all", "all", "(blank)", ""}
        ]

        try:
            current_state = await self.get_slicer_state(filter_name)
            current_values = {
                self._normalize_value(value)
                for value in current_state.get("selected_values", [])
            } if current_state and not current_state.get("error") else set()
        except Exception as exc:
            logger.warning(
                "Could not read current state before choosing an option for '%s': %s",
                filter_name,
                exc,
            )
            current_values = set()

        def _already_selected(item: dict) -> bool:
            if item.get("selected"):
                return True
            return self._normalize_value(item["text"]) in current_values

        candidates = [item for item in valid_options if not _already_selected(item)]

        if not candidates:
            logger.warning(
                "No unselected valid options found for filter '%s'; "
                "discovered=%d selected=%d | no scenario will be created "
                "for this filter.",
                filter_name,
                len(valid_options),
                sum(1 for item in valid_options if _already_selected(item)),
            )
            return None

        selected_option = random.choice([item["text"] for item in candidates])
        success = await self.apply_filter(filter_name, selected_option)
        if not success:
            logger.warning(
                "Filter application was not verified | filter=%s | value=%s",
                filter_name,
                selected_option,
            )
            return None

        return selected_option

    async def run_filter_render_test(self) -> dict:
        """Dynamically apply one real filter interaction and measure its render.

        Flow (matches the browser-metrics contract):
            1. Discover usable slicers from the live DOM (no hardcoding).
            2. For each slicer in DOM order, apply a valid runtime-discovered
               option that is NOT currently selected, via the existing
               apply_random_valid_option() (which prefers values different from
               the current selection and verifies the click actually selected).
            3. Time the interaction with the shared PerformanceTimer under the
               dashboard_render key until the dashboard reaches its existing
               stable/render state (wait_for_dashboard runs inside apply_filter).
               dashboard_render_seconds IS this filter-application measurement;
               page_load_seconds separately covers opening the link through to the
               dashboard being fully rendered.
            4. Return an auditable dict. filter_dashboard_render_seconds is a
               real measured value or None -- never a fabricated 0.

        Reset Filters is intentionally NOT invoked here: the supplied
        URL/bookmark/page state must remain unchanged, and
        reset_dashboard_filters() / _find_reset_filters_control() are kept
        available but must not be called.
        """
        result = {
            "status": "not_run",
            "slicer": None,
            "value": None,
            "applied": False,
            "filter_dashboard_render_seconds": None,
            "error": None,
        }

        if self.page is None or self.page.is_closed():
            result.update({"status": "failed", "error": "page_closed"})
            return result

        filter_names = await self.extract_filters_from_dom()
        if not filter_names:
            result.update({
                "status": "unavailable",
                "error": "no_slicers_found",
            })
            return result

        validator = _get_validator()
        last_slicer = None
        probe_errors = []

        for filter_name in filter_names:
            last_slicer = filter_name
            if self.page.is_closed():
                break

            validator.timer.start("dashboard_render")
            try:
                applied_value = await self.apply_random_valid_option(filter_name)
            except Exception as exc:
                logger.warning(
                    "Filter render test probe failed | filter=%s | error=%s",
                    filter_name,
                    exc,
                )
                probe_errors.append(f"{filter_name}: {exc}")
                applied_value = None
            finally:
                validator.timer.stop("dashboard_render")

            if applied_value is not None:
                # This is the dashboard_render figure the report shows: the
                # wait for the dashboard to re-render once the filter is live.
                filter_render_seconds = validator.timer.get("dashboard_render")
                result.update({
                    "status": "applied",
                    "slicer": filter_name,
                    "value": applied_value,
                    "applied": True,
                    "filter_dashboard_render_seconds": filter_render_seconds,
                    "error": None,
                })
                # Recorded on the shared timer too, so every consumer that reads
                # dashboard_render (metrics, Excel, the payload above) sees the
                # filter-application value instead of a stale page-load value.
                validator.timer.set_elapsed("dashboard_render", filter_render_seconds)
                logger.info(
                    "Filter render measured | filter=%s | dashboard_render_seconds=%.3f",
                    filter_name,
                    filter_render_seconds,
                )
                return result

        result.update({
            "status": "unavailable",
            "slicer": last_slicer,
            "error": (
                "no_usable_slicer_option"
                if not probe_errors
                else "; ".join(probe_errors[:3])
            ),
        })
        return result

    async def _verify_applied_filter_state(self, applied_filters: dict) -> tuple[bool, dict]:
        """Verify that every expected filter is active on the current page.

        This is intentionally data-driven: filter names and values come from
        the accumulated runtime state. No dashboard-specific names or values
        are assumed.
        """
        observed_states = {}

        for filter_name, expected_value in applied_filters.items():
            try:
                state = await self.get_slicer_state(filter_name)
            except Exception as exc:
                logger.warning(
                    "Could not verify slicer '%s': %s", filter_name, exc
                )
                return False, observed_states

            observed_states[filter_name] = state

            if state.get("error"):
                logger.warning(
                    "Slicer verification failed | filter=%s | error=%s",
                    filter_name,
                    state.get("error"),
                )
                return False, observed_states

            actual_values = {
                self._normalize_value(value)
                for value in (state.get("selected_values") or [])
            }

            if isinstance(expected_value, (list, tuple, set)):
                expected_values = {
                    self._normalize_value(value) for value in expected_value
                }
                matches = expected_values.issubset(actual_values)
            else:
                matches = self._normalize_value(expected_value) in actual_values

            if not matches:
                logger.warning(
                    "Cumulative slicer verification failed | filter=%s | "
                    "expected=%s | actual=%s",
                    filter_name,
                    expected_value,
                    state.get("selected_values"),
                )
                return False, observed_states

        return True, observed_states

    async def process_dashboard_page(
            self,
            dashboard,
            page,
            response,
            page_name,
            predetermined_filters=None,
            screenshot_dir=None,
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

            # ------------------------------------------------------------------
            # TEMPORARILY DISABLED: dashboard-level Reset Filters.
            # reset_dashboard_filters() and _find_reset_filters_control() are
            # kept intact below for later re-enabling, but must NOT be invoked
            # right now: the supplied URL/bookmark/page state (including
            # hidden/non-default pages) has to be preserved exactly as provided.
            #
            # logger.info(
            #     "Establishing baseline filters with dashboard-level Reset "
            #     "on page '%s'",
            #     page_name,
            # )
            # try:
            #     slicer_baseline = await self.reset_dashboard_filters()
            # except Exception as e:
            #     logger.error("Reset Filters failed on page '%s': %s", page_name, e)
            #     slicer_baseline = {
            #         "status": "verification_failed",
            #         "action": "reset_filters",
            #         "verified": False,
            #         "error": str(e),
            #         "before_state": [],
            #         "after_state": [],
            #     }
            #
            # if slicer_baseline and slicer_baseline.get("verified"):
            #     # Reset Filters changed the dashboard; let Power BI settle
            #     # before extracting the baseline visuals.
            #     try:
            #         await wait_for_dashboard(page)
            #     except Exception as e:
            #         logger.warning(
            #             "Wait for dashboard after Reset Filters failed on page '%s': %s",
            #             page_name, e,
            #         )
            # ------------------------------------------------------------------
            slicer_baseline = {
                "status": "disabled",
                "action": "reset_filters",
                "verified": False,
                "error": None,
                "before_state": [],
                "after_state": [],
            }

            if page.is_closed():
                logger.warning(
                    "Target page closed while establishing slicer baseline on page '%s'. Skipping.",
                    page_name,
                )
                return [], {}

            # Capture the default view screenshot FIRST, from the stable
            # dashboard state already established by wait_for_dashboard above.
            # Extraction/export below performs live "Export Data" actions that
            # scroll nested Power BI canvas containers (table_exporter
            # _open_more_options -> scroll_into_view_if_needed), which would
            # displace the canvas in any later screenshot.
            default_screenshot_path = None
            if screenshot_dir is not None:
                default_screenshot_path = (
                    screenshot_dir
                    / (
                        f"{sanitize_filename(dashboard.get('name'))}__"
                        f"{sanitize_filename(page_name)}__default.png"
                    )
                )
                try:
                    await page.screenshot(
                        path=str(default_screenshot_path),
                        full_page=True,
                    )
                    logger.info(
                        "default.screenshot.saved | page=%s | path=%s",
                        page_name,
                        default_screenshot_path,
                    )
                except Exception:
                    logger.exception(
                        "Failed to capture default view screenshot | page=%s",
                        page_name,
                    )
                    default_screenshot_path = None

            # extract_visual_data(attempt_export=True) already identifies the
            # table/matrix visuals on this page and exports them as part of
            # extraction (see VisualDataExporter.extract_dashboard_data). Reuse
            # that result instead of calling export_table_visuals() a second
            # time, which previously re-triggered a live Export Data action on
            # the same visuals and produced duplicate exports.
            logger.info("default.visual_extraction.begin | page=%s", page_name)
            default_visual_data = await extract_visual_data(
                page,
                attempt_export=True,
                dashboard_title=str(dashboard.get("name") or "") or None,
                page_name=page_name,
            )
            default_tables = default_visual_data.get("table_exports", [])
            logger.info(
                "default.visual_extraction.completed | page=%s | exports=%d",
                page_name,
                len(default_tables),
            )

            # Publish the slicers this page actually shows, read from the live
            # DOM. The filter comparison and the cross-dashboard slicer
            # scenarios both key off visual_data["filters"], so without this the
            # report would claim "no filters" and no shared slicer could ever be
            # applied to both dashboards.
            detected_filter_names = await self.extract_filters_from_dom()
            default_visual_data["filters"] = await self.read_filter_state(
                detected_filter_names
            )
            logger.info(
                "default.filter_state.published | page=%s | filters=%d",
                page_name,
                len(default_visual_data["filters"]),
            )

            default_metrics = await validator._capture_metrics(
                dashboard,
                page,
                response,
                page_name=page_name,
                screenshot_path=default_screenshot_path,
            )

            executions.append({
                "dashboard": {
                    **dashboard,
                    "page_name": page_name,
                    "filter_applied": "Default View"
                },
                "page_name": page_name,
                "filter_applied": "Default View",
                "applied_filters": {},
                "filter_state_verified": True,
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
                # No explicit predetermined_filters: never auto-sweep arbitrary
                # DOM-order slicers for random scenario testing. The DOM probe
                # cannot distinguish a real content filter (e.g. Division /
                # Facility) from a measure-selector slicer (e.g. "Cases Metric"
                # / "Dollars Metric"), so a blind [:2] pick randomly re-chose
                # which measure was plotted -- making the dashboard "dance" and
                # runs non-reproducible. Controlled slicer-scenario coverage is
                # still produced deterministically by _run_slicer_scenarios() /
                # _run_multi_page_slicer_scenarios() during capture.
                detected_filters = await self.extract_filters_from_dom()
                if detected_filters:
                    logger.info(f"Detected filters on page '{page_name}': {detected_filters}")
                filters_to_apply = []
            for f_name, predetermined_value in filters_to_apply:
                if page.is_closed():
                    logger.warning(
                        "Page closed before applying filter '%s'. Skipping.", f_name
                    )
                    break

                previous_snapshot = await capture_dashboard_snapshot(page)

                if predetermined_value is not None:
                    logger.info(
                        "Reproducing filter on target: %s = '%s'",
                        f_name,
                        predetermined_value,
                    )
                    applied_option = predetermined_value
                    success = await self.apply_filter(f_name, applied_option)
                else:
                    logger.info("Applying runtime-selected option to filter: %s", f_name)
                    applied_option = await self.apply_random_valid_option(f_name)
                    success = applied_option is not None

                if not success or applied_option is None:
                    logger.warning(
                        "Filter scenario not recorded because application was not "
                        "verified | page=%s | filter=%s | value=%s",
                        page_name,
                        f_name,
                        applied_option,
                    )
                    break

                # Update the cumulative state only after the individual filter
                # application has been verified. Never mutate earlier snapshots.
                applied_selection[f_name] = applied_option
                scenario_filters = dict(applied_selection)

                filter_label = ", ".join(
                    f"{name} = '{value}'"
                    for name, value in scenario_filters.items()
                )

                logger.info(
                    "Cumulative filter state | page=%s | filters=%s",
                    page_name,
                    scenario_filters,
                )

                validator.timer.start("filter_dashboard_render")
                logger.info("Waiting for Power BI visuals to recalculate...")
                await wait_for_dashboard(page, previous_snapshot=previous_snapshot)
                scenario_render_seconds = validator.timer.stop(
                    "filter_dashboard_render"
                )
                # This scenario's re-render is a dashboard_render measurement too,
                # so it updates the shared timer rather than being reported under
                # a second, separate name.
                validator.timer.set_elapsed(
                    "dashboard_render", scenario_render_seconds
                )

                if page.is_closed():
                    logger.warning(
                        "Page closed after applying cumulative filters on '%s'.",
                        page_name,
                    )
                    break

                # Verify the complete accumulated state, not only the most recent
                # filter. This prevents a scenario from being recorded if a prior
                # slicer selection was lost during recalculation.
                state_verified, observed_states = await self._verify_applied_filter_state(
                    scenario_filters
                )

                if not state_verified:
                    logger.warning(
                        "Cumulative filter state could not be verified; "
                        "scenario will not be recorded | page=%s | filters=%s",
                        page_name,
                        scenario_filters,
                    )
                    break

                # Reuse the current dashboard state exactly once after the full
                # cumulative filter state has been verified. Capture the
                # scenario screenshot BEFORE extract_visual_data below: the
                # scroll-aware fallback export opens live "Export Data" actions
                # that scroll nested Power BI canvas containers, which would
                # displace the canvas in any later screenshot.
                scenario_screenshot_path = None
                if screenshot_dir is not None:
                    scenario_screenshot_path = (
                        screenshot_dir
                        / (
                            f"{sanitize_filename(dashboard.get('name'))}__"
                            f"{sanitize_filename(page_name)}__"
                            f"{sanitize_filename(filter_label)}.png"
                        )
                    )
                    try:
                        await page.screenshot(
                            path=str(scenario_screenshot_path),
                            full_page=True,
                        )
                        logger.info(
                            "scenario.screenshot.saved | page=%s | path=%s",
                            page_name,
                            scenario_screenshot_path,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to capture filtered scenario screenshot | page=%s",
                            page_name,
                        )
                        scenario_screenshot_path = None

                logger.info(
                    "scenario.visual_extraction.begin | page=%s | filters=%s",
                    page_name,
                    scenario_filters,
                )
                filtered_visual_data = await extract_visual_data(
                    page,
                    attempt_export=False,
                    scroll_export_fallback=True,
                    dashboard_title=str(dashboard.get("name") or "") or None,
                    page_name=page_name,
                )
                filtered_tables = filtered_visual_data.get("table_exports", [])
                logger.info(
                    "scenario.visual_extraction.completed | page=%s | exports=%d",
                    page_name,
                    len(filtered_tables),
                )

                executions.append({
                    "dashboard": {
                        **dashboard,
                        "page_name": page_name,
                        "filter_applied": filter_label,
                    },
                    "page_name": page_name,
                    "filter_applied": filter_label,
                    "applied_filters": scenario_filters,
                    "filter_state_verified": True,
                    "slicer_states": observed_states,
                    "extraction": {
                        "status": "not_used",
                        "data": None,
                        "error": None,
                    },
                    "visual_data": filtered_visual_data,
                    "tables": filtered_tables,
                    # Re-render wait for this scenario's cumulative filters.
                    "dashboard_render_seconds": scenario_render_seconds,
                    "metrics": await validator._capture_metrics(
                        dashboard,
                        page,
                        response,
                        page_name=page_name,
                        screenshot_path=scenario_screenshot_path,
                    ),
                    "_page": page,
                })

            return executions, applied_selection