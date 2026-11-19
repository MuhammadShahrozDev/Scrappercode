"""
Upwork job scraper (Patchright test version; initial test limit: 10)

- Opens a persistent Patchright Chromium profile. Log in manually on the first run.
- Types the search into Upwork's own search box and collects the results the page receives.
- Clicks each job tile and reads the job-details response the page receives.
- Looks up the client's previous jobs through the same job-details API, by running
  the captured request inside the Upwork tab (page.evaluate + fetch) with the
  previous job's ciphertext. This returns description + category/categoryGroup
  without visiting each page.
- Appends only new job IDs to a JSON file. Raw job objects are appended to a
  separate JSONL file.
- Uses only freelancer-written reviews of the client: feedbackToClient.comment.

Use only with your own account and respect Upwork's terms and rate limits.
If Upwork presents a security challenge or block, resolve it manually; this
script does not attempt to bypass it. A 401/403/429 on a previous-job lookup
stops further lookups for that client.
"""

from __future__ import annotations

import base64
import json
import os
import random
import re
import sys
import threading
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from patchright.sync_api import (
    Page,
    Request,
    Response,
    sync_playwright,
)

from client_extraction import analyze_record  # keep client_extraction.py in the same folder

SEARCH_URL = (
    "https://www.upwork.com/nx/search/jobs?"
    # "client_hires=1-9,10-&jobs_feed=all-jobs&location=United%2520States"
    # "&payment_verified=1&q=agentic%20ai&sort=relevance%2Bdesc"
)
SEARCH_ALIAS = "alias=userJobSearch"
DETAILS_ALIAS = "alias=gql-query-get-auth-job-details-v2"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = DATA_DIR / "upwork_agentic_ai_jobs.json"
FULL_OBJECTS_FILE = DATA_DIR / "upwork_agentic_ai_jobs_full_objects.jsonl"
PROFILE_DIR = DATA_DIR / "upwork_patchright_profile"

def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# CI / unattended mode: no "press Enter" prompts. GitHub Actions sets CI=true.
NONINTERACTIVE = _env_bool("UPWORK_NONINTERACTIVE", _env_bool("CI", False))
# Real Chrome under xvfb (headless=False) is the most reliable with Patchright; keep it unless told otherwise.
HEADLESS = _env_bool("UPWORK_HEADLESS", False)

PAGE_SIZE = 10
SEARCH_QUERY = os.getenv("UPWORK_QUERY", "agentic ai")
JOBS_PER_RUN = int(os.getenv("UPWORK_JOBS_PER_RUN", "60"))   # new jobs scraped per invocation
MAX_PAGES = int(os.getenv("UPWORK_MAX_PAGES", "10"))         # result pages visited per invocation
PER_PAGE = os.getenv("UPWORK_PER_PAGE", "50")                # Upwork accepts 10 / 20 / 50
SORT = os.getenv("UPWORK_SORT", "recency")                   # "" keeps the UI default (relevance)
PROXY = os.getenv("UPWORK_PROXY", "").strip()                # http://user:pass@host:port (optional)
STATE_FILE = DATA_DIR / "upwork_search_state.json"           # remembers the next results page
CURRENT_SEARCH_URL = SEARCH_URL
DELAY_BETWEEN_DETAILS_SECONDS = 5.0

# Previous-job lookups (through the job-details API)
MAX_HISTORY_JOBS_PER_CLIENT = 10
DELAY_BETWEEN_HISTORY_FETCHES_SECONDS = (1.5, 3.0)  # random range
FETCH_HISTORY_ONLY_IF_NO_INDUSTRY = False           # True = also skip when Upwork already gives the industry

# Key in each workHistory entry that holds the CLIENT's feedback about the freelancer.
# "feedback" is a guess: check it against the raw JSONL (full objects file).
CLIENT_FEEDBACK_KEY = "feedback"
SLIM_HISTORY_OBJECTS = True  # drop the repeated buyer.workHistory from previous-job lines

# Review text is retained only when it contains a plausible reference to the
# client/name. These patterns are intentionally conservative; review parsing
# is heuristic and must not be treated as identity verification.
RELEVANCE_PATTERNS = [
    re.compile(r"\b(?:client|working with|work with|worked with|working for|"
               r"work for|experience with|great to work with|"
               r"pleasure to work with|happy to work with)\b", re.I),
    re.compile(r"^\s*(?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?)?\s*[A-Z][a-z]{1,30}"
               r"(?:\s+[A-Z][a-z]{1,30}){0,2}\s+"
               r"(?:was|is|has been|made|provided|helped|communicated)\b"),
]
NAME_PATTERNS = [
    # "Myles was great to work with"; "Mr. Myles was a great client"
    re.compile(
        r"^\s*(?:(?:Mr|Mrs|Ms|Dr)\.?\s+)?"
        r"([A-Z][a-z]{1,30}(?:\s+[A-Z][a-z]{1,30}){0,2})\s+"
        r"(?:was|is|has been|made|provided|helped|communicated|"
        r"gave|offered|allowed|let|would)\b"
    ),
    # "great experience working with Maanish"
    re.compile(
        r"\b(?:working with|worked with|work with|working for|worked for|"
        r"work for|experience with|client)\s+"
        r"(?:(?:Mr|Mrs|Ms|Dr)\.?\s+)?"
        r"([A-Z][a-z]{1,30}(?:\s+[A-Z][a-z]{1,30}){0,2})"
    ),
]

