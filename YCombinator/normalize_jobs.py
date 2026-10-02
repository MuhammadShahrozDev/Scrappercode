import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

INPUT_FILE = BASE_DIR / "data" / "jobs_all.json"
OUTPUT_FILE = BASE_DIR / "data" / "jobs_ycombinator.json"


def main():

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    output = []

    for job in jobs:

        # ------------------------------------------------------
        # Base job fields
        # ------------------------------------------------------

        clean_job = {
            "source": "ycombinator",
            "job_title": job.get("title"),
            "job_description": job.get("description"),
            "role": job.get("role"),
            "company_name": job.get("company_name"),
            "company_website": job.get("company_website"),
            "company_linkedin": None,
            # "company_location": None,
            # "job_location": None,
            "hiring_contact": None,
        }


        # ------------------------------------------------------
        # Founders -> person_1, person_2, etc.
        # ------------------------------------------------------

        founders = job.get("founders", [])

        for i, founder in enumerate(founders, start=1):

            clean_job[f"person_{i}_name"] = founder.get(
                "full_name"
            )

            clean_job[f"person_{i}_role"] = "Founder"

            clean_job[f"person_{i}_profile_url"] = (
                founder.get("linkedin")
            )


        # ------------------------------------------------------
        # Job URL
        # ------------------------------------------------------

        clean_job["job_url"] = job.get(
            "search_path"
        )


        # ------------------------------------------------------
        # Add to output
        # ------------------------------------------------------

        output.append(clean_job)


    # ----------------------------------------------------------
    # Save
    # ----------------------------------------------------------

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False,
        )


    print(f"Loaded: {len(jobs)} jobs")
    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()