import json
from patchright.sync_api import sync_playwright
from pathlib import Path

# ==========================================================
# Configuration
# ==========================================================

BASE_DIR = Path(__file__).resolve().parent

PROFILE_DIR = BASE_DIR / "yc_profile"

INPUT_FILE = BASE_DIR / "data" / "jobs_all.json"
OUTPUT_FILE = BASE_DIR / "data" / "companies.json"

COMPANY_URL = "https://www.workatastartup.com/companies/fetch"

BATCH_SIZE = 100


# ==========================================================
# Get Company IDs
# ==========================================================

def get_company_ids():
    """
    Extract unique company IDs from jobs_all.json.
    """

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        jobs = json.load(f)

    company_ids = set()

    for job in jobs:

        company_id = job.get("company_id")

        if company_id is not None:
            company_ids.add(company_id)

    return sorted(company_ids)


# ==========================================================
# Fetch Companies
# ==========================================================

def fetch_companies(page, company_ids):
    """
    Fetch company information using the existing YC browser session.
    """

    companies = []

    total = len(company_ids)

    for start in range(0, total, BATCH_SIZE):

        batch = company_ids[
            start:start + BATCH_SIZE
        ]

        end = min(
            start + BATCH_SIZE,
            total
        )

        print(
            f"Fetching companies "
            f"{start + 1}-{end} of {total}"
        )

        result = page.evaluate(
            """
            async ({ ids }) => {

                const csrfToken = document
                    .querySelector('meta[name="csrf-token"]')
                    ?.getAttribute("content");

                const response = await fetch(
                    "/companies/fetch",
                    {
                        method: "POST",

                        headers: {
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                            "X-Requested-With": "XMLHttpRequest",
                            "X-CSRF-Token": csrfToken || ""
                        },

                        credentials: "include",

                        body: JSON.stringify({
                            ids: ids
                        })
                    }
                );

                return {
                    status: response.status,
                    text: await response.text(),
                    csrfTokenFound: !!csrfToken
                };
            }
            """,
            {
                "ids": batch
            }
        )

        if result["status"] != 200:

            print()
            print("REQUEST FAILED")
            print("Status:", result["status"])
            print("CSRF token found:", result["csrfTokenFound"])
            print("Response:", result["text"])
            print()

            raise RuntimeError(
                f"Company fetch failed: {result['status']}"
            )

        data = json.loads(result["text"])

        batch_companies = data.get(
            "companies",
            []
        )

        companies.extend(batch_companies)

        print(
            f"Received {len(batch_companies)} companies"
        )

    return companies


# ==========================================================
# Clean Company Data
# ==========================================================

def clean_company(company):
    """
    Keep company website and founder details.
    """

    founders = []

    for founder in company.get("founders", []):

        founders.append({
            "id": founder.get("id"),
            "first_name": founder.get("first_name"),
            "last_name": founder.get("last_name"),
            "full_name": founder.get("full_name"),
            "founder_bio": founder.get("founder_bio"),
            "linkedin": founder.get("linkedin"),
        })

    return {
        "company_id": company.get("id"),
        "company_name": company.get("name"),
        "company_website": company.get("website"),
        "founders": founders,
    }


# ==========================================================
# Save
# ==========================================================

def save_companies(companies):

    cleaned_companies = []

    for company in companies:

        cleaned_companies.append(
            clean_company(company)
        )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            cleaned_companies,
            f,
            indent=4,
            ensure_ascii=False
        )


# ==========================================================
# Main
# ==========================================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("Extracting company IDs")
    print("=" * 60)
    print()

    company_ids = get_company_ids()

    print(
        f"Found {len(company_ids)} unique companies."
    )

    print()
    print("=" * 60)
    print("Opening YC browser")
    print("=" * 60)
    print()

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        context = browser.new_context(viewport=None, no_viewport=True)
        page = context.new_page()

        page.goto(
            "https://www.workatastartup.com/"
        )

        print("YC browser opened.")
        print()

        companies = fetch_companies(
            page,
            company_ids
        )

        print()
        print(
            f"Total companies received: "
            f"{len(companies)}"
        )

        save_companies(companies)

        print()
        print("=" * 60)
        print("Finished")
        print("=" * 60)
        print()

        print(
            f"Saved to {OUTPUT_FILE}"
        )

        context.close()
        browser.close()