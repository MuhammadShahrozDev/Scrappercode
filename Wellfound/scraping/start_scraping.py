import os
import random

from browser import start_browser
from roles import (
    load_roles,
    build_role_tree,
    get_scrape_order,
)
from storage import (
    load_seen_job_ids,
    load_completed_roles,
    mark_role_complete,
    reset_run_state,
)
from role_selector import select_role
from role_scraper import scrape_role


DAYS = int(
    os.getenv(
        "WELLFOUND_DAYS",
        "3"
    )
)

TARGET_NEW = int(
    os.getenv(
        "SMART_SCRAPER_TARGET",
        "5"
    )
)

WANTED = {
    role.strip()
    for role in os.getenv(
        "WELLFOUND_ROLES",
        "Machine Learning Engineer,Product Manager"
    ).split(",")
    if role.strip()
}


def main():
    # Critical: remove repository/stale artifacts before each acquisition run.
    reset_run_state()

    seen_job_ids = load_seen_job_ids()
    completed_roles = load_completed_roles()

    print(
        f"Fresh run starts with "
        f"{len(seen_job_ids)} jobs."
    )
    print(
        f"Target new jobs: {TARGET_NEW}"
    )
    print(
        f"Freshness window: {DAYS} day(s)"
    )

    playwright, context, page = start_browser()

    total_saved = 0

    try:
        page.goto(
            "https://wellfound.com/jobs/home",
            wait_until="domcontentloaded",
            timeout=45000,
        )

        page.wait_for_timeout(2000)

        current_url = page.url.lower()

        print(f"Current URL: {page.url}")

        if (
            "login" in current_url
            or "signin" in current_url
        ):
            raise RuntimeError(
                "Wellfound saved session is expired "
                "or invalid."
            )

        print(
            "[*] Wellfound authenticated session active."
        )

        page.goto(
            "https://wellfound.com/jobs",
            wait_until="domcontentloaded",
            timeout=45000,
        )

        page.wait_for_load_state("load")
        page.wait_for_timeout(
            random.uniform(1500, 2500)
        )

        roles = load_roles()
        tree = build_role_tree(roles)
        scrape_order = get_scrape_order(tree)

        scrape_order = [
            role
            for role in scrape_order
            if role["title"] in WANTED
        ]

        print(
            f"Scraping {len(scrape_order)} roles."
        )

        for index, role in enumerate(
            scrape_order,
            start=1,
        ):
            if total_saved >= TARGET_NEW:
                break

            if str(role["id"]) in completed_roles:
                continue

            print(
                f"\n===== "
                f"[{index}/{len(scrape_order)}] "
                f"{role['title']} ====="
            )

            try:
                search_results = select_role(
                    page,
                    role["title"],
                )

                saved = scrape_role(
                    page,
                    role,
                    seen_job_ids,
                    search_results,
                    DAYS,
                    max_new_jobs=(
                        TARGET_NEW - total_saved
                    ),
                )

                total_saved += saved

                mark_role_complete(
                    role["id"]
                )

                print(
                    f"Run total: "
                    f"{total_saved}/{TARGET_NEW}"
                )

            except Exception as exc:
                print(
                    f"[WARN] Role '{role['title']}' failed: "
                    f"{exc}"
                )
                continue

        if total_saved <= 0:
            raise RuntimeError(
                "Wellfound returned 0 fresh jobs. "
                "No stale data will be processed."
            )

        print(
            f"Wellfound fresh acquisition complete: "
            f"{total_saved} job(s)."
        )

    finally:
        context.close()
        playwright.stop()


if __name__ == "__main__":
    main()
