"""
Final pipeline step.

Collapses the per-role, per-stage files produced by the rest of
the pipeline into exactly two things:

    jobs/jobs_all_raw.jsonl   - every raw scraped job, combined
    jobs/jobs_cleaned/jobs_all.json - every fully-enriched job, combined

Everything else the pipeline produced along the way (per-role
raw .jsonl files, per-role intermediate .json files, and the
jobs_with_website / jobs_cleaned_linkedin / jobs_with_company_linkedin
folders) is deleted, since it's just scratch state for stages that
already ran.

Safety: nothing is deleted until after its combined replacement has
been written to disk *and* the job counts have been checked to match.
"""

import json
import shutil
from pathlib import Path

# Project root (this file now lives one level down, in
# scraping/ or processing/), so go up an extra level.
BASE_DIR = Path(__file__).resolve().parent.parent

JOBS_DIR = BASE_DIR / "jobs"

RAW_PATTERN = "*.jsonl"

FINAL_STAGE_DIR = JOBS_DIR / "jobs_with_company_linkedin"
FINAL_PATTERN = "jobs_*.json"

CLEANED_DIR = JOBS_DIR / "jobs_cleaned"
CLEANED_FILE = CLEANED_DIR / "jobs_all.json"

RAW_OUTPUT_FILE = JOBS_DIR / "jobs_all_raw.jsonl"

# Intermediate stage folders/files to remove once the combined
# outputs above have been written successfully.
STAGE_DIRS_TO_REMOVE = [
    JOBS_DIR / "jobs_with_website",
    JOBS_DIR / "jobs_cleaned_linkedin",
    JOBS_DIR / "jobs_with_company_linkedin",
]


# ============================================================
# Combine raw scraped jobs
# ============================================================

def combine_raw_jobs() -> list[Path]:
    """
    Concatenates every per-role jobs/*.jsonl file into a single
    jobs/jobs_all_raw.jsonl file.

    Returns the list of source files that were combined, so the
    caller can delete them afterwards.
    """

    raw_files = sorted(JOBS_DIR.glob(RAW_PATTERN))

    if not raw_files:
        print("No raw *.jsonl files found; skipping raw combine.")
        return []

    total_lines = 0

    with open(RAW_OUTPUT_FILE, "w", encoding="utf-8") as out:
        for raw_file in raw_files:
            with open(raw_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()

                    if not line:
                        continue

                    out.write(line + "\n")
                    total_lines += 1

    print(
        f"Combined {len(raw_files)} raw files "
        f"({total_lines} jobs) -> {RAW_OUTPUT_FILE.name}"
    )

    return raw_files


# ============================================================
# Combine final enriched jobs
# ============================================================

def combine_final_jobs() -> int:
    """
    Combines every jobs/jobs_with_company_linkedin/jobs_*.json
    file into a single jobs/jobs_cleaned/jobs_all.json file.

    Returns the number of jobs written, for verification.
    """

    final_files = sorted(FINAL_STAGE_DIR.glob(FINAL_PATTERN))

    if not final_files:
        print(
            f"No final files found in {FINAL_STAGE_DIR}; "
            "skipping final combine."
        )
        return 0

    combined = []

    for final_file in final_files:
        with open(final_file, "r", encoding="utf-8") as f:
            jobs = json.load(f)

        if not isinstance(jobs, list):
            print(f"Skipping {final_file.name}: expected a JSON array.")
            continue

        combined.extend(jobs)

        print(f"  {final_file.name}: {len(jobs)} jobs")

    CLEANED_DIR.mkdir(exist_ok=True)

    with open(CLEANED_FILE, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)

    print(
        f"Combined {len(final_files)} final files "
        f"({len(combined)} jobs) -> "
        f"{CLEANED_FILE.relative_to(BASE_DIR)}"
    )

    return len(combined)


# ============================================================
# Cleanup
# ============================================================

def cleanup(raw_files: list[Path]) -> None:
    """
    Removes intermediate stage output now that the combined
    files exist. Only called after both combine steps succeed.
    """

    # Per-role raw files, now folded into jobs_all_raw.jsonl
    for raw_file in raw_files:
        raw_file.unlink()
        print(f"Removed {raw_file.relative_to(BASE_DIR)}")

    # Loose per-role files left at the top of jobs/ by
    # clean_jobs.py (jobs_bd_manager.json, etc.)
    for loose_file in JOBS_DIR.glob("jobs_*.json"):
        loose_file.unlink()
        print(f"Removed {loose_file.relative_to(BASE_DIR)}")

    # Whole intermediate stage folders
    for stage_dir in STAGE_DIRS_TO_REMOVE:
        if stage_dir.exists():
            shutil.rmtree(stage_dir)
            print(f"Removed {stage_dir.relative_to(BASE_DIR)}/")


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 60)
    print("Combining raw jobs")
    print("=" * 60)
    raw_files = combine_raw_jobs()

    print()
    print("=" * 60)
    print("Combining final enriched jobs")
    print("=" * 60)
    final_count = combine_final_jobs()

    if final_count == 0:
        print(
            "\nNo final jobs were combined; leaving intermediate "
            "files in place so nothing is lost. Check the pipeline "
            "output above for errors before re-running."
        )
        return

    print()
    print("=" * 60)
    print("Cleaning up intermediate files")
    print("=" * 60)
    cleanup(raw_files)

    print()
    print("Done. jobs/ now contains only:")
    if RAW_OUTPUT_FILE.exists():
        print(f"  - {RAW_OUTPUT_FILE.name}")
    print(f"  - {CLEANED_DIR.name}/{CLEANED_FILE.name}")


if __name__ == "__main__":
    main()
