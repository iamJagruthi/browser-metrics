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

# EXPECTED_DOMAIN = "@cswg.com"
# PROFILE_SELECTOR = "[data-testid='user-menu-button']" #CHANGE NEEDED HERE
# EMAIL_SELECTOR = ".user-email"


def find_edge_profiles():
    """
    Finds all available Microsoft Edge user profiles.

    Returns
    -------
    list[Path]
        Sorted list of Edge profile directories.
    """

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

# async def get_logged_in_email(page):
#     """
#     Opens the Power BI profile popup
#     and returns the signed-in email.

#     Returns
#     -------
#     str
#         Logged-in Microsoft email.
#     """
#     await page.pause()
#     # Open profile popup
#     await page.locator(PROFILE_SELECTOR).click()

#     # Wait until the email is visible
#     await page.locator(
#         EMAIL_SELECTOR
#     ).wait_for(state="visible")

#     # Read email
#     email = await page.locator(
#         EMAIL_SELECTOR
#     ).inner_text()

#     # Close popup
#     # await page.keyboard.press("Escape")

#     return email.strip()
async def wait_for_dashboard(page):
    """
    Wait until the Power BI dashboard is fully rendered.

    Parameters
    ----------
    page : Page
        Playwright page instance.
    """

    await page.wait_for_selector(
        ".visualContainer",
        timeout=PAGE_TIMEOUT,
    )

    # Allow any remaining animations or visual rendering to complete.
    await page.wait_for_timeout(RENDER_WAIT)

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

    #tries default first then the remianing profiles
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

            if context:
                await context.close()
            if playwright:
                await playwright.stop()

    raise RuntimeError(
        "No Edge profile could open the dashboard."
    )

# async def validate_profile(page, dashboard_url):
#     """
#     Checks whether the current profile
#     can successfully open the Power BI dashboard.

#     Returns
#     -------
#     tuple[bool, str | None]
#         (is_valid_profile, logged_in_email)
#     """

#     try:
#         print("step1: Starting goto")
#         # Open dashboard
#         await page.goto(
#             dashboard_url,
#             wait_until="domcontentloaded",
#             timeout=PAGE_TIMEOUT,
#         )
#         print("step2: Goto completed")
#         # Wait until the page is fully rendered
#         await page.wait_for_load_state("domcontentloaded")
#         await page.wait_for_timeout(5000)
#         print("Step3: Wait Completed")
#         # --------------------------------------------------
#         # Check if redirected to Microsoft login
#         # --------------------------------------------------

#         url = page.url.lower()

#         if "login.microsoftonline.com" in url:
#             print("Profile redirected to Microsoft login.")
#             return False, None

#         if "signin" in url:
#             print("Profile requires sign in.")
#             return False, None

#         # --------------------------------------------------
#         # Check for access issues
#         # --------------------------------------------------

#         content = (await page.content()).lower()

#         blocked_text = [
#             "request access",
#             "access denied",
#             "you need permission",
#         ]

#         for text in blocked_text:
#             if text in content:
#                 print(f"Profile rejected: '{text}' found on page.")
#                 return False, None

#         # --------------------------------------------------
#         # Verify logged-in Microsoft account
#         # --------------------------------------------------

#         # email = await get_logged_in_email(page)

#         # print(f"Detected account: {email}")

#         # if not email.lower().endswith(EXPECTED_DOMAIN.lower()):
#         #     print(f"Rejected account: {email}")
#         #     return False, None
#         email = await get_logged_in_email(page)

#         print("=" * 50)
#         print(f"Detected account: '{email}'")
#         print(f"Expected domain: '{EXPECTED_DOMAIN}'")
#         print("=" * 50)

#         return True, email

#         # --------------------------------------------------
#         # Profile is valid
#         # --------------------------------------------------

#         return True, email

#     except Exception as e:
#         print(f"Profile validation failed: {e}")
#         return False, None

# async def launch_browser(dashboard_url):
#     """
#     Finds the first Microsoft Edge profile
#     that has access to the Power BI dashboard.

#     Parameters
#     ----------
#     dashboard_url : str

#     Returns
#     -------
#     playwright
#     context
#     page
#     """

#     profiles = find_edge_profiles()

#     print(f"\nFound {len(profiles)} Edge profiles.\n")

#     for profile in profiles:

#         print(f"Trying profile: {profile.name}")

#         playwright, context, page = await launch_profile(profile)

#         valid, email = await validate_profile(
#             page,
#             dashboard_url
#         )

#         if valid:

#             print(
#                 f"\nUsing profile: "
#                 f"{profile.name} ({email})\n"
#             )

#             return playwright, context, page

#         print("Profile rejected.\n")

#         await context.close()
#         await playwright.stop()

#     raise RuntimeError(
#         "No Microsoft Edge profile with "
#         "Power BI access was found."
#     )