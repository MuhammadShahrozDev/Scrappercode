"""
get hiring_managers and founders from yc website job url
"""

from playwright.sync_api import sync_playwright
import json
import html
import random
import time
from pathlib import Path
# import browser_cookie3

#import requests
from bs4 import BeautifulSoup
#from requests.adapters import HTTPAdapter
#from urllib3.util.retry import Retry


# ==========================================================
# Configuration
# ==========================================================

BASE_DIR = Path(__file__).resolve().parent

PROFILE_DIR = BASE_DIR / "yc_profile"

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"



# take the full jobs/ directory
INPUT_DIR = BASE_DIR / "data"

BASE_URL = "https://www.workatastartup.com/jobs/{}"

USER_AGENTS = [
    # Chrome - Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.7204.101 Safari/537.36",

    # Chrome - Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.7151.120 Safari/537.36",

    # Chrome - Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.114 Safari/537.36",

    # Chrome - macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.7204.101 Safari/537.36",

    # Chrome - Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.7204.101 Safari/537.36",

    # Edge - Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.7204.101 Safari/537.36 Edg/138.0.3351.83",
]

# # Average request rate (~1 request/sec)
# MIN_DELAY = 0.8
# MAX_DELAY = 1.2

# Normal request delay
SHORT_DELAY_MIN = 0.7
SHORT_DELAY_MAX = 1.3

# Break after a random number of jobs
BATCH_SIZE_MIN = 60
BATCH_SIZE_MAX = 90

# Short break between batches
BATCH_BREAK_MIN = 10
BATCH_BREAK_MAX = 20

# Long break after several batches
LONG_BREAK_AFTER_MIN = 250
LONG_BREAK_AFTER_MAX = 350

# Long break duration
LONG_BREAK_MIN = 45
LONG_BREAK_MAX = 90

# Retry configuration
MAX_RETRIES = 5
BACKOFF_FACTOR = 2

# Request timeout
TIMEOUT = 30


# ==========================================================
# Browser
# ==========================================================

def create_browser():
    playwright = sync_playwright().start()

    browser = playwright.chromium.launch(
        executable_path=CHROME_PATH,
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ],
    )

    context = browser.new_context(viewport=None, no_viewport=True)
    page = context.new_page()

    return playwright, browser, page


# ==========================================================
# Helpers
# ==========================================================

def random_delay():
    time.sleep(random.uniform(SHORT_DELAY_MIN, SHORT_DELAY_MAX))


def load_job_ids(input_file):
    with open(input_file, "r", encoding="utf-8") as f:
        return json.load(f)

def load_existing_contacts(output_file):

    path = Path(output_file)

    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        print(f"{output_file} is corrupted.")
        print("Starting with an empty dictionary.")
        return {}


def save_contacts(data, output_file):

    temp_file = output_file + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=4,
            ensure_ascii=False,
            sort_keys=True,
        )

    Path(temp_file).replace(output_file)

# ==========================================================
# HTML parsing
# ==========================================================

def extract_page_json(html_text):
    """
    Extract the JSON stored inside the data-page attribute.
    """
    soup = BeautifulSoup(html_text, "html.parser")

    element = soup.find(attrs={"data-page": True})

    if element is None:
        raise ValueError("Could not find data-page attribute.")

    data = html.unescape(element["data-page"])

    return json.loads(data)


# ==========================================================
# Contact extraction — pulls ALL jobs for the company at once
# ==========================================================

def extract_company_contacts(page_json):
    """
    From a single job page's JSON, extract contacts for
    EVERY job listed at that company (not just the current one).

    Returns:
    {
        "<job_id>": {
            "founders": [...],
            "hiring_managers": [...]
        },
        ...
    }
    """
    props = page_json["props"]
    company_jobs = props["companyFull"].get("jobs", [])
    company_founders = props["companyFull"].get("founders", [])

    # # --- DEBUG: inspect raw structure ---
    # if company_jobs:
    #     print("DEBUG sample job keys:", list(company_jobs[0].keys()))
    #     print("DEBUG sample hiring_manager:", company_jobs[0].get("hiring_manager"))
    # # --- end debug ---

    founder_names = []
    for f in company_founders:
        name = f.get("full_name", "").strip()
        if not name:
            name = f"{f.get('first_name', '')} {f.get('last_name', '')}".strip()
        if name:
            founder_names.append(name)

    result = {}

    for job in company_jobs:
        job_id = str(job.get("id"))
        if not job_id or job_id == "None":
            continue

        hm_names = []
        hm = job.get("hiring_manager")

        # # --- DEBUG ---
        # if job_id in ("249", "254"):
        #     print(f"DEBUG job {job_id} raw hiring_manager:", hm)
        # # --- end debug ---

        if hm:
            first = hm.get("first_name", "").strip()
            last = hm.get("last_name", "").strip()
            full = f"{first} {last}".strip()
            if full:
                hm_names.append(full)

        result[job_id] = {
            "founders": founder_names,
            "hiring_managers": hm_names,
        }

    return result


# ==========================================================
# Scrape a single job (and its whole company)
# ==========================================================

def scrape_job(page, job_id):
    url = BASE_URL.format(job_id)

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)

    html_text = page.content()
    page_json = extract_page_json(html_text)

    company_contacts = extract_company_contacts(page_json)

    return company_contacts


# ==========================================================
# Process a single job safely
# ==========================================================

