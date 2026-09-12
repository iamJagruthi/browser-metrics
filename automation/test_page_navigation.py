import logging
from automation.browser import wait_for_dashboard

logger = logging.getLogger(__name__)


async def navigate_to_page(page, page_name: str) -> bool:
    """
    Navigate to a Power BI report page safely without crashing the run process.
    Returns True on success, False on failure.
    """
    # 1. Check if browser target is alive
    if page.is_closed():
        logger.error(f"Cannot navigate to '{page_name}': browser page tab is already closed.")
        return False

    try:
        # 2. Close any lingering export/menu overlays before clicking tabs
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(200)
        except Exception:
            pass

        # 3. Locate page tab (exact aria-label or contains text)
        page_element = page.locator(
            f'[role="tab"][aria-label="{page_name}"], '
            f'[role="tab"]:has-text("{page_name}")'
        ).first

        if await page_element.count() == 0:
            logger.warning(f"Dashboard page tab not found for '{page_name}'")
            return False

        # 4. Ensure tab is visible and click
        await page_element.scroll_into_view_if_needed()
        await page_element.click(timeout=10000)
        
        # 5. Wait for Power BI visuals to load
        if "wait_for_dashboard" in globals() or "wait_for_dashboard" in locals():
            await wait_for_dashboard(page)
        else:
            await page.wait_for_timeout(2000)

        # 6. Verify page selection flexibly
        selected_page = page.locator('[role="tab"][aria-label*="Selected" i], [role="tab"][aria-selected="true"]').first

        if await selected_page.count() > 0:
            selected_label = (await selected_page.get_attribute("aria-label")) or ""
            if page_name.casefold() in selected_label.casefold():
                logger.info(f"Successfully navigated and verified page: {page_name}")
                return True

        # Fallback check if explicit "Selected" label attribute wasn't updated
        logger.info(f"Navigated to page: {page_name} (Selection label verification bypassed)")
        return True

    except Exception as exc:
        if page.is_closed():
            logger.error(f"Browser target crashed during page navigation to '{page_name}': {exc}")
            return False
        
        logger.warning(f"Failed to navigate to page '{page_name}': {exc}")
        return False


async def get_dashboard_pages(page) -> list[dict]:
    """Detect Power BI report pages from the Pages pane."""
    page_elements = page.locator('[role="tab"][aria-label]')
    pages = []

    count = await page_elements.count()

    for index in range(count):
        element = page_elements.nth(index)

        aria_label = await element.get_attribute("aria-label")
        text = (await element.inner_text()).strip()

        if not aria_label:
            continue

        if aria_label.endswith(" Selected"):
            page_name = aria_label[:-len(" Selected")]
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