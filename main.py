import os
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

TARGET_NEW = int(
    os.getenv("SMART_SCRAPER_TARGET", "500")
)

BATCH_SIZE = int(
    os.getenv("SMART_SCRAPER_BATCH_SIZE", "100")
)

MAX_RUNTIME_MINUTES = int(
    os.getenv(
        "SMART_SCRAPER_MAX_RUNTIME_MINUTES",
        "180"
    )
)

SOURCE = os.getenv(
    "SMART_SCRAPER_SOURCE",
    "all"
).strip().lower()

VALID_SOURCES = {
    "all",
    "ycombinator",
    "linkedin",
    "wellfound",
}

if SOURCE not in VALID_SOURCES:
    print(
        f"[ERROR] Invalid SMART_SCRAPER_SOURCE: {SOURCE}. "
        f"Allowed: {', '.join(sorted(VALID_SOURCES))}",
        file=sys.stderr,
    )
    sys.exit(2)

MAX_RUNTIME_SECONDS = (
    MAX_RUNTIME_MINUTES * 60
)


YC_PIPELINE = (
    BASE_DIR / "YCombinator" / "main.py"
)

WF_PIPELINE = (
    BASE_DIR / "Wellfound" / "main.py"
)

LINKEDIN_PIPELINE = (
    BASE_DIR
    / "Linkedin-Scrapper"
    / "main.py"
)

INGEST_SCRIPT = (
    BASE_DIR
    / "postprocessing"
    / "save_to_mysql.py"
)


YC_OUTPUT = (
    BASE_DIR
    / "YCombinator"
    / "data"
    / "jobs_ycombinator.json"
)

WF_OUTPUT = (
    BASE_DIR
    / "Wellfound"
    / "jobs"
    / "jobs_wellfound.json"
)

LINKEDIN_OUTPUT = (
    BASE_DIR
    / "Linkedin-Scrapper"
    / "jobs"
    / "jobs_wellfound.json"
)


def elapsed(started_at):
    return time.monotonic() - started_at


def remaining_seconds(started_at):
    remaining = (
        MAX_RUNTIME_SECONDS
        - elapsed(started_at)
    )

    return max(0, int(remaining))


def time_exhausted(started_at):
    return remaining_seconds(started_at) <= 0


def should_run(source_name):
    return SOURCE == "all" or SOURCE == source_name


def run_command(
    command,
    cwd,
    started_at,
    label,
):
    remaining = remaining_seconds(started_at)

    if remaining <= 0:
        print(
            f"[TIME] No time remaining "
            f"before {label}."
        )
        return False

    print("")
    print("=" * 70)
    print(f"Running: {label}")
    print(
        f"Remaining runtime: "
        f"{remaining // 60} minutes"
    )
    print("=" * 70)

    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            timeout=remaining,
        )

    except subprocess.TimeoutExpired:
        print(
            f"[TIME] {label} reached "
            f"the smart_scraper runtime limit."
        )
        return False

    if result.returncode != 0:
        print(
            f"[WARN] {label} failed "
            f"with exit code "
            f"{result.returncode}."
        )
        return False

    return True


def run_python_script(
    script_path,
    started_at,
    label,
):
    if not script_path.exists():
        print(
            f"[WARN] Missing script: "
            f"{script_path}"
        )
        return False

    return run_command(
        command=[
            sys.executable,
            str(script_path),
        ],
        cwd=script_path.parent,
        started_at=started_at,
        label=label,
    )


def ingest_file(
    file_path,
    source,
    mode,
    started_at,
):
    if time_exhausted(started_at):
        print(
            f"[TIME] Skipping {source} "
            f"{mode}; runtime exhausted."
        )
        return False

    if not file_path.exists():
        print(
            f"[WARN] Cannot ingest "
            f"{source}. Missing file: "
            f"{file_path}"
        )
        return False

    command = [
        sys.executable,
        str(INGEST_SCRIPT),
        "--file",
        str(file_path),
        "--source",
        source,
        "--mode",
        mode,
        "--batch-size",
        str(BATCH_SIZE),
    ]

    return run_command(
        command=command,
        cwd=BASE_DIR,
        started_at=started_at,
        label=(
            f"{source} {mode} ingestion"
        ),
    )


