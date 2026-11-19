"""
smart_scraper orchestrator.

Sources: ycombinator, wellfound, linkedin (enriches Wellfound jobs with people), upwork.

Goal of a run: at least SMART_SCRAPER_MIN_PER_SOURCE leads from EVERY selected source
(default 50 each = 200 for 4 sources), never more than SMART_SCRAPER_MAX_TOTAL leads in total
(default 1000), inside SMART_SCRAPER_MAX_RUNTIME_MINUTES (default 240).

How it works
  * Sources run in rounds. In each round every source that is still below its minimum gets a
    fair share of the remaining time, runs, and its NEW leads are ingested immediately.
  * A source that adds nothing in a round is marked exhausted (no point retrying a login/bot
    problem), so the other sources keep their time.
  * LinkedIn needs a pool of Wellfound companies. If LinkedIn runs out of companies before it
    reaches its minimum, Wellfound is re-run with a bigger/wider pool (more days, bigger target).
  * Ingestion stays stable across rounds: only rows not ingested earlier in this run are sent.
"""

import json
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parent


def env_int(name, default):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"[WARN] {name}={raw!r} is not a number; using {default}.")
        return default


# SMART_SCRAPER_TARGET is the per-source minimum (kept for compatibility with the dashboard/workflow).
MIN_PER_SOURCE = env_int(
    "SMART_SCRAPER_MIN_PER_SOURCE",
    env_int("SMART_SCRAPER_TARGET", 50),
)
MAX_TOTAL = env_int("SMART_SCRAPER_MAX_TOTAL", 1000)
BATCH_SIZE = env_int("SMART_SCRAPER_BATCH_SIZE", 100)
MAX_RUNTIME_MINUTES = env_int("SMART_SCRAPER_MAX_RUNTIME_MINUTES", 240)
MAX_ROUNDS = env_int("SMART_SCRAPER_MAX_ROUNDS", 4)
# How many Wellfound jobs to collect per LinkedIn lead wanted (LinkedIn finds people for only
# some companies, so its pool must be bigger than its target).
WELLFOUND_POOL_FACTOR = env_int("SMART_SCRAPER_WELLFOUND_POOL_FACTOR", 4)
MIN_STAGE_MINUTES = env_int("SMART_SCRAPER_MIN_STAGE_MINUTES", 5)
INGEST_TIMEOUT_SECONDS = 900

SOURCE = os.getenv("SMART_SCRAPER_SOURCE", "all").strip().lower()

ALL_SOURCES = ["ycombinator", "wellfound", "linkedin", "upwork"]
VALID_SOURCES = {"all", *ALL_SOURCES}

if SOURCE not in VALID_SOURCES:
    print(
        f"[ERROR] Invalid SMART_SCRAPER_SOURCE: {SOURCE}. "
        f"Allowed: {', '.join(sorted(VALID_SOURCES))}",
        file=sys.stderr,
    )
    sys.exit(2)

MAX_RUNTIME_SECONDS = MAX_RUNTIME_MINUTES * 60

YC_PIPELINE = BASE_DIR / "YCombinator" / "main.py"
WF_PIPELINE = BASE_DIR / "Wellfound" / "main.py"
LINKEDIN_PIPELINE = BASE_DIR / "Linkedin-Scrapper" / "main.py"
UPWORK_PIPELINE = BASE_DIR / "Upwork" / "main.py"
INGEST_SCRIPT = BASE_DIR / "postprocessing" / "save_to_mysql.py"

YC_OUTPUT = BASE_DIR / "YCombinator" / "data" / "jobs_ycombinator.json"
WF_OUTPUT = BASE_DIR / "Wellfound" / "jobs" / "jobs_cleaned" / "jobs_all.json"
LINKEDIN_OUTPUT = BASE_DIR / "Linkedin-Scrapper" / "jobs" / "jobs_wellfound.json"
UPWORK_OUTPUT = BASE_DIR / "Upwork" / "data" / "jobs_upwork.json"

TMP_DIR = BASE_DIR / ".smart_scraper_tmp"

