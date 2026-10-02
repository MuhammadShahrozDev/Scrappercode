
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

JOBS_DIR = BASE_DIR / "data"

for input_file in JOBS_DIR.glob("jobs_*.json"):

    with open(input_file, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    # Extract unique IDs and sort them
    job_ids = sorted(
        {job["id"] for job in jobs if "id" in job}
    )

    # jobs_backend.json -> job_ids_backend.json
    output_file = input_file.with_name(
        input_file.name.replace("jobs_", "job_ids_", 1)
    )

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            job_ids,
            f,
            indent=4,
        )

    print(
        f"Saved {len(job_ids)} unique IDs to {output_file.name}"
    )