from urllib.parse import urlparse
import json
import re
from pathlib import Path


# ============================================================
# Configuration
# ============================================================

# Project root (this file now lives one level down, in
# scraping/ or processing/), so go up an extra level.
BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_DIR = BASE_DIR / "jobs" / "jobs_with_company_linkedin"
INPUT_PATTERN = "jobs_*.json"


# ============================================================
# Helpers
# ============================================================

def normalize_company_name(text: str) -> str:
    """
    Lowercase and remove everything except letters and numbers.

    Examples:
        "Interexy"      -> "interexy"
        "Inter Exy"     -> "interexy"
        "INTEREXY"      -> "interexy"
        "Inter-Exy"     -> "interexy"
    """
    return re.sub(r"[^a-z0-9]", "", text.lower())


def filter_company_linkedin(company_name, linkedin_results):

    if not company_name:
        return linkedin_results

    if not isinstance(linkedin_results, list):
        return linkedin_results

    normalized_company = normalize_company_name(company_name)

    print("\nDEBUG")
    print("Company:", repr(company_name))
    print("Normalized company:", repr(normalized_company))

    filtered = []

    for result in linkedin_results:

        if not isinstance(result, dict):
            continue

        href = result.get("href", "")
        snippet = result.get("snippet", "")

        normalized_href = normalize_company_name(href)
        normalized_snippet = normalize_company_name(snippet)

        href_match = normalized_company in normalized_href
        snippet_match = normalized_company in normalized_snippet

        print("\nRESULT")
        print("href:", href)
        print("normalized href:", normalized_href)
        print("href match:", href_match)

        print("snippet:", snippet)
        print("normalized snippet:", normalized_snippet)
        print("snippet match:", snippet_match)

        if href_match or snippet_match:
            print(">>> KEEP")
            filtered.append(result)
        else:
            print(">>> DELETE")

    return filtered


# ============================================================
# Process one file
# ============================================================

def process_file(file_path: Path):

    print("=" * 70)
    print(f"Processing: {file_path.name}")

    with open(file_path, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    if not isinstance(jobs, list):
        print("Skipping: expected a JSON array.")
        return

    total_jobs = 0
    jobs_with_linkedin = 0
    total_removed = 0

    for job in jobs:

        if not isinstance(job, dict):
            continue

        total_jobs += 1

        company_name = job.get("company_name")
        company_linkedin = job.get("company_linkedin")

        if not company_linkedin:
            continue

        if not isinstance(company_linkedin, list):
            continue

        jobs_with_linkedin += 1

        original_count = len(company_linkedin)
        
        filtered = filter_company_linkedin(
            company_name,
            company_linkedin,
        )

        # Normalize LinkedIn URLs and remove duplicates
        filtered = deduplicate_linkedin_results(filtered)

        removed = original_count - len(filtered)
        total_removed += removed

        job["company_linkedin"] = filtered

    # Overwrite original file
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(
            jobs,
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"Jobs processed:       {total_jobs}")
    print(f"Jobs with LinkedIn:   {jobs_with_linkedin}")
    print(f"LinkedIn results removed: {total_removed}")



# ============================================================
# Normalize LinkedIn URL
# ============================================================

def normalize_linkedin_url(url: str) -> str:
    """
    Normalize LinkedIn company URLs.

    Examples:
        https://by.linkedin.com/company/interexy
        https://uk.linkedin.com/company/interexy?trk=ppro_cprof
        https://ca.linkedin.com/company/interexy/
        https://www.linkedin.com/company/interexy

    All become:
        https://www.linkedin.com/company/interexy
    """

    if not url:
        return ""

    # Handle markdown links: [text](url)
    if "](" in url:
        url = url.split("](", 1)[1].rstrip(")")

    parsed = urlparse(url)

    parts = [part for part in parsed.path.split("/") if part]

    if len(parts) >= 2 and parts[0].lower() == "company":
        return f"https://www.linkedin.com/company/{parts[1]}"

    return ""

# ============================================================
# Deduplicate LinkedIn results
# ============================================================


def deduplicate_linkedin_results(linkedin_results):
    """
    Normalize LinkedIn URLs and remove duplicate URLs.

    Keeps the first result when duplicates are found.
    """

    seen = set()
    unique = []

    for result in linkedin_results:

        if not isinstance(result, dict):
            continue

        href = result.get("href", "")

        normalized_url = normalize_linkedin_url(href)

        if not normalized_url:
            unique.append(result)
            continue

        if normalized_url in seen:
            continue

        seen.add(normalized_url)

        # Save normalized URL
        result["href"] = normalized_url

        unique.append(result)

    return unique

# ============================================================
# Main
# ============================================================

def main():

    files = sorted(INPUT_DIR.glob(INPUT_PATTERN))

    if not files:
        print(
            f"No files found in {INPUT_DIR} "
            f"matching {INPUT_PATTERN}"
        )
        return

    print(f"Found {len(files)} files.")

    for file_path in files:
        process_file(file_path)

    print("=" * 70)
    print("Finished.")


if __name__ == "__main__":
    main()