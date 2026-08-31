"""
browser.py

Responsible for:
1. Finding all Edge profiles
2. Launching an Edge profile
3. Validating whether the profile has Power BI access
4. Returning the first working profile

Jagruthi — features:
- Dashboard stability wait until loading placeholders clear
- Safer signature polling via page.evaluate (not evaluate_all)
"""
import logging

from playwright.async_api import async_playwright

from utils.config import (
    BROWSER_CHANNEL,
    HEADLESS,
    PAGE_TIMEOUT,
    EDGE_USER_DATA,
    RENDER_WAIT,
    PROFILE_DIR,
)


# Power BI paints empty visual shells first. Wait on both class and custom tags.
_VISUAL_SELECTOR = ".visualContainer, [data-visual-container], visual-container"

# Snapshot of how many visuals exist and whether they still look like a loading screen.
_DASHBOARD_SNAPSHOT_JS = """() => {
    const nodes = [...document.querySelectorAll(
        '.visualContainer, [data-visual-container], visual-container'
    )];
    const texts = nodes.map(node => (node.innerText || '').trim());
    const joined = texts.join('\\n');
    const loadingUi = document.querySelectorAll(
        ".loading, [aria-busy='true'], [aria-label*='loading' i], [class*='spinner' i], [class*='busySpinner' i]"
    ).length;
    const placeholder = nodes.some(node => {
        const text = (node.innerText || '').trim();
        return /\\bvisuals?\\s+are\\s+loading\\b/i.test(text)
            || /\\bloading\\.\\.\\./i.test(text);
    });
    return {
        count: nodes.length,
        text: joined.slice(0, 50000),
        loadingUi,
        placeholder,
    };
}"""

# Wait until loading placeholders are gone and at least one visual container
# is actually visible. Power BI often renders empty visual-container shells
# first, so waiting for the *first* matching element to be visible can time
# out even when 62 containers are present.
_DASHBOARD_READY_JS = """() => {
    // 1. Check for VISIBLE loading spinners only (ignore hidden background spinners)
    const isVisible = el => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        return style.display !== 'none' && 
               style.visibility !== 'hidden' && 
               style.opacity !== '0' &&
               (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
    };

    const activeSpinners = [...document.querySelectorAll(
        ".loading, [aria-busy='true'], [class*='spinner' i], [class*='busySpinner' i]"
    )].filter(isVisible);

    if (activeSpinners.length > 0) return false;

    // 2. Check for visual containers
    const nodes = [...document.querySelectorAll(
        '.visualContainer, [data-visual-container], visual-container'
    )];
    
    if (nodes.length === 0) return false;

    // 3. Ensure no container displays active loading text
    const hasLoadingPlaceholder = nodes.some(node => {
        if (!isVisible(node)) return false;
        const text = (node.innerText || '').trim();
        return /\\bvisuals?\\s+are\\s+loading\\b/i.test(text) || /\\bloading\\.\\.\\./i.test(text);
    });

    if (hasLoadingPlaceholder) return false;

    // 4. Return true if at least one container is rendered & visible
    return nodes.some(isVisible);
}"""


logger = logging.getLogger(__name__)


def find_edge_profiles():
    """
    Finds all available Microsoft Edge user profiles.

    Returns
    -------
    list[Path]
        Sorted list of Edge profile directories.
    """

    try:
        if not EDGE_USER_DATA.exists():
            raise FileNotFoundError(
                "Microsoft Edge User Data folder not found."
            )

        profiles = []

        for folder in EDGE_USER_DATA.iterdir():

            if (
                folder.is_dir()
                and (
                    folder.name == "Default"
                    or folder.name.startswith("Profile")
                )
            ):
                profiles.append(folder)

        return sorted(profiles)

    except Exception as e:
        print(f"Error while finding Edge profiles: {e}")
        raise

# hi
async def launch_profile(profile_path):
    """
    Launch a Microsoft Edge browser using the given profile.

    Parameters
    ----------
    profile_path : Path
        Path to the Edge user profile.

    Returns
    -------
    tuple
        (playwright, context, page)
    """

    try:
        playwright = await async_playwright().start()

        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            channel=BROWSER_CHANNEL,
            headless=HEADLESS,
            slow_mo=300,
            no_viewport=True,
            args=[
                "--start-maximized",
            ],
        )

        page = (
            context.pages[0]
            if context.pages
            else await context.new_page()
        )

        return playwright, context, page

    except Exception as e:
        print(f"Error launching profile '{profile_path}': {e}")
        raise


