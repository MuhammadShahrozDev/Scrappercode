import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Sibling projects. Each owns its own source and hands off one
# final file in the same flattened row schema (source, job_title,
# company_name, person_N_name, ...).
YC_FILE = BASE_DIR.parent / "YCombinator" / "data" / "jobs_ycombinator.json"
WF_FILE = BASE_DIR.parent / "Linkedin-Scrapper" / "jobs" / "jobs_wellfound.json"

OUTPUT_FILE = BASE_DIR / "jobs" / "jobs_combined.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():

    print(f"Reading {YC_FILE}")
    yc_jobs = load_json(YC_FILE)
    print(f"Loaded {len(yc_jobs)} YC jobs")

    print(f"Reading {WF_FILE}")
    wf_jobs = load_json(WF_FILE)
    print(f"Loaded {len(wf_jobs)} Wellfound jobs")

    # Combine
    combined = yc_jobs + wf_jobs

    # Save
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            combined,
            f,
            indent=2,
            ensure_ascii=False,
        )

    print()
    print("=" * 60)
    print("Finished")
    print("=" * 60)
    print(f"YC jobs:       {len(yc_jobs)}")
    print(f"Wellfound jobs: {len(wf_jobs)}")
    print(f"Total jobs:    {len(combined)}")
    print(f"Saved to:      {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
