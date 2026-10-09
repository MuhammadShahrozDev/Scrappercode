import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

SCRIPTS = [
    "scraping/start_scraping.py",
    "processing/clean_jobs.py",
    "processing/wellfound_company_websites_01.py",
    "processing/normalize_linkedin_urls.py",
    "processing/search_company_linkedin.py",
    "processing/filter_company_linkedins.py",
    "processing/combine_and_cleanup.py",
]

FINAL_OUTPUT = (
    BASE_DIR
    / "jobs"
    / "jobs_cleaned"
    / "jobs_all.json"
)


def main():
    for script in SCRIPTS:
        print()
        print("=" * 60)
        print(f"Running {script}")
        print("=" * 60)
        print()

        result = subprocess.run(
            [sys.executable, str(BASE_DIR / script)],
            cwd=str(BASE_DIR),
        )

        if result.returncode != 0:
            print(
                f"[ERROR] {script} failed "
                f"with exit code {result.returncode}"
            )
            sys.exit(result.returncode or 1)

    if not FINAL_OUTPUT.exists():
        print(
            "[ERROR] Wellfound pipeline completed "
            "without fresh final output."
        )
        sys.exit(1)

    print()
    print("Pipeline completed successfully.")


if __name__ == "__main__":
    main()
