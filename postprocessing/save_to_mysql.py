import argparse
import json
import os
import sys
from pathlib import Path

import requests


API_URL = os.getenv("SMART_SCRAPER_API_URL", "").rstrip("/")
INGEST_TOKEN = os.getenv("SMART_SCRAPER_INGEST_TOKEN", "")
RUN_ID = os.getenv("SMART_SCRAPER_RUN_ID", "")

DEFAULT_BATCH_SIZE = int(
    os.getenv("SMART_SCRAPER_BATCH_SIZE", "100")
)


def clean(value):
    if isinstance(value, str):
        value = value.strip()
        return value if value else None
    return value


def normalize_list(value):
    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def normalize_job(job):
    contact = job.get("contact") or {}

    return {
        "source": clean(job.get("source")),

        "source_job_id": clean(
            job.get("id")
            or job.get("source_job_id")
        ),

        "job_title": clean(
            job.get("job_title")
            or job.get("title")
        ),

        "role": clean(job.get("role")),

        "job_description": clean(
            job.get("job_description")
            or job.get("description")
        ),

        "job_url": clean(
            job.get("job_url")
            or job.get("url")
        ),

        "company_id": clean(job.get("company_id")),

        "company_name": clean(
            job.get("company_name")
            or job.get("company")
        ),

        "company_slug": clean(job.get("company_slug")),

        "company_website": clean(
            job.get("company_website")
            or job.get("company_url")
        ),

        "company_linkedin": clean(
            job.get("company_linkedin")
            or job.get("company_linkedin_url")
        ),

        "company_location": normalize_list(
            job.get("company_location")
        ),

        "company_size": clean(job.get("company_size")),

        "job_location": normalize_list(
            job.get("location")
            or job.get("job_location")
        ),

        "remote": job.get("remote"),

        "remote_type": clean(
            job.get("remote_type")
            or job.get("remote_status")
        ),

        "relocation_allowed": job.get(
            "relocation_allowed"
        ),

        "job_type": clean(
            job.get("job_type")
            or job.get("employment_type")
        ),

        "experience_min": job.get("experience_min"),

        "experience_max": job.get("experience_max"),

        "experience_text": clean(
            job.get("experience")
        ),

        "skills": normalize_list(job.get("skills")),

        "compensation": job.get("compensation"),

        "salary_min": job.get("salary_min"),

        "salary_max": job.get("salary_max"),

        "salary_currency": clean(
            job.get("salary_currency")
        ),

        "equity": job.get("equity"),

        "visa_sponsorship": job.get(
            "visa_sponsorship"
        ),

        "posted_timestamp": clean(
            job.get("posted_timestamp")
        ),

        "hiring_contact": clean(
            job.get("hiring_contact")
            or contact.get("hiring_contact")
        ),

        "hiring_manager": clean(
            contact.get("hiring_manager")
        ),

        "founders": normalize_list(
            contact.get("founders")
        ),

        "person_1_name": clean(
            job.get("person_1_name")
        ),

        "person_1_role": clean(
            job.get("person_1_role")
        ),

        "person_1_profile_url": clean(
            job.get("person_1_profile_url")
        ),

        "person_2_name": clean(
            job.get("person_2_name")
        ),

        "person_2_role": clean(
            job.get("person_2_role")
        ),

        "person_2_profile_url": clean(
            job.get("person_2_profile_url")
        ),

        "raw_payload": job,
    }


def load_jobs(input_file):
    path = Path(input_file)

    if not path.exists():
        raise FileNotFoundError(
            f"Input file not found: {path}"
        )

    with open(path, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    if not isinstance(jobs, list):
        raise ValueError(
            "Input JSON must contain a list of jobs."
        )

    return jobs


def send_batch(
    batch,
    batch_number,
    mode,
    source_name,
):
    if not API_URL:
        raise RuntimeError(
            "SMART_SCRAPER_API_URL is missing"
        )

    if not INGEST_TOKEN:
        raise RuntimeError(
            "SMART_SCRAPER_INGEST_TOKEN is missing"
        )

    endpoint = (
        f"{API_URL}/api/v1/smart_scraper/ingest.php"
    )

    payload = {
        "run_id": RUN_ID or None,
        "batch_number": batch_number,
        "mode": mode,
        "source": source_name,
        "jobs": [
            normalize_job(job)
            for job in batch
        ],
    }

    response = requests.post(
        endpoint,
        json=payload,
        headers={
            "Authorization": (
                f"Bearer {INGEST_TOKEN}"
            ),
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=90,
    )

    if not response.ok:
        raise RuntimeError(
            f"API error HTTP "
            f"{response.status_code}: "
            f"{response.text}"
        )

    try:
        return response.json()
    except Exception as exc:
        raise RuntimeError(
            "API returned invalid JSON: "
            f"{response.text}"
        ) from exc


def ingest_file(
    input_file,
    mode,
    source_name,
    batch_size,
):
    jobs = load_jobs(input_file)

    print(
        f"Loaded {len(jobs)} jobs "
        f"from {input_file}"
    )

    totals = {
        "received": 0,
        "inserted": 0,
        "updated": 0,
        "duplicates": 0,
        "failed": 0,
    }

    batch_number = 1

    for start in range(
        0,
        len(jobs),
        batch_size,
    ):
        batch = jobs[
            start:start + batch_size
        ]

        print(
            f"Sending batch {batch_number} "
            f"with {len(batch)} jobs..."
        )

        result = send_batch(
            batch=batch,
            batch_number=batch_number,
            mode=mode,
            source_name=source_name,
        )

        for key in totals:
            totals[key] += int(
                result.get(key, 0)
            )

        print(
            f"Batch {batch_number}: "
            f"inserted={result.get('inserted', 0)} "
            f"updated={result.get('updated', 0)} "
            f"duplicates={result.get('duplicates', 0)} "
            f"failed={result.get('failed', 0)}"
        )

        batch_number += 1

    print("")
    print("Ingestion finished")

    for key, value in totals.items():
        print(f"{key}: {value}")

    return totals


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--file",
        required=True,
    )

    parser.add_argument(
        "--mode",
        choices=[
            "acquisition",
            "enrichment",
        ],
        default="acquisition",
    )

    parser.add_argument(
        "--source",
        required=True,
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
    )

    args = parser.parse_args()

    try:
        ingest_file(
            input_file=args.file,
            mode=args.mode,
            source_name=args.source,
            batch_size=args.batch_size,
        )

    except Exception as exc:
        print(
            f"[ERROR] {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
