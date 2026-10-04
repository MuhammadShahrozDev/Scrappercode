import os
import json
import requests

API_URL = os.getenv("LUXRA_API_URL", "").rstrip("/")
INGEST_TOKEN = os.getenv("LUXRA_INGEST_TOKEN", "")

INPUT_FILE = "postprocessing/jobs/jobs_combined.json"
BATCH_SIZE = 100


def load_jobs():
    if not os.path.exists(INPUT_FILE):
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("jobs_combined.json must contain a list of jobs")

    return data


def normalize_job(job):
    return {
        "source": job.get("source"),
        "source_job_id": job.get("source_job_id"),
        "job_title": job.get("job_title") or job.get("title"),
        "company_name": job.get("company_name") or job.get("company"),
        "job_url": job.get("job_url") or job.get("url"),
        "company_url": job.get("company_url"),
        "location": job.get("location"),
        "remote_status": job.get("remote_status") or job.get("remote"),
        "employment_type": job.get("employment_type"),
        "experience": job.get("experience"),
        "description": job.get("description"),
        "skills": job.get("skills"),
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
        "salary_currency": job.get("salary_currency"),
        "equity": job.get("equity"),
        "visa_sponsorship": job.get("visa_sponsorship"),
        "contact_name": job.get("contact_name"),
        "contact_title": job.get("contact_title"),
        "contact_email": job.get("contact_email"),
        "contact_linkedin_url": job.get("contact_linkedin_url"),
        "company_linkedin_url": job.get("company_linkedin_url"),
        "raw_payload": job,
    }


def send_batch(batch, batch_number):
    if not API_URL:
        raise RuntimeError("LUXRA_API_URL is missing")

    if not INGEST_TOKEN:
        raise RuntimeError("LUXRA_INGEST_TOKEN is missing")

    endpoint = f"{API_URL}/api/v1/scraper/ingest.php"

    payload = {
        "batch_number": batch_number,
        "jobs": [normalize_job(job) for job in batch],
    }

    response = requests.post(
        endpoint,
        json=payload,
        headers={
            "Authorization": f"Bearer {INGEST_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=60,
    )

    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(
            f"Ingest failed. HTTP {response.status_code}: {response.text}"
        )

    try:
        return response.json()
    except Exception:
        raise RuntimeError(
            f"Invalid JSON returned by Luxra API: {response.text}"
        )


def main():
    jobs = load_jobs()

    if not jobs:
        print("No jobs found.")
        return

    print(f"Loaded {len(jobs)} jobs")

    total_received = 0
    total_inserted = 0
    total_duplicates = 0
    total_failed = 0

    batch_number = 1

    for start in range(0, len(jobs), BATCH_SIZE):
        batch = jobs[start:start + BATCH_SIZE]

        print(
            f"Sending batch {batch_number} "
            f"({len(batch)} records)..."
        )

        result = send_batch(batch, batch_number)

        received = int(result.get("received", len(batch)))
        inserted = int(result.get("inserted", 0))
        duplicates = int(result.get("duplicates", 0))
        failed = int(result.get("failed", 0))

        total_received += received
        total_inserted += inserted
        total_duplicates += duplicates
        total_failed += failed

        print(
            f"Batch {batch_number} complete | "
            f"received={received} "
            f"inserted={inserted} "
            f"duplicates={duplicates} "
            f"failed={failed}"
        )

        batch_number += 1

    print("")
    print("Luxra ingestion complete")
    print(f"Received:   {total_received}")
    print(f"Inserted:   {total_inserted}")
    print(f"Duplicates: {total_duplicates}")
    print(f"Failed:     {total_failed}")


if __name__ == "__main__":
    main()
