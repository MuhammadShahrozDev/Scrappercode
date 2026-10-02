"""
Get company website + LinkedIn URL from Wellfound company pages.

For each unique company_slug found in jobs_*.json:

1. Opens https://wellfound.com/company/{company_slug}
2. Extracts the company website
3. Finds all Wellfound social-link buttons
4. Clicks each social button
5. Captures the popup/new tab
6. Checks whether the popup URL is LinkedIn
7. Saves the LinkedIn URL if found
8. Saves results to jobs/company_websites.json
9. Creates updated job files in jobs/jobs_with_website/

Uses the existing logged-in browser from browser.py.
"""

import json
import random
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Set, Any

# browser.py lives in scraping/, alongside the other
# Playwright/session-handling code, since it's shared
# infrastructure rather than a processing step.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraping"))
from browser import start_browser


# ============================================================
# CONFIG
# ============================================================

# Project root (this file now lives one level down, in
# scraping/ or processing/), so go up an extra level.
BASE_DIR = Path(__file__).resolve().parent.parent

JOBS_DIR = BASE_DIR / "jobs"

INPUT_PATTERN = "jobs_*.json"

CACHE_DIR = BASE_DIR / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

# Resume cache: not part of the final data output, so it lives
# outside jobs/ and survives the end-of-pipeline data cleanup.
OUTPUT_FILE = CACHE_DIR / "company_websites.json"

OUTPUT_JOB_DIR = BASE_DIR / JOBS_DIR / "jobs_with_website"


# ============================================================
# LOAD JOB FILES
# ============================================================

def load_job_files() -> list[Path]:

    return sorted(
        JOBS_DIR.glob(INPUT_PATTERN)
    )


# ============================================================
# UPDATE JOB FILES
# ============================================================

def update_job_files(
    mapping: Dict[str, Dict[str, Optional[str]]],
    job_files: list[Path],
) -> None:

    OUTPUT_JOB_DIR.mkdir(exist_ok=True)

    for job_file in job_files:

        try:

            with open(
                job_file,
                "r",
                encoding="utf-8",
            ) as f:

                jobs = json.load(f)

        except Exception as exc:

            print(
                f"Skipping update for {job_file.name}: "
                f"failed to read JSON ({exc})"
            )

            continue

        if not isinstance(jobs, list):

            print(
                f"Skipping {job_file.name}: "
                f"expected a JSON array"
            )

            continue

        updated_count = 0

        for job in jobs:

            if not isinstance(job, dict):
                continue

            company_slug = job.get("company_slug")

            if not company_slug:
                continue

            if not isinstance(company_slug, str):
                continue

            company_slug = company_slug.strip()

            company_data = mapping.get(
                company_slug
            )

            if not company_data:
                continue

            website = company_data.get(
                "website"
            )

            linkedin = company_data.get(
                "linkedin"
            )

            # ------------------------------------------------
            # COMPANY WEBSITE
            # ------------------------------------------------

            if website is not None or "company_website" not in job:

                job["company_website"] = website

            # ------------------------------------------------
            # COMPANY LINKEDIN
            # ------------------------------------------------

            if linkedin is not None or "company_linkedin" not in job:

                job["company_linkedin"] = linkedin

            updated_count += 1

        output_file = (
            OUTPUT_JOB_DIR /
            job_file.name
        )

        try:

            with open(
                output_file,
                "w",
                encoding="utf-8",
            ) as f:

                json.dump(
                    jobs,
                    f,
                    indent=2,
                    ensure_ascii=False,
                )

        except Exception as exc:

            print(
                f"Failed to write updated jobs "
                f"for {job_file.name}: {exc}"
            )

            continue

        print(
            f"Updated {job_file.name}: "
            f"wrote {len(jobs)} jobs "
            f"({updated_count} jobs processed)"
        )


# ============================================================
# EXTRACT COMPANY SLUGS
# ============================================================

