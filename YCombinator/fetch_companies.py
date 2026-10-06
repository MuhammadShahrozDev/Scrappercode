import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup


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


BLOCKED_DOMAINS = {
    "ycombinator.com",
    "www.ycombinator.com",
    "news.ycombinator.com",
    "account.ycombinator.com",
    "bookface.ycombinator.com",

    "startupschool.org",
    "www.startupschool.org",

    "linkedin.com",
    "www.linkedin.com",

    "twitter.com",
    "www.twitter.com",

    "x.com",
    "www.x.com",

    "facebook.com",
    "www.facebook.com",

    "instagram.com",
    "www.instagram.com",

    "youtube.com",
    "www.youtube.com",

    "crunchbase.com",
    "www.crunchbase.com",

    "bloomberg.com",
    "www.bloomberg.com",

    "techcrunch.com",
    "www.techcrunch.com",

    "github.com",
    "www.github.com",
}


SPECIAL_COMPANY_NAMES = {
    "y-combinator": "Y Combinator",
    "questdb": "QuestDB",
    "signadot": "Signadot",
    "recall-ai": "Recall.ai",
    "bluecargo": "BlueCargo",
    "piinpoint": "PiinPoint",
    "gogograndparent": "GoGoGrandparent",
    "inevent": "InEvent",
    "mixrank": "MixRank",
    "onechronos": "OneChronos",
    "veryfi-inc": "Veryfi",
}


SPECIAL_WEBSITES = {
    "y-combinator": "https://www.ycombinator.com",
}


def clean_text(value):

    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value)
    ).strip()


def get_domain(url):

    try:

        return (
            urlsplit(url)
            .netloc
            .lower()
            .split(":")[0]
        )

    except Exception:

        return ""


def normalize_domain(domain):

    domain = (
        domain
        .lower()
        .strip()
    )

    if domain.startswith("www."):
        domain = domain[4:]

    return domain


def is_blocked_domain(domain):

    if not domain:
        return True

    domain = normalize_domain(
        domain
    )

    for blocked in BLOCKED_DOMAINS:

        blocked = normalize_domain(
            blocked
        )

        if domain == blocked:
            return True

        if domain.endswith(
            "." + blocked
        ):
            return True

    return False


def is_valid_company_website(url):

    if not url:
        return False

    url = url.strip()

    if not url.startswith(
        (
            "http://",
            "https://"
        )
    ):
        return False

    domain = get_domain(
        url
    )

    if not domain:
        return False

    if is_blocked_domain(
        domain
    ):
        return False

    return True


def get_company_slugs():

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        jobs = json.load(f)

    slugs = set()

    for job in jobs:

        slug = clean_text(
            job.get(
                "company_slug"
            )
        )

        if slug:
            slugs.add(slug)

    return sorted(slugs)


def slug_to_company_name(slug):

    if slug in SPECIAL_COMPANY_NAMES:

        return (
            SPECIAL_COMPANY_NAMES[
                slug
            ]
        )

    words = (
        slug
        .replace("-", " ")
        .replace("_", " ")
        .split()
    )

    result = []

    for word in words:

        lower = word.lower()

        special = {
            "ai": "AI",
            "inc": "Inc",
            "hq": "HQ",
            "labs": "Labs",
            "health": "Health",
            "financial": "Financial",
        }

        if lower in special:

            result.append(
                special[lower]
            )

        else:

            result.append(
                word.capitalize()
            )

    return " ".join(result)


def extract_meta_content(
    soup,
    property_name=None,
    name=None
):

    if property_name:

        tag = soup.find(
            "meta",
            attrs={
                "property": property_name
            }
        )

        if tag:

            return clean_text(
                tag.get("content")
            )

    if name:

        tag = soup.find(
            "meta",
            attrs={
                "name": name
            }
        )

        if tag:

            return clean_text(
                tag.get("content")
            )

    return ""