try:
    import spacy
    _NLP = spacy.load("en_core_web_sm")
except Exception:
    _NLP = None  # spaCy not installed; fall back to regex + stoplist only

NON_NAME_WORDS = {
    "he", "she", "it", "they", "we", "i", "you", "his", "her", "their",
    "the", "this", "that", "a", "an", "my", "our", "your", "client",
    "communication", "great", "excellent", "good", "amazing", "awesome",
    "wonderful", "fantastic", "perfect", "nice", "super", "very", "highly",
    "clear", "fast", "quick", "thanks", "thank", "work", "job", "project",
    "payment", "team", "company", "upwork", "pleasure", "experience",
    "overall", "definitely", "always", "everything", "everyone", "working",
    "responsive", "professional", "easy", "friendly", "helpful", "patient",
}


def is_plausible_name(name: str) -> bool:
    tokens = name.split()
    if not tokens or len(tokens) > 3:
        return False
    return not any(t.lower() in NON_NAME_WORDS for t in tokens)


def ner_person_tokens(text: str) -> set[str]:
    """Lowercased name tokens that spaCy tags as PERSON in this text."""
    if _NLP is None:
        return set()
    tokens: set[str] = set()
    for ent in _NLP(text).ents:
        if ent.label_ == "PERSON":
            tokens.update(t.lower() for t in ent.text.split())
    return tokens


def wait_for_enter(page: Page, prompt: str) -> None:
    """Wait for Enter without blocking Playwright's event processing."""
    if NONINTERACTIVE:
        page.wait_for_timeout(3000)  # unattended: give the page a moment instead of prompting
        return
    done = threading.Event()

    def _reader() -> None:
        try:
            input(prompt)
        finally:
            done.set()

    threading.Thread(target=_reader, daemon=True).start()
    while not done.is_set():
        page.wait_for_timeout(250)  # keeps Playwright processing events


def load_existing(path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    if not path.exists():
        return [], set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Expected a JSON array in output file.")
        ids = {str(item.get("job_id")) for item in data if item.get("job_id")}
        return data, ids
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Cannot safely append to {path}: {exc}. Back it up and fix the JSON first."
        ) from exc