def extract_company_slugs(
    job_files: list[Path],
) -> Set[str]:

    slugs: Set[str] = set()

    for job_file in job_files:

        try:

            with open(
                job_file,
                "r",
                encoding="utf-8",
            ) as f:

                jobs = json.load(f)

        except Exception as exc:

            print(
                f"Skipping {job_file.name}: "
                f"failed to read JSON ({exc})"
            )

            continue

        if not isinstance(jobs, list):

            print(
                f"Skipping {job_file.name}: "
                f"expected a JSON array"
            )

            continue

        for job in jobs:

            if not isinstance(job, dict):
                continue

            company_slug = job.get(
                "company_slug"
            )

            if (
                company_slug
                and isinstance(company_slug, str)
            ):

                slugs.add(
                    company_slug.strip()
                )

    return slugs


# ============================================================
# LOAD EXISTING MAPPING
# ============================================================

def load_existing_mapping() -> Dict[str, Dict[str, Optional[str]]]:

    if not OUTPUT_FILE.exists():

        return {}

    try:

        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8",
        ) as f:

            data = json.load(f)

        if not isinstance(data, dict):

            return {}

        normalized = {}

        for slug, value in data.items():

            if not isinstance(slug, str):
                continue

            # ------------------------------------------------
            # New format
            #
            # "coupang": {
            #     "website": "...",
            #     "linkedin": "..."
            # }
            # ------------------------------------------------

            if isinstance(value, dict):

                normalized[slug] = {
                    "website": value.get(
                        "website"
                    ),
                    "linkedin": value.get(
                        "linkedin"
                    ),
                }

            # ------------------------------------------------
            # Old format
            #
            # "coupang": "https://..."
            #
            # Keep compatibility with your existing file.
            # ------------------------------------------------

            elif isinstance(value, str):

                normalized[slug] = {
                    "website": value,
                    "linkedin": None,
                }

            # ------------------------------------------------
            # Old format with null
            # ------------------------------------------------

            elif value is None:

                normalized[slug] = {
                    "website": None,
                    "linkedin": None,
                }

        return normalized

    except Exception as exc:

        print(
            f"Could not load existing mapping "
            f"from {OUTPUT_FILE}: {exc}"
        )

        return {}


# ============================================================
# SAVE MAPPING
# ============================================================

def save_mapping(
    mapping: Dict[str, Dict[str, Optional[str]]]
) -> None:

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            mapping,
            f,
            indent=2,
            ensure_ascii=False,
        )


# ============================================================
# RANDOM DELAY
# ============================================================

def random_delay(
    min_seconds: float = 1.0,
    max_seconds: float = 2.5,
) -> None:

    time.sleep(
        random.uniform(
            min_seconds,
            max_seconds,
        )
    )


# ============================================================
# EXTRACT WEBSITE
# ============================================================

def extract_website_from_page(
    page,
) -> Optional[str]:

    script = """
    (function() {

        const websiteLabel =
            Array.from(
                document.querySelectorAll('dl dd')
            ).find(
                el =>
                    el.textContent
                        .trim()
                        .toLowerCase() === 'website'
            );

        if (
            !websiteLabel ||
            !websiteLabel.nextElementSibling
        ) {
            return null;
        }

        const detail =
            websiteLabel.nextElementSibling;

        const candidate =
            detail.querySelector(
                'button[class*="websiteLink"], ' +
                'a[class*="websiteLink"], ' +
                'a, ' +
                'button'
            );

        if (candidate) {

            const href =
                candidate.getAttribute('href');

            const text =
                candidate.textContent?.trim();

            return href
                ? href.trim()
                : text || null;
        }

        return (
            detail.textContent?.trim()
            || null
        );

    })();
    """

    try:

        return page.evaluate(
            script
        )

    except Exception as exc:

        print(
            f"  Failed to extract website: {exc}"
        )

        return None


# ============================================================
# EXTRACT LINKEDIN
# ============================================================