def valid_company_name(
    name,
    slug
):

    name = clean_text(
        name
    )

    if not name:
        return False

    lower = name.lower()

    bad_names = {
        "company",
        "jobs",
        "news",
        "about",
        "tl;dr",
        "🎯tl;dr",
        "production deployments & flagship customers",
        "active founders",
        "founders",
        "company information",
        "company details",
    }

    if lower in bad_names:
        return False

    if len(name) > 100:
        return False

    if name.startswith("http"):
        return False

    return True

def extract_company_name(
    soup,
    slug
):

    if slug in SPECIAL_COMPANY_NAMES:

        return (
            SPECIAL_COMPANY_NAMES[
                slug
            ]
        )

    #
    # 1. OpenGraph title
    #
    og_title = extract_meta_content(
        soup,
        property_name="og:title"
    )

    if og_title:

        name = clean_text(
            og_title
        )

        #
        # Remove YC suffix first
        #
        name = re.sub(
            r"\s*[|]\s*Y Combinator.*$",
            "",
            name,
            flags=re.IGNORECASE
        )

        #
        # YC commonly formats:
        # Company Name: Tagline
        #
        # We only want company name.
        #
        if ":" in name:

            first_part = clean_text(
                name.split(
                    ":",
                    1
                )[0]
            )

            if valid_company_name(
                first_part,
                slug
            ):

                return first_part

        if valid_company_name(
            name,
            slug
        ):

            return name

    #
    # 2. HTML title
    #
    if soup.title:

        title = clean_text(
            soup.title.get_text(
                " ",
                strip=True
            )
        )

        title = re.sub(
            r"\s*[|]\s*Y Combinator.*$",
            "",
            title,
            flags=re.IGNORECASE
        )

        if ":" in title:

            first_part = clean_text(
                title.split(
                    ":",
                    1
                )[0]
            )

            if valid_company_name(
                first_part,
                slug
            ):

                return first_part

        if valid_company_name(
            title,
            slug
        ):

            return title

    #
    # 3. H1 fallback
    #
    for h1 in soup.find_all(
        "h1"
    ):

        value = clean_text(
            h1.get_text(
                " ",
                strip=True
            )
        )

        if valid_company_name(
            value,
            slug
        ):

            return value

    #
    # 4. Slug fallback
    #
    return slug_to_company_name(
        slug
    )

def canonical_linkedin(url):

    if not url:
        return None

    match = re.search(
        r"https?://(?:www\.)?"
        r"linkedin\.com/company/"
        r"([^/?#]+)",
        url,
        re.IGNORECASE
    )

    if not match:
        return None

    company_id = clean_text(
        match.group(1)
    )

    if not company_id:
        return None

    return (
        "https://www.linkedin.com/"
        f"company/{company_id}/"
    )


def extract_company_linkedin(
    soup
):

    for link in soup.find_all(
        "a",
        href=True
    ):

        canonical = canonical_linkedin(
            link.get(
                "href",
                ""
            )
        )

        if canonical:
            return canonical

    return None


def score_website_candidate(
    link
):

    href = clean_text(
        link.get(
            "href",
            ""
        )
    )

    if not is_valid_company_website(
        href
    ):
        return -1000

    score = 0

    text = clean_text(
        link.get_text(
            " ",
            strip=True
        )
    ).lower()

    domain = normalize_domain(
        get_domain(
            href
        )
    )

    parent_text = ""

    parent = link.parent

    if parent:

        parent_text = clean_text(
            parent.get_text(
                " ",
                strip=True
            )
        ).lower()

    if "website" in text:
        score += 50

    if "website" in parent_text:
        score += 35

    if (
        domain
        and domain in text
    ):
        score += 30

    #
    # Homepage preferred
    #
    parsed = urlsplit(
        href
    )

    path = parsed.path or "/"

    if path in {
        "",
        "/"
    }:

        score += 25

    #
    # Penalize obvious article / media URLs
    #
    bad_path_words = [
        "/news/",
        "/blog/",
        "/article/",
        "/video/",
        "/videos/",
        "/press/",
        "/careers/",
        "/career/",
        "/jobs/",
        "/job/",
    ]

    lower_path = path.lower()

    for word in bad_path_words:

        if word in lower_path:
            score -= 25

    #
    # Careers link can still be company domain,
    # but homepage is preferable.
    #
    if "careers" in text:
        score -= 10

    return score


