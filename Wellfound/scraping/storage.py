import json
import os
from pathlib import Path

# JOBS_FILE = "jobs.jsonl"

# Project root (this file now lives one level down, in
# scraping/ or processing/), so go up an extra level.
BASE_DIR = Path(__file__).resolve().parent.parent
JOBS_DIR = BASE_DIR / "jobs"

os.makedirs(JOBS_DIR, exist_ok=True)
CACHE_DIR = BASE_DIR / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

# Resume-progress state, not final data - lives in .cache/
ROLES_FILE = CACHE_DIR / "completed_roles.json"

def role_filename(role_title):
    """
    Converts a role title into a safe filename.
    """

    name = (
        role_title.lower()
        .replace("/", "_")
        .replace("\\", "_")
        .replace(" ", "_")
    )

    return os.path.join(JOBS_DIR, f"{name}.jsonl")

def load_seen_job_ids():
    """
    Returns a set containing every job_id already saved.
    Looks through every .jsonl file in the jobs directory.
    """

    seen = set()

    if not os.path.exists(JOBS_DIR):
        return seen

    for filename in os.listdir(JOBS_DIR):

        if not filename.endswith(".jsonl"):
            continue

        filepath = os.path.join(JOBS_DIR, filename)

        with open(filepath, "r", encoding="utf-8") as f:

            for line in f:

                line = line.strip()

                if not line:
                    continue

                try:
                    job = json.loads(line)
                    seen.add(job["id"])

                except Exception:
                    continue

    return seen


def append_job(job, role_title):
    """
    Appends a single job to jobs.jsonl.
    """

    filename = role_filename(role_title)

    with open(filename, "a", encoding="utf-8") as f:
        f.write(json.dumps(job, ensure_ascii=False) + "\n")


def load_completed_roles():
    """
    Returns a set of completed role IDs.
    """

    if not os.path.exists(ROLES_FILE):
        return set()

    with open(ROLES_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))


def mark_role_complete(role_id):
    """
    Marks a role as completed.
    """

    completed = load_completed_roles()

    completed.add(str(role_id))

    with open(ROLES_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(completed), f, indent=4)

def reset_run_state():
    """Clear stale Wellfound artifacts before a fresh acquisition run."""
    import shutil

    for path in JOBS_DIR.glob("*.jsonl"):
        path.unlink(missing_ok=True)

    for path in JOBS_DIR.glob("jobs_*.json"):
        path.unlink(missing_ok=True)

    for path in [
        JOBS_DIR / "jobs_all_raw.jsonl",
        JOBS_DIR / "jobs_cleaned" / "jobs_all.json",
    ]:
        path.unlink(missing_ok=True)

    for folder in [
        JOBS_DIR / "jobs_with_website",
        JOBS_DIR / "jobs_cleaned_linkedin",
        JOBS_DIR / "jobs_with_company_linkedin",
    ]:
        if folder.exists():
            shutil.rmtree(folder)

    if ROLES_FILE.exists():
        ROLES_FILE.unlink()

    print("[*] Cleared stale Wellfound run artifacts.")
