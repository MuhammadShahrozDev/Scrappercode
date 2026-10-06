import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent

SEARCHES_FILE = BASE_DIR / "searches.json"

OUTPUT_DIR = BASE_DIR / "data"
FILTERED_DIR = OUTPUT_DIR / "jobs_filtered"

YC_BASE = "https://www.ycombinator.com"
YC_JOBS_URL = "https://www.ycombinator.com/jobs/role/all"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def clean_text(value):
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value)
    ).strip()


def html_to_text(value):
    if not value:
        return ""

    return clean_text(
        BeautifulSoup(
            str(value),
            "html.parser"
        ).get_text(
            " ",
            strip=True
        )
    )


def load_searches():
    with open(
        SEARCHES_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


def fetch_html(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    return response.text


def stable_job_id(job_url):
    match = re.search(
        r"/jobs/([^/?#]+)",
        job_url
    )

    if match:
        return match.group(1)

    return hashlib.sha256(
        job_url.encode("utf-8")
    ).hexdigest()[:24]


def company_id_from_slug(slug):
    return hashlib.sha256(
        slug.encode("utf-8")
    ).hexdigest()[:16]


def extract_company_slug(job_url):
    match = re.search(
        r"/companies/([^/]+)/jobs/",
        job_url
    )

    if not match:
        return ""

    return match.group(1)


def parse_json_ld(soup):
    objects = []

    for tag in soup.find_all(
        "script",
        type="application/ld+json"
    ):
        try:
            raw = (
                tag.string
                or tag.get_text()
            )

            if not raw:
                continue

            data = json.loads(raw)

            if isinstance(data, list):
                objects.extend(data)

            elif isinstance(data, dict):
                graph = data.get("@graph")

                if isinstance(graph, list):
                    objects.extend(graph)

                objects.append(data)

        except Exception:
            continue

    for obj in objects:
        if not isinstance(obj, dict):
            continue

        object_type = obj.get("@type")

        if object_type == "JobPosting":
            return obj

        if (
            isinstance(object_type, list)
            and "JobPosting" in object_type
        ):
            return obj

    return {}


def valid_location_text(value):
    value = clean_text(value)

    if not value:
        return False

    invalid = {
        "pde",
        "n/a",
        "na",
        "none",
        "null",
        "unknown",
    }

    if value.lower() in invalid:
        return False

    if len(value) == 1:
        return False

    if (
        len(value) <= 3
        and value.isupper()
        and value not in {
            "US",
            "CA",
            "IN",
            "UK",
            "GB",
            "AU",
            "DE",
            "FR",
            "NL",
            "SG",
            "AE",
        }
    ):
        return False

    return True


def normalize_location(value):
    if not value:
        return []

    if isinstance(value, str):
        text = clean_text(value)

        if valid_location_text(text):
            return [text]

        return []

    if isinstance(value, list):
        result = []

        for item in value:
            parsed = normalize_location(
                item
            )

            for location in parsed:
                if location not in result:
                    result.append(location)

        return result

    if isinstance(value, dict):
        address = value.get(
            "address",
            value
        )

        if isinstance(address, str):
            return normalize_location(
                address
            )

        if isinstance(address, dict):
            country = address.get(
                "addressCountry"
            )

            if isinstance(country, dict):
                country = (
                    country.get("name")
                    or country.get("@id")
                )

            parts = [
                address.get(
                    "addressLocality"
                ),
                address.get(
                    "addressRegion"
                ),
                country,
            ]

            parts = [
                clean_text(item)
                for item in parts
                if clean_text(item)
            ]

            location = ", ".join(
                parts
            )

            if valid_location_text(
                location
            ):
                return [location]

    return []


def extract_remote_location_from_text(
    title,
    description
):
    text = (
        clean_text(title)
        + " "
        + html_to_text(description)
    )

    patterns = [
        r"remote\s*,\s*([A-Za-z ]{3,40})",
        r"remote\s+in\s+([A-Za-z ]{3,40})",
        r"remote\s+position\s+located\s+in\s+"
        r"(?:the\s+)?([A-Za-z ]{3,40})",
        r"based\s+in\s+(?:the\s+)?"
        r"(United States|Canada|Colombia|India)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:
            value = clean_text(
                match.group(1)
            )

            value = re.split(
                r"[.;()]",
                value
            )[0].strip()

            if valid_location_text(
                value
            ):
                return [value]

    return []


def salary_number(
    value,
    suffix=""
):
    if value is None:
        return None

    try:
        number = float(
            str(value)
            .replace(",", "")
            .strip()
        )

    except (
        TypeError,
        ValueError
    ):
        return None

    suffix = (
        suffix
        .strip()
        .lower()
    )

    if suffix == "k":
        number *= 1000

    elif suffix == "m":
        number *= 1000000

    if number <= 0:
        return None

    if number.is_integer():
        return int(number)

    return number


def detect_currency(
    code1=None,
    code2=None,
    code3=None,
    symbol1=None,
    symbol2=None
):
    for code in [
        code1,
        code2,
        code3
    ]:
        if code:
            return (
                str(code)
                .upper()
                .strip()
            )

    symbols = [
        symbol1,
        symbol2
    ]

    mapping = {
        "$": "USD",
        "₹": "INR",
        "£": "GBP",
        "€": "EUR",
    }

    for symbol in symbols:
        if symbol in mapping:
            return mapping[symbol]

    return None


def parse_visible_salary(text):
    if not text:
        return None

    text = clean_text(text)

    pattern = re.compile(
        r"(?:(?P<code1>"
        r"USD|INR|GBP|EUR|CAD|AUD"
        r")\s*)?"
        r"(?P<symbol1>[$₹£€])?\s*"
        r"(?P<min>\d[\d,.]*)"
        r"\s*(?P<min_suffix>[KkMm]?)"
        r"\s*(?:-|–|—|\bto\b)\s*"
        r"(?:(?P<code2>"
        r"USD|INR|GBP|EUR|CAD|AUD"
        r")\s*)?"
        r"(?P<symbol2>[$₹£€])?\s*"
        r"(?P<max>\d[\d,.]*)"
        r"\s*(?P<max_suffix>[KkMm]?)"
        r"(?:\s*(?P<code3>"
        r"USD|INR|GBP|EUR|CAD|AUD"
        r"))?",
        re.IGNORECASE
    )

    candidates = []

    for match in pattern.finditer(text):
        start = max(
            0,
            match.start() - 100
        )

        end = min(
            len(text),
            match.end() + 100
        )

        context = text[
            start:end
        ].lower()

        currency = detect_currency(
            match.group("code1"),
            match.group("code2"),
            match.group("code3"),
            match.group("symbol1"),
            match.group("symbol2"),
        )

        salary_context = any(
            word in context
            for word in [
                "salary",
                "compensation",
                "base pay",
                "base salary",
                "pay range",
                "salary range",
                "target salary",
                "compensation range",
                "annual salary",
            ]
        )

        has_currency_marker = bool(
            currency
        )

        if (
            not salary_context
            and not has_currency_marker
        ):
            continue

        if (
            "years" in context
            and not has_currency_marker
        ):
            continue

        minimum = salary_number(
            match.group("min"),
            match.group("min_suffix")
        )

        maximum = salary_number(
            match.group("max"),
            match.group("max_suffix")
        )

        if (
            minimum is None
            or maximum is None
        ):
            continue

        if maximum < minimum:
            continue

        #
        # YC sometimes exposes:
        # $130 - $190
        #
        # meaning:
        # $130K - $190K
        #
        if (
            currency == "USD"
            and not match.group(
                "min_suffix"
            )
            and not match.group(
                "max_suffix"
            )
            and 20 <= minimum < 1000
            and 20 <= maximum < 1000
        ):
            minimum *= 1000
            maximum *= 1000

        #
        # Similar compact representation
        # can occur with GBP/CAD/AUD.
        #
        if (
            currency in {
                "GBP",
                "CAD",
                "AUD",
                "EUR",
            }
            and not match.group(
                "min_suffix"
            )
            and not match.group(
                "max_suffix"
            )
            and 20 <= minimum < 1000
            and 20 <= maximum < 1000
        ):
            minimum *= 1000
            maximum *= 1000

        candidates.append(
            (
                minimum,
                maximum,
                currency,
                salary_context
            )
        )

    if not candidates:
        return None

    #
    # Prefer candidate explicitly surrounded
    # by salary/compensation wording.
    #
    candidates.sort(
        key=lambda item: (
            item[3] is True
        ),
        reverse=True
    )

    minimum, maximum, currency, _ = (
        candidates[0]
    )

    return (
        minimum,
        maximum,
        currency
    )


def parse_structured_salary(
    job_data
):
    base_salary = job_data.get(
        "baseSalary"
    )

    if not isinstance(
        base_salary,
        dict
    ):
        return None

    currency = clean_text(
        base_salary.get(
            "currency"
        )
    ).upper() or None

    value = base_salary.get(
        "value"
    )

    minimum = None
    maximum = None

    if isinstance(value, dict):
        minimum = salary_number(
            value.get(
                "minValue"
            )
        )

        maximum = salary_number(
            value.get(
                "maxValue"
            )
        )

        single = salary_number(
            value.get(
                "value"
            )
        )

        if minimum is None:
            minimum = single

        if maximum is None:
            maximum = single

    elif value is not None:
        single = salary_number(
            value
        )

        minimum = single
        maximum = single

    if (
        minimum is None
        and maximum is None
    ):
        return None

    if (
        minimum is not None
        and maximum is not None
        and maximum < minimum
    ):
        minimum, maximum = (
            maximum,
            minimum
        )

    if (
        currency == "USD"
        and minimum is not None
        and maximum is not None
        and 20 <= minimum < 1000
        and 20 <= maximum < 1000
    ):
        minimum *= 1000
        maximum *= 1000

    return (
        minimum,
        maximum,
        currency
    )


def parse_salary(
    job_data,
    description,
    page_text
):
    #
    # 1. Job description is most trustworthy.
    #
    visible = parse_visible_salary(
        html_to_text(
            description
        )
    )

    if visible:
        return visible

    #
    # 2. Then visible page text.
    #
    visible = parse_visible_salary(
        page_text
    )

    if visible:
        return visible

    #
    # 3. Finally structured JobPosting data.
    #
    structured = (
        parse_structured_salary(
            job_data
        )
    )

    if structured:
        return structured

    return (
        None,
        None,
        None
    )


def detect_remote(
    title,
    description,
    job_data,
    job_locations
):
    description_text = html_to_text(
        description
    )

    title_text = clean_text(
        title
    )

    combined = (
        title_text
        + " "
        + description_text
    ).lower()

    location_text = " ".join(
        job_locations or []
    ).lower()

    #
    # 1. Explicit onsite/in-person
    # always has highest priority.
    #
    onsite_patterns = [
        r"\bon[\s-]?site\b",
        r"\bin[\s-]?person\b",
        r"\bwork[\s-]?in[\s-]?person\b",
        r"\bworking[\s-]?in[\s-]?person\b",
        r"\bin[\s-]?office\b",
        r"\bwork from (?:our|the) office\b",
        r"\bbased in .{0,60} office\b",
    ]

    for pattern in onsite_patterns:
        if re.search(
            pattern,
            combined,
            re.IGNORECASE
        ):
            return (
                False,
                "onsite"
            )

    #
    # 2. Explicit hybrid employment language.
    #
    hybrid_patterns = [
        r"\bhybrid position\b",
        r"\bhybrid role\b",
        r"\bhybrid work\b",
        r"\bhybrid schedule\b",
        r"\bhybrid workplace\b",
        r"\bhybrid work model\b",
        r"\bhybrid working\b",
        r"\bhybrid office\b",
    ]

    for pattern in hybrid_patterns:
        if re.search(
            pattern,
            combined,
            re.IGNORECASE
        ):
            return (
                True,
                "hybrid"
            )

    #
    # 3. Explicit remote employment language.
    #
    remote_patterns = [
        r"\bfully remote\b",
        r"\b100%\s+remote\b",
        r"\bremote position\b",
        r"\bremote role\b",
        r"\bremote job\b",
        r"\bremote-friendly\b",
        r"\bremote friendly\b",
        r"\bwork remotely\b",
        r"\bwork from home\b",
        r"\bremote-first\b",
        r"\bremote first\b",
        r"\bfully distributed\b",
        r"\bdistributed team\b",
        r"\bremote team\b",
        r"\bremote,\s*[A-Za-z]",
        r"\bremote\s+in\s+[A-Za-z]",
    ]

    for pattern in remote_patterns:
        if re.search(
            pattern,
            combined,
            re.IGNORECASE
        ):
            return (
                True,
                "remote"
            )

    #
    # 4. Title explicitly says Remote.
    #
    if re.search(
        r"\bremote\b",
        title_text,
        re.IGNORECASE
    ):
        return (
            True,
            "remote"
        )

    #
    # 5. Structured jobLocation itself.
    #
    if re.search(
        r"\bremote\b",
        location_text,
        re.IGNORECASE
    ):
        return (
            True,
            "remote"
        )

    #
    # 6. Structured schema.
    #
    location_type = clean_text(
        job_data.get(
            "jobLocationType"
        )
    ).lower()

    if (
        "telecommute"
        in location_type
        or "remote"
        in location_type
    ):
        return (
            True,
            "remote"
        )

    if (
        "onsite"
        in location_type
        or "on-site"
        in location_type
    ):
        return (
            False,
            "onsite"
        )

    return (
        None,
        None
    )


def detect_relocation(
    description
):
    text = html_to_text(
        description
    ).lower()

    negatives = [
        "no relocation",
        "relocation not available",
        "relocation not offered",
        "does not offer relocation",
        "no relocation assistance",
        "unable to provide relocation",
        "cannot provide relocation",
    ]

    for phrase in negatives:
        if phrase in text:
            return False

    positives = [
        "relocation assistance",
        "relocation available",
        "relocation support",
        "offers relocation",
        "relocation provided",
        "relocation package",
    ]

    for phrase in positives:
        if phrase in text:
            return True

    return None


def parse_experience_text(
    text
):
    if not text:
        return (
            None,
            None,
            None
        )

    text = clean_text(text)

    #
    # Strong patterns first.
    #
    patterns = [
        (
            r"\b(\d{1,2})\s*[-–—]\s*"
            r"(\d{1,2})\s+years?"
            r"(?:\s+of)?\s+"
            r"(?:relevant\s+)?experience\b"
        ),

        (
            r"\b(\d{1,2})\s+to\s+"
            r"(\d{1,2})\s+years?"
            r"(?:\s+of)?\s+"
            r"(?:relevant\s+)?experience\b"
        ),

        (
            r"\b(\d{1,2})\s*\+\s*years?"
            r"(?:\s+of)?\s+"
            r"(?:relevant\s+)?experience\b"
        ),

        (
            r"\bexperience\s*:?\s*"
            r"(\d{1,2})\s*[-–—]\s*"
            r"(\d{1,2})\s+years?\b"
        ),

        (
            r"\bexperience\s*:?\s*"
            r"(\d{1,2})\s+to\s+"
            r"(\d{1,2})\s+years?\b"
        ),

        (
            r"\bexperience\s*:?\s*"
            r"(\d{1,2})\s*\+\s*years?\b"
        ),

        (
            r"\bat least\s+"
            r"(\d{1,2})\s+years?"
            r"(?:\s+of)?\s+experience\b"
        ),

        (
            r"\bminimum(?:\s+of)?\s+"
            r"(\d{1,2})\s+years?"
            r"(?:\s+of)?\s+experience\b"
        ),

        (
            r"\b(\d{1,2})\s*[-–—]\s*"
            r"(\d{1,2})\s+years?\s+"
            r"(?:product|engineering|software|"
            r"professional|industry|technical)"
            r"\s+experience\b"
        ),

        (
            r"\b(\d{1,2})\s*\+\s*years?\s+"
            r"(?:product|engineering|software|"
            r"professional|industry|technical)"
            r"\s+experience\b"
        ),
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if not match:
            continue

        groups = match.groups()

        minimum = int(
            groups[0]
        )

        maximum = None

        if (
            len(groups) > 1
            and groups[1]
        ):
            maximum = int(
                groups[1]
            )

        #
        # Guard against clearly unrealistic
        # accidental values.
        #
        if minimum > 30:
            continue

        if (
            maximum is not None
            and maximum > 40
        ):
            continue

        return (
            minimum,
            maximum,
            clean_text(
                match.group(0)
            )
        )

    return (
        None,
        None,
        None
    )


def detect_experience(
    description,
    job_data
):
    #
    # 1. Actual description first.
    #
    description_text = html_to_text(
        description
    )

    result = parse_experience_text(
        description_text
    )

    if result[0] is not None:
        return result

    #
    # 2. Structured experienceRequirements.
    #
    structured = job_data.get(
        "experienceRequirements"
    )

    structured_text = ""

    if isinstance(
        structured,
        str
    ):
        structured_text = structured

    elif isinstance(
        structured,
        dict
    ):
        structured_text = " ".join(
            clean_text(value)
            for value
            in structured.values()
            if isinstance(
                value,
                (
                    str,
                    int,
                    float
                )
            )
        )

    elif isinstance(
        structured,
        list
    ):
        structured_text = " ".join(
            clean_text(item)
            for item in structured
        )

    result = parse_experience_text(
        structured_text
    )

    if result[0] is not None:
        return result

    return (
        None,
        None,
        None
    )


def detect_skills(text):
    patterns = {
        "Python": r"\bPython\b",

        "JavaScript": (
            r"\bJavaScript\b"
        ),

        "TypeScript": (
            r"\bTypeScript\b"
        ),

        "React": (
            r"\bReact(?:\.js)?\b"
        ),

        "React Native": (
            r"\bReact Native\b"
        ),

        "Node.js": (
            r"\bNode(?:\.js)?\b"
        ),

        "Flutter": (
            r"\bFlutter\b"
        ),

        "Dart": (
            r"\bDart\b"
        ),

        "Java": (
            r"\bJava\b"
        ),

        "Kotlin": (
            r"\bKotlin\b"
        ),

        "Swift": (
            r"\bSwift\b"
        ),

        "C++": (
            r"\bC\+\+\b"
        ),

        "C#": (
            r"\bC#\b"
        ),

        "PHP": (
            r"\bPHP\b"
        ),

        "Laravel": (
            r"\bLaravel\b"
        ),

        "Django": (
            r"\bDjango\b"
        ),

        "FastAPI": (
            r"\bFastAPI\b"
        ),

        "Ruby": (
            r"\bRuby\b"
        ),

        "Rails": (
            r"\bRails\b"
            r"|"
            r"\bRuby on Rails\b"
        ),

        #
        # Never generic English "go".
        #
        "Go": (
            r"\bGolang\b"
            r"|"
            r"\bGo programming\b"
            r"|"
            r"\bGo language\b"
        ),

        "Rust": (
            r"\bRust\b"
        ),

        "AWS": (
            r"\bAWS\b"
            r"|"
            r"\bAmazon Web Services\b"
        ),

        "GCP": (
            r"\bGCP\b"
            r"|"
            r"\bGoogle Cloud Platform\b"
            r"|"
            r"\bGoogle Cloud\b"
        ),

        "Azure": (
            r"\bAzure\b"
        ),

        "Docker": (
            r"\bDocker\b"
        ),

        "Kubernetes": (
            r"\bKubernetes\b"
        ),

        "PostgreSQL": (
            r"\bPostgreSQL\b"
            r"|"
            r"\bPostgres\b"
        ),

        "MySQL": (
            r"\bMySQL\b"
        ),

        "MongoDB": (
            r"\bMongoDB\b"
        ),

        "Redis": (
            r"\bRedis\b"
        ),

        "SQL": (
            r"\bSQL\b"
        ),

        "TensorFlow": (
            r"\bTensorFlow\b"
        ),

        "PyTorch": (
            r"\bPyTorch\b"
        ),

        "Machine Learning": (
            r"\bMachine Learning\b"
            r"|"
            r"\bML systems?\b"
            r"|"
            r"\bML models?\b"
        ),

        "Deep Learning": (
            r"\bDeep Learning\b"
        ),

        "LLM": (
            r"\bLLMs?\b"
            r"|"
            r"\bLarge Language Models?\b"
        ),

        "RAG": (
            r"\bRAG\b"
            r"|"
            r"\bRetrieval[- ]Augmented Generation\b"
        ),

        "AI": (
            r"\bAI\b"
            r"|"
            r"\bArtificial Intelligence\b"
        ),

        "AI Agents": (
            r"\bAI Agents?\b"
            r"|"
            r"\bAgentic Systems?\b"
            r"|"
            r"\bAgentic Workflows?\b"
        ),

        "Fine-tuning": (
            r"\bFine[- ]tuning\b"
            r"|"
            r"\bFinetuning\b"
        ),

        "Figma": (
            r"\bFigma\b"
        ),

        "NATS": (
            r"\bNATS\b"
        ),

        "Prisma": (
            r"\bPrisma\b"
        ),

        "Remix": (
            r"\bRemix\b"
        ),

        "MapLibre": (
            r"\bMapLibre\b"
        ),

        "PostGIS": (
            r"\bPostGIS\b"
        ),

        "GeoPandas": (
            r"\bGeoPandas\b"
        ),

        "Shapely": (
            r"\bShapely\b"
        ),

        "GDAL": (
            r"\bGDAL\b"
        ),
    }

    found = []

    for skill, pattern in patterns.items():
        if re.search(
            pattern,
            text,
            re.IGNORECASE
        ):
            found.append(skill)

    #
    # Avoid duplicate semantic entry
    # when React Native exists.
    #
    if (
        "React Native" in found
        and "React" not in found
    ):
        found.append(
            "React"
        )

    return found


def extract_description(
    soup
):
    job_data = parse_json_ld(
        soup
    )

    structured = job_data.get(
        "description"
    )

    if structured:
        return clean_text(
            structured
        )

    #
    # Fallback to probable job description
    # content from page.
    #
    main = soup.find("main")

    if main:
        candidates = []

        for element in main.find_all(
            [
                "p",
                "ul",
                "ol",
                "h2",
                "h3",
                "h4"
            ]
        ):
            html = str(element)

            text = html_to_text(
                html
            )

            if text:
                candidates.append(
                    html
                )

        if candidates:
            return " ".join(
                candidates
            )

    return ""


def detect_job_type(
    page_text,
    job_data
):
    employment_type = job_data.get(
        "employmentType"
    )

    if isinstance(
        employment_type,
        list
    ):
        employment_type = ", ".join(
            clean_text(item)
            for item in employment_type
            if clean_text(item)
        )

    if employment_type:
        value = clean_text(
            employment_type
        )

        upper = value.upper()

        mappings = {
            "FULLTIME": "FULL_TIME",
            "FULL_TIME": "FULL_TIME",
            "FULL-TIME": "FULL_TIME",

            "PARTTIME": "PART_TIME",
            "PART_TIME": "PART_TIME",
            "PART-TIME": "PART_TIME",

            "CONTRACTOR": "CONTRACT",
            "CONTRACT": "CONTRACT",

            "INTERN": "INTERNSHIP",
            "INTERNSHIP": "INTERNSHIP",

            "TEMPORARY": "TEMPORARY",
        }

        normalized = re.sub(
            r"\s+",
            "_",
            upper
        )

        if normalized in mappings:
            return mappings[
                normalized
            ]

        if "FULL" in upper:
            return "FULL_TIME"

        if "PART" in upper:
            return "PART_TIME"

        if "CONTRACT" in upper:
            return "CONTRACT"

        if "INTERN" in upper:
            return "INTERNSHIP"

    lower = page_text.lower()

    if (
        "full-time" in lower
        or "full time" in lower
    ):
        return "FULL_TIME"

    if (
        "part-time" in lower
        or "part time" in lower
    ):
        return "PART_TIME"

    if "internship" in lower:
        return "INTERNSHIP"

    if "contract" in lower:
        return "CONTRACT"

    if "temporary" in lower:
        return "TEMPORARY"

    return None


def extract_job_details(
    job_url,
    title=""
):
    result = {
        "description": "",
        "job_location": [],
        "remote": None,
        "remote_type": None,
        "relocation_allowed": None,
        "job_type": None,
        "experience_min": None,
        "experience_max": None,
        "experience": None,
        "skills": [],
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "compensation": None,
        "posted_timestamp": None,
    }

    try:
        html = fetch_html(
            job_url
        )

    except Exception as exc:
        print(
            f"[!] Detail page failed: "
            f"{job_url} "
            f"({type(exc).__name__}: {exc})"
        )

        return result

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    page_text = clean_text(
        soup.get_text(
            " ",
            strip=True
        )
    )

    job_data = parse_json_ld(
        soup
    )

    description = extract_description(
        soup
    )

    result[
        "description"
    ] = description

    #
    # -----------------------------
    # JOB LOCATION
    # -----------------------------
    #
    locations = normalize_location(
        job_data.get(
            "jobLocation"
        )
    )

    applicant_locations = (
        normalize_location(
            job_data.get(
                "applicantLocationRequirements"
            )
        )
    )

    for location in applicant_locations:
        if location not in locations:
            locations.append(location)

    #
    # If structured location is empty,
    # try useful remote geography from text.
    #
    if not locations:
        fallback_locations = (
            extract_remote_location_from_text(
                title,
                description
            )
        )

        for location in fallback_locations:
            if location not in locations:
                locations.append(
                    location
                )

    result[
        "job_location"
    ] = locations

    #
    # -----------------------------
    # REMOTE / HYBRID / ONSITE
    # -----------------------------
    #
    remote, remote_type = (
        detect_remote(
            title,
            description,
            job_data,
            locations
        )
    )

    result[
        "remote"
    ] = remote

    result[
        "remote_type"
    ] = remote_type

    #
    # -----------------------------
    # RELOCATION
    # -----------------------------
    #
    result[
        "relocation_allowed"
    ] = detect_relocation(
        description
    )

    #
    # -----------------------------
    # JOB TYPE
    # -----------------------------
    #
    result[
        "job_type"
    ] = detect_job_type(
        page_text,
        job_data
    )

    #
    # -----------------------------
    # EXPERIENCE
    # -----------------------------
    #
    (
        experience_min,
        experience_max,
        experience_text
    ) = detect_experience(
        description,
        job_data
    )

    result[
        "experience_min"
    ] = experience_min

    result[
        "experience_max"
    ] = experience_max

    result[
        "experience"
    ] = experience_text

    #
    # -----------------------------
    # SKILLS
    # -----------------------------
    #
    skill_source = html_to_text(
        description
    )

    if not skill_source:
        skill_source = page_text

    result[
        "skills"
    ] = detect_skills(
        skill_source
    )

    #
    # -----------------------------
    # SALARY
    # -----------------------------
    #
    (
        salary_min,
        salary_max,
        salary_currency
    ) = parse_salary(
        job_data,
        description,
        page_text
    )

    #
    # Never save meaningless zero salary.
    #
    if (
        salary_min is not None
        and salary_min <= 0
    ):
        salary_min = None

    if (
        salary_max is not None
        and salary_max <= 0
    ):
        salary_max = None

    if (
        salary_min is None
        and salary_max is None
    ):
        salary_currency = None

    result[
        "salary_min"
    ] = salary_min

    result[
        "salary_max"
    ] = salary_max

    result[
        "salary_currency"
    ] = salary_currency

    if (
        salary_min is not None
        or salary_max is not None
    ):
        result[
            "compensation"
        ] = {
            "min": salary_min,
            "max": salary_max,
            "currency": salary_currency,
        }

    else:
        result[
            "compensation"
        ] = None

    #
    # -----------------------------
    # POSTED DATE
    # -----------------------------
    #
    result[
        "posted_timestamp"
    ] = (
        clean_text(
            job_data.get(
                "datePosted"
            )
        )
        or None
    )

    return result


def detect_role(
    card_text
):
    roles = [
        "Engineering",
        "Product",
        "Design",
        "Sales",
        "Marketing",
        "Operations",
        "Recruiting",
        "Science",
        "Support",
        "Finance",
        "Legal",
    ]

    lower = card_text.lower()

    for role in roles:
        if role.lower() in lower:
            return role

    return ""


def extract_jobs_from_page():
    html = fetch_html(
        YC_JOBS_URL
    )

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    jobs = []
    seen = set()

    links = soup.find_all(
        "a",
        href=True
    )

    for link in links:
        href = link.get(
            "href",
            ""
        )

        if not re.search(
            r"/companies/[^/]+/jobs/[^/]+",
            href
        ):
            continue

        job_url = urljoin(
            YC_BASE,
            href
        )

        if job_url in seen:
            continue

        title = clean_text(
            link.get_text(
                " ",
                strip=True
            )
        )

        if not title:
            continue

        seen.add(
            job_url
        )

        company_slug = (
            extract_company_slug(
                job_url
            )
        )

        company_name = ""
        card_text = ""

        parent = link.parent

        for _ in range(8):
            if parent is None:
                break

            parent_text = clean_text(
                parent.get_text(
                    " ",
                    strip=True
                )
            )

            company_link = parent.find(
                "a",
                href=re.compile(
                    rf"/companies/"
                    rf"{re.escape(company_slug)}"
                    rf"/?$"
                )
            )

            if company_link:
                company_name = (
                    clean_text(
                        company_link.get_text(
                            " ",
                            strip=True
                        )
                    )
                )

                card_text = parent_text
                break

            parent = parent.parent

        if not company_name:
            company_name = (
                company_slug
                .replace(
                    "-",
                    " "
                )
                .title()
            )

        role = detect_role(
            card_text
        )

        details = extract_job_details(
            job_url,
            title
        )

        job_id = stable_job_id(
            job_url
        )

        created_at = (
            details.get(
                "posted_timestamp"
            )
            or datetime.now(
                timezone.utc
            ).isoformat()
        )

        job = {
            "id": job_id,
            "created_at": created_at,

            "title": title,

            "description": (
                details.get(
                    "description"
                )
            ),

            "role": role,

            "company_id": (
                company_id_from_slug(
                    company_slug
                )
            ),

            "company_slug": (
                company_slug
            ),

            "company_name": (
                company_name
            ),

            "search_path": (
                job_url
            ),

            "job_url": (
                job_url
            ),

            "job_location": (
                details.get(
                    "job_location",
                    []
                )
            ),

            "remote": (
                details.get(
                    "remote"
                )
            ),

            "remote_type": (
                details.get(
                    "remote_type"
                )
            ),

            "relocation_allowed": (
                details.get(
                    "relocation_allowed"
                )
            ),

            "job_type": (
                details.get(
                    "job_type"
                )
            ),

            "experience_min": (
                details.get(
                    "experience_min"
                )
            ),

            "experience_max": (
                details.get(
                    "experience_max"
                )
            ),

            "experience": (
                details.get(
                    "experience"
                )
            ),

            "skills": (
                details.get(
                    "skills",
                    []
                )
            ),

            "compensation": (
                details.get(
                    "compensation"
                )
            ),

            "salary_min": (
                details.get(
                    "salary_min"
                )
            ),

            "salary_max": (
                details.get(
                    "salary_max"
                )
            ),

            "salary_currency": (
                details.get(
                    "salary_currency"
                )
            ),

            "posted_timestamp": (
                details.get(
                    "posted_timestamp"
                )
            ),

            "objectID": job_id,
        }

        jobs.append(job)

    return jobs


def matches_search(
    job,
    search
):
    query = clean_text(
        search.get(
            "query",
            ""
        )
    ).lower()

    role = clean_text(
        search.get(
            "role",
            ""
        )
    ).lower()

    searchable = " ".join([
        clean_text(
            job.get(
                "title"
            )
        ),

        html_to_text(
            job.get(
                "description",
                ""
            )
        ),

        clean_text(
            job.get(
                "role"
            )
        ),

        " ".join(
            job.get(
                "skills",
                []
            )
        ),
    ]).lower()

    if query:
        query_parts = [
            item.strip()
            for item
            in re.split(
                r"[-_\s]+",
                query
            )
            if item.strip()
        ]

        if not all(
            item in searchable
            for item in query_parts
        ):
            return False

    if role:
        if role not in searchable:
            return False

    return True


def save_jobs(
    jobs,
    filename
):
    data = []

    if os.path.exists(
        filename
    ):
        try:
            with open(
                filename,
                "r",
                encoding="utf-8"
            ) as f:
                loaded = json.load(f)

            if isinstance(
                loaded,
                list
            ):
                data = loaded

        except Exception:
            data = []

    existing = {
        str(
            item.get(
                "id"
            )
        ): index
        for index, item
        in enumerate(data)
        if (
            isinstance(item, dict)
            and item.get("id")
        )
    }

    for job in jobs:
        job_id = str(
            job.get(
                "id"
            )
        )

        if job_id in existing:
            data[
                existing[
                    job_id
                ]
            ] = job

        else:
            existing[
                job_id
            ] = len(data)

            data.append(
                job
            )

    with open(
        filename,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            indent=4,
            ensure_ascii=False
        )


def main():
    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    os.makedirs(
        FILTERED_DIR,
        exist_ok=True
    )

    searches = load_searches()

    print("=" * 60)
    print(
        "Fetching current YC jobs page"
    )
    print("=" * 60)

    jobs = extract_jobs_from_page()

    print(
        f"Collected "
        f"{len(jobs)} jobs "
        f"from YC."
    )

    all_jobs = []
    seen = set()

    for search in searches:
        print()
        print("=" * 60)

        print(
            f"Running search: "
            f"{search['name']}"
        )

        print("=" * 60)

        filtered_jobs = [
            job
            for job in jobs
            if matches_search(
                job,
                search
            )
        ]

        print(
            f"Collected "
            f"{len(filtered_jobs)} "
            f"jobs."
        )

        filename = (
            FILTERED_DIR
            / (
                f"jobs_"
                f"{search['name']}"
                f".json"
            )
        )

        save_jobs(
            filtered_jobs,
            filename
        )

        print(
            f"Saved to "
            f"{filename}"
        )

        for job in filtered_jobs:
            job_id = str(
                job.get(
                    "id"
                )
            )

            if job_id in seen:
                continue

            seen.add(
                job_id
            )

            all_jobs.append(
                job
            )

    all_filename = (
        OUTPUT_DIR
        / "jobs_all.json"
    )

    save_jobs(
        all_jobs,
        all_filename
    )

    print()
    print("=" * 60)
    print("Finished")
    print("=" * 60)

    print(
        f"Total unique jobs: "
        f"{len(all_jobs)}"
    )

    print(
        f"Saved to "
        f"{all_filename}"
    )


if __name__ == "__main__":
    main()