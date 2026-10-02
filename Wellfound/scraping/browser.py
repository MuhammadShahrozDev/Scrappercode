from patchright.sync_api import sync_playwright
from pathlib import Path


# Project root (this file now lives one level down, in
# scraping/ or processing/), so go up an extra level.
BASE_DIR = Path(__file__).resolve().parent.parent

USER_DATA_DIR = BASE_DIR / "wellfound_profile"


def start_browser():

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ],
    )

    context = browser.new_context(
        viewport=None,
        no_viewport=True,
    )

    page = context.new_page()

    return playwright, context, page