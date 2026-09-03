import logging
from automation.browser import wait_for_dashboard

logger = logging.getLogger(__name__)


async def navigate_to_page(page, page_name: str):
    """Navigate to a Power BI report page and verify the selected page."""
    if page.is_closed():
        raise RuntimeError(
            f"Cannot navigate to '{page_name}': target page is closed or crashed."
        )

    try:
        page_element = page.locator(f'[role="tab"][aria-label="{page_name}"]')

        if await page_element.count() == 0:
            raise RuntimeError(f"Dashboard page tab not found: {page_name}")

        await page_element.first.click()
        await wait_for_dashboard(page)

        selected_page = page.locator('[role="tab"][aria-label$=" Selected"]')

        if await selected_page.count() == 0:
            raise RuntimeError(
                f"Could not verify selected page after navigating to: {page_name}"
            )

        selected_label = await selected_page.first.get_attribute("aria-label")
        expected_label = f"{page_name} Selected"

        if selected_label != expected_label:
            raise RuntimeError(
                f"Page navigation verification failed. "
                f"Expected: {expected_label}, "
                f"Actual: {selected_label}"
            )

        logger.info(f"Successfully navigated to page: {page_name}")

    except Exception as exc:
        if page.is_closed():
            logger.error(
                f"Browser target crashed during page navigation to '{page_name}': {exc}"
            )
            raise RuntimeError(
                f"Browser crashed while attempting to load page: {page_name}"
            ) from exc
        raise


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