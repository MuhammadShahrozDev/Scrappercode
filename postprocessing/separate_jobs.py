"""
filter jobs based on linkedin link present or not
"""

from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

INPUT_FILE = BASE_DIR / "jobs" / "jobs_combined.xlsx"
OUTPUT_FILE = PROJECT_ROOT / "jobs_combined_filtered.xlsx"


# Load Excel
df = pd.read_excel(INPUT_FILE)


# ----------------------------------------------------------
# Separate based on person_1_name
# ----------------------------------------------------------

person1_present = df[
    df["person_1_name"].notna()
    & (df["person_1_name"].astype(str).str.strip() != "")
]

no_person1 = df[
    df["person_1_name"].isna()
    | (df["person_1_name"].astype(str).str.strip() == "")
]


# ----------------------------------------------------------
# Write Excel
# ----------------------------------------------------------

with pd.ExcelWriter(
    OUTPUT_FILE,
    engine="openpyxl",
) as writer:

    df.to_excel(
        writer,
        sheet_name="All Jobs",
        index=False,
    )

    person1_present.to_excel(
        writer,
        sheet_name="Person 1 Present",
        index=False,
    )

    no_person1.to_excel(
        writer,
        sheet_name="No Person 1",
        index=False,
    )


# ----------------------------------------------------------
# Summary
# ----------------------------------------------------------

print("=" * 60)
print("Finished")
print("=" * 60)

print(f"Total jobs:       {len(df)}")
print(f"Person 1 present: {len(person1_present)}")
print(f"No Person 1:      {len(no_person1)}")
print(f"Saved to:         {OUTPUT_FILE}")