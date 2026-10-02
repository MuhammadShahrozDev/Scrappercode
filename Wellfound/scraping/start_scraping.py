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

    print(f"Already have {len(seen_job_ids)} jobs.")

    playwright, context, page = start_browser()

    try:

        # Open login page
        page.goto(
            "https://wellfound.com/login",
            wait_until="domcontentloaded",
        )

        if "login" in page.url:
            print("Waiting for login...")
            page.wait_for_url(
                lambda url: "login" not in url,
                timeout=300000,
            )

        # Open jobs page
        page.goto(
            "https://wellfound.com/jobs",
            wait_until="domcontentloaded",
        )

        page.wait_for_load_state("load")
        page.wait_for_timeout(random.uniform(1500, 2500))


        roles = load_roles()

        tree = build_role_tree(roles)

        # scrape_order = get_scrape_order(tree)
        # ONLy get roles i want

        scrape_order = get_scrape_order(tree)

        # wanted = {
        #     "Machine Learning Engineer",
        #     "Product Manager",
        #     "Business Development",
        #     "Sales Development Representative",
        #     "BD Manager",
        # }

        # days = days

        scrape_order = [
            role
            for role in scrape_order
            if role["title"] in wanted
        ]

        input(f"\nPress Enter to scrape {len(scrape_order)} roles...")

        print(f"Scraping {len(scrape_order)} roles.\n")

        for i, role in enumerate(scrape_order, start=1):

            if str(role["id"]) in completed_roles:
                print(f"Skipping role: {role['title']}")
                continue

            print(f"\n===== [{i}/{len(scrape_order)}] {role['title']} =====")

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

                mark_role_complete(role["id"])

            except Exception as e:

                print(f"Failed role '{role['title']}': {e}")
                
    finally:


        context.close()
        playwright.stop()


if __name__ == "__main__":
    main()