"""
Turn the Upwork pipeline output into lead rows the shared ingestion script understands.

A lead = an Upwork job whose client was matched to a LinkedIn profile.

Inputs  (Upwork/data/):
  upwork_agentic_ai_jobs_industry.json   job + client + company + industry
  linkedin_matching_results.json         best LinkedIn profile per job (Gemini / exact-name filter)
  linkedin_client_profile_details.json   scraped profile details (headline, company, location)

Output:
  Upwork/data/jobs_upwork.json           list of rows, source = "upwork"
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

JOBS_FILE = DATA_DIR / "upwork_agentic_ai_jobs_industry.json"
MATCH_FILE = DATA_DIR / "linkedin_matching_results.json"
PROFILE_FILE = DATA_DIR / "linkedin_client_profile_details.json"
OUTPUT_FILE = DATA_DIR / "jobs_upwork.json"


def load_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def norm_url(url: Any) -> str:
    return str(url or "").strip().rstrip("/").lower()


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def first(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def build_rows() -> list[dict[str, Any]]:
    jobs = {str(j.get("job_id")): j for j in load_list(JOBS_FILE)}

    profiles: dict[str, dict[str, Any]] = {}
    for record in load_list(PROFILE_FILE):
        details = as_dict(record.get("profile_details"))
        url = norm_url(record.get("linkedin_profile_url"))
        if url and details:
            profiles[url] = details

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in load_list(MATCH_FILE):
        if item.get("error"):
            continue

        result = as_dict(item.get("result"))
        best = as_dict(result.get("best_match"))
        profile_url = str(best.get("linkedin_profile_url") or "").strip()
        if not profile_url:
            continue

        job_id = str(item.get("id") or "")
        job = jobs.get(job_id)
        if not job or job_id in seen:
            continue
        seen.add(job_id)

        saved = as_dict(as_dict(item.get("saved_profile")).get("profile_details"))
        profile = profiles.get(norm_url(profile_url)) or saved

        client_info = as_dict(job.get("client_info"))
        location = as_dict(job.get("client_location"))
        industry = as_dict(job.get("industry_final"))

        company_name = first(
            job.get("company_name_final"),
            client_info.get("company_name"),
            profile.get("current_company"),
        )
        person_name = first(
            profile.get("name"),
            best.get("name"),
            job.get("client_name_final"),
        )

        rows.append({
            "id": f"upwork-{job_id}",
            "source": "upwork",
            "title": job.get("title"),
            "role": client_info.get("job_category"),
            "description": job.get("description"),
            "url": job.get("url"),
            "company_name": company_name,
            "company_size": client_info.get("company_size"),
            "company_location": [location["formatted"]] if location.get("formatted") else [],
            "location": [location["formatted"]] if location.get("formatted") else [],
            "posted_timestamp": job.get("scraped_at"),
            "hiring_contact": first(job.get("client_name_final"), person_name),
            "person_1_name": person_name,
            "person_1_role": profile.get("headline"),
            "person_1_profile_url": profile_url,
            "industry": industry.get("label"),
            "match_status": result.get("match_status"),
            "match_confidence": best.get("confidence"),
            "upwork_job_id": job_id,
            "linkedin_enriched": True,
        })

    return rows


def main() -> int:
    rows = build_rows()
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUTPUT_FILE)
    print(f"Upwork leads (client matched to a LinkedIn profile): {len(rows)}")
    print(f"Saved: {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
