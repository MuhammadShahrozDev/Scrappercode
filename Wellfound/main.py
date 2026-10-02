import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

scripts = [
    "scraping/start_scraping.py",
    "processing/clean_jobs.py",
    "processing/wellfound_company_websites_01.py",
    "processing/normalize_linkedin_urls.py",
    "processing/search_company_linkedin.py",
    "processing/filter_company_linkedins.py",
    "processing/combine_and_cleanup.py",
]

failures = []

for script in scripts:
    print(f"\n{'=' * 60}")
    print(f"Running {script}")
    print(f"{'=' * 60}\n")

    result = subprocess.run(
        [sys.executable, str(BASE_DIR / script)],
    )

    if result.returncode != 0:
        print(f"[!] {script} failed with exit code {result.returncode}")
        failures.append(script)

if failures:
    print(f"\n[!] Wellfound pipeline had {len(failures)} failed step(s): {', '.join(failures)}")
else:
    print("\nPipeline completed successfully.")