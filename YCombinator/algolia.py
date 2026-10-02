import json
import os
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv


from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

SEARCHES = BASE_DIR / "searches.json"

# ==========================================================
# Algolia Credentials
# ==========================================================

load_dotenv()

ALGOLIA_APP_ID = os.getenv("ALGOLIA_APP_ID")
ALGOLIA_API_KEY = os.getenv("ALGOLIA_API_KEY")
URL = os.getenv("URL")

HEADERS = {
    "X-Algolia-Application-Id": ALGOLIA_APP_ID,
    "X-Algolia-API-Key": ALGOLIA_API_KEY,
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://www.ycombinator.com",
    "Referer": "https://www.ycombinator.com/",
}


def validate_algolia_credentials():
    """Fail fast with a clear message when the Algolia config is missing or invalid."""
    if not ALGOLIA_APP_ID or not ALGOLIA_API_KEY or not URL:
        raise RuntimeError(
            "Missing Algolia configuration. Set ALGOLIA_APP_ID, "
            "ALGOLIA_API_KEY, and URL in YCombinator/.env"
        )


# ==========================================================
# Configuration
# ==========================================================

# Collect jobs posted within the last N days.
LOOKBACK_DAYS = 5


# ==========================================================
# Time Helpers
# ==========================================================

def within_lookback_period(job):
    """
    Returns True if the job is newer than LOOKBACK_DAYS.
    """

    created = datetime.fromisoformat(
        job["created_at"].replace("Z", "+00:00")
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)

    return created >= cutoff


# ==========================================================
# Trim Old Jobs
# ==========================================================

def trim_old_jobs(hits):
    """
    Results are already sorted newest -> oldest.

    Instead of checking every job:

        99
        89
        79
        ...

    we check every 10th job from the end until we find
    one inside the lookback period, then scan only that
    final block.
    """

    if not hits:
        return hits

    # Entire page is within lookback.
    if within_lookback_period(hits[-1]):
        return hits

    block_start = 0

    # Coarse search.
    for i in range(len(hits) - 1, -1, -10):

        if within_lookback_period(hits[i]):
            block_start = i + 1
            break

    # Fine search.
    cutoff = len(hits)

    for i in range(block_start, len(hits)):

        if not within_lookback_period(hits[i]):
            cutoff = i
            break

    return hits[:cutoff]


# ==========================================================
# Load Searches
# ==========================================================

with open(SEARCHES, "r", encoding="utf-8") as f:
    SEARCHES = json.load(f)