def extract_linkedin_from_page(
    page,
) -> Optional[str]:

    """
    Find all Wellfound social-link buttons.

    Does NOT assume LinkedIn is button #3,
    #4, or any specific position.

    Each button is clicked.

    If the button opens a new tab/window,
    the popup URL is checked.

    The first URL containing linkedin.com
    is returned.
    """

    try:

        social_buttons = page.locator(
            'button[class*="socialLink"]'
        )

        count = social_buttons.count()

        print(
            f"  Found {count} social buttons"
        )

        if count == 0:

            print(
                "  No social buttons found"
            )

            return None

        for i in range(count):

            button = social_buttons.nth(i)

            print(
                f"  Checking social button "
                f"{i + 1}/{count}"
            )

            try:

                # ------------------------------------------------
                # Make sure button is visible
                # ------------------------------------------------

                if not button.is_visible():

                    print(
                        "    Button not visible"
                    )

                    continue

                # ------------------------------------------------
                # Scroll it into view
                # ------------------------------------------------

                button.scroll_into_view_if_needed()

                page.wait_for_timeout(
                    random.randint(200, 500)
                )

                # ------------------------------------------------
                # Click and capture popup
                # ------------------------------------------------

                popup = None

                try:

                    with page.expect_popup(
                        timeout=5000
                    ) as popup_info:

                        button.click(
                            timeout=5000
                        )

                    popup = popup_info.value

                except Exception as exc:

                    print(
                        f"    No popup detected: "
                        f"{exc}"
                    )

                    continue

                # ------------------------------------------------
                # Wait for popup navigation
                # ------------------------------------------------

                try:

                    popup.wait_for_load_state(
                        "domcontentloaded",
                        timeout=10000,
                    )

                except Exception:

                    pass

                # Small additional wait in case
                # redirect happens after DOM load.

                popup.wait_for_timeout(
                    1000
                )

                popup_url = popup.url

                print(
                    f"    Popup URL: {popup_url}"
                )

                # ------------------------------------------------
                # Check LinkedIn
                # ------------------------------------------------

                if (
                    popup_url
                    and
                    "linkedin.com"
                    in popup_url.lower()
                ):

                    print(
                        f"    LINKEDIN FOUND: "
                        f"{popup_url}"
                    )

                    try:
                        popup.close()
                    except Exception:
                        pass

                    return popup_url

                # ------------------------------------------------
                # Not LinkedIn
                # ------------------------------------------------

                print(
                    "    Not LinkedIn"
                )

                try:
                    popup.close()
                except Exception:
                    pass

            except Exception as exc:

                print(
                    f"    Failed checking "
                    f"button {i + 1}: {exc}"
                )

                continue

        print(
            "  LinkedIn button not found"
        )

        return None

    except Exception as exc:

        print(
            f"  Failed to inspect social "
            f"buttons: {exc}"
        )

        return None


# ============================================================
# FETCH COMPANY DATA
# ============================================================

