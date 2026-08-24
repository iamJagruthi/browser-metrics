import logging
import random
from playwright.async_api import Page

logger = logging.getLogger("automation.slicer")

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
            # 1. Force close any lingering dropdown
            await self._close_any_open_popups()

            # 2. Locate exact visual container
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

            # 3. Click dropdown trigger
            dropdown_btn = slicer_visual.locator(
                ".slicer-dropdown-menu, .slicer-rest-item, [role='combobox']"
            ).first
            
            if await dropdown_btn.count() == 0:
                logger.warning(f"Dropdown trigger for '{filter_name}' not found.")
                return options

            await dropdown_btn.click(force=True)

            # 4. Wait explicitly for a visible popup to appear
            popup = self.page.locator(".slicer-dropdown-popup:visible").first
            try:
                await popup.wait_for(state="visible", timeout=3000)
            except Exception:
                logger.warning(f"Popup failed to open for filter '{filter_name}'.")
                return options

            # 5. Read options from the newly verified popup
            items = popup.locator(".slicerItemContainer .slicerText")
            count = await items.count()

            for i in range(min(count, 15)):
                txt = await items.nth(i).text_content()
                clean = txt.strip() if txt else ""
                if clean and clean not in options:
                    options.append(clean)

            # 6. Clean up popup state
            await self._close_any_open_popups()

            logger.info(f"✅ Discovered options for '{filter_name}': {options}")
            return options

        except Exception as e:
            logger.error(f"Error reading options for '{filter_name}': {e}")
            await self._close_any_open_popups()
            return options
    
    async def apply_filter(self, filter_name: str, option_value: str):
        """Auto-selects option in active popup after ensuring clean popup state."""
        logger.info(f"Applying filter: [{filter_name} = '{option_value}']")
        try:
            # 1. Close any leftover popups first
            await self._close_any_open_popups()

            # 2. Locate visual container using exact text match
            slicer_visual = self.page.locator(f"visual-container:has(.slicer-header-text:text-is('{filter_name}'))").first
            if await slicer_visual.count() == 0:
                slicer_visual = self.page.locator(f"visual-container:has(.slicer-header-text:has-text('{filter_name}'))").first

            # 3. Click dropdown trigger button
            dropdown_btn = slicer_visual.locator(".slicer-dropdown-menu, .slicer-rest-item, [role='combobox']").first
            if await dropdown_btn.count() > 0:
                await dropdown_btn.click(force=True)
                await self.page.wait_for_timeout(600)

            # 4. Target freshly opened popup
            popup = self.page.locator(".slicer-dropdown-popup:visible, .slicer-dropdown-popup.focused").first

            # 5. Find matching item row
            target_row = popup.locator(f".slicerItemContainer:has(.slicerText:text-is('{option_value}'))").first
            if await target_row.count() == 0:
                target_row = popup.locator(f".slicerItemContainer:has(.slicerText:has-text('{option_value}'))").first

            if await target_row.count() > 0:
                await target_row.scroll_into_view_if_needed()
                await self.page.wait_for_timeout(200)

                text_el = target_row.locator(".slicerText").first
                if await text_el.count() > 0:
                    await text_el.click(force=True)
                else:
                    await target_row.click(force=True)

                logger.info(f"✅ Successfully selected option '{option_value}' under '{filter_name}'.")
            else:
                logger.warning(f"Option '{option_value}' not found in '{filter_name}' dropdown popup.")

            # 6. Close popup menu and pause for DAX recalculations
            await self.page.keyboard.press("Escape")
            await self.page.wait_for_timeout(3000)

        except Exception as e:
            logger.error(f"Error applying filter '{filter_name}' = '{option_value}': {e}")
            await self._close_any_open_popups()

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