def extract_company_website(
    soup,
    slug
):

    if slug in SPECIAL_WEBSITES:

        return (
            SPECIAL_WEBSITES[
                slug
            ]
        )

    candidates = []

    for link in soup.find_all(
        "a",
        href=True
    ):

        href = clean_text(
            link.get(
                "href",
                ""
            )
        )

        if not is_valid_company_website(
            href
        ):
            continue

        score = score_website_candidate(
            link
        )

        candidates.append(
            (
                score,
                href
            )
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: item[0],
        reverse=True
    )

    best_score, best_url = (
        candidates[0]
    )

    #
    # Avoid weak random external link.
    #
    if best_score < 0:
        return None

    return best_url


def extract_company_location(
    soup,
    page_text
):

    #
    # Explicit visible Location label
    #
    for node in soup.find_all(
        string=re.compile(
            r"^\s*Locations?\s*:?\s*$",
            re.IGNORECASE
        )
    ):

        parent = node.parent

        if parent is None:
            continue

        container = parent

        for _ in range(3):

            if container is None:
                break

            text = clean_text(
                container.get_text(
                    " ",
                    strip=True
                )
            )

            text = re.sub(
                r"^Locations?\s*:?\s*",
                "",
                text,
                flags=re.IGNORECASE
            )

            if (
                text
                and len(text) <= 120
                and "team size" not in text.lower()
                and "founded" not in text.lower()
            ):
                return [text]

            container = container.parent

    patterns = [
        (
            r"\bLocation\s*:?\s*"
            r"(.+?)"
            r"(?=\s+Team Size"
            r"|\s+Primary Partner"
            r"|\s+Founded"
            r"|\s+Batch"
            r"|\s+Status"
            r"|\s+Website"
            r"|$)"
        ),

        (
            r"\bLocations\s*:?\s*"
            r"(.+?)"
            r"(?=\s+Team Size"
            r"|\s+Primary Partner"
            r"|\s+Founded"
            r"|\s+Batch"
            r"|\s+Status"
            r"|\s+Website"
            r"|$)"
        ),
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            page_text,
            re.IGNORECASE
        )

        if not match:
            continue

        location = clean_text(
            match.group(1)
        )

        if (
            location
            and len(location) <= 120
        ):
            return [location]

    return []


def extract_company_size(
    page_text
):

    patterns = [
        r"\bTeam Size\s*:?\s*(\d+)",
        r"\bTeam\s*:?\s*(\d+)",
        r"\b(\d+)\s*-\s*(\d+)\s+employees\b",
        r"\b(\d+)\s+employees\b",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            page_text,
            re.IGNORECASE
        )

        if not match:
            continue

        if (
            "Team Size"
            in pattern
            or "Team\\s"
            in pattern
        ):

            return int(
                match.group(1)
            )

        if (
            len(match.groups()) == 2
            and match.group(2)
        ):

            return clean_text(
                match.group(0)
            )

        return int(
            match.group(1)
        )

    return None


def normalize_person_linkedin(
    url
):

    if not url:
        return None

    match = re.search(
        r"https?://(?:www\.)?"
        r"linkedin\.com/in/"
        r"([^/?#]+)",
        url,
        re.IGNORECASE
    )

    if not match:
        return None

    username = clean_text(
        match.group(1)
    )

    if not username:
        return None

    return (
        "https://www.linkedin.com/in/"
        f"{username}/"
    )


def find_founder_card(
    link
):

    current = link

    best = None

    for _ in range(8):

        current = current.parent

        if current is None:
            break

        text = clean_text(
            current.get_text(
                " ",
                strip=True
            )
        )

        if not text:
            continue

        lower = text.lower()

        if (
            "founder"
            in lower
            or "co-founder"
            in lower
            or "cofounder"
            in lower
        ):

            best = current

            #
            # Don't go too high into whole-page container.
            #
            if len(text) <= 500:
                break

    return best