def search_jobs(search):
    """
    Executes one search from searches.json.

    Stops automatically once jobs older than LOOKBACK_DAYS
    are reached.
    """

    query = search.get("query", "")
    role = search.get("role")
    eng_type = search.get("eng_type")
    design_type = search.get("design_type")
    science_type = search.get("science_type")
    recruiting_type = search.get("recruiting_type")
    min_experience = search.get("min_experience")
    remote = search.get("remote")
    job_type = search.get("job_type")
    has_equity = search.get("has_equity")
    company_parent_sector = search.get("company_parent_sector")
    us_visa_required = search.get("us_visa_required")

    jobs = []
    seen = set()
    page = 0

    while True:

        # ---------------------------------------
        # Build filters
        # ---------------------------------------

        filter_parts = []

        if role:
            filter_parts.append(f"role:{role}")

        if eng_type:
            filter_parts.append(f"eng_type:{eng_type}")

        if design_type:
            filter_parts.append(f"design_type:{design_type}")

        if science_type:
            filter_parts.append(f"science_type:{science_type}")

        if recruiting_type:
            filter_parts.append(f"recruiting_type:{recruiting_type}")

        if min_experience is not None:
            filter_parts.append(
                f"min_experience:{min_experience}"
            )

        if remote:
            filter_parts.append(
                f'{"NOT " if remote.startswith("!") else ""}'
                f'remote:"{remote.lstrip("!")}"'
            )

        if us_visa_required:
            filter_parts.append(
                f'{"NOT " if us_visa_required.startswith("!") else ""}'
                f'us_visa_required:"{us_visa_required.lstrip("!")}"'
            )

        if job_type:
            filter_parts.append(
                f"job_type:{job_type}"
            )

        if has_equity is not None:
            filter_parts.append(
                f"has_equity:{has_equity}"
            )

        if company_parent_sector:
            filter_parts.append(
                f'{"NOT " if company_parent_sector.startswith("!") else ""}'
                f'company_parent_sector:"{company_parent_sector.lstrip("!")}"'
            )

        filters = " AND ".join(filter_parts)

        # ---------------------------------------
        # Build request
        # ---------------------------------------

        params = (
            f"query={query}"
            f"&page={page}"
            f"&filters={filters}"
            "&attributesToRetrieve=%5B%22*%22%5D"
            "&hitsPerPage=100"
            "&distinct=false"
            "&clickAnalytics=true"
        )

        payload = {
            "requests": [
                {
                    "indexName":
                        "WaaSPublicCompanyJob_created_at_desc_production",
                    "params": params,
                }
            ]
        }

        try:
            response = requests.post(
                URL,
                headers=HEADERS,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 403:
                print(
                    "[!] Algolia rejected the configured Application ID or API key. "
                    "Skipping this YC search. Update YCombinator/.env with valid credentials."
                )
                return []
            raise

        result = response.json()["results"][0]
        hits = result["hits"]

        if not hits:
            break

        if page == 0:
            print(
                f"Total matching jobs: {result['nbHits']}"
            )
            print()

        print(
            f"Page {page}: {len(hits)} jobs"
        )

        # ---------------------------------------
        # Remove jobs outside lookback period
        # ---------------------------------------

        trimmed_hits = trim_old_jobs(hits)

        for job in trimmed_hits:

            if job["id"] in seen:
                continue

            seen.add(job["id"])
            jobs.append(job)

        # ---------------------------------------
        # Stop once old jobs appear
        # ---------------------------------------

        if len(trimmed_hits) != len(hits):

            print()
            print(
                f"Reached jobs older than "
                f"{LOOKBACK_DAYS} day(s)."
            )

            break

        page += 1

    return jobs


def save_jobs(jobs, filename):
    """
    Saves a flat list of jobs into the specified JSON file.

    Existing data is preserved and new jobs are merged
    while preventing duplicates. Older grouped output is
    flattened when it is encountered.
    """

    if os.path.exists(filename):

        with open(
            filename,
            "r",
            encoding="utf-8",
        ) as f:

            data = json.load(f)


        print(f"Loaded {filename}")

        if isinstance(data, dict):
            existing_jobs = []

            for block in data.values():
                if not isinstance(block, dict):
                    continue

                block_jobs = block.get("jobs", [])

                if isinstance(block_jobs, list):
                    existing_jobs.extend(block_jobs)

            data = existing_jobs

        elif not isinstance(data, list):
            data = []


    else:

        data = []

    existing_ids = {
        job["id"]
        for job in data
        if isinstance(job, dict) and "id" in job
    }

    for job in jobs:
        if job["id"] in existing_ids:
            continue

        data.append(job)
        existing_ids.add(job["id"])

    with open(
        filename,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            data,
            f,
            indent=4,
            ensure_ascii=False,
        )


if __name__ == "__main__":

    # Create output directory.
    OUTPUT_DIR = BASE_DIR / "data"
    FILTERED_DIR = OUTPUT_DIR / "jobs_filtered"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(FILTERED_DIR, exist_ok=True)

    all_jobs = []
    seen = set()

    print()

    for search in SEARCHES:

        print("=" * 60)
        print(f"Running search: {search['name']}")
        print("=" * 60)
        print()

        jobs = search_jobs(search)

        print()
        print(f"Collected {len(jobs)} jobs.")
        print()

        # --------------------------------------
        # Save this filter's jobs
        # --------------------------------------

        filename = os.path.join(
            FILTERED_DIR,
            f"jobs_{search['name']}.json"
        )

        save_jobs(
            jobs,
            filename,
        )

        print(f"Saved to {filename}")
        print()

        # --------------------------------------
        # Add to master list
        # --------------------------------------

        for job in jobs:

            if job["id"] in seen:
                continue

            seen.add(job["id"])
            all_jobs.append(job)

    # --------------------------------------
    # Save master file
    # --------------------------------------

    all_filename = os.path.join(
        OUTPUT_DIR,
        "jobs_all.json",
    )

    save_jobs(
        all_jobs,
        all_filename,
    )

    print("=" * 60)
    print("Finished")
    print("=" * 60)
    print(f"Total unique jobs: {len(all_jobs)}")
    print(f"Saved to {all_filename}")