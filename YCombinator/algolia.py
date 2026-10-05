import json
import os
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent
SEARCHES_FILE = BASE_DIR / "searches.json"

OUTPUT_DIR = BASE_DIR / "data"
FILTERED_DIR = OUTPUT_DIR / "jobs_filtered"

YC_BASE = "https://www.ycombinator.com"
YC_JOBS_URL = "https://www.ycombinator.com/jobs/role/all"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def load_searches():
    with open(SEARCHES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def stable_job_id(job_url):
    match = re.search(r"/jobs/([^/?#]+)", job_url)

    if match:
        return match.group(1)

    return hashlib.sha256(
        job_url.encode("utf-8")
    ).hexdigest()[:24]


def company_id_from_slug(slug):
    return hashlib.sha256(
        slug.encode("utf-8")
    ).hexdigest()[:16]


def clean_text(value):
    if not value:
        return ""

    return re.sub(
        r"\s+",
        " ",
        value
    ).strip()


def fetch_html(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    return response.text


def extract_company_slug(job_url):
    match = re.search(
        r"/companies/([^/]+)/jobs/",
        job_url,
    )

    if not match:
        return ""

    return match.group(1)


def extract_description(job_url):
    try:
        html = fetch_html(job_url)
    except Exception as exc:
        print(
            f"[!] Detail page failed: "
            f"{job_url} ({type(exc).__name__})"
        )
        return ""

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    heading = None

    for tag in soup.find_all(
        ["h1", "h2", "h3"]
    ):
        text = clean_text(
            tag.get_text(" ", strip=True)
        )

        if text.lower() == "about the role":
            heading = tag
            break

    if heading is None:
        return ""

    parts = []

    for node in heading.find_all_next():

        if node.name in {
            "h1",
            "h2",
        }:
            text = clean_text(
                node.get_text(
                    " ",
                    strip=True,
                )
            )

            if (
                text
                and text.lower()
                != "about the role"
            ):
                break

        if node.name in {
            "p",
            "li",
            "h3",
            "h4",
        }:
            text = clean_text(
                node.get_text(
                    " ",
                    strip=True,
                )
            )

            if text:
                parts.append(text)

    return "\n".join(parts).strip()


def detect_role(card_text):
    roles = [
        "Engineering",
        "Product",
        "Design",
        "Sales",
        "Marketing",
        "Operations",
        "Recruiting",
        "Science",
        "Support",
        "Finance",
        "Legal",
    ]

    lower = card_text.lower()

    for role in roles:
        if role.lower() in lower:
            return role

    return ""


def extract_jobs_from_page():
    html = fetch_html(YC_JOBS_URL)

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    jobs = []
    seen = set()

    links = soup.find_all(
        "a",
        href=True,
    )

    for link in links:

        href = link.get("href", "")

        if not re.search(
            r"/companies/[^/]+/jobs/[^/]+",
            href,
        ):
            continue

        job_url = urljoin(
            YC_BASE,
            href,
        )

        if job_url in seen:
            continue

        title = clean_text(
            link.get_text(
                " ",
                strip=True,
            )
        )

        if not title:
            continue

        seen.add(job_url)

        company_slug = extract_company_slug(
            job_url
        )

        company_name = ""

        parent = link.parent

        for _ in range(6):

            if parent is None:
                break

            parent_text = clean_text(
                parent.get_text(
                    " ",
                    strip=True,
                )
            )

            company_link = parent.find(
                "a",
                href=re.compile(
                    rf"/companies/{re.escape(company_slug)}$"
                ),
            )

            if company_link:
                company_name = clean_text(
                    company_link.get_text(
                        " ",
                        strip=True,
                    )
                )
                card_text = parent_text
                break

            parent = parent.parent

        else:
            card_text = ""

        if not company_name:
            company_name = (
                company_slug
                .replace("-", " ")
                .title()
            )

        role = detect_role(
            card_text
        )

        description = extract_description(
            job_url
        )

        job = {
            "id": stable_job_id(
                job_url
            ),
            "created_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "title": title,
            "description": description,
            "role": role,
            "company_id": company_id_from_slug(
                company_slug
            ),
            "company_slug": company_slug,
            "company_name": company_name,
            "search_path": job_url,
            "objectID": stable_job_id(
                job_url
            ),
        }

        jobs.append(job)

    return jobs


def matches_search(job, search):
    query = clean_text(
        search.get("query", "")
    ).lower()

    role = clean_text(
        search.get("role", "")
    ).lower()

    title = clean_text(
        job.get("title", "")
    ).lower()

    description = clean_text(
        job.get("description", "")
    ).lower()

    job_role = clean_text(
        job.get("role", "")
    ).lower()

    searchable = (
        title
        + " "
        + description
        + " "
        + job_role
    )

    if query:
        query_parts = [
            item.strip()
            for item in re.split(
                r"[-_\s]+",
                query,
            )
            if item.strip()
        ]

        if not all(
            item in searchable
            for item in query_parts
        ):
            return False

    if role:
        if (
            role not in job_role
            and role not in searchable
        ):
            return False

    return True


def save_jobs(jobs, filename):
    if os.path.exists(filename):

        with open(
            filename,
            "r",
            encoding="utf-8",
        ) as f:
            try:
                data = json.load(f)
            except Exception:
                data = []

        if isinstance(data, dict):
            existing_jobs = []

            for block in data.values():
                if not isinstance(
                    block,
                    dict,
                ):
                    continue

                block_jobs = block.get(
                    "jobs",
                    [],
                )

                if isinstance(
                    block_jobs,
                    list,
                ):
                    existing_jobs.extend(
                        block_jobs
                    )

            data = existing_jobs

        elif not isinstance(
            data,
            list,
        ):
            data = []

    else:
        data = []

    existing_ids = {
        str(job.get("id"))
        for job in data
        if isinstance(job, dict)
        and job.get("id")
    }

    for job in jobs:

        job_id = str(
            job.get("id")
        )

        if job_id in existing_ids:
            continue

        data.append(job)
        existing_ids.add(job_id)

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


def main():
    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True,
    )

    os.makedirs(
        FILTERED_DIR,
        exist_ok=True,
    )

    searches = load_searches()

    print("=" * 60)
    print("Fetching current YC jobs page")
    print("=" * 60)

    jobs = extract_jobs_from_page()

    print(
        f"Collected {len(jobs)} "
        f"jobs from YC."
    )

    all_jobs = []
    seen = set()

    for search in searches:

        print()
        print("=" * 60)
        print(
            f"Running search: "
            f"{search['name']}"
        )
        print("=" * 60)

        filtered_jobs = [
            job
            for job in jobs
            if matches_search(
                job,
                search,
            )
        ]

        print(
            f"Collected "
            f"{len(filtered_jobs)} jobs."
        )

        filename = (
            FILTERED_DIR
            / f"jobs_{search['name']}.json"
        )

        save_jobs(
            filtered_jobs,
            filename,
        )

        print(
            f"Saved to {filename}"
        )

        for job in filtered_jobs:

            job_id = str(
                job.get("id")
            )

            if job_id in seen:
                continue

            seen.add(job_id)
            all_jobs.append(job)

    all_filename = (
        OUTPUT_DIR
        / "jobs_all.json"
    )

    save_jobs(
        all_jobs,
        all_filename,
    )

    print()
    print("=" * 60)
    print("Finished")
    print("=" * 60)

    print(
        f"Total unique jobs: "
        f"{len(all_jobs)}"
    )

    print(
        f"Saved to "
        f"{all_filename}"
    )


if __name__ == "__main__":
    main()