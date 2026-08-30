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


async def wait_for_dashboard(page):
    """
    Wait until the Power BI dashboard is fully rendered.

    Parameters
    ----------
    page : Page
        Playwright page instance.
    """

    try:
        await page.wait_for_selector(
            ".visualContainer",
            timeout=PAGE_TIMEOUT,
        )

        # Power BI often creates the visual containers before their data is
        # painted.  A fixed sleep captured loading placeholders and led to
        # duplicate/partial visual extraction.  Require a quiet, non-loading
        # interval before the screenshot and DOM collection begin.
        # Jagruthi: wait until loading placeholders clear, not only DOM text stability.
        stable_samples = 0
        previous_signature = None
        for _ in range(max(6, RENDER_WAIT // 500)):
            signature = await page.evaluate(
                """() => [...document.querySelectorAll('.visualContainer')]
                    .map(node => (node.innerText || '').trim())
                    .filter(Boolean)
                    .join('\\n')
                    .slice(0, 50000)"""
            )
            loading_count = await page.locator(
                ".loading, [aria-label*='loading' i], [aria-busy='true']"
            ).count()
            has_loading_placeholder = await page.evaluate(
                """() => [...document.querySelectorAll('.visualContainer')].some(node =>
                    /\\bvisuals?\\s+are\\s+loading\\b/i.test((node.innerText || '').trim())
                    || /\\bvisuals?\\s+are\\s+loading\\b/i.test(
                        (node.querySelector('.visualTitle, [class*="visualTitle"]')?.innerText || '').trim()
                    ))"""
            )
            if (
                signature == previous_signature
                and loading_count == 0
                and not has_loading_placeholder
            ):
                stable_samples += 1
                if stable_samples >= 3:
                    logger.info("Dashboard visuals are ready for extraction")
                    return
            else:
                stable_samples = 0
            previous_signature = signature
            await page.wait_for_timeout(500)

        logger.warning("Dashboard did not reach a fully stable state; continuing after timeout")

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
