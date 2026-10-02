import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

scripts = [
    "algolia.py",
    "fetch_companies.py",
    "clean_data.py",
    "normalize_jobs.py",
]

failures = []

for script in scripts:
    script_path = BASE_DIR / script

    print(f"\n{'=' * 60}")
    print(f"Running {script}")
    print(f"{'=' * 60}\n")

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(BASE_DIR)
    )

    if result.returncode != 0:
        print(f"[!] {script} failed with exit code {result.returncode}")
        failures.append(script)

if failures:
    print(f"\n[!] Y Combinator pipeline had {len(failures)} failed step(s): {', '.join(failures)}")
else:
    print("\nPipeline completed successfully.")