RUN_ID = os.getenv("SMART_SCRAPER_RUN_ID", "").strip()
API_URL = os.getenv("SMART_SCRAPER_API_URL", "").rstrip("/")
INGEST_TOKEN = os.getenv("SMART_SCRAPER_INGEST_TOKEN", "")

# source key -> (source name sent to the API, ingestion mode)
INGEST_AS = {
    "ycombinator": ("ycombinator", "acquisition"),
    "wellfound": ("wellfound", "acquisition"),
    "linkedin": ("wellfound", "enrichment"),
    "upwork": ("upwork", "acquisition"),
}


# --------------------------------------------------------------------------
# status callback
# --------------------------------------------------------------------------

def api_endpoint(name):
    if API_URL.endswith("ingest.php"):
        return API_URL.rsplit("/", 1)[0] + "/" + name
    return API_URL + "/api/v1/smart_scraper/" + name


def fetch_daily_remaining():
    """How many more new leads may be added today (server counts today's inserts)."""
    if not API_URL or not INGEST_TOKEN:
        return None
    try:
        response = requests.get(
            api_endpoint("daily-count.php"),
            headers={
                "Authorization": f"Bearer {INGEST_TOKEN}",
                "Accept": "application/json",
            },
            timeout=30,
        )
        if not response.ok:
            print(f"[WARN] Daily count unavailable (HTTP {response.status_code}); using the run cap only.")
            return None
        data = response.json()
        print(f"[daily] today {data.get('today')} / limit {data.get('limit')} new leads")
        return int(data.get("remaining"))
    except Exception as exc:
        print(f"[WARN] Daily count unavailable: {exc}")
        return None


