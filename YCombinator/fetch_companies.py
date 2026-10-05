import json
import re
import requests
from bs4 import BeautifulSoup
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

INPUT_FILE = BASE_DIR / "data" / "jobs_all.json"
OUTPUT_FILE = BASE_DIR / "data" / "companies.json"

YC_BASE = "https://www.ycombinator.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def clean_text(value):
    if not value:
        return ""

    return re.sub(
        r"\s+",
        " ",
        value
    ).strip()


def get_company_slugs():
    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        jobs = json.load(f)

    slugs = set()

    for job in jobs:
        slug = job.get("company_slug")

        if slug:
            slugs.add(slug)

    return sorted(slugs)


def fetch_company(slug):
    url = f"{YC_BASE}/companies/{slug}"

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    company_name = ""

    h1 = soup.find("h1")

    if h1:
        company_name = clean_text(
            h1.get_text(" ", strip=True)
        )

    if not company_name:
        company_name = (
            slug
            .replace("-", " ")
            .title()
        )

    company_website = None

    for link in soup.find_all(
        "a",
        href=True
    ):
        href = link.get("href", "")

        if not href.startswith("http"):
            continue

        if "ycombinator.com" in href:
            continue

        if "linkedin.com" in href:
            continue

        if "twitter.com" in href:
            continue

        if "x.com" in href:
            continue

        company_website = href
        break

    founders = []

    founder_section = None

    for heading in soup.find_all(
        ["h2", "h3"]
    ):
        heading_text = clean_text(
            heading.get_text(
                " ",
                strip=True
            )
        ).lower()

        if (
            "founder" in heading_text
            or
            "active founders" in heading_text
        ):
            founder_section = heading
            break

    if founder_section:

        parent = founder_section.parent

        candidates = parent.find_all(
            ["div", "li"]
        )

        seen_founders = set()

        for candidate in candidates:

            text = clean_text(
                candidate.get_text(
                    " ",
                    strip=True
                )
            )

            if "Founder" not in text:
                continue

            linkedin = None

            linkedin_link = candidate.find(
                "a",
                href=re.compile(
                    r"linkedin\.com"
                )
            )

            if linkedin_link:
                linkedin = linkedin_link.get(
                    "href"
                )

            name = None

            for tag in candidate.find_all(
                ["h3", "h4", "p", "span"]
            ):
                value = clean_text(
                    tag.get_text(
                        " ",
                        strip=True
                    )
                )

                if not value:
                    continue

                if value.lower() in {
                    "founder",
                    "founder/ceo",
                    "founder/cto",
                    "co-founder",
                }:
                    continue

                if len(value) > 80:
                    continue

                name = value
                break

            if not name:
                continue

            key = name.lower()

            if key in seen_founders:
                continue

            seen_founders.add(key)

            founders.append({
                "full_name": name,
                "linkedin": linkedin,
            })

    return {
        "company_slug": slug,
        "company_name": company_name,
        "company_website": company_website,
        "founders": founders,
    }


def main():

    print()
    print("=" * 60)
    print("Extracting company slugs")
    print("=" * 60)
    print()

    slugs = get_company_slugs()

    print(
        f"Found {len(slugs)} unique companies."
    )

    companies = []

    for index, slug in enumerate(
        slugs,
        start=1
    ):

        print(
            f"Fetching company "
            f"{index}/{len(slugs)}: "
            f"{slug}"
        )

        try:

            company = fetch_company(
                slug
            )

            companies.append(
                company
            )

        except Exception as exc:

            print(
                f"[!] Failed: "
                f"{slug} "
                f"({type(exc).__name__})"
            )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            companies,
            f,
            indent=4,
            ensure_ascii=False
        )

    print()
    print("=" * 60)
    print("Finished")
    print("=" * 60)

    print(
        f"Total companies: "
        f"{len(companies)}"
    )

    print(
        f"Saved to: "
        f"{OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()