"""
Upwork lead pipeline runner (unattended).

Each cycle scrapes a batch of new Upwork jobs, then runs the identification steps:
  upw_scraper -> client_extraction -> company_extraction -> industry_extraction
  -> google_profile_search -> linkedin_profile_scrape -> gemini_profile_matching -> to_leads

Cycles repeat until UPWORK_TARGET_LEADS leads exist, the time budget ends, or no new jobs appear.
Every step resumes from its own output file, so a cycle only pays for new jobs.

Environment:
  UPWORK_TARGET_LEADS            leads wanted (default: SMART_SCRAPER_TARGET or 50)
  UPWORK_MAX_RUNTIME_SECONDS     time budget for this stage (default 3600)
  UPWORK_BATCH_JOBS              new jobs scraped per cycle (default 60)
  UPWORK_MAX_CYCLES              safety limit (default 12)
  UPWORK_QUERY, UPWORK_STORAGE_STATE_B64, UPWORK_PROXY, GEMINI_API_KEY, LINKEDIN_LI_AT  (see README)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
JOBS_FILE = DATA_DIR / "upwork_agentic_ai_jobs.json"
LEADS_FILE = DATA_DIR / "jobs_upwork.json"

TARGET = int(os.getenv("UPWORK_TARGET_LEADS") or os.getenv("SMART_SCRAPER_TARGET") or "50")
MAX_RUNTIME = int(os.getenv("UPWORK_MAX_RUNTIME_SECONDS", "3600"))
BATCH_JOBS = int(os.getenv("UPWORK_BATCH_JOBS", "60"))
MAX_CYCLES = int(os.getenv("UPWORK_MAX_CYCLES", "12"))

STARTED = time.monotonic()


def remaining() -> int:
    return max(0, int(MAX_RUNTIME - (time.monotonic() - STARTED)))


def count_json(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return len(data) if isinstance(data, list) else 0
    except Exception:
        return 0


def run(script: str, *args: str, env: dict | None = None) -> bool:
    left = remaining()
    if left <= 0:
        print(f"[TIME] No time left before {script}.")
        return False

    print(f"\n{'=' * 60}\nUpwork step: {script} {' '.join(args)}  (time left: {left // 60} min)\n{'=' * 60}")
    merged = {**os.environ, **(env or {})}
    try:
        result = subprocess.run(
            [sys.executable, str(BASE_DIR / script), *args],
            cwd=str(BASE_DIR),
            env=merged,
            timeout=left,
        )
    except subprocess.TimeoutExpired:
        print(f"[TIME] {script} hit the Upwork time budget.")
        return False

    if result.returncode != 0:
        print(f"[WARN] {script} exited with code {result.returncode}")
        return False
    return True


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Upwork pipeline: target {TARGET} leads, budget {MAX_RUNTIME // 60} min, batch {BATCH_JOBS} jobs")

    leads = count_json(LEADS_FILE)

    for cycle in range(1, MAX_CYCLES + 1):
        if leads >= TARGET:
            print(f"Target reached: {leads}/{TARGET} leads.")
            break
        if remaining() <= 0:
            print("Time budget used up.")
            break

        jobs_before = count_json(JOBS_FILE)
        print(f"\n##### Upwork cycle {cycle}: {leads}/{TARGET} leads, {jobs_before} jobs scraped so far #####")

        scraper_ok = run("upw_scraper.py", env={"UPWORK_JOBS_PER_RUN": str(BATCH_JOBS)})
        jobs_after = count_json(JOBS_FILE)

        if not scraper_ok and jobs_after == 0:
            print("[ERROR] Upwork scraper produced nothing (login/bot-check problem). Stopping.")
            return 1

        run("client_extraction.py")
        run("company_extraction.py", "all")
        run("industry_extraction.py", "all")
        run("google_profile_search.py")
        run("linkedin_profile_scrape.py")
        run("gemini_profile_matching.py")
        run("to_leads.py")

        leads = count_json(LEADS_FILE)

        if jobs_after <= jobs_before:
            print("No new Upwork jobs were scraped in this cycle; stopping.")
            break

    print(f"\nUpwork pipeline finished with {leads} lead(s).")
    return 0 if leads > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
