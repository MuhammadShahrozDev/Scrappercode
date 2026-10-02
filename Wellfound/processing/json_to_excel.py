import json
from pathlib import Path

import pandas as pd


# ============================================================
# Configuration
# ============================================================
# Project root (this file now lives one level down, in
# scraping/ or processing/), so go up an extra level.
BASE_DIR = Path(__file__).resolve().parent.parent

JOBS_DIR = BASE_DIR / "jobs"
EXCEL_DIR = BASE_DIR / JOBS_DIR / "excel_files"

EXCEL_DIR.mkdir(parents=True, exist_ok=True)

COMBINED_FILE = BASE_DIR / EXCEL_DIR / "all_jobs.xlsx"


# ============================================================
# Helpers
# ============================================================

def load_json_file(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        if "jobs" in data and isinstance(data["jobs"], list):
            return data["jobs"]

        return [data]

    return []


def jobs_to_dataframe(jobs):
    df = pd.json_normalize(jobs)

    for column in df.columns:

        df[column] = df[column].apply(
            lambda value:
                json.dumps(
                    value,
                    ensure_ascii=False
                )
                if isinstance(value, (dict, list))
                else value
        )

    return df


# ============================================================
# Main
# ============================================================

def main():

    json_files = sorted(
        JOBS_DIR.glob("jobs_*.json")
    )

    if not json_files:
        print(
            f"No jobs_*.json files found in {JOBS_DIR}"
        )
        return

    all_jobs = []

    print(
        f"Found {len(json_files)} JSON files."
    )

    # --------------------------------------------------------
    # Separate Excel file for each JSON
    # --------------------------------------------------------

    for json_file in json_files:

        print(
            f"\nProcessing: {json_file.name}"
        )

        jobs = load_json_file(json_file)

        if not jobs:
            print(
                "  No jobs found. Skipping."
            )
            continue

        all_jobs.extend(jobs)

        df = jobs_to_dataframe(jobs)

        output_file = (
            EXCEL_DIR /
            f"{json_file.stem}.xlsx"
        )

        df.to_excel(
            output_file,
            index=False,
            engine="openpyxl",
        )

        print(
            f"  Jobs: {len(jobs)}"
        )

        print(
            f"  Saved: {output_file}"
        )

    # --------------------------------------------------------
    # Combined Excel
    # --------------------------------------------------------

    if all_jobs:

        combined_df = jobs_to_dataframe(
            all_jobs
        )

        combined_df.to_excel(
            COMBINED_FILE,
            index=False,
            engine="openpyxl",
        )

        print(
            "\n" + "=" * 60
        )

        print(
            f"Total jobs: {len(all_jobs)}"
        )

        print(
            f"Combined file: {COMBINED_FILE}"
        )

        print(
            "=" * 60
        )


if __name__ == "__main__":
    main()