def extract_name_from_founder_card(
    card,
    linkedin_url
):

    if card is None:
        return None

    candidates = []

    for tag in card.find_all(
        [
            "h2",
            "h3",
            "h4",
            "h5",
            "strong",
            "b",
            "p",
            "span",
            "a",
        ]
    ):

        value = clean_text(
            tag.get_text(
                " ",
                strip=True
            )
        )

        if not value:
            continue

        if len(value) > 80:
            continue

        lower = value.lower()

        blocked = [
            "linkedin",
            "founder",
            "co-founder",
            "cofounder",
            "twitter",
            "github",
            "website",
            "active founders",
        ]

        if any(
            word in lower
            for word in blocked
        ):
            continue

        if value.startswith("http"):
            continue

        #
        # Names usually short.
        #
        words = value.split()

        if (
            1 <= len(words) <= 5
        ):

            candidates.append(
                value
            )

    #
    # Prefer candidate nearest to LinkedIn link
    #
    if candidates:
        return candidates[0]

    return None


def extract_founders(
    soup
):

    founders = []
    seen_linkedin = set()

    links = soup.find_all(
        "a",
        href=re.compile(
            r"linkedin\.com/in/",
            re.IGNORECASE
        )
    )

    for link in links:

        linkedin = normalize_person_linkedin(
            link.get(
                "href",
                ""
            )
        )

        if not linkedin:
            continue

        if linkedin in seen_linkedin:
            continue

        card = find_founder_card(
            link
        )

        if card is None:
            continue

        card_text = clean_text(
            card.get_text(
                " ",
                strip=True
            )
        ).lower()

        if not (
            "founder" in card_text
            or "co-founder" in card_text
            or "cofounder" in card_text
        ):
            continue

        name = extract_name_from_founder_card(
            card,
            linkedin
        )

        if not name:
            continue

        founders.append({
            "full_name": name,
            "linkedin": linkedin,
        })

        seen_linkedin.add(
            linkedin
        )

    return founders


def fetch_company(
    slug
):

    company_url = (
        f"{YC_BASE}/companies/"
        f"{slug}"
    )

    response = requests.get(
        company_url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    page_text = clean_text(
        soup.get_text(
            " ",
            strip=True
        )
    )

    company_name = (
        extract_company_name(
            soup,
            slug
        )
    )

    company_website = (
        extract_company_website(
            soup,
            slug
        )
    )

    company_linkedin = (
        extract_company_linkedin(
            soup
        )
    )

    company_location = (
        extract_company_location(
            soup,
            page_text
        )
    )

    company_size = (
        extract_company_size(
            page_text
        )
    )

    founders = (
        extract_founders(
            soup
        )
    )

    return {
        "company_slug": slug,

        "company_name": (
            company_name
        ),

        "company_website": (
            company_website
        ),

        "company_linkedin": (
            company_linkedin
        ),

        "company_location": (
            company_location
        ),

        "company_size": (
            company_size
        ),

        "founders": (
            founders
        ),
    }


def main():

    print()
    print("=" * 60)
    print(
        "Extracting company slugs"
    )
    print("=" * 60)
    print()

    slugs = get_company_slugs()

    print(
        f"Found {len(slugs)} "
        f"unique companies."
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

            print(
                f"  Name: "
                f"{company.get('company_name')}"
            )

            print(
                f"  Website: "
                f"{company.get('company_website')}"
            )

            print(
                f"  LinkedIn: "
                f"{company.get('company_linkedin')}"
            )

            print(
                f"  Location: "
                f"{company.get('company_location')}"
            )

            print(
                f"  Size: "
                f"{company.get('company_size')}"
            )

            print(
                f"  Founders: "
                f"{len(company.get('founders', []))}"
            )

        except Exception as exc:

            print(
                f"[!] Failed: "
                f"{slug} "
                f"("
                f"{type(exc).__name__}: "
                f"{exc}"
                f")"
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