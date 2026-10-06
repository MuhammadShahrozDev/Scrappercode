import json
from pathlib import Path


BASE_DIR = Path(
    __file__
).resolve().parent

INPUT_FILE = (
    BASE_DIR
    / "data"
    / "jobs_all.json"
)

OUTPUT_FILE = (
    BASE_DIR
    / "data"
    / "jobs_ycombinator.json"
)


def main():

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        jobs = json.load(f)

    output = []

    for job in jobs:

        clean_job = {
            "source": "ycombinator",

            "id": job.get(
                "id"
            ),

            "source_job_id": (
                job.get("id")
            ),

            "job_title": (
                job.get("title")
            ),

            "job_description": (
                job.get(
                    "description"
                )
            ),

            "role": job.get(
                "role"
            ),

            "job_url": (
                job.get(
                    "search_path"
                )
                or job.get(
                    "job_url"
                )
            ),

            "company_id": (
                job.get(
                    "company_id"
                )
            ),

            "company_slug": (
                job.get(
                    "company_slug"
                )
            ),

            "company_name": (
                job.get(
                    "company_name"
                )
            ),

            "company_website": (
                job.get(
                    "company_website"
                )
            ),

            "company_linkedin": (
                job.get(
                    "company_linkedin"
                )
            ),

            "company_location": (
                job.get(
                    "company_location",
                    []
                )
            ),

            "company_size": (
                job.get(
                    "company_size"
                )
            ),

            "job_location": (
                job.get(
                    "job_location",
                    []
                )
            ),

            "remote": job.get(
                "remote"
            ),

            "remote_type": (
                job.get(
                    "remote_type"
                )
            ),

            "relocation_allowed": (
                job.get(
                    "relocation_allowed"
                )
            ),

            "job_type": (
                job.get(
                    "job_type"
                )
            ),

            "experience_min": (
                job.get(
                    "experience_min"
                )
            ),

            "experience_max": (
                job.get(
                    "experience_max"
                )
            ),

            "experience": (
                job.get(
                    "experience"
                )
            ),

            "skills": (
                job.get(
                    "skills",
                    []
                )
            ),

            "compensation": (
                job.get(
                    "compensation"
                )
            ),

            "salary_min": (
                job.get(
                    "salary_min"
                )
            ),

            "salary_max": (
                job.get(
                    "salary_max"
                )
            ),

            "salary_currency": (
                job.get(
                    "salary_currency"
                )
            ),

            "posted_timestamp": (
                job.get(
                    "posted_timestamp"
                )
            ),

            "hiring_contact": None,
        }

        founders = job.get(
            "founders",
            []
        )

        for i, founder in enumerate(
            founders,
            start=1
        ):

            clean_job[
                f"person_{i}_name"
            ] = founder.get(
                "full_name"
            )

            clean_job[
                f"person_{i}_role"
            ] = "Founder"

            clean_job[
                f"person_{i}_profile_url"
            ] = founder.get(
                "linkedin"
            )

        output.append(
            clean_job
        )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(
        f"Loaded: "
        f"{len(jobs)} jobs"
    )

    print(
        f"Saved: "
        f"{OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()