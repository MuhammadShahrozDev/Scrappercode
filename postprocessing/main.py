import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

scripts = [
    "combine_sources.py",
    "all_jobs_to_excel.py",
    "separate_jobs.py",
    "save_to_mysql.py",
]

for script in scripts:
    print(f"\n{'=' * 60}")
    print(f"Running {script}")
    print(f"{'=' * 60}\n")

    subprocess.run(
        [sys.executable, str(BASE_DIR / script)],
        check=True,
    )

print("\npostprocessing pipeline completed successfully.")
print("Final output: jobs/jobs_combined_filtered.xlsx")
print("Jobs synchronized with Hostinger MySQL successfully.")