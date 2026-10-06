import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

JOBS_FILE = (
    BASE_DIR
    / "data"
    / "jobs_all.json"
)

COMPANIES_FILE = (
    BASE_DIR
    / "data"
    / "companies.json"
)


DROP_FIELDS = {
    "_highlightResult",
    "_tags",
    "objectID",
    "model_type",
    "model_id",
}


def load_json(path):

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


def main():

    print(
        f"Reading {JOBS_FILE}"
    )

    jobs = load_json(
        JOBS_FILE
    )

    print(
        f"Loaded {len(jobs)} jobs"
    )


    print(
        f"Reading {COMPANIES_FILE}"
    )

    companies = load_json(
        COMPANIES_FILE
    )

    print(
        f"Loaded "
        f"{len(companies)} companies"
    )


    company_lookup = {
        company["company_slug"]: company
        for company in companies
        if company.get(
            "company_slug"
        )
    }


    clean_jobs = []

    matched = 0
    unmatched = 0


    for job in jobs:

        clean_job = {
            key: value
            for key, value
            in job.items()
            if key not in DROP_FIELDS
        }


        clean_job[
            "source"
        ] = "ycombinator"


        company_slug = job.get(
            "company_slug"
        )

        company = company_lookup.get(
            company_slug
        )


        if company is None:

            unmatched += 1

            print(
                f"Company not found: "
                f"{company_slug} "
                f"({job.get('company_name')})"
            )

        else:

            matched += 1


            clean_job[
                "company_name"
            ] = (
                company.get(
                    "company_name"
                )
                or job.get(
                    "company_name"
                )
            )


            clean_job[
                "company_website"
            ] = company.get(
                "company_website"
            )


            clean_job[
                "company_linkedin"
            ] = company.get(
                "company_linkedin"
            )


            clean_job[
                "company_location"
            ] = company.get(
                "company_location",
                []
            )


            clean_job[
                "company_size"
            ] = company.get(
                "company_size"
            )


            clean_job[
                "founders"
            ] = [
                {
                    "full_name": founder.get(
                        "full_name"
                    ),

                    "linkedin": founder.get(
                        "linkedin"
                    ),
                }

                for founder
                in company.get(
                    "founders",
                    []
                )
            ]


        clean_jobs.append(
            clean_job
        )


    clean_jobs.sort(
        key=lambda job: (
            job.get(
                "created_at",
                ""
            )
            or ""
        ),
        reverse=True,
    )


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


    print()
    print("=" * 60)
    print("Finished")
    print("=" * 60)

    print(
        f"Total jobs: "
        f"{len(clean_jobs)}"
    )

    print(
        f"Companies matched: "
        f"{matched}"
    )

    print(
        f"Companies unmatched: "
        f"{unmatched}"
    )

    print(
        f"Saved to: "
        f"{JOBS_FILE}"
    )


if __name__ == "__main__":
    main()