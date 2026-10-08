import argparse
import hashlib
import html
import re
from urllib.parse import urlparse
import json
import os
import sys
from pathlib import Path

import requests


API_URL = os.getenv(
    "SMART_SCRAPER_API_URL",
    ""
).rstrip("/")

INGEST_TOKEN = os.getenv(
    "SMART_SCRAPER_INGEST_TOKEN",
    ""
)

RUN_ID = os.getenv(
    "SMART_SCRAPER_RUN_ID",
    ""
)

DEFAULT_BATCH_SIZE = int(
    os.getenv(
        "SMART_SCRAPER_BATCH_SIZE",
        "100"
    )
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


def derive_source_job_id(job):
    existing = clean(
        job.get("id")
        or job.get("source_job_id")
    )

    if existing:
        return existing

    url = clean(
        job.get("job_url")
        or job.get("url")
    )

    if url:
        match = re.search(r"/jobs/(\\d+)", url)

        if match:
            return match.group(1)

        return "url-" + hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()[:24]

    fingerprint = "|".join([
        str(job.get("company_name") or job.get("company") or "").strip().lower(),
        str(job.get("job_title") or job.get("title") or "").strip().lower(),
        str(job.get("location") or job.get("job_location") or "").strip().lower(),
    ])

    return "fp-" + hashlib.sha256(
        fingerprint.encode("utf-8")
    ).hexdigest()[:24]


def canonicalize_url(value):
    value = clean(value)

    if not value:
        return None

    parts = urlparse(value)

    return parts._replace(
        query="",
        fragment=""
    ).geturl()


def plain_text(value):
    value = str(value or "")

    value = re.sub(
        r"<[^>]+>",
        " ",
        value
    )

    value = html.unescape(value)

    return re.sub(
        r"\s+",
        " ",
        value
    ).strip()


def parse_money(value):
    value = value.lower().replace(",", "").strip()

    multiplier = 1

    if value.endswith("k"):
        multiplier = 1000
        value = value[:-1]
    elif value.endswith("m"):
        multiplier = 1000000
        value = value[:-1]

    try:
        return round(
            float(value) * multiplier,
            2
        )
    except Exception:
        return None


def infer_structured_fields(job):
    text = plain_text(
        job.get("job_description")
        or job.get("description")
    )

    lower = text.lower()

    inferred = {}

    # Experience: only accept patterns explicitly tied to "experience".
    exp_match = re.search(
        r"\b(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\+?\s+years?"
        r"(?:\s+of)?\s+(?:relevant\s+|professional\s+|work\s+)?experience\b",
        lower,
    )

    if exp_match:
        inferred["experience_min"] = float(
            exp_match.group(1)
        )

        if exp_match.group(2):
            inferred["experience_max"] = float(
                exp_match.group(2)
            )

        inferred["experience_text"] = (
            exp_match.group(0)
        )

    # Salary: require an explicit compensation/salary context and a range.
    salary_context = re.search(
        r"(?:salary|compensation|base pay|base salary)"
        r".{0,180}?"
        r"(?:usd\s*)?\$\s*([0-9][0-9,.]*\s*[km]?)"
        r"\s*(?:-|–|—|to)\s*"
        r"(?:usd\s*)?\$\s*([0-9][0-9,.]*\s*[km]?)",
        lower,
    )

    if not salary_context:
        salary_context = re.search(
            r"(?:usd\s*)?\$\s*([0-9][0-9,.]*\s*[km]?)"
            r"\s*(?:-|–|—|to)\s*"
            r"(?:usd\s*)?\$\s*([0-9][0-9,.]*\s*[km]?)"
            r".{0,100}?(?:salary|compensation|base pay|base salary)",
            lower,
        )

    if salary_context:
        salary_min = parse_money(
            salary_context.group(1)
        )
        salary_max = parse_money(
            salary_context.group(2)
        )

        if (
            salary_min
            and salary_max
            and salary_max >= salary_min
            and salary_min >= 1000
        ):
            inferred["salary_min"] = salary_min
            inferred["salary_max"] = salary_max
            inferred["salary_currency"] = "USD"
            inferred["compensation"] = {
                "min": salary_min,
                "max": salary_max,
                "currency": "USD",
                "inferred": True,
            }

    # Work arrangement.
    if re.search(r"\bhybrid\b", lower):
        inferred["remote_type"] = "hybrid"
    elif re.search(
        r"\b(?:fully\s+remote|remote-first|remote role|work remotely|100% remote)\b",
        lower,
    ):
        inferred["remote_type"] = "remote"
        inferred["remote"] = True
    elif re.search(
        r"\b(?:on-site|onsite|in-office|in office)\b",
        lower,
    ):
        inferred["remote_type"] = "onsite"
        inferred["remote"] = False

    # Employment type.
    employment_patterns = [
        ("FULL_TIME", r"\b(?:full[- ]time|fulltime)\b"),
        ("PART_TIME", r"\b(?:part[- ]time|parttime)\b"),
        ("CONTRACT", r"\b(?:contract|contractor)\b"),
        ("INTERNSHIP", r"\b(?:internship|intern)\b"),
        ("TEMPORARY", r"\btemporary\b"),
    ]

    for employment_type, pattern in employment_patterns:
        if re.search(pattern, lower):
            inferred["job_type"] = employment_type
            break

    # Conservative skill extraction for matching.
    skill_patterns = {
        "Python": r"\bpython\b",
        "JavaScript": r"\bjavascript\b|\bjs\b",
        "TypeScript": r"\btypescript\b",
        "React": r"\breact(?:\.js|js)?\b",
        "Node.js": r"\bnode(?:\.js|js)?\b",
        "PHP": r"\bphp\b",
        "Laravel": r"\blaravel\b",
        "Flutter": r"\bflutter\b",
        "Dart": r"\bdart\b",
        "Java": r"\bjava\b",
        "Kotlin": r"\bkotlin\b",
        "Swift": r"\bswift\b",
        "AWS": r"\baws\b|amazon web services",
        "Azure": r"\bazure\b",
        "GCP": r"\bgcp\b|google cloud",
        "Docker": r"\bdocker\b",
        "Kubernetes": r"\bkubernetes\b|\bk8s\b",
        "PostgreSQL": r"\bpostgres(?:ql)?\b",
        "MySQL": r"\bmysql\b",
        "MongoDB": r"\bmongodb\b",
        "Redis": r"\bredis\b",
        "SQL": r"\bsql\b",
        "Machine Learning": r"\bmachine learning\b",
        "AI": r"\bartificial intelligence\b|\bai\b",
        "LLM": r"\bllms?\b|large language model",
        "NLP": r"\bnlp\b|natural language processing",
        "TensorFlow": r"\btensorflow\b",
        "PyTorch": r"\bpytorch\b",
        "Git": r"\bgit\b",
        "REST API": r"\brest(?:ful)?\s+api\b|\brest\b",
        "GraphQL": r"\bgraphql\b",
    }

    skills = []

    for skill, pattern in skill_patterns.items():
        if re.search(pattern, lower):
            skills.append(skill)

    if skills:
        inferred["skills"] = skills

    return inferred


def apply_inferred_fields(job):
    enriched = dict(job)
    inferred = infer_structured_fields(enriched)

    mapping = {
        "experience_min": ["experience_min"],
        "experience_max": ["experience_max"],
        "experience_text": ["experience", "experience_text"],
        "salary_min": ["salary_min"],
        "salary_max": ["salary_max"],
        "salary_currency": ["salary_currency"],
        "compensation": ["compensation"],
        "remote": ["remote"],
        "remote_type": ["remote_type", "remote_status"],
        "job_type": ["job_type", "employment_type"],
        "skills": ["skills"],
    }

    inferred_used = []

    for target, source_keys in mapping.items():
        has_existing = any(
            enriched.get(key) not in (
                None,
                "",
                [],
                {}
            )
            for key in source_keys
        )

        if has_existing:
            continue

        if target in inferred:
            enriched[target] = inferred[target]
            inferred_used.append(target)

    quality_points = 0
    quality_total = 10

    for key in [
        "job_title",
        "title",
        "job_description",
        "description",
        "job_url",
        "url",
        "company_name",
        "company_website",
        "company_linkedin",
        "skills",
    ]:
        if enriched.get(key) not in (
            None,
            "",
            [],
            {}
        ):
            quality_points += 1

    enriched["data_quality"] = {
        "score": round(
            min(
                quality_points,
                quality_total
            ) / quality_total * 100
        ),
        "inferred_fields": inferred_used,
        "method": "structured-source-plus-conservative-parser",
    }

    return enriched


def normalize_job(job):
    job = apply_inferred_fields(job)
    contact = job.get("contact") or {}

    return {
        "source": clean(
            job.get("source")
        ),

        "source_job_id": derive_source_job_id(job),

        "job_title": clean(
            job.get("job_title")
            or job.get("title")
        ),

        "role": clean(
            job.get("role")
        ),

        "job_description": clean(
            job.get("job_description")
            or job.get("description")
        ),

        "job_url": clean(
            job.get("job_url")
            or job.get("url")
        ),

        "canonical_job_url": canonicalize_url(
            job.get("canonical_job_url")
            or job.get("job_url")
            or job.get("url")
        ),

        "company_id": clean(
            job.get("company_id")
        ),

        "company_name": clean(
            job.get("company_name")
            or job.get("company")
        ),

        "company_slug": clean(
            job.get("company_slug")
        ),

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

        "company_size": clean(
            job.get("company_size")
        ),

        "job_location": normalize_list(
            job.get("location")
            or job.get("job_location")
        ),

        "remote": job.get(
            "remote"
        ),

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

        "experience_min": job.get(
            "experience_min"
        ),

        "experience_max": job.get(
            "experience_max"
        ),

        "experience_text": clean(
            job.get("experience")
        ),

        "skills": normalize_list(
            job.get("skills")
        ),

        "compensation": job.get(
            "compensation"
        ),

        "salary_min": job.get(
            "salary_min"
        ),

        "salary_max": job.get(
            "salary_max"
        ),

        "salary_currency": clean(
            job.get("salary_currency")
        ),

        "equity": job.get(
            "equity"
        ),

        "visa_sponsorship": job.get(
            "visa_sponsorship"
        ),

        "posted_timestamp": clean(
            job.get("posted_timestamp")
        ),

        "hiring_contact": clean(
            job.get("hiring_contact")
            or contact.get(
                "hiring_contact"
            )
        ),

        "hiring_manager": clean(
            contact.get(
                "hiring_manager"
            )
        ),

        "founders": normalize_list(
            contact.get(
                "founders"
            )
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

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:
        jobs = json.load(f)

    if not isinstance(jobs, list):
        raise ValueError(
            "Input JSON must contain "
            "a list of jobs."
        )

    return jobs


def get_endpoint():
    if not API_URL:
        raise RuntimeError(
            "SMART_SCRAPER_API_URL "
            "is missing"
        )

    if API_URL.endswith(
        "ingest.php"
    ):
        return API_URL

    return (
        f"{API_URL}"
        f"/api/v1/smart_scraper/"
        f"ingest.php"
    )


def send_batch(
    batch,
    batch_number,
    mode,
    source_name,
):
    if not INGEST_TOKEN:
        raise RuntimeError(
            "SMART_SCRAPER_INGEST_TOKEN "
            "is missing"
        )

    endpoint = get_endpoint()

    payload = {
        "run_id": (
            RUN_ID
            or None
        ),

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
                f"Bearer "
                f"{INGEST_TOKEN}"
            ),
            "Accept": (
                "application/json"
            ),
            "Content-Type": (
                "application/json"
            ),
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
        result = response.json()

    except Exception as exc:
        raise RuntimeError(
            "API returned invalid JSON: "
            f"{response.text}"
        ) from exc

    if not isinstance(
        result,
        dict
    ):
        raise RuntimeError(
            "API returned unexpected "
            "JSON response."
        )

    if result.get("ok") is False:
        raise RuntimeError(
            f"API rejected batch: "
            f"{result}"
        )

    return result


def ingest_file(
    input_file,
    mode,
    source_name,
    batch_size,
):
    jobs = load_jobs(
        input_file
    )

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
            start:
            start + batch_size
        ]

        print(
            f"Sending batch "
            f"{batch_number} "
            f"with {len(batch)} "
            f"jobs..."
        )

        result = send_batch(
            batch=batch,
            batch_number=batch_number,
            mode=mode,
            source_name=source_name,
        )

        inserted = int(
            result.get(
                "new",
                result.get(
                    "inserted",
                    0
                )
            )
        )

        updated = int(
            result.get(
                "updated",
                0
            )
        )

        duplicates = int(
            result.get(
                "duplicates",
                0
            )
        )

        failed = int(
            result.get(
                "failed",
                0
            )
        )

        totals[
            "received"
        ] += len(batch)

        totals[
            "inserted"
        ] += inserted

        totals[
            "updated"
        ] += updated

        totals[
            "duplicates"
        ] += duplicates

        totals[
            "failed"
        ] += failed

        print(
            f"Batch {batch_number}: "
            f"inserted={inserted} "
            f"updated={updated} "
            f"duplicates={duplicates} "
            f"failed={failed}"
        )

        if result.get(
            "run_new_total"
        ) is not None:

            print(
                "Run new total: "
                f"{result.get('run_new_total')}"
                f"/"
                f"{result.get('target')}"
            )

        if result.get(
            "target_reached"
        ) is True:

            print(
                "Target reached."
            )

        batch_number += 1

    print()
    print(
        "Ingestion finished"
    )

    for key, value in (
        totals.items()
    ):
        print(
            f"{key}: {value}"
        )

    return totals


def main():
    parser = (
        argparse.ArgumentParser()
    )

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
        default=(
            DEFAULT_BATCH_SIZE
        ),
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