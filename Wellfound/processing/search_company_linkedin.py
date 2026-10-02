"""
Working code to get company linkedins using DDGS python library
"""


import json
import random
import time
import re
from pathlib import Path

from ddgs import DDGS


# ============================================================
# Configuration
# ============================================================

# Project root (this file now lives one level down, in
# scraping/ or processing/), so go up an extra level.
BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_DIR = BASE_DIR / "jobs" / "jobs_cleaned_linkedin"
OUTPUT_DIR = BASE_DIR / "jobs" / "jobs_with_company_linkedin"
CACHE_DIR = BASE_DIR / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

# Resume cache: not part of the final data output, so it lives
# outside jobs/ and survives the end-of-pipeline data cleanup.
RESULTS_FILE = CACHE_DIR / "company_linkedin_mapping.json"

INPUT_PATTERN = "jobs_*.json"


# ------------------------------------------------------------
# Search backends
# ------------------------------------------------------------

# DDG is intentionally NOT included because your current IP
# is already blocked by DuckDuckGo.
SEARCH_BACKENDS = [
   "bing",
]


# ------------------------------------------------------------
# Request pacing
# ------------------------------------------------------------

MIN_DELAY = 5
MAX_DELAY = 12

LONG_PAUSE_EVERY_MIN = 30
LONG_PAUSE_EVERY_MAX = 50

LONG_PAUSE_MIN = 30
LONG_PAUSE_MAX = 90


# ------------------------------------------------------------
# DDGS
# ------------------------------------------------------------

DDGS_TIMEOUT = 15


# ------------------------------------------------------------
# Backend failure handling
# ------------------------------------------------------------

MAX_BACKEND_FAILURES = 3

BACKEND_COOLDOWN_MIN = 300       # 5 minutes
BACKEND_COOLDOWN_MAX = 900       # 15 minutes

BACKEND_RETRY_BACKOFF_MIN = 30
BACKEND_RETRY_BACKOFF_MAX = 120


def random_delay(
    min_seconds: float = MIN_DELAY,
    max_seconds: float = MAX_DELAY,
) -> None:
    delay = random.uniform(min_seconds, max_seconds)
    print(f"Sleeping {delay:.1f} seconds...")
    time.sleep(delay)


class SearchBackendManager:
    def __init__(self, backends):
        self.backends = list(backends)

        self.failure_counts = {
            backend: 0
            for backend in self.backends
        }

        self.cooldown_until = {
            backend: 0
            for backend in self.backends
        }

        self.total_searches = {
            backend: 0
            for backend in self.backends
        }

        self.last_backend_index = -1

    def _is_available(self, backend):
        return time.time() >= self.cooldown_until[backend]

    def available_backends(self):
        return [
            backend
            for backend in self.backends
            if self._is_available(backend)
        ]

    def get_next_backend(self):
        available = self.available_backends()

        if not available:
            return None

        # Round-robin selection
        for _ in range(len(self.backends)):
            self.last_backend_index = (
                self.last_backend_index + 1
            ) % len(self.backends)

            backend = self.backends[self.last_backend_index]

            if backend in available:
                return backend

        return available[0]

    def record_success(self, backend):
        self.failure_counts[backend] = 0
        self.total_searches[backend] += 1

    def record_failure(self, backend):
        self.failure_counts[backend] += 1
        self.total_searches[backend] += 1

        failures = self.failure_counts[backend]

        print(
            f"Backend '{backend}' failure "
            f"{failures}/{MAX_BACKEND_FAILURES}"
        )

        if failures >= MAX_BACKEND_FAILURES:
            cooldown = random.uniform(
                BACKEND_COOLDOWN_MIN,
                BACKEND_COOLDOWN_MAX,
            )

            self.cooldown_until[backend] = (
                time.time() + cooldown
            )

            print(
                f"Temporarily disabling '{backend}' "
                f"for {cooldown:.1f} seconds."
            )

            self.failure_counts[backend] = 0

    def print_status(self):
        print("\nSearch backend status:")

        for backend in self.backends:
            cooldown_remaining = max(
                0,
                self.cooldown_until[backend] - time.time(),
            )

            if cooldown_remaining > 0:
                status = (
                    f"cooldown ({cooldown_remaining:.0f}s)"
                )
            else:
                status = "available"

            print(
                f"  {backend}: "
                f"searches={self.total_searches[backend]}, "
                f"status={status}"
            )

        print()