def report_run_status(status, message, runtime_minutes):
    if not RUN_ID or not API_URL or not INGEST_TOKEN:
        return

    endpoint = api_endpoint("run-status.php")

    try:
        response = requests.post(
            endpoint,
            json={
                "run_id": RUN_ID,
                "source": SOURCE,
                "status": status,
                "message": message,
                "runtime_minutes": runtime_minutes,
            },
            headers={
                "Authorization": f"Bearer {INGEST_TOKEN}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        if not response.ok:
            print(
                f"[WARN] Run status callback failed "
                f"HTTP {response.status_code}: {response.text}"
            )
    except Exception as exc:
        print(f"[WARN] Run status callback failed: {exc}")


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------

STARTED_AT = time.monotonic()


def elapsed():
    return time.monotonic() - STARTED_AT


def remaining_seconds():
    return max(0, int(MAX_RUNTIME_SECONDS - elapsed()))


def time_exhausted():
    return remaining_seconds() <= 0


# --------------------------------------------------------------------------
# subprocess with a real timeout (kills the whole process tree: Chrome, grandchildren)
# --------------------------------------------------------------------------

def run_command(command, cwd, timeout, label, extra_env=None):
    if timeout <= 0:
        print(f"[TIME] No time remaining before {label}.")
        return False

    print("")
    print("=" * 70)
    print(f"Running: {label}")
    print(f"Time available for this step: {int(timeout) // 60} min")
    print(f"Overall time left: {remaining_seconds() // 60} min")
    print("=" * 70, flush=True)

    env = {**os.environ, **(extra_env or {})}

    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        start_new_session=True,
    )

    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[TIME] {label} reached its time limit; stopping it.")
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                break
            try:
                process.wait(timeout=15)
                break
            except subprocess.TimeoutExpired:
                continue
        return False

    if returncode != 0:
        print(f"[WARN] {label} failed with exit code {returncode}.")
        return False

    return True


# --------------------------------------------------------------------------
# data helpers
# --------------------------------------------------------------------------

def load_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def row_key(row):
    return str(
        row.get("id")
        or row.get("source_job_id")
        or row.get("job_url")
        or row.get("url")
        or json.dumps(row, sort_keys=True)[:200]
    )


def rows_for(source):
    if source == "ycombinator":
        return load_rows(YC_OUTPUT)
    if source == "wellfound":
        return load_rows(WF_OUTPUT)
    if source == "linkedin":
        # Only jobs where LinkedIn really found a person are leads.
        return [r for r in load_rows(LINKEDIN_OUTPUT) if r.get("person_1_name")]
    if source == "upwork":
        return load_rows(UPWORK_OUTPUT)
    return []


# --------------------------------------------------------------------------
# state of this run
# --------------------------------------------------------------------------

ingested_keys = {s: set() for s in ALL_SOURCES}   # leads already ingested in this run
server_totals = {s: {"inserted": 0, "updated": 0, "duplicates": 0, "failed": 0} for s in ALL_SOURCES}
exhausted = {s: False for s in ALL_SOURCES}
failures = []   # (source, text)
wellfound_runs = 0


def count(source):
    return len(ingested_keys[source])


def total_count():
    return sum(count(s) for s in ALL_SOURCES)


def ingest_new_rows(source, rows):
    """Send only rows not sent before in this run, respecting the overall cap. Returns #new leads."""
    api_source, mode = INGEST_AS[source]

    fresh = [r for r in rows if row_key(r) not in ingested_keys[source]]

    # One source (e.g. Y Combinator, which can return hundreds of jobs) must not eat the whole cap
    # and starve the others: keep room for every other source's unmet minimum.
    free = MAX_TOTAL - total_count()
    reserve = sum(
        max(MIN_PER_SOURCE - count(other), 0)
        for other in selected_sources()
        if other != source and not exhausted[other]
    )
    allowance = min(free, max(MIN_PER_SOURCE - count(source), free - reserve))

    if allowance <= 0:
        print(f"[CAP] Daily/run cap of {MAX_TOTAL} leads reached; not ingesting more {source} leads.")
        return 0

    if len(fresh) > allowance:
        print(f"[CAP] Trimming {source} from {len(fresh)} to {allowance} leads (cap {MAX_TOTAL}).")
        fresh = fresh[:allowance]

    if not fresh:
        return 0

    TMP_DIR.mkdir(exist_ok=True)
    payload_file = TMP_DIR / f"{source}_{mode}.json"
    result_file = TMP_DIR / f"{source}_{mode}_result.json"

    with open(payload_file, "w", encoding="utf-8") as f:
        json.dump(fresh, f, ensure_ascii=False)

    result_file.unlink(missing_ok=True)

    ok = run_command(
        [
            sys.executable,
            str(INGEST_SCRIPT),
            "--file", str(payload_file),
            "--source", api_source,
            "--mode", mode,
            "--batch-size", str(BATCH_SIZE),
            "--result-file", str(result_file),
        ],
        cwd=BASE_DIR,
        timeout=INGEST_TIMEOUT_SECONDS,
        label=f"{source} {mode} ingestion ({len(fresh)} leads)",
    )

    if not ok:
        failures.append((source, f"{source} ingestion"))
        return 0

    for row in fresh:
        ingested_keys[source].add(row_key(row))

    try:
        with open(result_file, "r", encoding="utf-8") as f:
            totals = json.load(f)
        for key in server_totals[source]:
            server_totals[source][key] += int(totals.get(key, 0) or 0)
    except Exception:
        pass

    return len(fresh)


# --------------------------------------------------------------------------
# stages
# --------------------------------------------------------------------------

def stage_ycombinator(budget_seconds, round_no):
    if round_no == 1:
        YC_OUTPUT.unlink(missing_ok=True)
    ok = run_command(
        [sys.executable, str(YC_PIPELINE)],
        cwd=YC_PIPELINE.parent,
        timeout=budget_seconds,
        label="Y Combinator acquisition",
        extra_env={"SMART_SCRAPER_TARGET": str(MIN_PER_SOURCE)},
    )
    if not ok and not YC_OUTPUT.exists():
        failures.append(("ycombinator", "Y Combinator acquisition"))
        return False
    return ok


def stage_wellfound(budget_seconds, round_no):
    global wellfound_runs
    wellfound_runs += 1
    attempt = wellfound_runs

    base_days = env_int("WELLFOUND_DAYS", 3)
    days = [base_days, max(base_days, 7), max(base_days, 14), max(base_days, 30)][min(attempt, 4) - 1]

    pool = WELLFOUND_POOL_FACTOR if "linkedin" in selected_sources() else 1.25
    target = min(MAX_TOTAL, math.ceil(MIN_PER_SOURCE * pool) * attempt)

    print(f"[wellfound] attempt {attempt}: target {target} jobs, freshness window {days} day(s)")

    # Wellfound wipes its previous output at the start of every run. Keep the last good file so a
    # timed-out / failed later attempt does not leave LinkedIn without its company pool.
    backup = WF_OUTPUT.read_bytes() if WF_OUTPUT.exists() else None

    ok = run_command(
        [sys.executable, str(WF_PIPELINE)],
        cwd=WF_PIPELINE.parent,
        timeout=budget_seconds,
        label=f"Wellfound acquisition (attempt {attempt})",
        extra_env={
            "SMART_SCRAPER_TARGET": str(target),
            "WELLFOUND_DAYS": str(days),
        },
    )
    if not ok:
        failures.append(("wellfound", "Wellfound acquisition"))
        if backup is not None and not WF_OUTPUT.exists():
            WF_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            WF_OUTPUT.write_bytes(backup)
            print("[wellfound] attempt failed; restored the previous jobs_all.json.")
    return ok


def stage_linkedin(budget_seconds, round_no):
    """Returns True when the stage ended because it ran out of companies (not out of time)."""
    if not WF_OUTPUT.exists():
        print("[WARN] LinkedIn enrichment requires Wellfound/jobs/jobs_cleaned/jobs_all.json.")
        failures.append(("linkedin", "LinkedIn input data missing"))
        return False

    # Never ingest an old committed/previous file by mistake.
    LINKEDIN_OUTPUT.unlink(missing_ok=True)

    deadline = time.time() + budget_seconds - 60
    ok = run_command(
        [sys.executable, str(LINKEDIN_PIPELINE)],
        cwd=LINKEDIN_PIPELINE.parent,
        timeout=budget_seconds,
        label="LinkedIn enrichment",
        extra_env={
            "TARGET_OUTPUT": str(max(MIN_PER_SOURCE - count("linkedin"), 5)),
            "LINKEDIN_DEADLINE_EPOCH": str(deadline),
        },
    )
    if not ok:
        failures.append(("linkedin", "LinkedIn enrichment"))
    return ok


def stage_upwork(budget_seconds, round_no):
    if not UPWORK_PIPELINE.exists():
        failures.append(("upwork", "Upwork pipeline missing"))
        return False

    ok = run_command(
        [sys.executable, str(UPWORK_PIPELINE)],
        cwd=UPWORK_PIPELINE.parent,
        timeout=budget_seconds,
        label="Upwork lead pipeline",
        extra_env={
            "UPWORK_TARGET_LEADS": str(MIN_PER_SOURCE),
            "UPWORK_MAX_RUNTIME_SECONDS": str(max(budget_seconds - 120, 60)),
        },
    )
    if not ok:
        failures.append(("upwork", "Upwork pipeline"))
    return ok


STAGES = {
    "ycombinator": stage_ycombinator,
    "wellfound": stage_wellfound,
    "linkedin": stage_linkedin,
    "upwork": stage_upwork,
}


def selected_sources():
    if SOURCE == "all":
        return list(ALL_SOURCES)
    return [SOURCE]


# --------------------------------------------------------------------------
# main loop
# --------------------------------------------------------------------------

def run_source(source, budget_seconds, round_no):
    before = count(source)
    stage_started = time.monotonic()

    stage_ok = STAGES[source](budget_seconds, round_no)

    added = ingest_new_rows(source, rows_for(source))
    print(f"[{source}] +{added} new lead(s) -> {count(source)}/{MIN_PER_SOURCE}")

    if added == 0:
        exhausted[source] = True
        print(f"[{source}] added nothing this round; not retrying.")

    return stage_ok, count(source) - before, time.monotonic() - stage_started < budget_seconds - 90


def main():
    global MAX_TOTAL, MIN_PER_SOURCE

    sources = selected_sources()

    remaining_today = fetch_daily_remaining()
    if remaining_today is not None and remaining_today < MAX_TOTAL:
        MAX_TOTAL = remaining_today

    if MAX_TOTAL <= 0:
        message = "Daily lead limit already reached; nothing to do."
        print(message)
        report_run_status("completed", message, round(elapsed() / 60, 2))
        return

    # A per-source minimum that cannot fit under the cap would starve the later sources.
    fit = max(MAX_TOTAL // len(sources), 1)
    if MIN_PER_SOURCE > fit:
        print(f"[WARN] Minimum per source {MIN_PER_SOURCE} does not fit cap {MAX_TOTAL}; using {fit}.")
        MIN_PER_SOURCE = fit

    print("")
    print("=" * 70)
    print("smart_scraper started")
    print("=" * 70)
    print(f"Sources: {', '.join(sources)}")
    print(f"Minimum leads per source: {MIN_PER_SOURCE}")
    print(f"Maximum leads in total: {MAX_TOTAL}")
    print(f"Maximum runtime: {MAX_RUNTIME_MINUTES} minutes")
    print(f"Rounds: up to {MAX_ROUNDS}")

    need_wellfound_pool = False

    for round_no in range(1, MAX_ROUNDS + 1):
        pending = [
            s for s in sources
            if count(s) < MIN_PER_SOURCE and not exhausted[s]
        ]

        if need_wellfound_pool and "wellfound" in sources and "wellfound" not in pending:
            pending.insert(0, "wellfound")

        if not pending:
            break

        if time_exhausted() or total_count() >= MAX_TOTAL:
            break

        print(f"\n########## Round {round_no}: {', '.join(pending)} ##########")

        order = [s for s in ALL_SOURCES if s in pending]

        for position, source in enumerate(order):
            left = remaining_seconds()
            if left <= 0 or total_count() >= MAX_TOTAL:
                break

            # Fair share of what is left for the sources that still have to run this round.
            share = left // (len(order) - position)
            budget = max(min(left, MIN_STAGE_MINUTES * 60), share)

            if source == "wellfound" and need_wellfound_pool:
                need_wellfound_pool = False

            stage_ok, gained, finished_early = run_source(source, budget, round_no)

            # LinkedIn ran out of companies before reaching its minimum -> grow the Wellfound pool.
            if (
                source == "linkedin"
                and count("linkedin") < MIN_PER_SOURCE
                and stage_ok
                and finished_early
                and "wellfound" in sources
                and wellfound_runs < 4
            ):
                need_wellfound_pool = True
                exhausted["linkedin"] = False
                print("[linkedin] pool exhausted; Wellfound will be re-run with a wider/larger pool.")

    total_minutes = round(elapsed() / 60, 2)

    print("")
    print("=" * 70)
    print("smart_scraper finished")
    print("=" * 70)
    print(f"Runtime: {total_minutes} minutes")

    short = []
    for source in sources:
        got = count(source)
        srv = server_totals[source]
        flag = "" if got >= MIN_PER_SOURCE else f"  (below minimum {MIN_PER_SOURCE})"
        print(
            f" - {source}: {got} leads  "
            f"[server: inserted={srv['inserted']} updated={srv['updated']} "
            f"duplicates={srv['duplicates']} failed={srv['failed']}]{flag}"
        )
        if got < MIN_PER_SOURCE:
            short.append(f"{source} {got}/{MIN_PER_SOURCE}")

    print(f"Total leads this run: {total_count()} (cap {MAX_TOTAL})")

    if time_exhausted():
        print("Reason: maximum runtime reached.")

    short_sources = [s for s in sources if count(s) < MIN_PER_SOURCE]
    relevant_failures = [text for source, text in failures if source in short_sources]

    if short:
        problems = ["below minimum: " + ", ".join(short)]
        problems.extend(dict.fromkeys(relevant_failures))

        print("Completed with warnings:")
        for problem in problems:
            print(f" - {problem}")

        if time_exhausted():
            status = "timeout"
        elif total_count() > 0:
            status = "completed_with_warnings"
        else:
            status = "failed"
        report_run_status(status, "; ".join(problems), total_minutes)
        sys.exit(1)

    print("All selected sources reached their minimum.")
    report_run_status(
        "completed",
        "All selected sources reached their minimum: "
        + ", ".join(f"{s}={count(s)}" for s in sources),
        total_minutes,
    )


if __name__ == "__main__":
    main()
