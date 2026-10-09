import base64
import json
import os
from pathlib import Path

from patchright.sync_api import sync_playwright


BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / ".cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = CACHE_DIR / "wellfound_storage_state.json"


def restore_storage_state():
    encoded = os.getenv(
        "WELLFOUND_STORAGE_STATE_B64",
        ""
    ).strip()

    if not encoded:
        raise RuntimeError(
            "WELLFOUND_STORAGE_STATE_B64 secret is missing"
        )

    decoded = base64.b64decode(
        encoded
    ).decode("utf-8")

    state = json.loads(
        decoded
    )

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            state,
            f,
            ensure_ascii=False
        )

    print(
        "[*] Wellfound saved session restored."
    )

    return str(
        STATE_FILE
    )


def start_browser():
    playwright = sync_playwright().start()

    browser = playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ],
    )

    storage_state = restore_storage_state()

    context = browser.new_context(
        storage_state=storage_state,
        viewport={
            "width": 1440,
            "height": 1000,
        },
    )

    page = context.new_page()

    return playwright, context, page