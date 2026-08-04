"""
browser.py

Responsible for:
1. Finding all Edge profiles
2. Launching an Edge profile
3. Validating whether the profile has Power BI access
4. Returning the first working profile
"""
from playwright.async_api import async_playwright

from utils.config import (
    BROWSER_CHANNEL,
    HEADLESS,
    PAGE_TIMEOUT,
    EDGE_USER_DATA,
    RENDER_WAIT,
    PROFILE_DIR,
)


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

        # Allow any remaining animations or visual rendering to complete.
        await page.wait_for_timeout(RENDER_WAIT)

    except Exception as e:
        print(f"Error while waiting for dashboard to render: {e}")
        raise


async def launch_browser(dashboard_url):
    """
    Automatically find a working Microsoft Edge Profile and open the powerbi dashbord

    Parameters
    ----------
    dashboard_url : str
        URL of the Power BI dashboard.

    Returns
    -------
    tuple
        (playwright, context, page)
    """

    profiles = find_edge_profiles()
    if not profiles:
        raise RuntimeError("No Edge profiles found.")

    print("\nDetected Edge profiles:")

    for p in profiles:
        print(f"  - '{p.name}'")
    print(f"\nFound {len(profiles)} Edge profile(s).\n")

    # Tries default first, then the remaining profiles.
    ordered_profiles = sorted(
        profiles,
        key=lambda p: p.name != "Default"
    )

    for profile in ordered_profiles:

        print(f"Trying profile: {profile.name}")

        playwright = None
        context = None

        try:
            playwright, context, page = await launch_profile(profile)

            await page.goto(
                dashboard_url,
                wait_until="domcontentloaded",
                timeout=PAGE_TIMEOUT,
            )

            await wait_for_dashboard(page)

            print(f"Using profile: {profile.name}")

            return playwright, context, page

        except Exception as e:
            print(f"✗ {profile.name} failed: {e}")

            try:
                if context:
                    await context.close()
                if playwright:
                    await playwright.stop()
            except Exception as cleanup_error:
                print(f"Error cleaning up profile '{profile.name}': {cleanup_error}")

    raise RuntimeError(
        "No Edge profile could open the dashboard."
    )