class SearchClient:
    def __init__(self):
        self.ddgs = DDGS(
            timeout=DDGS_TIMEOUT
        )

        self.backend_manager = SearchBackendManager(
            SEARCH_BACKENDS
        )

    def search(self, query, max_results=10):
        backend = self.backend_manager.get_next_backend()

        if backend is None:
            print(
                "All search backends are currently "
                "in cooldown."
            )

            wait_time = random.uniform(
                BACKEND_RETRY_BACKOFF_MIN,
                BACKEND_RETRY_BACKOFF_MAX,
            )

            print(
                f"Waiting {wait_time:.1f} seconds..."
            )

            time.sleep(wait_time)

            backend = self.backend_manager.get_next_backend()

            if backend is None:
                return {
                    "status": "error",
                    "backend": None,
                    "results": [],
                    "error": "No backend available",
                }

        print(
            f"Using backend: {backend}"
        )

        print(
            f"Searching: {query}"
        )

        try:
            results = list(
                self.ddgs.text(
                    query,
                    backend=backend,
                    max_results=max_results,
                )
            )

            self.backend_manager.record_success(
                backend
            )

            if not results:
                print(
                    f"{backend}: search succeeded "
                    f"with 0 results."
                )

                return {
                    "status": "empty",
                    "backend": backend,
                    "results": [],
                    "error": None,
                }

            print(
                f"{backend}: received "
                f"{len(results)} results."
            )

            return {
                "status": "success",
                "backend": backend,
                "results": results,
                "error": None,
            }

        except Exception as exc:
            print(
                f"{backend} search failed: {exc}"
            )

            self.backend_manager.record_failure(
                backend
            )

            return {
                "status": "error",
                "backend": backend,
                "results": [],
                "error": str(exc),
            }


def normalize_website(website: str) -> str:
    website = website.strip().lower()
    website = re.sub(r"https?://", "", website)
    website = website.rstrip("/")
    website = website.replace("www.", "")
    return website


def task_key(
    company_name: str,
    website: str,
    location: str,
) -> str:
    return "||".join([
        company_name.strip().lower(),
        (website or "").strip().lower(),
        (location or "").strip().lower(),
    ])


def load_existing_mapping() -> dict:
    if not RESULTS_FILE.exists():
        return {}

    try:
        with open(
            RESULTS_FILE,
            encoding="utf8",
        ) as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data

    except Exception as exc:
        print(
            f"Warning: could not load existing "
            f"results: {exc}"
        )

    return {}


def save_mapping(mapping: dict) -> None:
    with open(
        RESULTS_FILE,
        "w",
        encoding="utf8",
    ) as f:
        json.dump(
            mapping,
            f,
            indent=2,
            ensure_ascii=False,
        )


def load_job_files() -> list[Path]:
    return sorted(
        INPUT_DIR.glob(INPUT_PATTERN)
    )


def get_company_location(job: dict) -> str:
    company_location = job.get(
        "company_location"
    )

    if (
        isinstance(company_location, list)
        and company_location
    ):
        return str(
            company_location[0]
        ).strip()

    if (
        isinstance(company_location, str)
        and company_location.strip()
    ):
        return company_location.strip()

    location = job.get("location")

    if (
        isinstance(location, list)
        and location
    ):
        return str(
            location[0]
        ).strip()

    if (
        isinstance(location, str)
        and location.strip()
    ):
        return location.strip()

    return ""


