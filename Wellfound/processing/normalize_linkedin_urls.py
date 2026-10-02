import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote


# ============================================================
# CONFIG
# ============================================================

# Project root (this file now lives one level down, in
# scraping/ or processing/), so go up an extra level.
BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_DIR = BASE_DIR / "jobs" / "jobs_with_website"
OUTPUT_DIR = BASE_DIR / "jobs" / "jobs_cleaned_linkedin"

INPUT_PATTERN = "jobs_*.json"

OUTPUT_DIR.mkdir(exist_ok=True)


# ============================================================
# CLEAN LINKEDIN URL
# ============================================================

def clean_linkedin_url(url):
    """
    Convert different LinkedIn company URL formats into:

        https://www.linkedin.com/company/company-name

    Examples:

        https://www.linkedin.com/company/signal-daddy-media/?viewasmember=true

    becomes:

        https://www.linkedin.com/company/signal-daddy-media

    And:

        https://www.linkedin.com/login/?session_redirect=https%3A%2F%2Fwww.linkedin.com%2Fcompany%2Fmedvidi%2Fposts%2F%3Ffeedview%3Dall

    becomes:

        https://www.linkedin.com/company/medvidi
    """

    if not url:
        return url

    if not isinstance(url, str):
        return url

    url = url.strip()

    if not url:
        return url

    # --------------------------------------------------------
    # Sometimes the URL may accidentally be wrapped in
    # markdown-style text.
    #
    # Example:
    # [https://www.linkedin.com/company/test/](https://...)
    # --------------------------------------------------------

    if url.startswith("[") and "](" in url:
        try:
            url = url.split("](", 1)[1].rstrip(")")
        except Exception:
            pass

    # Remove whitespace
    url = url.strip()

    # --------------------------------------------------------
    # Make sure this is actually LinkedIn
    # --------------------------------------------------------

    if "linkedin.com" not in url.lower():
        return url

    # --------------------------------------------------------
    # Parse URL
    # --------------------------------------------------------

    try:
        parsed = urlparse(url)
    except Exception:
        return url

    # --------------------------------------------------------
    # Case 1:
    #
    # LinkedIn login URL containing the real company URL:
    #
    # /login/?session_redirect=https://www.linkedin.com/company/...
    # --------------------------------------------------------

    if "/login" in parsed.path.lower():

        query = parse_qs(parsed.query)

        session_redirect = query.get("session_redirect")

        if session_redirect:

            redirected_url = unquote(session_redirect[0])

            # Parse the redirected LinkedIn URL
            try:
                redirected = urlparse(redirected_url)
            except Exception:
                return url

            parsed = redirected

    # --------------------------------------------------------
    # Get path
    # --------------------------------------------------------

    path = unquote(parsed.path)

    # Normalize backslashes just in case
    path = path.replace("\\", "/")

    # Remove leading/trailing slashes
    path = path.strip("/")

    parts = path.split("/")

    # --------------------------------------------------------
    # Find "company" in the path
    #
    # This allows URLs such as:
    #
    # /company/foo
    # /company/foo/posts
    # /company/foo/about
    # /company/foo/life
    # --------------------------------------------------------

    company_index = None

    for i, part in enumerate(parts):

        if part.lower() == "company":
            company_index = i
            break

    if company_index is None:
        return url

    # Need something after /company/
    if company_index + 1 >= len(parts):
        return url

    company_name = parts[company_index + 1].strip()

    if not company_name:
        return url

    # --------------------------------------------------------
    # Remove accidental query/hash from company name
    # --------------------------------------------------------

    company_name = company_name.split("?")[0]
    company_name = company_name.split("#")[0]

    company_name = company_name.strip("/")

    if not company_name:
        return url

    # --------------------------------------------------------
    # Final normalized URL
    # --------------------------------------------------------

    return f"https://www.linkedin.com/company/{company_name}"


# ============================================================
# PROCESS ONE JOB
# ============================================================

def process_job(job):
    """
    Looks for linkedin_url anywhere in the job's top-level fields.
    """

    if not isinstance(job, dict):
        return False

    if "company_linkedin" not in job:
        return False

    old_url = job.get("company_linkedin")

    if not old_url:
        return False

    new_url = clean_linkedin_url(old_url)

    if new_url != old_url:
        job["clean_company_linkedin_url"] = new_url
        return True

    return False


# ============================================================
# PROCESS ONE FILE
# ============================================================

def process_file(input_file):
    print()
    print("=" * 60)
    print(f"Processing: {input_file.name}")
    print("=" * 60)

    try:
        with open(
            input_file,
            "r",
            encoding="utf-8",
        ) as f:

            jobs = json.load(f)

    except Exception as exc:

        print(
            f"Failed to read {input_file}: {exc}"
        )

        return

    if not isinstance(jobs, list):

        print(
            f"Skipping {input_file.name}: "
            "expected a JSON array."
        )

        return

    changed = 0
    linkedin_count = 0

    for job in jobs:

        if not isinstance(job, dict):
            continue

        for field_name in ("linkedin_url", "company_linkedin"):
            if field_name not in job:
                continue

            url_value = job.get(field_name)

            if not url_value:
                continue

            linkedin_count += 1

            old_url = url_value
            new_url = clean_linkedin_url(old_url)

            if new_url != old_url:

                print()
                print("Changed:")
                print("  FIELD:", field_name)
                print("  OLD:", old_url)
                print("  NEW:", new_url)

                job[field_name] = new_url
                changed += 1

    # --------------------------------------------------------
    # Save to separate directory
    # --------------------------------------------------------

    output_file = OUTPUT_DIR / input_file.name

    try:

        with open(
            output_file,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                jobs,
                f,
                indent=2,
                ensure_ascii=False,
            )

    except Exception as exc:

        print(
            f"Failed to save {output_file}: {exc}"
        )

        return

    print()
    print(f"LinkedIn URLs found: {linkedin_count}")
    print(f"URLs cleaned:        {changed}")
    print(f"Saved:               {output_file}")


# ============================================================
# MAIN
# ============================================================

def main():

    files = sorted(
        INPUT_DIR.glob(INPUT_PATTERN)
    )

    if not files:

        print(
            f"No files found matching "
            f"{INPUT_PATTERN} in {INPUT_DIR}"
        )

        return

    print(
        f"Found {len(files)} job files."
    )

    for input_file in files:

        process_file(input_file)

    print()
    print("=" * 60)
    print("DONE")
    print("=" * 60)

    print(
        f"Cleaned files are in: {OUTPUT_DIR}"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()