def write_json_atomically(path: Path, records: list[dict[str, Any]]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def find_dicts_with_key(value: Any, key: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if key in value:
            found.append(value)
        for child in value.values():
            found.extend(find_dicts_with_key(child, key))
    elif isinstance(value, list):
        for child in value:
            found.extend(find_dicts_with_key(child, key))
    return found


def extract_search_jobs(payload: Any) -> list[dict[str, Any]]:
    """Find search-result objects despite minor response nesting changes."""
    candidates: list[dict[str, Any]] = []
    for item in find_dicts_with_key(payload, "jobTile"):
        tile = item.get("jobTile")
        job = tile.get("job") if isinstance(tile, dict) else None
        if isinstance(job, dict) and (job.get("ciphertext") or job.get("id")):
            candidates.append(item)

    # Fallback: result records may expose id/title/ciphertext directly.
    if not candidates:
        for item in find_dicts_with_key(payload, "ciphertext"):
            if item.get("title") and item.get("ciphertext"):
                candidates.append(item)

    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        tile = item.get("jobTile") if isinstance(item.get("jobTile"), dict) else {}
        job = tile.get("job") if isinstance(tile.get("job"), dict) else {}
        ciphertext = job.get("ciphertext") or item.get("ciphertext")
        job_id = ciphertext or job.get("id") or item.get("id")
        if not job_id:
            continue
        key = str(job_id)
        if key in seen:
            continue
        seen.add(key)
        jobs.append({
            "job_id": key,
            "ciphertext": ciphertext or key,
            "title": item.get("title") or job.get("title"),
            "description": item.get("description"),
            "search_result": item,
        })
    return jobs


def response_json(response: Response) -> Any | None:
    try:
        if "json" in response.headers.get("content-type", "").lower():
            return response.json()
    except Exception:
        pass
    return None


def trigger_search_from_ui(page: Page, query: str) -> bool:
    """Type the query into the visible search box and press Enter."""
    selectors = [
        'input[type="search"]',
        'input[placeholder*="Search" i]',
        'input[aria-label*="Search" i]',
        'input[name="q"]',
        '[data-test="search-input"] input',
    ]
    for selector in selectors:
        try:
            for box in page.locator(selector).all():
                if not box.is_visible():
                    continue
                box.click()
                box.fill("")
                box.type(query, delay=80)
                page.wait_for_timeout(500)
                box.press("Enter")
                return True
        except Exception:
            continue
    return False


def post_data_json(request: Request) -> dict[str, Any]:
    try:
        data = request.post_data_json
    except Exception:
        data = None
    if not isinstance(data, dict):
        raise RuntimeError(f"Could not parse JSON request payload from {request.url}")
    return data


def normalize_job_url(ciphertext: str, title: str | None = None) -> str:
    # The common Upwork route accepts a job ciphertext directly. The browser
    # may redirect to its canonical title URL.
    return f"https://www.upwork.com/jobs/{ciphertext}"


def find_job_anchor(page: Page, ciphertext: str) -> str | None:
    try:
        anchors = page.locator("a[href*='~']").evaluate_all(
            "(els) => els.map(a => a.href)"
        )
        needle = ciphertext.lstrip("~")
        for href in anchors:
            if needle and needle in href:
                return href
    except Exception:
        return None
    return None


def get_detail_object(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return {}
    detail = data.get("jobAuthDetails")
    return detail if isinstance(detail, dict) else {}


def is_relevant_review(comment: str) -> bool:
    text = comment.strip()
    return bool(text) and any(pattern.search(text) for pattern in RELEVANCE_PATTERNS)


def extract_name_candidates(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    votes: dict[str, float] = {}
    counts: Counter[str] = Counter()
    evidence: dict[str, list[dict[str, str]]] = {}

    for review in reviews:
        comment = review["comment"].strip()
        ner_tokens = ner_person_tokens(comment)
        found: dict[str, float] = {}
        for pattern in NAME_PATTERNS:
            for match in pattern.finditer(comment):
                name = re.sub(r"\s+", " ", match.group(1)).strip(" .,!?:;")
                if not name or not is_plausible_name(name):
                    continue
                weight = 1.0
                if ner_tokens and all(t.lower() in ner_tokens for t in name.split()):
                    weight = 2.0  # NER agrees this is a person
                found[name] = max(found.get(name, 0.0), weight)
        for name, weight in found.items():
            votes[name] = votes.get(name, 0.0) + weight
            counts[name] += 1
            evidence.setdefault(name, []).append({
                "comment": comment,
                "work_history_job_title": review.get("work_history_job_title", ""),
            })

    # Merge a first name into a full name when it matches exactly one
    # (e.g. "Myles" into "Myles Smith").
    for short in [n for n in votes if " " not in n]:
        longer = [n for n in votes
                  if " " in n and n.split()[0].lower() == short.lower()]
        if len(longer) == 1:
            votes[longer[0]] += votes.pop(short)
            counts[longer[0]] += counts.pop(short)
            evidence[longer[0]].extend(evidence.pop(short))

    if not votes:
        return []

    total = sum(votes.values())
    support = min(1.0, total / 3.0)  # little evidence caps the confidence
    candidates = []
    for name, vote in sorted(votes.items(), key=lambda kv: kv[1], reverse=True):
        candidates.append({
            "name": name,
            "mention_count": counts[name],
            "confidence": round(vote / total * support, 3),
            "evidence": evidence[name],
        })
    return candidates


def as_dict(value: Any) -> dict[str, Any]:
    """Return value if it's a dict, otherwise an empty dict."""
    return value if isinstance(value, dict) else {}


# ---------- previous-job lookup through the job-details API ----------

DETAIL_TEMPLATE: dict[str, Any] = {}  # latest captured details request: url, headers, payload

_SKIP_HEADERS = {
    "host", "content-length", "cookie", "origin", "referer", "user-agent",
    "accept-encoding", "connection", "priority", "te", "upgrade-insecure-requests",
}
_STOP_STATUSES = {"http_401", "http_403", "http_429"}

_FETCH_JS = """
async ({url, headers, body}) => {
  try {
    const resp = await fetch(url, {method: "POST", headers, body, credentials: "include"});
    return {status: resp.status, text: await resp.text()};
  } catch (e) {
    return {status: 0, text: String(e)};
  }
}
"""


def make_detail_template(request: Request) -> dict[str, Any]:
    """Keep the URL, body and headers of a real details request (browser-controlled headers dropped)."""
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _SKIP_HEADERS
        and not k.startswith(":")
        and not k.lower().startswith("sec-")
    }
    return {"url": request.url, "headers": headers, "payload": post_data_json(request)}


def fetch_job_via_api(page: Page, ciphertext: str) -> tuple[dict[str, Any] | None, str]:
    """Run the details request inside the Upwork tab for another job's ciphertext."""
    if not DETAIL_TEMPLATE:
        return None, "no_request_template"
    payload = json.loads(json.dumps(DETAIL_TEMPLATE["payload"]))
    variables = payload.get("variables")
    if not isinstance(variables, dict) or "id" not in variables:
        return None, "template_has_no_id_variable"
    variables["id"] = ciphertext
    try:
        result = page.evaluate(_FETCH_JS, {
            "url": DETAIL_TEMPLATE["url"],
            "headers": DETAIL_TEMPLATE["headers"],
            "body": json.dumps(payload),
        })
    except Exception as exc:
        print(f"      fetch error: {exc}")
        return None, "evaluate_error"
    status = result.get("status", 0)
    if status != 200:
        return None, f"http_{status}"
    try:
        data = json.loads(result.get("text") or "")
    except json.JSONDecodeError:
        return None, "invalid_json"
    if isinstance(data, dict) and data.get("errors"):
        return None, "graphql_errors"
    if not get_detail_object(data):
        return None, "no_details"  # e.g. a private/unavailable job
    return data, "retrieved"


def extract_category(node: Any) -> tuple[str | None, str | None]:
    """Find category / categoryGroup names wherever they sit inside `node`."""
    for d in find_dicts_with_key(node, "categoryGroup"):
        category = as_dict(d.get("category")).get("name")
        group = as_dict(d.get("categoryGroup")).get("name")
        if category or group:
            return category, group
    return None, None


def top_hiring_categories(items: list[dict[str, Any]], n: int = 2) -> list[dict[str, Any]]:
    counts = Counter(
        (i.get("category"), i.get("category_group"))
        for i in items if i.get("category") or i.get("category_group")
    )
    total = sum(counts.values())
    if not total:
        return []
    return [
        {"category": c, "category_group": g, "share": round(k / total, 2)}
        for (c, g), k in counts.most_common(n)
    ]


def slim_history_object(data: dict[str, Any]) -> dict[str, Any]:
    """Copy of a previous-job response without the repeated buyer.workHistory."""
    slim = json.loads(json.dumps(data))
    buyer = as_dict(get_detail_object(slim).get("buyer"))
    buyer.pop("workHistory", None)
    return slim

def append_full_object(path: Path, kind: str, job_id: str, payload: Any,
                       parent_job_id: str | None = None) -> None:
    """Append one raw object as a line of JSONL (cheap, no rewrite of the whole file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "kind": kind,  # "current" or "history"
        "job_id": job_id,
        "parent_job_id": parent_job_id,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "payload": payload,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def enrich_work_history(page: Page, work_history: list[dict[str, Any]],
                        parent_job_id: str, cache: dict[str, dict[str, Any]]) -> None:
    """Fill description + category for the client's previous jobs via the details API."""
    api_calls = 0
    stopped = False
    for entry in work_history:
        ciphertext = entry.get("ciphertext")
        if not ciphertext:
            entry["description_status"] = "no_public_job_id"
            continue
        ciphertext = str(ciphertext)
        if not ciphertext.startswith("~"):
            ciphertext = "~" + ciphertext

        if ciphertext in cache:  # already fetched earlier in this run
            entry.update(cache[ciphertext])
            continue
        if stopped:
            entry["description_status"] = "skipped_after_block"
            continue
        if api_calls >= MAX_HISTORY_JOBS_PER_CLIENT:
            entry["description_status"] = "skipped_over_cap"
            continue

        data, status = fetch_job_via_api(page, ciphertext)
        api_calls += 1
        entry["description_status"] = status

        if data is not None:
            opening = as_dict(get_detail_object(data).get("opening"))
            job = as_dict(opening.get("job"))
            category, group = extract_category(opening)
            result = {
                "description": job.get("description"),
                "category": category,
                "category_group": group,
                "description_status": "retrieved",
            }
            entry.update(result)
            cache[ciphertext] = result
            # append_full_object(FULL_OBJECTS_FILE, "history", ciphertext, data, parent_job_id)
            append_full_object(FULL_OBJECTS_FILE, "history", ciphertext,
                               slim_history_object(data) if SLIM_HISTORY_OBJECTS else data,
                               parent_job_id)
        elif status in _STOP_STATUSES:
            print(f"      Upwork answered {status}. Stopping previous-job lookups for this client.")
            stopped = True

        time.sleep(random.uniform(*DELAY_BETWEEN_HISTORY_FETCHES_SECONDS))


def parse_details(details_payload: Any, fallback_job: dict[str, Any]) -> dict[str, Any]:
    detail = get_detail_object(details_payload)
    opening = as_dict(detail.get("opening"))
    job = as_dict(opening.get("job"))
    info = as_dict(job.get("info"))
    buyer = as_dict(detail.get("buyer"))
    buyer_info = as_dict(buyer.get("info"))

    raw_location = buyer_info.get("location")
    location = as_dict(raw_location)
    city = location.get("city")
    country = location.get("country")
    if isinstance(raw_location, str) and not country:
        country = raw_location  # location came back as plain text

    # Company profile + this job's category
    # company = as_dict(buyer.get("company"))
    company = as_dict(buyer_info.get("company")) or as_dict(buyer.get("company"))
    profile = as_dict(company.get("profile"))
    job_category, job_category_group = extract_category(opening)

    work_history = buyer.get("workHistory")
    if not isinstance(work_history, list):
        work_history = []

    all_work_history = []
    all_reviews = []  # every freelancer comment, unfiltered
    client_feedback = []  # the client's comments about the freelancer

    for entry in work_history:
        entry = as_dict(entry)
        job_info = as_dict(entry.get("jobInfo"))
        contractor_info = as_dict(entry.get("contractorInfo"))
        feedback_to_client = as_dict(entry.get("feedbackToClient"))

        ciphertext = job_info.get("ciphertext")
        job_id = ciphertext or job_info.get("id") or job_info.get("uid")

        # Keep all review text for the GLiNER/Gemini step
        raw_comment = feedback_to_client.get("comment")
        if isinstance(raw_comment, str) and raw_comment.strip():
            all_reviews.append({
                "comment": raw_comment.strip(),
                "score": feedback_to_client.get("score"),
                "work_history_job_title": job_info.get("title") or "",
                "work_history_job_id": job_id,
            })

        raw_client_fb = as_dict(entry.get(CLIENT_FEEDBACK_KEY)).get("comment")
        if isinstance(raw_client_fb, str) and raw_client_fb.strip():
            client_feedback.append({
                "comment": raw_client_fb.strip(),
                "work_history_job_title": job_info.get("title") or "",
                "work_history_job_id": job_id,
            })

        all_work_history.append({
            "title": job_info.get("title"),
            "job_id": job_id,
            "ciphertext": ciphertext,
            "access": job_info.get("access"),
            "type": job_info.get("type"),
            "status": entry.get("status"),
            "start_date": entry.get("startDate"),
            "end_date": entry.get("endDate"),
            "total_charge": entry.get("totalCharge"),
            "total_hours": entry.get("totalHours"),
            "contractor_name": contractor_info.get("contractorName"),
            "feedback_to_client": feedback_to_client.get("comment"),
            "description": None,
            "category": None,
            "category_group": None,
            "description_status": "not_attempted",
        })

    relevant_reviews: list[dict[str, Any]] = []
    for entry in work_history:
        entry = as_dict(entry)
        feedback_to_client = as_dict(entry.get("feedbackToClient"))
        comment = feedback_to_client.get("comment")
        if not isinstance(comment, str) or not comment.strip():
            continue
        if not is_relevant_review(comment):
            continue
        job_info = as_dict(entry.get("jobInfo"))
        relevant_reviews.append({
            "comment": comment.strip(),
            "score": feedback_to_client.get("score"),
            "feedback_suppressed": feedback_to_client.get("feedbackSuppressed"),
            "work_history_job_title": job_info.get("title") or "",
            "work_history_job_id": job_info.get("ciphertext") or job_info.get("id"),
            "status": entry.get("status"),
            "start_date": entry.get("startDate"),
            "end_date": entry.get("endDate"),
        })

    candidates = extract_name_candidates(relevant_reviews)
    return {
        "job_id": str(info.get("ciphertext") or info.get("id")
                      or fallback_job.get("job_id")),
        "title": info.get("title") or fallback_job.get("title"),
        "description": job.get("description") or fallback_job.get("description"),
        "url": fallback_job.get("url"),
        "client_location": {
            "city": city,
            "country": country,
            "formatted": ", ".join(
                part for part in (city, country) if isinstance(part, str) and part
            ) or None,
        },
        # Company profile from Upwork; hiring_focus is filled in main() after the
        # previous-job lookups.
        "client_info": {
            "company_name": company.get("name"),
            "company_id": company.get("companyId"),
            "industry": profile.get("industry"),
            "company_size": profile.get("size"),
            "job_category": job_category,
            "job_category_group": job_category_group,
            "hiring_focus": [],
        },
        "client_name_most_likely": candidates[0]["name"] if candidates else None,
        "client_name_confidence": candidates[0]["confidence"] if candidates else 0.0,
        "client_name_candidates": candidates,
        "reviews": all_reviews,
        "client_feedback": client_feedback,
        "relevant_reviews": relevant_reviews,
        "work_history": all_work_history,
        "review_count_relevant": len(relevant_reviews),
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def collect_search_responses(page: Page, timeout_ms: int = 90_000) -> list[Response]:
    """Type the search into the page and collect the results the page receives."""
    responses: list[Response] = []

    def on_response(resp: Response) -> None:
        if SEARCH_ALIAS.lower() in resp.url.lower() and resp.request.method.upper() == "POST":
            responses.append(resp)

    page.on("response", on_response)
    try:
        if trigger_search_from_ui(page, SEARCH_QUERY):
            print(f"Typed {SEARCH_QUERY!r} into the search box and pressed Enter.")
        else:
            print(f"Could not find the search box. Please type '{SEARCH_QUERY}' "
                  "in Upwork's search bar and press Enter in the browser now.")

        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline and not responses:
            page.wait_for_timeout(250)
        if not responses:
            raise RuntimeError("No search results were received from the page.")
        page.wait_for_timeout(1500)  # let any extra result batches arrive
        return list(responses)
    finally:
        page.remove_listener("response", on_response)


def fetch_job_details(page: Page, listing: dict[str, Any]) -> dict[str, Any] | None:
    """Click a job tile on the search page (opens the side panel) and return
    the job-details response the page receives."""
    ciphertext = str(listing.get("ciphertext") or listing.get("job_id"))
    needle = ciphertext.lstrip("~")

    # Make sure we're on the search results page.
    if "/nx/search/jobs" not in page.url:
        page.goto(CURRENT_SEARCH_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3000)

    collected: list[Response] = []

    def on_response(resp: Response) -> None:
        if DETAILS_ALIAS in resp.url and resp.request.method.upper() == "POST":
            collected.append(resp)

    page.on("response", on_response)
    try:
        link = page.locator(f"a[href*='{needle}']").first
        if link.count() == 0:
            print("  Could not find this job's tile on the search page.")
            return None
        link.scroll_into_view_if_needed()
        link.click()

        deadline = time.time() + 25
        while time.time() < deadline and not collected:
            page.wait_for_timeout(250)
        if not collected:
            print("  The side panel opened, but no job-details request arrived.")
            return None

        page.wait_for_timeout(500)  # let the response body finish

        try:  # remember this real request so previous jobs can reuse it
            DETAIL_TEMPLATE.update(make_detail_template(collected[0].request))
        except Exception as exc:
            print(f"  (could not save the details request template: {exc})")

        try:
            data = collected[0].json()
        except Exception as exc:
            print(f"  Could not read the details response: {exc}")
            return None
        if isinstance(data, dict) and data.get("errors"):
            print(f"  Page returned errors: {json.dumps(data['errors'])[:300]}")
            return None
        return data
    except Exception as exc:
        print(f"  Could not open the job panel: {exc}")
        return None
    finally:
        page.remove_listener("response", on_response)
        try:
            page.keyboard.press("Escape")  # close the side panel
            page.wait_for_timeout(1000)
        except Exception:
            pass


def search_page_url(base_url: str, page_no: int) -> str:
    """Return the search URL for result page N (keeps whatever filters the UI search produced)."""
    parts = urlparse(base_url)
    qs = parse_qs(parts.query, keep_blank_values=True)
    qs["page"] = [str(page_no)]
    qs["per_page"] = [PER_PAGE]
    if SORT:
        qs["sort"] = [SORT]
    return urlunparse(parts._replace(query=urlencode(qs, doseq=True)))


def load_search_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_search_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def collect_search_responses_via_goto(page: Page, url: str, timeout_ms: int = 60_000) -> list[Response]:
    """Open a results URL (page 2, 3, ...) and collect the search responses the page receives."""
    responses: list[Response] = []

    def on_response(resp: Response) -> None:
        if SEARCH_ALIAS.lower() in resp.url.lower() and resp.request.method.upper() == "POST":
            responses.append(resp)

    page.on("response", on_response)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        assert_not_blocked(page, f"results page {url}")
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline and not responses:
            page.wait_for_timeout(250)
        page.wait_for_timeout(1500)
        return list(responses)
    finally:
        page.remove_listener("response", on_response)


def assert_not_blocked(page: Page, where: str) -> None:
    """Fail loudly (instead of scraping nothing) when Upwork shows a bot check or a login page."""
    url = (page.url or "").lower()
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    if "just a moment" in title or "attention required" in title or "cloudflare" in title:
        raise RuntimeError(
            f"Upwork showed a bot check at {where} (title={title!r}). A datacenter IP is usually "
            "challenged; run this stage from a residential/self-hosted machine or set UPWORK_PROXY."
        )
    if "/login" in url or "account-security" in url:
        raise RuntimeError(
            f"Upwork session is not logged in at {where} ({page.url}). "
            "Refresh the UPWORK_STORAGE_STATE_B64 secret (run export_session.py again)."
        )


def restore_upwork_session(context) -> bool:
    """Load the saved Upwork cookies from the UPWORK_STORAGE_STATE_B64 secret (CI)."""
    encoded = os.getenv("UPWORK_STORAGE_STATE_B64", "").strip()
    if not encoded:
        return False
    state = json.loads(base64.b64decode(encoded).decode("utf-8"))
    cookies = state.get("cookies") or []
    if cookies:
        context.add_cookies(cookies)
        print(f"[*] Restored {len(cookies)} saved Upwork cookies.")
    return bool(cookies)


def proxy_settings() -> dict[str, str] | None:
    if not PROXY:
        return None
    parts = urlparse(PROXY)
    settings = {"server": f"{parts.scheme}://{parts.hostname}:{parts.port}"}
    if parts.username:
        settings["username"] = parts.username
        settings["password"] = parts.password or ""
    return settings


def process_listing(
    page: Page,
    listing: dict[str, Any],
    index: int,
    total: int,
    records: list[dict[str, Any]],
    known_ids: set[str],
    history_cache: dict[str, dict[str, Any]],
) -> bool:
    """Scrape one job (details, GLiNER client-name check, previous jobs). True if a record was added."""
    job_id = str(listing.get("job_id"))
    print(f"[{index}/{total}] Opening {listing.get('title') or job_id}")
    try:
        details_response = fetch_job_details(page, listing)
        if details_response is None:
            wait_for_enter(
                page,
                "  If a check appeared, solve it in the browser, then press Enter to retry "
                "(or just press Enter to skip)... ",
            )
            details_response = fetch_job_details(page, listing)
        if details_response is None:
            print("  Skipping this job.")
            return False

        parsed = parse_details(details_response, listing)

        # Keep the raw current-job objects in the side file.
        append_full_object(
            FULL_OBJECTS_FILE, "current",
            str(parsed.get("job_id") or job_id),
            {"search_result": listing.get("search_result"), "details": details_response},
        )

        # GLiNER on the reviews: is there a client name?
        try:
            analysis = analyze_record(parsed)
            parsed.update(analysis)
            has_name = analysis["has_client_name"]
        except Exception as exc:
            print(f"  GLiNER extraction failed ({exc}); falling back to the regex name.")
            has_name = bool(parsed.get("client_name_most_likely"))

        work_history = parsed.get("work_history", [])
        client_info = parsed["client_info"]
        print(f"  Historical contracts found: {len(work_history)}")

        if not has_name:
            print("  No client name found in reviews. Skipping previous-job lookups.")
            for entry in work_history:
                entry["description_status"] = "skipped_no_client_name"
        elif FETCH_HISTORY_ONLY_IF_NO_INDUSTRY and client_info.get("industry"):
            print(f"  Industry from Upwork: {client_info['industry']}. "
                  "Skipping previous-job lookups.")
            for entry in work_history:
                entry["description_status"] = "skipped_industry_known"
        else:
            print(f"  Client name: {parsed.get('client_name_most_likely')}. "
                  "Fetching previous jobs through the details API...")
            enrich_work_history(
                page, work_history,
                str(parsed.get("job_id") or job_id), history_cache,
            )
            print("  Previous-job statuses:",
                  dict(Counter(e["description_status"] for e in work_history)))

        current = {
            "category": client_info.get("job_category"),
            "category_group": client_info.get("job_category_group"),
        }
        client_info["hiring_focus"] = top_hiring_categories([current] + work_history)

        if not parsed.get("job_id"):
            parsed["job_id"] = job_id
        parsed["search_result"] = {
            "title": listing.get("title"),
            "description": listing.get("description"),
            "ciphertext": listing.get("ciphertext"),
            "url": listing.get("url"),
        }
        records.append(parsed)
        known_ids.add(str(parsed["job_id"]))
        write_json_atomically(OUTPUT_FILE, records)
        return True
    except Exception as exc:
        print(f"  ERROR: {exc}", file=sys.stderr)
        traceback.print_exc()
        return False


def main() -> int:
    global CURRENT_SEARCH_URL

    records, known_ids = load_existing(OUTPUT_FILE)
    state = load_search_state()
    start_page = max(1, int(state.get("next_page", 1)))
    print(f"Existing records: {len(records)}; known job IDs: {len(known_ids)}")
    print(f"Persistent profile: {PROFILE_DIR.resolve()}")
    print(f"Query: {SEARCH_QUERY!r}; start page: {start_page}; "
          f"max new jobs this run: {JOBS_PER_RUN}; max pages: {MAX_PAGES}")
    if not NONINTERACTIVE:
        print("Opening Upwork. On first run, log in manually in the browser window.")
        print("If a security challenge/block appears, resolve it manually and do not try to bypass it.")

    launch_args = ["--start-maximized"]
    if NONINTERACTIVE:
        launch_args += ["--no-sandbox", "--disable-dev-shm-usage"]

    with sync_playwright() as p:  # Patchright uses the Playwright-compatible API
        launch_kwargs: dict[str, Any] = dict(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",      # real Chrome instead of bundled Chromium
            headless=HEADLESS,
            no_viewport=True,      # don't force a fixed viewport
            args=launch_args,
        )
        proxy = proxy_settings()
        if proxy:
            launch_kwargs["proxy"] = proxy
        context = p.chromium.launch_persistent_context(**launch_kwargs)
        page = context.pages[0] if context.pages else context.new_page()
        added = 0
        try:
            restore_upwork_session(context)

            page.goto(
                "https://www.upwork.com/",
                wait_until="domcontentloaded",
                timeout=60_000,
            )

            print("\nUpwork homepage navigation completed.")
            print(f"Current URL: {page.url}")
            assert_not_blocked(page, "the Upwork homepage")
            wait_for_enter(page, "When login is complete, press Enter here... ")

            open_pages = [tab for tab in context.pages if not tab.is_closed()]
            if not open_pages:
                raise RuntimeError("No browser tabs are open.")
            if page.is_closed():
                raise RuntimeError(
                    "The original Upwork tab was closed during login. "
                    "Rerun the script and keep the original Upwork tab open."
                )

            print(f"\nNavigating to search from: {page.url}")
            try:
                response = page.goto(
                    SEARCH_URL,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
            except Exception as exc:
                print(f"\nNAVIGATION FAILED: {type(exc).__name__}: {exc}")
                print(f"URL at failure: {page.url}")
                raise

            print(
                "Navigation HTTP status:",
                response.status if response else "No response",
            )
            print(f"Actual URL after navigation: {page.url}")
            print(f"Page title: {page.title()}")
            assert_not_blocked(page, "the search page")

            if "/nx/search/jobs" not in page.url:
                raise RuntimeError(
                    "Search page was not reached. "
                    "The actual URL is printed above. "
                    "Stopping before any scraping requests."
                )

            # The first page always comes from the real search box (page 1 results).
            first_page_responses = collect_search_responses(page)
            base_search_url = page.url

            history_cache: dict[str, dict[str, Any]] = {}
            page_no = start_page
            pages_done = 0

            while pages_done < MAX_PAGES and added < JOBS_PER_RUN:
                if page_no == 1:
                    search_responses = first_page_responses
                else:
                    search_responses = collect_search_responses_via_goto(
                        page, search_page_url(base_search_url, page_no)
                    )

                listings: list[dict[str, Any]] = []
                seen_ids: set[str] = set()
                for resp in search_responses:
                    payload = response_json(resp)
                    if payload is None:
                        continue
                    for job in extract_search_jobs(payload):
                        if job["job_id"] not in seen_ids:
                            seen_ids.add(job["job_id"])
                            listings.append(job)

                if not listings:
                    print(f"Page {page_no} returned no jobs; end of results. Next run restarts at page 1.")
                    save_search_state({"next_page": 1})
                    break

                CURRENT_SEARCH_URL = page.url if page_no > 1 else base_search_url

                for item in listings:
                    ciphertext = str(item.get("ciphertext") or item.get("job_id"))
                    item["url"] = find_job_anchor(page, ciphertext) or normalize_job_url(
                        ciphertext, item.get("title")
                    )

                pending = [j for j in listings if str(j.get("job_id")) not in known_ids]
                print(f"Page {page_no}: search jobs collected: {len(listings)}; new IDs: {len(pending)}")

                finished_page = True
                for index, listing in enumerate(pending, start=1):
                    if added >= JOBS_PER_RUN:
                        finished_page = False
                        break
                    if process_listing(page, listing, index, len(pending),
                                       records, known_ids, history_cache):
                        added += 1
                    time.sleep(DELAY_BETWEEN_DETAILS_SECONDS)

                page_no = page_no if not finished_page else page_no + 1
                save_search_state({"next_page": page_no})
                pages_done += 1

            print(f"\nFinished. New records this run: {added}; total JSON records: {len(records)}")
            print(f"Output: {OUTPUT_FILE.resolve()}")
            print(f"Raw job objects: {FULL_OBJECTS_FILE.resolve()}")
            return 0

        finally:
            context.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped by user. Completed records already saved.")