# def process_job(page, contacts, job_id):
def process_job(page, contacts, job_id, output_file):
    """
    Processes one job. If the job's company has already been
    scraped (because another job at the same company was visited
    earlier), this is a no-op.

    Returns:
        True  -> success or already covered
        False -> failed
    """
    job_key = str(job_id)

    if job_key in contacts:
        return True

    try:
        company_contacts = scrape_job(page, job_id)

        new_count = 0
        for jid, data in company_contacts.items():
            if jid not in contacts:
                contacts[jid] = data
                new_count += 1

        if job_key not in contacts:
            contacts[job_key] = {"founders": [], "hiring_managers": []}

        # save_contacts(contacts)
        save_contacts(contacts, output_file)

        print(f"✓ {job_id} -> added {new_count} job(s) from this company")

        return True

    except KeyboardInterrupt:
        raise

    except Exception as e:
        contacts[job_key] = {"error": str(e)}
        # save_contacts(contacts)
        save_contacts(contacts, output_file)
        print(f"✗ {job_id} -> {e}")
        return False

    finally:
        random_delay()


# ==========================================================
# Retry failed jobs (optional)
# ==========================================================

# def retry_failed_jobs(page, contacts):
def retry_failed_jobs(page, contacts, output_file):
    failed_jobs = []

    for job_id, data in contacts.items():
        if isinstance(data, dict) and "error" in data:
            failed_jobs.append(int(job_id))

    if not failed_jobs:
        return

    print("\nRetrying failed jobs...")
    print(f"{len(failed_jobs)} jobs to retry.\n")

    recovered = 0

    for job_id in failed_jobs:
        job_key = str(job_id)
        try:
            company_contacts = scrape_job(page, job_id)

            for jid, data in company_contacts.items():
                contacts[jid] = data  # overwrite the error entry / fill in others

            if job_key not in contacts or "error" in contacts.get(job_key, {}):
                contacts[job_key] = {"founders": [], "hiring_managers": []}

            # save_contacts(contacts)
            save_contacts(contacts, output_file)

            recovered += 1

            print(f"Recovered {job_id}")

        except Exception:
            pass

        finally:
            random_delay()

    print(f"\nRecovered {recovered}/{len(failed_jobs)} failed jobs.")


# ==========================================================
# Main
# ==========================================================

def main():

    print("=" * 60)
    print("YC Contact Scraper")
    print("=" * 60)

    playwright, browser, page = create_browser()

    try:
        input("\nPress Enter to start scraping jobs from the 'jobs/' directory...\n")

        for input_file in sorted(INPUT_DIR.glob("job_ids_*.json")):


            output_file = input_file.with_name(
                input_file.name.replace(
                    "job_ids_",
                    "contacts_",
                    1,
                )
            )

            print()
            print("=" * 60)
            print(input_file.name)
            print("=" * 60)

            job_ids = load_job_ids(input_file)
            contacts = load_existing_contacts(output_file)

            total_jobs = len(job_ids)
            completed = len(contacts)

            print(f"Total job IDs : {total_jobs}")
            print(f"Already done  : {completed}")
            print(f"Remaining     : {max(0, total_jobs - completed)}")
            print()

            success = 0
            failed = 0
            skipped = 0

            start_time = time.time()

            jobs_in_batch = 0
            batch_limit = random.randint(
                BATCH_SIZE_MIN,
                BATCH_SIZE_MAX,
            )

            next_long_break = random.randint(
                LONG_BREAK_AFTER_MIN,
                LONG_BREAK_AFTER_MAX,
            )

            for index, job_id in enumerate(job_ids, start=1):

                job_key = str(job_id)

                elapsed = time.time() - start_time
                processed = success + failed + skipped

                if processed:
                    avg = elapsed / processed
                    remaining = total_jobs - index + 1
                    eta = avg * remaining
                else:
                    eta = 0

                print(
                    f"[{index}/{total_jobs}] Job {job_id} "
                    f"(ETA: {eta/60:.1f} min)"
                )

                if job_key in contacts:
                    skipped += 1
                    print("Already processed.\n")
                    continue

                ok = process_job(
                    page,
                    contacts,
                    job_id,
                    str(output_file),
                )

                if ok:
                    success += 1
                else:
                    failed += 1

                jobs_in_batch += 1

                if jobs_in_batch >= batch_limit:

                    pause = random.uniform(
                        BATCH_BREAK_MIN,
                        BATCH_BREAK_MAX,
                    )

                    print(f"\nBatch complete.")
                    print(f"Sleeping {pause:.1f} sec\n")

                    time.sleep(pause)

                    jobs_in_batch = 0
                    batch_limit = random.randint(
                        BATCH_SIZE_MIN,
                        BATCH_SIZE_MAX,
                    )

                processed = success + failed

                if processed >= next_long_break:

                    pause = random.uniform(
                        LONG_BREAK_MIN,
                        LONG_BREAK_MAX,
                    )

                    print(
                        f"\nLong break "
                        f"({pause:.1f} sec)\n"
                    )

                    time.sleep(pause)

                    next_long_break += random.randint(
                        LONG_BREAK_AFTER_MIN,
                        LONG_BREAK_AFTER_MAX,
                    )

            retry_failed_jobs(
                page,
                contacts,
                str(output_file),
            )

            print()
            print(f"Finished {input_file.name}")
            print(f"Saved to {output_file.name}")

    finally:

        browser.close()
        playwright.stop()


# ==========================================================
# Entry point
# ==========================================================

if __name__ == "__main__":
    main()