def load_jobs(job_file: Path) -> list[dict]:
    with open(
        job_file,
        encoding="utf8",
    ) as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(
            f"Expected JSON array in {job_file}"
        )

    return data


def save_jobs(
    job_file: Path,
    jobs: list[dict],
) -> None:
    OUTPUT_DIR.mkdir(
        exist_ok=True
    )

    output_path = (
        OUTPUT_DIR / job_file.name
    )

    with open(
        output_path,
        "w",
        encoding="utf8",
    ) as f:
        json.dump(
            jobs,
            f,
            indent=2,
            ensure_ascii=False,
        )


def search_company_linkedin(
    search_client,
    company_name,
    website,
    location,
):
    query_parts = [
        f'site:linkedin.com/company/ {company_name}'
    ]

    if website:
        query_parts.append(
            f'{website}'
        )

    if location:
        query_parts.append(
            f'{location}'
        )

    query = " ".join(query_parts)

    search_response = search_client.search(
        query,
        max_results=10,
    )

    status = search_response["status"]

    if status == "error":
        print(
            "Search failed; this company "
            "will NOT be treated as 'no LinkedIn'."
        )

        return {
            "status": "error",
            "backend": search_response["backend"],
            "results": [],
            "error": search_response["error"],
        }

    if status == "empty":
        return {
            "status": "empty",
            "backend": search_response["backend"],
            "results": [],
            "error": None,
        }

    search_items = search_response["results"]

    normalized_website = (
        normalize_website(website)
        if website
        else ""
    )

    exact_matches = []

    for item in search_items:
        href = item.get("href", "")
        snippet = item.get("body", "")

        snippet_lower = snippet.lower()

        if (
            normalized_website
            and normalized_website in snippet_lower
        ):
            exact_matches.append({
                "href": href,
                "snippet": snippet,
            })

    if exact_matches:
        print(
            "Found website match in search result:"
        )
        print(
            exact_matches[0]["href"]
        )

        return {
            "status": "success",
            "backend": search_response["backend"],
            "results": exact_matches,
            "error": None,
        }

    return {
        "status": "success",
        "backend": search_response["backend"],
        "results": [
            {
                "href": item.get("href", ""),
                "snippet": item.get("body", ""),
            }
            for item in search_items
        ],
        "error": None,
    }


def build_search_tasks(
    job_files: list[Path],
) -> list[tuple[str, str, str, str]]:
    tasks = []
    seen = set()

    for job_file in job_files:
        jobs = load_jobs(job_file)

        for job in jobs:

            # Do not touch jobs that already have
            # a company LinkedIn URL.
            existing_linkedin = job.get("company_linkedin")

            if existing_linkedin not in (None, ""):
                continue

            company_name = job.get(
                "company_name"
            )

            if not company_name:
                continue

            company_website = (
                job.get("company_website")
                or ""
            )

            company_location = (
                get_company_location(job)
            )

            existing_linkedin = job.get("company_linkedin")
            if existing_linkedin not in (None, ""):
                continue

            task_key = (
                company_name.strip().lower(),
                (
                    company_website or ""
                ).strip().lower(),
                (
                    company_location or ""
                ).strip().lower(),
            )

            if task_key in seen:
                continue

            seen.add(task_key)

            tasks.append(
                (
                    company_name.strip(),
                    (
                        company_website.strip()
                        if company_website
                        else ""
                    ),
                    (
                        company_location
                        or ""
                    ),
                    job_file.name,
                )
            )

    return tasks


