import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

scripts = [
    "extract_companies.py",
    "scraper.py",
    "add_linkedin_to_wf_jobs.py",
]

for script in scripts:
    print(f"\n{'=' * 60}")
    print(f"Running {script}")
    print(f"{'=' * 60}\n")

    subprocess.run(
        [sys.executable, str(BASE_DIR / script)],
        check=True,
    )

print("\nLinkedin pipeline completed successfully.")
print("Final output: jobs/jobs_wellfound.json")