def fetch_company_data(
    page,
    company_slug: str,
) -> Dict[str, Optional[str]]:

    company_url = (
        f"https://wellfound.com/company/"
        f"{company_slug}"
    )

    print()
    print(
        f"Visiting {company_url}"
    )

    # --------------------------------------------------------
    # Open company page
    # --------------------------------------------------------

    try:

        page.goto(
            company_url,
            wait_until="domcontentloaded",
            timeout=30000,
        )

    except Exception as exc:

        print(
            f"  Failed to load "
            f"{company_slug}: {exc}"
        )

        return {
            "website": None,
            "linkedin": None,
        }

    # --------------------------------------------------------
    # Handle login redirect
    # --------------------------------------------------------

    if "login" in page.url:

        print(
            "  Redirected to login page."
        )

        print(
            "  Waiting for manual login..."
        )

        try:

            page.wait_for_url(
                lambda url:
                    "login" not in url,
                timeout=300000,
            )

        except Exception as exc:

            print(
                f"  Login wait failed: {exc}"
            )

            return {
                "website": None,
                "linkedin": None,
            }

        # Re-open company page after login.

        try:

            page.goto(
                company_url,
                wait_until="domcontentloaded",
                timeout=30000,
            )

        except Exception as exc:

            print(
                f"  Failed to reopen "
                f"{company_slug}: {exc}"
            )

            return {
                "website": None,
                "linkedin": None,
            }

    # --------------------------------------------------------
    # Give page time to render
    # --------------------------------------------------------

    try:

        page.wait_for_load_state(
            "load",
            timeout=15000,
        )

    except Exception:

        pass

    page.wait_for_timeout(
        1500
    )

    random_delay(
        0.8,
        1.8,
    )

    # ========================================================
    # WEBSITE
    # ========================================================

    website = extract_website_from_page(
        page
    )

    if website:

        website = website.strip()

        if website.endswith("/"):

            website = website[:-1]

    print(
        f"  Website: {website}"
    )

    # ========================================================
    # LINKEDIN
    # ========================================================

    linkedin = extract_linkedin_from_page(
        page
    )

    if linkedin:

        linkedin = linkedin.strip()

        if linkedin.endswith("/"):

            linkedin = linkedin[:-1]

    print(
        f"  LinkedIn: {linkedin}"
    )

    # ========================================================
    # RESULT
    # ========================================================

    return {
        "website": website,
        "linkedin": linkedin,
    }


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    # --------------------------------------------------------
    # Find job files
    # --------------------------------------------------------

    job_files = load_job_files()

    if not job_files:

        print(
            f"No job files found in "
            f"{JOBS_DIR} matching "
            f"{INPUT_PATTERN}"
        )

        return

    print(
        f"Found {len(job_files)} job files."
    )

    # --------------------------------------------------------
    # Extract unique company slugs
    # --------------------------------------------------------

    slugs = extract_company_slugs(
        job_files
    )

    if not slugs:

        print(
            "No company_slug values found "
            "in job files."
        )

        return

    print(
        f"Found {len(slugs)} unique "
        f"company slugs."
    )

    # --------------------------------------------------------
    # Load existing results
    # --------------------------------------------------------

    existing = load_existing_mapping()

    # --------------------------------------------------------
    # Determine which companies need processing
    #
    # We process a company again if:
    #
    #   - it doesn't exist
    #   - website is missing
    #   - LinkedIn is missing
    #
    # This is important because your old company_websites.json
    # only contained website URLs.
    # --------------------------------------------------------

    pending = []

    for slug in sorted(slugs):

        existing_data = existing.get(
            slug
        )

        if not existing_data:

            pending.append(slug)
            continue

        website = existing_data.get(
            "website"
        )

        linkedin = existing_data.get(
            "linkedin"
        )

        # If either is missing, revisit company.

        if not website or not linkedin:

            pending.append(slug)

    # --------------------------------------------------------
    # Nothing to do
    # --------------------------------------------------------

    if not pending:

        print(
            f"All {len(slugs)} companies "
            f"already have website + LinkedIn."
        )

        # Still update job files.

        update_job_files(
            existing,
            job_files,
        )

        return

    print(
        f"{len(pending)} companies need "
        f"to be visited."
    )

    # --------------------------------------------------------
    # Start your existing logged-in browser
    # --------------------------------------------------------

    playwright, context, page = start_browser()

    try:

        # ----------------------------------------------------
        # Make sure logged in
        # ----------------------------------------------------

        print(
            "Opening Wellfound login page..."
        )

        page.goto(
            "https://wellfound.com/login",
            wait_until="domcontentloaded",
        )

        if "login" in page.url:

            print(
                "Please log in to Wellfound "
                "in the browser window."
            )

            page.wait_for_url(
                lambda url:
                    "login" not in url,
                timeout=300000,
            )

        print(
            "Logged in."
        )

        # ----------------------------------------------------
        # Process companies
        # ----------------------------------------------------

        total = len(pending)

        for index, company_slug in enumerate(
            pending,
            1,
        ):

            print()
            print(
                "=" * 60
            )

            print(
                f"Company {index}/{total}: "
                f"{company_slug}"
            )

            print(
                "=" * 60
            )

            # -----------------------------------------------
            # Visit company and get website + LinkedIn
            # -----------------------------------------------

            company_data = fetch_company_data(
                page,
                company_slug,
            )

            # -----------------------------------------------
            # Save immediately
            #
            # This means if the script stops halfway through,
            # the companies already processed remain saved.
            # -----------------------------------------------

            existing[
                company_slug
            ] = company_data

            save_mapping(
                existing
            )

            print(
                f"Saved {company_slug}"
            )

            random_delay(
                1.0,
                2.0,
            )

        # ----------------------------------------------------
        # Update all job files
        # ----------------------------------------------------

        print()
        print(
            "Updating job files..."
        )

        update_job_files(
            existing,
            job_files,
        )

        print()
        print(
            "Done."
        )

    finally:

        print()
        print(
            f"Saved results to "
            f"{OUTPUT_FILE}"
        )

        print(
            f"Updated job files in "
            f"{OUTPUT_JOB_DIR}"
        )

        context.close()

        playwright.stop()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()