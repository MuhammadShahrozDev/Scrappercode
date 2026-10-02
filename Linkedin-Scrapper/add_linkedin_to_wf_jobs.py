import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# wf/ is a sibling project; it now produces one combined file
# instead of five per-role files.
WF_INPUT_FILE = BASE_DIR.parent / "Wellfound" / "jobs" / "jobs_cleaned" / "jobs_all.json"

PEOPLE_FILE = BASE_DIR / "output" / "people_links.json"

# lin's own final output: Wellfound jobs enriched with LinkedIn
# company + people data, ready for postprocessing to combine with
# other sources. One file, not a per-role split.
OUTPUT_FILE = BASE_DIR / "jobs" / "jobs_wellfound.json"


def load_people():
    with open(PEOPLE_FILE, "r", encoding="utf-8") as f:
        people_data = json.load(f)

    return {
        str(company["company_id"]): company
        for company in people_data
        if company.get("company_id")
    }


def merge_people_into_jobs(jobs, people_by_company):
    for job in jobs:
        company_id = str(job.get("company_id", ""))
        company_data = people_by_company.get(company_id)

        if company_data:
            job["linkedin_people"] = company_data.get("people", [])
            job["company_linkedin"] = company_data.get("linkedin_company_url")
        else:
            job["linkedin_people"] = []
            job["company_linkedin"] = None

    return jobs


def job_to_row(job):
    people = job.get("linkedin_people", [])

    row = {
        "source": job.get("source"),
        "job_title": job.get("title"),
        "job_description": job.get("description"),
        "role": job.get("role"),

        "company_name": job.get("company_name"),
        "company_website": job.get("company_website"),
        "company_linkedin": job.get("company_linkedin"),

        "hiring_contact": job.get("contact", {}).get("hiring_contact"),
        "job_url": job.get("url")
    }

    # Add each person exactly how it was structured for the spreadsheet
    for i, person in enumerate(people, start=1):
        row[f"person_{i}_name"] = person.get("person_name")
        row[f"person_{i}_role"] = person.get("person_role")
        row[f"person_{i}_profile_url"] = person.get("person_profile_url")

    return row


def main():
    people_by_company = load_people()
    print(f"Loaded {len(people_by_company)} companies from {PEOPLE_FILE}")

    print(f"Reading: {WF_INPUT_FILE}")

    with open(WF_INPUT_FILE, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    print(f"Loaded {len(jobs)} jobs")

    jobs = merge_people_into_jobs(jobs, people_by_company)

    rows = [job_to_row(job) for job in jobs]

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    print("\n==============================")
    print("DONE")
    print("==============================")
    print(f"Saved: {OUTPUT_FILE}")
    print(f"Total jobs: {len(rows)}")


if __name__ == "__main__":
    main()
