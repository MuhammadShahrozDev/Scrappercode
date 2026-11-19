"""
Client name / company extraction from Upwork reviews, using a small quantized
GLiNER model (INT8 ONNX, ~205 MB). No browser, no Upwork requests, no Gemini.

Two ways to use it:

1. Imported by the scraper, to decide whether a client's previous jobs are
   worth fetching (only when a client person name is found in the reviews):

       from client_extraction import analyze_record
       analysis = analyze_record(parsed)      # parsed = one scraped job record
       parsed.update(analysis)
       if analysis["has_client_name"]: ...

2. Run offline on the scraper's JSON (re-processing without re-scraping):

       python client_extraction.py

Two kinds of review text are analysed:

- record["reviews"]         freelancer -> client feedback.
                            Client person names AND company names are taken.
- record["client_feedback"] client -> freelancer feedback (optional field).
                            Company names ONLY. Any person name in it is the
                            freelancer's, so person entities are ignored.

Reviews that contain both a client person name and a company name are collected
in "gemini_review_queue" for the later Gemini verification step (not done here).

Install:  pip install "gliner[onnx]"
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

INPUT_FILE = DATA_DIR / "upwork_agentic_ai_jobs.json"
OUTPUT_FILE = DATA_DIR / "upwork_agentic_ai_jobs_with_names.json"

MODEL_ID = "GG-QandV/gliner_small-v2.5-onnx"
MODEL_FILE = "model_quantized.onnx"
THRESHOLD = 0.4
MAX_COMMENT_CHARS = 1500
MAX_EVIDENCE_PER_CANDIDATE = 3

FROM_FREELANCER = "from_freelancer"  # freelancer's feedback about the client
FROM_CLIENT = "from_client"          # client's feedback about the freelancer

# (company label, person label, tool label). Natural-language labels: the
# "software tool" label soaks up vendors (Salesforce, OpenAI...) so they do not
# end up in the company column.
LABELS_FROM_FREELANCER = ("client company name", "client person name", "software tool or platform")
LABELS_FROM_CLIENT = ("company name", "person name", "software tool or platform")

# Vendors / tech terms that are never "the client's company". Extend as you
# find more in real data.
IGNORE = {
    "openai", "anthropic", "aws", "google", "slack", "upwork", "salesforce", "hubspot",
    "microsoft", "github", "zoom", "notion", "stripe", "paypal", "chatgpt", "gemini",
    "llm", "api", "ai", "ml", "gpt", "sql",
}
GENERIC = {"client", "company", "team", "the client", "he", "she", "they", "him", "her"}
GENERIC_SUFFIX = (" company", " team", " firm", " agency", " startup")


# ---------------------------------------------------------------------------
# Model (loaded once, on first use, so importing this file stays cheap)
# ---------------------------------------------------------------------------

_MODEL: Any = None


def get_model() -> Any:
    global _MODEL
    if _MODEL is None:
        from gliner import GLiNER  # imported here so `import client_extraction` is fast

        _MODEL = GLiNER.from_pretrained(
            MODEL_ID,
            load_onnx_model=True,
            onnx_model_file=MODEL_FILE,
        )
    return _MODEL


# ---------------------------------------------------------------------------
# Cleaning / filtering
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip(" .,!?:;'\"")
    return re.sub(r"['\u2019]s$", "", t)  # "Jason's" -> "Jason"


def _strip_title(name: str) -> str:
    return re.sub(r"^(?:Mr|Mrs|Ms|Dr)\.?\s+", "", name).strip()


def _is_generic(text: str) -> bool:
    low = text.lower()
    if low in GENERIC:
        return True
    # "retail company" is a descriptor, not a name; "Acme Labs" has a capitalised word, so it passes.
    return low.endswith(GENERIC_SUFFIX) and not any(w[0].isupper() for w in text.split())


def _is_person_name(text: str) -> bool:
    return (
        bool(text)
        and text.lower() not in GENERIC
        and not any(ch.isdigit() for ch in text)
        and text[0].isupper()
        and len(text.split()) <= 3
    )


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for item in items:
        key = item["name"].lower()
        if key not in best or item["score"] > best[key]["score"]:
            best[key] = item
    return list(best.values())


# ---------------------------------------------------------------------------
# One review comment
# ---------------------------------------------------------------------------

def analyze_comment(text: str, direction: str) -> dict[str, Any]:
    """Return {"people": [...], "companies": [...], "tools": [...]} for one comment.

    For FROM_CLIENT comments "people" is always empty (they would be the freelancer).
    """
    model = get_model()
    labels = LABELS_FROM_FREELANCER if direction == FROM_FREELANCER else LABELS_FROM_CLIENT
    company_label, person_label, tool_label = labels

    text = text[:MAX_COMMENT_CHARS]
    entities = model.predict_entities(text, list(labels), threshold=THRESHOLD)
    tools = {_clean(e["text"]).lower() for e in entities if e["label"] == tool_label}

    def company_ok(name: str) -> bool:
        low = name.lower()
        return bool(name) and low not in IGNORE and low not in tools and not _is_generic(name)

    companies: list[dict[str, Any]] = []
    for e in entities:
        if e["label"] != company_label:
            continue
        name = _clean(e["text"])
        if company_ok(name):
            companies.append({"name": name, "score": round(float(e["score"]), 3)})

    if not companies:  # rescue pass: the plain "company" label catches names the long label misses
        for e in model.predict_entities(text, ["company"], threshold=THRESHOLD):
            name = _clean(e["text"])
            if company_ok(name):
                companies.append({"name": name, "score": round(float(e["score"]), 3)})

    people: list[dict[str, Any]] = []
    if direction == FROM_FREELANCER:  # never take person names from the client's feedback
        for e in entities:
            if e["label"] != person_label:
                continue
            name = _strip_title(_clean(e["text"]))
            if _is_person_name(name):
                people.append({"name": name, "score": round(float(e["score"]), 3)})

    return {
        "people": _dedupe(people),
        "companies": _dedupe(companies),
        "tools": sorted(tools),
    }


# ---------------------------------------------------------------------------
# Combine all reviews of one job record
# ---------------------------------------------------------------------------

def _aggregate(hits: list[dict[str, Any]], merge_first_names: bool) -> list[dict[str, Any]]:
    """Group mentions of the same name and score them.

    confidence = mean GLiNER score, halved when the name appears in only one review.
    """
    groups: dict[str, dict[str, Any]] = {}
    for h in hits:
        g = groups.setdefault(h["name"].lower(), {
            "names": Counter(), "scores": [], "evidence": [], "sources": set(),
        })
        g["names"][h["name"]] += 1
        g["scores"].append(h["score"])
        g["evidence"].append({"comment": h["comment"], "work_history_job_title": h["title"]})
        g["sources"].add(h["source"])

    if merge_first_names:  # "Myles" + "Myles Smith" -> one entry, only when unambiguous
        for short in [k for k in groups if " " not in k]:
            longer = [k for k in groups if " " in k and k.split()[0] == short]
            if len(longer) == 1:
                target, source = groups[longer[0]], groups.pop(short)
                target["names"].update(source["names"])
                target["scores"] += source["scores"]
                target["evidence"] += source["evidence"]
                target["sources"] |= source["sources"]

    out: list[dict[str, Any]] = []
    for g in groups.values():
        count = len(g["scores"])
        mean = sum(g["scores"]) / count
        display = max(g["names"], key=lambda n: (len(n.split()), g["names"][n]))
        out.append({
            "name": display,
            "mention_count": count,
            "mean_score": round(mean, 3),
            "confidence": round(mean * min(1.0, count / 2), 3),
            "sources": sorted(g["sources"]),
            "evidence": g["evidence"][:MAX_EVIDENCE_PER_CANDIDATE],
        })
    out.sort(key=lambda c: (c["confidence"], c["mention_count"]), reverse=True)
    return out


def _usable_reviews(value: Any) -> list[dict[str, Any]]:
    return [
        r for r in (value or [])
        if isinstance(r, dict) and isinstance(r.get("comment"), str) and r["comment"].strip()
    ]


def analyze_record(record: dict[str, Any]) -> dict[str, Any]:
    """Analyse one scraped job record and return the fields to merge into it."""
    from_freelancer = _usable_reviews(record.get("reviews"))
    from_client = _usable_reviews(record.get("client_feedback"))

    person_hits: list[dict[str, Any]] = []
    company_hits: list[dict[str, Any]] = []
    gemini_queue: list[dict[str, Any]] = []

    for direction, reviews in ((FROM_FREELANCER, from_freelancer), (FROM_CLIENT, from_client)):
        for review in reviews:
            comment = review["comment"].strip()
            title = str(review.get("work_history_job_title") or "")
            result = analyze_comment(comment, direction)

            for p in result["people"]:
                person_hits.append({**p, "comment": comment, "title": title, "source": direction})
            for c in result["companies"]:
                company_hits.append({**c, "comment": comment, "title": title, "source": direction})

            # Later Gemini step: only freelancer->client reviews where both a
            # client name and a company were found.
            # if direction == FROM_FREELANCER and result["people"] and result["companies"]:
            if direction == FROM_FREELANCER and result["companies"]:
                gemini_queue.append({
                    "direction": direction,
                    "comment": comment,
                    "work_history_job_title": title,
                    "people": [p["name"] for p in result["people"]],
                    "companies": [c["name"] for c in result["companies"]],
                })

    people = _aggregate(person_hits, merge_first_names=True)
    companies = _aggregate(company_hits, merge_first_names=False)

    return {
        "client_name_most_likely": people[0]["name"] if people else None,
        "client_name_confidence": people[0]["confidence"] if people else 0.0,
        "client_name_candidates": people,
        "company_most_likely": companies[0]["name"] if companies else None,
        "company_candidates": companies,
        "has_client_name": bool(people),  # the scraper's gate for fetching previous jobs
        "gemini_review_queue": gemini_queue,
        "review_counts": {FROM_FREELANCER: len(from_freelancer), FROM_CLIENT: len(from_client)},
        "extraction_method": f"gliner:{MODEL_ID}",
    }


# ---------------------------------------------------------------------------
# Offline run over the scraper's JSON
# ---------------------------------------------------------------------------

def main() -> None:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Scraper output not found: {INPUT_FILE}. Run the scraper first."
        )
    records = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"Expected a JSON array in {INPUT_FILE}")

    for index, record in enumerate(records, start=1):
        record.update(analyze_record(record))
        print(
            f"[{index}/{len(records)}] {record.get('title') or record.get('job_id')}: "
            f"name={record['client_name_most_likely']} | company={record['company_most_likely']} | "
            f"gemini_queue={len(record['gemini_review_queue'])} | "
            f"fetch_history={record['has_client_name']}"
        )

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = OUTPUT_FILE.with_suffix(OUTPUT_FILE.suffix + ".tmp")
    temp_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_file.replace(OUTPUT_FILE)

    with_name = sum(1 for r in records if r["has_client_name"])
    print(f"\nProcessed {len(records)} records; client name found in {with_name}.")
    print(f"Output: {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()