async def capture_dashboard_snapshot(page) -> dict:
    """How many visual boxes exist and what text they currently show."""
    snapshot = await page.evaluate(_DASHBOARD_SNAPSHOT_JS)
    return snapshot or {"count": 0, "text": "", "loadingUi": 0, "placeholder": False}


def _snapshot_signature(snapshot: dict) -> tuple:
    return (int(snapshot.get("count") or 0), snapshot.get("text") or "")


def _snapshot_is_busy(snapshot: dict) -> bool:
    return bool(
        snapshot.get("loadingUi")
        or snapshot.get("placeholder")
        or int(snapshot.get("count") or 0) < 1
    )


async def wait_for_dashboard(page, *, previous_snapshot: dict | None = None):
    """
    Wait until visual containers exist, stop appearing, and stop showing
    loading placeholders.

    Pass previous_snapshot (from capture_dashboard_snapshot) after a filter
    click. We then wait until visuals change or a loading state appears,
    so we do not treat the old stable screen as "already done".
    """

    try:
        await page.wait_for_function(_DASHBOARD_READY_JS, timeout=PAGE_TIMEOUT)

        # Let Power BI finish creating the rest of the visual shells.
        await page.wait_for_timeout(750)

        poll_ms = 750
        stable_needed = 4
        max_wait_ms = max(int(RENDER_WAIT), 15000)
        max_loops = max(8, max_wait_ms // poll_ms)

        if previous_snapshot:
            before_sig = _snapshot_signature(previous_snapshot)
            changed = False
            for _ in range(max(8, 20000 // poll_ms)):
                current = await capture_dashboard_snapshot(page)
                if _snapshot_is_busy(current) or _snapshot_signature(current) != before_sig:
                    changed = True
                    logger.info(
                        "Dashboard refresh detected | visuals=%d | loading=%s",
                        current.get("count"),
                        bool(current.get("loadingUi") or current.get("placeholder")),
                    )
                    break
                await page.wait_for_timeout(poll_ms)
            if not changed:
                logger.info(
                    "No visual change yet after filter; waiting for a quiet render anyway"
                )

        stable_samples = 0
        previous_signature = None
        previous_count = None

        for _ in range(max_loops):
            snapshot = await capture_dashboard_snapshot(page)
            signature = _snapshot_signature(snapshot)
            count = snapshot.get("count") or 0

            count_settled = previous_count is not None and count == previous_count
            content_settled = previous_signature is not None and signature == previous_signature

            if (
                count >= 1
                and count_settled
                and content_settled
                and not _snapshot_is_busy(snapshot)
            ):
                stable_samples += 1
                if stable_samples >= stable_needed:
                    logger.info(
                        "Dashboard visuals are stable | containers=%d",
                        count,
                    )
                    return
            else:
                stable_samples = 0

            previous_signature = signature
            previous_count = count
            await page.wait_for_timeout(poll_ms)

        logger.warning(
            "Dashboard did not reach a fully stable state; continuing after timeout"
        )

    except Exception as e:
        print(f"Error while waiting for dashboard to render: {e}")
        raise


async def launch_browser():
    """
    Launch Microsoft Edge using the first available profile.

    Returns
    -------
    tuple
        (playwright, context, page)
    """

    profiles = find_edge_profiles()

    if not profiles:
        raise RuntimeError("No Edge profiles found.")

    print("\nDetected Edge profiles:")

    for profile in profiles:
        print(f"  - {profile.name}")

    print(f"\nFound {len(profiles)} Edge profile(s).\n")

    # Try Default profile first, then the remaining profiles.
    ordered_profiles = sorted(
        profiles,
        key=lambda profile: profile.name != "Default"
    )

    for profile in ordered_profiles:

        playwright = None
        context = None

        try:
            print(f"Trying profile: {profile.name}")

            playwright, context, page = await launch_profile(profile)

            print(f"Using profile: {profile.name}")

            return (
                playwright,
                context,
                page,
            )

        except Exception as error:

            print(
                f"✗ Failed to launch '{profile.name}': {error}"
            )

            try:
                if context:
                    await context.close()

                if playwright:
                    await playwright.stop()

            except Exception:
                pass

    raise RuntimeError(
        "Unable to launch Microsoft Edge using any available profile."
    )
