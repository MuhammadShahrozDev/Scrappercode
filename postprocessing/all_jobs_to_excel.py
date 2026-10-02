import json
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent

INPUT_FILE = BASE_DIR / "jobs" / "jobs_combined.json"
OUTPUT_FILE = BASE_DIR / "jobs" / "jobs_combined.xlsx"


def main():

    # ----------------------------------------------------------
    # Load JSON
    # ----------------------------------------------------------

    print(f"Reading {INPUT_FILE}")

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    print(f"Loaded {len(jobs)} jobs")


    # ----------------------------------------------------------
    # Convert to DataFrame
    # ----------------------------------------------------------

    df = pd.DataFrame(jobs)


    # ----------------------------------------------------------
    # Save to Excel
    # ----------------------------------------------------------

    df.to_excel(
        OUTPUT_FILE,
        index=False,
        engine="openpyxl",
    )


    # ----------------------------------------------------------
    # Done
    # ----------------------------------------------------------

    print()
    print("=" * 60)
    print("Finished")
    print("=" * 60)

    print(f"Rows: {len(df)}")
    print(f"Columns: {len(df.columns)}")
    print(f"Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()