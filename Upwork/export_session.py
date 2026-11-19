"""
Run this ONCE on your own computer to create the UPWORK_STORAGE_STATE_B64 GitHub secret.

    pip install patchright && patchright install chrome
    python export_session.py

A Chrome window opens: log in to Upwork normally (solve any check yourself), wait until you see
your job feed, then press Enter in the terminal. The base64 text is saved to
upwork_storage_state.b64.txt and printed. Paste it into GitHub:
  Repo -> Settings -> Secrets and variables -> Actions -> New repository secret
  Name: UPWORK_STORAGE_STATE_B64
"""

import base64
import json
from pathlib import Path

from patchright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "upwork_storage_state.b64.txt"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False)
        context = browser.new_context(no_viewport=True)
        page = context.new_page()
        page.goto("https://www.upwork.com/ab/account-security/login")
        input("Log in to Upwork in the opened window, then press Enter here... ")

        state = context.storage_state()
        browser.close()

    encoded = base64.b64encode(json.dumps(state).encode("utf-8")).decode("ascii")
    OUT.write_text(encoded, encoding="utf-8")

    print(f"\nSaved {len(encoded)} characters to {OUT}")
    if len(encoded) > 48000:
        print("WARNING: GitHub secrets are limited to 48 KB; this is too large. "
              "Log out of unrelated tabs/sites and export again.")
    print("\nUPWORK_STORAGE_STATE_B64 =\n")
    print(encoded)


if __name__ == "__main__":
    main()