def update_jobs_with_company_linkedin(
    mapping,
    job_files,
):
    OUTPUT_DIR.mkdir(
        exist_ok=True
    )

    for job_file in job_files:
        jobs = load_jobs(job_file)

        updated = 0

        for job in jobs:
            # Jobs that already have a company_linkedin value
            # (e.g. found earlier from the Wellfound company page)
            # were never searched, so they have no entry in
            # `mapping`. Leave them untouched instead of
            # overwriting them with None.
            existing_linkedin = job.get("company_linkedin")

            if existing_linkedin not in (None, ""):
                continue

            company_name = job.get(
                "company_name"
            )

            if not company_name:
                continue

            company_website = (
                job.get("company_website")
                or ""
            )

            company_location = (
                get_company_location(job)
            )

            key = task_key(
                company_name,
                company_website,
                company_location,
            )

            entry = mapping.get(key)

            if entry is None:
                # This company was never searched (e.g. no
                # task was created for it). Leave the field
                # as-is rather than guessing.
                continue

            if (
                isinstance(entry, dict)
                and entry.get("status")
                == "success"
            ):
                job["company_linkedin"] = (
                    entry.get("results")
                )
            elif (
                isinstance(entry, dict)
                and entry.get("status")
                == "empty"
            ):
                job["company_linkedin"] = None
            else:
                # Search failed. Do not claim
                # that the company has no LinkedIn.
                continue

            updated += 1

        save_jobs(
            job_file,
            jobs,
        )

        print(
            f"Wrote updated file "
            f"{job_file.name} "
            f"({updated} jobs)"
        )



def main():
    job_files = load_job_files()

    if not job_files:
        print(
            f"No job files found in "
            f"{INPUT_DIR} matching "
            f"{INPUT_PATTERN}"
        )
        return

    tasks = build_search_tasks(
        job_files
    )

    if not tasks:
        print(
            "No company search tasks found."
        )
        return

    mapping = load_existing_mapping()

    search_client = SearchClient()

    total = len(tasks)

    searches_since_long_pause = 0

    next_long_pause = random.randint(
        LONG_PAUSE_EVERY_MIN,
        LONG_PAUSE_EVERY_MAX,
    )

    for index, (
        company_name,
        website,
        location,
        source_file,
    ) in enumerate(
        tasks,
        start=1,
    ):
        key = task_key(
            company_name,
            website,
            location,
        )

        # ----------------------------------------------------
        # Skip successfully completed searches
        # ----------------------------------------------------

        existing = mapping.get(key)

        if (
            isinstance(existing, dict)
            and existing.get("status")
            in {"success", "empty"}
        ):
            print(
                f"Skipping already searched: "
                f"{company_name} "
                f"({source_file})"
            )
            continue

        print("=" * 70)

        print(
            f"[{index}/{total}] "
            f"{company_name}"
        )

        print(
            f"Website : {website}"
        )

        print(
            f"Location: {location}"
        )

        print(
            f"Source  : {source_file}"
        )

        print("=" * 70)

        result = search_company_linkedin(
            search_client,
            company_name,
            website,
            location,
        )

        mapping[key] = result

        # Save immediately so progress survives
        # crashes/interruption.
        save_mapping(mapping)

        searches_since_long_pause += 1

        # ----------------------------------------------------
        # Normal delay
        # ----------------------------------------------------

        random_delay()

        # ----------------------------------------------------
        # Long pause
        # ----------------------------------------------------

        if (
            searches_since_long_pause
            >= next_long_pause
        ):
            pause = random.uniform(
                LONG_PAUSE_MIN,
                LONG_PAUSE_MAX,
            )

            print(
                f"Taking a longer pause: "
                f"{pause:.1f}s..."
            )

            time.sleep(pause)

            searches_since_long_pause = 0

            next_long_pause = random.randint(
                LONG_PAUSE_EVERY_MIN,
                LONG_PAUSE_EVERY_MAX,
            )

        # ----------------------------------------------------
        # Print backend statistics periodically
        # ----------------------------------------------------

        if index % 10 == 0:
            search_client.backend_manager.print_status()

    update_jobs_with_company_linkedin(
        mapping,
        job_files,
    )

    print(
        "Finished updating jobs "
        "with company_linkedin."
    )


if __name__ == "__main__":
    main()