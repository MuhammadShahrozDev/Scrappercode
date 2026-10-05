import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
JOBS_FILE = BASE_DIR / "data" / "jobs_all.json"
COMPANIES_FILE = BASE_DIR / "data" / "companies.json"


# Fields to remove from jobs
DROP_FIELDS = {
    "_highlightResult",
    "_tags",
    "objectID",
    "model_type",
    "model_id",
}


def load_json(path):

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():

    # ==========================================================
    # Load jobs
    # ==========================================================

    print(f"Reading {JOBS_FILE}")

    jobs = load_json(JOBS_FILE)

    print(f"Loaded {len(jobs)} jobs")


    # ==========================================================
    # Load companies
    # ==========================================================

    print(f"Reading {COMPANIES_FILE}")

    companies = load_json(COMPANIES_FILE)

    print(f"Loaded {len(companies)} companies")


    # ==========================================================
    # Create company lookup
    #
    # companies.json uses "company_id"
    # ==========================================================

    company_lookup = {
        company["company_slug"]: company
        for company in companies
    }


    # ==========================================================
    # Clean and update jobs
    # ==========================================================

    clean_jobs = []

    matched = 0
    unmatched = 0

    for job in jobs:

        # ------------------------------------------------------
        # Remove unwanted fields
        # ------------------------------------------------------

        clean_job = {
            key: value
            for key, value in job.items()
            if key not in DROP_FIELDS
        }


        # ------------------------------------------------------
        # Add source
        # ------------------------------------------------------

        clean_job["source"] = "ycombinator"


        # ------------------------------------------------------
        # Find company
        # ------------------------------------------------------

        company_slug = job.get("company_slug")

        company = company_lookup.get(company_slug)


        if company is None:

            unmatched += 1

            print(
                f"Company not found: "
                f"{company_slug} "
                f"({job.get('company_name')})"
            )

        else:

            matched += 1

            # --------------------------------------------------
            # Company website
            # --------------------------------------------------

            clean_job["company_website"] = company.get(
                "company_website"
            )


            # --------------------------------------------------
            # Founder details
            #
            # Only keep name + LinkedIn
            # --------------------------------------------------

            clean_job["founders"] = [
                {
                    "full_name": founder.get("full_name"),
                    "linkedin": founder.get("linkedin"),
                }
                for founder in company.get("founders", [])
            ]


        # ------------------------------------------------------
        # Add cleaned job
        # ------------------------------------------------------

        clean_jobs.append(clean_job)


    # ==========================================================
    # Sort jobs newest -> oldest
    # ==========================================================

    clean_jobs.sort(
        key=lambda job: job.get("created_at", ""),
        reverse=True,
    )


    # ==========================================================
    # Save
    # ==========================================================

    with open(
        JOBS_FILE,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            clean_jobs,
            f,
            indent=2,
            ensure_ascii=False,
        )


    # ==========================================================
    # Summary
    # ==========================================================

    print()
    print("=" * 60)
    print("Finished")
    print("=" * 60)

    print(f"Total jobs: {len(clean_jobs)}")
    print(f"Companies matched: {matched}")
    print(f"Companies unmatched: {unmatched}")
    print(f"Saved to: {JOBS_FILE}")


if __name__ == "__main__":
    main()