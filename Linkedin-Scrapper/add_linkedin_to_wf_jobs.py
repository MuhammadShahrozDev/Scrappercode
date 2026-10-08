import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent

WF_INPUT_FILE = (
    BASE_DIR.parent
    / "Wellfound"
    / "jobs"
    / "jobs_cleaned"
    / "jobs_all.json"
)

PEOPLE_FILE = BASE_DIR / "output" / "people_links.json"
OUTPUT_FILE = BASE_DIR / "jobs" / "jobs_wellfound.json"


def load_people():
    with open(PEOPLE_FILE, "r", encoding="utf-8") as f:
        people_data = json.load(f)

    return {
        str(company["company_id"]): company
        for company in people_data
        if company.get("company_id")
        and company.get("linkedin_company_url")
    }


def stable_job_id(job):
    existing = (
        job.get("source_job_id")
        or job.get("id")
        or ""
    )

    if existing:
        return str(existing).strip()

    url = (
        job.get("job_url")
        or job.get("url")
        or ""
    ).strip()

    if url:
        match = re.search(r"/jobs/(\d+)", url)
        if match:
            return match.group(1)

        digest = hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()[:24]

        return f"url-{digest}"

    fingerprint = "|".join([
        str(job.get("company_name") or "").strip().lower(),
        str(job.get("title") or job.get("job_title") or "").strip().lower(),
        str(job.get("location") or job.get("job_location") or "").strip().lower(),
    ])

    return "fp-" + hashlib.sha256(
        fingerprint.encode("utf-8")
    ).hexdigest()[:24]


def canonical_job_url(job):
    url = (
        job.get("job_url")
        or job.get("url")
        or ""
    ).strip()

    if not url:
        return None

    parts = urlparse(url)

    return parts._replace(
        query="",
        fragment=""
    ).geturl()


def job_to_row(job, company_data):
    row = dict(job)

    row["source"] = "wellfound"
    row["source_job_id"] = stable_job_id(job)
    row["canonical_job_url"] = canonical_job_url(job)

    if not row.get("job_title"):
        row["job_title"] = row.get("title")

    if not row.get("job_description"):
        row["job_description"] = row.get("description")

    if not row.get("job_url"):
        row["job_url"] = row.get("url")

    row["company_linkedin"] = company_data.get(
        "linkedin_company_url"
    )

    people = company_data.get("people") or []

    for i, person in enumerate(people[:2], start=1):
        row[f"person_{i}_name"] = person.get(
            "person_name"
        )
        row[f"person_{i}_role"] = person.get(
            "person_role"
        )
        row[f"person_{i}_profile_url"] = person.get(
            "person_profile_url"
        )

    if not row.get("hiring_contact"):
        contact = row.get("contact") or {}
        row["hiring_contact"] = (
            contact.get("hiring_contact")
            or company_data.get("hiring_contact")
        )

    row["linkedin_enriched"] = True
    row["linkedin_company_verified"] = True

    return row


def main():
    people_by_company = load_people()

    print(
        f"Loaded {len(people_by_company)} enriched companies "
        f"from {PEOPLE_FILE}"
    )

    print(f"Reading: {WF_INPUT_FILE}")

    with open(WF_INPUT_FILE, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    print(f"Loaded {len(jobs)} Wellfound jobs")

    rows = []

    for job in jobs:
        company_id = str(
            job.get("company_id") or ""
        )

        company_data = people_by_company.get(
            company_id
        )

        if not company_data:
            continue

        rows.append(
            job_to_row(
                job,
                company_data
            )
        )

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            rows,
            f,
            indent=2,
            ensure_ascii=False
        )

    print("")
    print("==============================")
    print("DONE")
    print("==============================")
    print(f"Saved: {OUTPUT_FILE}")
    print(
        f"LinkedIn-enriched jobs only: {len(rows)}"
    )


if __name__ == "__main__":
    main()
