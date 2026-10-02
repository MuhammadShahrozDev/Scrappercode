import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# wf/ is a sibling project; it now produces one combined file
# instead of five per-role files.
WF_INPUT_FILE = BASE_DIR.parent / "Wellfound" / "jobs" / "jobs_cleaned" / "jobs_all.json"

OUTPUT_FILE = BASE_DIR / "jobs" / "companies.json"


def extract_linkedin_hrefs(company_linkedin):
    """
    company_linkedin can be:
      - a plain URL string (found directly on the Wellfound company page)
      - a list of {"href": ..., "snippet": ...} dicts (found via search)
      - None
    Normalize all of these into a flat list of href strings.
    """

    if not company_linkedin:
        return []

    if isinstance(company_linkedin, str):
        return [company_linkedin]

    if not isinstance(company_linkedin, list):
        return []

    hrefs = []

    for item in company_linkedin:
        if isinstance(item, dict):
            href = item.get("href")
        elif isinstance(item, str):
            href = item
        else:
            href = None

        if href and href not in hrefs:
            hrefs.append(href)

    return hrefs


def extract_unique_companies():
    companies = {}

    print(f"Reading: {WF_INPUT_FILE}")

    with open(WF_INPUT_FILE, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    print(f"Loaded {len(jobs)} jobs")

    for job in jobs:
        company_id = job.get("company_id")

        if not company_id:
            continue

        contact = job.get("contact") or {}
        linkedin_hrefs = extract_linkedin_hrefs(job.get("company_linkedin"))

        # If company doesn't exist yet, create it
        if company_id not in companies:
            companies[company_id] = {
                "company_id": company_id,
                "company_name": job.get("company_name"),
                "company_website": job.get("company_website"),
                "company_linkedin": linkedin_hrefs,
                "company_location": job.get("location", []),
                "hiring_contact": contact.get("hiring_contact")
            }

        # If company already exists, merge information
        else:
            company = companies[company_id]

            # Add any new LinkedIn URLs
            for href in linkedin_hrefs:
                if href not in company["company_linkedin"]:
                    company["company_linkedin"].append(href)

            # Fill missing fields from later jobs
            if not company["company_name"] and job.get("company_name"):
                company["company_name"] = job.get("company_name")

            if not company["company_website"] and job.get("company_website"):
                company["company_website"] = job.get("company_website")

            if not company["company_location"] and job.get("location"):
                company["company_location"] = job.get("location")

            if not company["hiring_contact"] and contact.get("hiring_contact"):
                company["hiring_contact"] = contact.get("hiring_contact")

    results = list(companies.values())

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nFound {len(results)} unique companies")
    print(f"Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    extract_unique_companies()
