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
)
from role_selector import select_role
from role_scraper import scrape_role


# ============================================================
# Configuration
# ============================================================

days = 1

wanted = {
    "Machine Learning Engineer",
    "Product Manager",
}


# ============================================================
# Main
# ============================================================

def main():

    seen_job_ids = load_seen_job_ids()
    completed_roles = load_completed_roles()

    print(
        f"Already have {len(seen_job_ids)} jobs."
    )

    playwright, context, page = start_browser()

    try:

        # ====================================================
        # Open Wellfound using saved authenticated session
        # ====================================================

        page.goto(
            "https://wellfound.com/jobs/home",
            wait_until="domcontentloaded",
            timeout=45000,
        )

        page.wait_for_timeout(2000)

        current_url = page.url.lower()

        print(
            f"Current URL: {page.url}"
        )

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

        # ====================================================
        # Open jobs page
        # ====================================================

        page.goto(
            "https://wellfound.com/jobs",
            wait_until="domcontentloaded",
            timeout=45000,
        )

        page.wait_for_load_state(
            "load"
        )

        page.wait_for_timeout(
            random.uniform(
                1500,
                2500
            )
        )

        # ====================================================
        # Load roles
        # ====================================================

        roles = load_roles()

        tree = build_role_tree(
            roles
        )

        scrape_order = get_scrape_order(
            tree
        )

        # ====================================================
        # Only scrape wanted roles
        # ====================================================

        scrape_order = [
            role
            for role in scrape_order
            if role["title"] in wanted
        ]

        print(
            f"Scraping "
            f"{len(scrape_order)} roles.\n"
        )

        # ====================================================
        # Scrape roles
        # ====================================================

        for i, role in enumerate(
            scrape_order,
            start=1
        ):

            if str(
                role["id"]
            ) in completed_roles:

                print(
                    f"Skipping role: "
                    f"{role['title']}"
                )

                continue

            print(
                f"\n===== "
                f"[{i}/{len(scrape_order)}] "
                f"{role['title']} "
                f"====="
            )

            try:

                search_results = select_role(
                    page,
                    role["title"],
                )

                scrape_role(
                    page,
                    role,
                    seen_job_ids,
                    search_results,
                    days,
                )

                mark_role_complete(
                    role["id"]
                )

            except Exception as e:

                print(
                    f"Failed role "
                    f"'{role['title']}': "
                    f"{e}"
                )

    finally:

        context.close()
        playwright.stop()


if __name__ == "__main__":
    main()