def run_ycombinator(started_at, failures):
    yc_ok = run_python_script(
        script_path=YC_PIPELINE,
        started_at=started_at,
        label="Y Combinator acquisition",
    )

    if not yc_ok:
        failures.append(
            "Y Combinator acquisition"
        )

    if YC_OUTPUT.exists():
        yc_ingest_ok = ingest_file(
            file_path=YC_OUTPUT,
            source="ycombinator",
            mode="acquisition",
            started_at=started_at,
        )

        if not yc_ingest_ok:
            failures.append(
                "Y Combinator ingestion"
            )


def run_wellfound(started_at, failures):
    if time_exhausted(started_at):
        return

    wf_ok = run_python_script(
        script_path=WF_PIPELINE,
        started_at=started_at,
        label="Wellfound acquisition",
    )

    if not wf_ok:
        failures.append(
            "Wellfound acquisition"
        )

    if WF_OUTPUT.exists():
        wf_ingest_ok = ingest_file(
            file_path=WF_OUTPUT,
            source="wellfound",
            mode="acquisition",
            started_at=started_at,
        )

        if not wf_ingest_ok:
            failures.append(
                "Wellfound ingestion"
            )


def run_linkedin(started_at, failures):
    if time_exhausted(started_at):
        return

    linkedin_input = (
        BASE_DIR
        / "Wellfound"
        / "jobs"
        / "jobs_cleaned"
        / "jobs_all.json"
    )

    if not linkedin_input.exists():
        print(
            "[WARN] LinkedIn enrichment requires "
            "Wellfound/jobs/jobs_cleaned/jobs_all.json."
        )
        failures.append(
            "LinkedIn input data missing"
        )
        return

    linkedin_ok = run_python_script(
        script_path=LINKEDIN_PIPELINE,
        started_at=started_at,
        label="LinkedIn enrichment",
    )

    if not linkedin_ok:
        failures.append(
            "LinkedIn enrichment"
        )

    if LINKEDIN_OUTPUT.exists():
        linkedin_ingest_ok = ingest_file(
            file_path=LINKEDIN_OUTPUT,
            source="linkedin",
            mode="enrichment",
            started_at=started_at,
        )

        if not linkedin_ingest_ok:
            failures.append(
                "LinkedIn enrichment ingestion"
            )


def main():
    started_at = time.monotonic()

    print("")
    print("=" * 70)
    print("smart_scraper started")
    print("=" * 70)

    print(
        f"Source: {SOURCE}"
    )

    print(
        f"Target new unique jobs: "
        f"{TARGET_NEW}"
    )

    print(
        f"Batch size: {BATCH_SIZE}"
    )

    print(
        f"Maximum runtime: "
        f"{MAX_RUNTIME_MINUTES} minutes"
    )

    failures = []

    if should_run("ycombinator"):
        run_ycombinator(
            started_at,
            failures,
        )

    if should_run("wellfound"):
        run_wellfound(
            started_at,
            failures,
        )

    if should_run("linkedin"):
        run_linkedin(
            started_at,
            failures,
        )

    total_seconds = int(
        elapsed(started_at)
    )

    total_minutes = round(
        total_seconds / 60,
        2,
    )

    print("")
    print("=" * 70)
    print("smart_scraper finished")
    print("=" * 70)

    print(
        f"Runtime: {total_minutes} minutes"
    )

    if time_exhausted(started_at):
        print(
            "Reason: maximum runtime "
            "reached."
        )

    if failures:
        print(
            "Completed with warnings:"
        )

        for failure in failures:
            print(
                f" - {failure}"
            )

        sys.exit(0)

    print(
        "All selected stages "
        "completed successfully."
    )


if __name__ == "__main__":
    main()
