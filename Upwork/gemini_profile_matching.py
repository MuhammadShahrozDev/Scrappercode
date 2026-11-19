
"""
Upwork -> LinkedIn final profile matching.

Flow:
1. Keep only LinkedIn candidates whose names exactly match an Upwork name.
   Matching is case/punctuation/whitespace insensitive. First and last names
   must match exactly; middle names may be omitted or represented by initials.
   No fuzzy, phonetic, spelling-correction, or AI name matching is used.
2. If the search was a company search:
   - More than one exact-name candidate: send the candidates to Gemini.
   - Exactly one exact-name candidate: save that profile directly; do not call Gemini.
   - Zero exact-name candidates: save the case as having no eligible candidates.
3. For non-company searches, send all exact-name candidates to Gemini as usual.
4. Gemini selects the most probable person using the complete case evidence.

Input:
- xnew_upwork_agentic_ai_jobs_industry.json: Upwork job/client/company/industry data.
- linkedin_client_profile_details.json: profiles collected by linkedin_profile_scrape.py.
- The script joins records using job_id and builds matching cases automatically.
- matching_cases.json remains available as a manual test input.

Set GEMINI_API_KEY in your .env file or environment before running.
"""

import os
import re
import json
import time
from pathlib import Path
from collections import defaultdict

from dotenv import load_dotenv
from google import genai
from google.genai import types


MODEL = "gemini-3.5-flash-lite"

DELAY = float(os.getenv("GEMINI_DELAY_SECONDS", "5"))

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

UPWORK_FILE = DATA_DIR / "upwork_agentic_ai_jobs_industry.json"
LINKEDIN_FILE = DATA_DIR / "linkedin_client_profile_details.json"

MANUAL_INPUT_FILE = DATA_DIR / "matching_cases.json"

RESULT_FILE = DATA_DIR / "linkedin_matching_results.json"


# ---------------------------------------------------------------------
# EMBEDDED TEST CASE FROM THE FINAL NOTEBOOK
# ---------------------------------------------------------------------

MATCHING_CASE = {
    "id": "test_001",

    "upwork_client": {
        "client_name": "Muhammad Zahid",
        "client_location": {
            "city": "New York",
            "country": "United States",
            "formatted": "New York, United States"
        },
        "client_name_confidence": 0.625
    },

    "original_job": {
        "title": "AI Agent & RAG Application Development",
        "description": """
        We are looking for an experienced AI developer to build an AI-powered
        application using RAG architecture. The system should be able to
        retrieve information from documents, answer user questions, and
        integrate with external APIs.

        Experience with Python, LLMs, vector databases, embeddings, and
        agent-based workflows is required.
        """
    },

    "work_history": [
        {
            "project_id": "P001",
            "title": "AI Automation and RAG Development",
            "description": """
            Build an AI-powered knowledge assistant using document retrieval,
            vector databases, OpenAI APIs, and Python. The application should
            support automated question answering and workflow execution.
            """,
            "status": "In Progress",
            "start_date": "2026-08-10",
            "end_date": None
        },
        {
            "project_id": "P002",
            "title": "n8n Automation with Shopify and WooCommerce",
            "description": """
            Develop automated workflows connecting Shopify, WooCommerce,
            CRM systems, and external APIs. Automate order processing,
            customer notifications, and business operations.
            """,
            "status": "Completed",
            "start_date": "2026-04-01",
            "end_date": "2026-06-15"
        },
        {
            "project_id": "P003",
            "title": "AI Website Assistant and MCP Integration",
            "description": """
            Create an AI assistant for a business website with MCP integration,
            API connections, and automated customer support functionality.
            """,
            "status": "Completed",
            "start_date": "2026-02-01",
            "end_date": "2026-03-20"
        },
        {
            "project_id": "P004",
            "title": "Amazon PPC Campaign Management",
            "description": """
            Manage Amazon advertising campaigns, optimize product listings,
            analyze campaign performance, and improve advertising ROI.
            """,
            "status": "Completed",
            "start_date": "2025-11-01",
            "end_date": "2026-01-15"
        },
        {
            "project_id": "P005",
            "title": "Medical Billing and Accounts Receivable Support",
            "description": """
            Provide medical billing support, insurance claim follow-ups,
            accounts receivable management, and payment reconciliation.
            """,
            "status": "Completed",
            "start_date": "2025-07-01",
            "end_date": "2025-10-01"
        },
        {
            "project_id": "P006",
            "title": "QuickBooks Bookkeeping for Real Estate Business",
            "description": """
            Manage bookkeeping, transaction categorization, reconciliation,
            and financial reporting for a real estate business.
            """,
            "status": "Completed",
            "start_date": "2025-03-01",
            "end_date": "2025-06-01"
        },
        {
            "project_id": "P007",
            "title": "Shopify Store Email Marketing with Klaviyo",
            "description": """
            Set up Klaviyo email automation, customer segmentation,
            abandoned cart flows, and promotional campaigns for Shopify.
            """,
            "status": "Completed",
            "start_date": "2024-11-01",
            "end_date": "2025-02-01"
        },
        {
            "project_id": "P008",
            "title": "B2B Lead Generation and Executive Assistance",
            "description": """
            Research potential business customers, build lead lists,
            manage outreach, and provide administrative support.
            """,
            "status": "Completed",
            "start_date": "2024-06-01",
            "end_date": "2024-10-01"
        },
        {
            "project_id": "P009",
            "title": "Social Media Content and Marketing",
            "description": """
            Create social media content, manage publishing schedules,
            and support digital marketing activities.
            """,
            "status": "Completed",
            "start_date": "2024-01-01",
            "end_date": "2024-05-01"
        },
        {
            "project_id": "P010",
            "title": "Business Operations Consultation",
            "description": None,
            "description_status": "private_or_unavailable",
            "status": "Completed",
            "start_date": "2023-08-01",
            "end_date": "2023-10-01"
        }
    ]
}


MATCHING_CASE["linkedin_candidates"] = [

    {
        "candidate_id": "C001",
        "linkedin_profile_url": "https://www.linkedin.com/in/muhammad-zahid-ventures/",
        "profile_details": {
            "name": "Muhammad Zahid",
            "headline": "Founder | E-commerce & Digital Business Operator",
            "location": "New York, New York, United States",

            "about": """
            Entrepreneur managing multiple online businesses.
            Experience in e-commerce operations, digital marketing,
            business administration, and technology implementation.

            Interested in automation and improving business operations
            through external technology partners.
            """,

            "experience": [
                {
                    "company": "Zahid Digital Commerce",
                    "title": "Founder",
                    "start_date": "2021",
                    "end_date": None,
                    "description": """
                    Founded an e-commerce business operating Shopify stores.
                    Oversees store operations, marketing, customer management,
                    and external service providers.
                    """
                },
                {
                    "company": "Zahid Business Services",
                    "title": "Managing Director",
                    "start_date": "2018",
                    "end_date": None,
                    "description": """
                    Provides digital operations and business support services.
                    Manages contractors for marketing, administrative work,
                    bookkeeping, and technology projects.
                    """
                },
                {
                    "company": "Independent",
                    "title": "E-commerce Consultant",
                    "start_date": "2015",
                    "end_date": "2018",
                    "description": """
                    Helped small businesses with online store setup,
                    digital marketing, and business operations.
                    """
                }
            ],

            "education": [
                {
                    "institution": "Baruch College",
                    "degree": "MBA",
                    "field": "Business Administration"
                }
            ],

            "skills": [
                "Shopify",
                "E-commerce",
                "Digital Marketing",
                "Business Operations",
                "Vendor Management",
                "Business Automation"
            ]
        }
    },

    {
        "candidate_id": "C002",
        "linkedin_profile_url": "https://www.linkedin.com/in/muhammad-zahid-tech-ventures/",
        "profile_details": {
            "name": "Muhammad Zahid",
            "headline": "Founder & CEO | AI Solutions | Technology Consulting",
            "location": "New York, New York, United States",

            "about": """
            Technology entrepreneur and founder of a software consulting
            company. Experience in AI applications, enterprise software,
            cloud solutions, and digital transformation.

            Also involved in technology-enabled business ventures.
            """,

            "experience": [
                {
                    "company": "Zahid AI Labs",
                    "title": "Founder & CEO",
                    "start_date": "2022",
                    "end_date": None,
                    "description": """
                    Builds AI-powered software products, RAG applications,
                    AI agents, and automation solutions for business clients.
                    Manages technical teams and external contractors.
                    """
                },
                {
                    "company": "Digital Ventures Group",
                    "title": "Co-Founder",
                    "start_date": "2019",
                    "end_date": None,
                    "description": """
                    Technology-focused venture studio investing in and
                    developing digital products and online businesses.
                    """
                },
                {
                    "company": "Microsoft",
                    "title": "Principal Software Engineer",
                    "start_date": "2014",
                    "end_date": "2019",
                    "description": """
                    Developed enterprise software and cloud applications.
                    """
                }
            ],

            "education": [
                {
                    "institution": "Columbia University",
                    "degree": "MS",
                    "field": "Computer Science"
                }
            ],

            "skills": [
                "Artificial Intelligence",
                "Python",
                "RAG",
                "LLMs",
                "AI Agents",
                "Cloud Architecture",
                "E-commerce Technology",
                "Business Automation"
            ]
        }
    },

    {
        "candidate_id": "C003",
        "linkedin_profile_url": "https://www.linkedin.com/in/zahid-ahmed-medical/",
        "profile_details": {
            "name": "Zahid Ahmed",
            "headline": "Founder | Healthcare & Business Services",
            "location": "Newark, New Jersey, United States",

            "about": """
            Business owner with experience in healthcare administration,
            medical billing, and real estate operations.
            """,

            "experience": [
                {
                    "company": "Apex Medical Services",
                    "title": "Founder",
                    "start_date": "2019",
                    "end_date": None,
                    "description": """
                    Runs a medical billing and healthcare administration
                    business.
                    """
                },
                {
                    "company": "Apex Property Group",
                    "title": "Managing Partner",
                    "start_date": "2016",
                    "end_date": None,
                    "description": """
                    Manages real estate investments and property operations.
                    """
                }
            ],

            "education": [
                {
                    "institution": "Rutgers University",
                    "degree": "Bachelor's Degree",
                    "field": "Business"
                }
            ],

            "skills": [
                "Medical Billing",
                "Healthcare Administration",
                "Real Estate",
                "Bookkeeping"
            ]
        }
    }
]


# ---------------------------------------------------------------------
# FINAL GEMINI PROMPT
# ---------------------------------------------------------------------

PROMPT = """
You are an identity-matching assistant.

Your task is to identify which LinkedIn candidate is most likely
to be the person behind an Upwork client account.

You will receive:
1. Upwork client name and location.
2. The original Upwork job title and description.
3. The client's previous and ongoing Upwork projects.
4. Multiple LinkedIn candidate profiles.

Analyze all the information together.

MATCHING OBJECTIVE:

The goal is to identify the MOST PROBABLE LinkedIn candidate
behind the Upwork client account, not to prove identity with
absolute certainty.

Always select the strongest candidate when the available
evidence allows a meaningful comparison.

Evaluate candidates using the combined evidence:
- Name and location similarity
- Professional and business background
- Company ownership and business activities
- Alignment with the complete Upwork project history
- Chronological alignment between the candidate's career
  and the client's Upwork hiring history
- Alignment with current and historical projects

Do not require direct evidence linking a LinkedIn account
to an Upwork account before selecting a candidate.

Do not treat missing profile information or differences in
professional specialization as contradictions.

Compare candidates against each other. The strongest candidate
may be a probable match even when some evidence is indirect.

CONFIDENCE:
Confidence represents how probable the selected candidate is
relative to the available alternatives. It does not represent
proof of identity.

MATCH STATUS:
- matched: One candidate is clearly the most probable match.
- uncertain: A leading candidate exists, but multiple candidates
  remain reasonably plausible.
- insufficient_evidence: There is not enough information to
  make a meaningful selection.

When a candidate aligns less strongly with some parts of the
Upwork history than another candidate, describe this as weaker
comparative alignment, not contradicting evidence.

Reserve contradicting evidence for actual inconsistencies
between known facts.

Even when status is uncertain, return the strongest candidate
as best_match whenever possible.

A candidate can rank first without having a verified identity connection.

Use these confidence guidelines:
- 0.90–1.00: Strong, specific identity connection.
- 0.75–0.89: Strong evidence, but identity connection is incomplete.
- 0.50–0.74: Plausible candidate with significant uncertainty.
- Below 0.50: Weak evidence.

Return valid JSON only:

{
  "best_match": {
    "candidate_id": "",
    "name": "",
    "linkedin_profile_url": "",
    "confidence": 0.0
  },
  "alternative_candidates": [],
  "candidate_analysis": [
    {
      "candidate_id": "",
      "name": "",
      "linkedin_profile_url": "",
      "direct_evidence": [],
      "indirect_evidence": [],
      "contradicting_evidence": [],
      "missing_information": [],
      "assessment": ""
    }
  ],
  "identity_verification": {
    "established": false,
    "evidence": [],
    "explanation": ""
  },
  "final_reasoning": "",
  "match_status": "matched"
}

Allowed match_status values:
- matched
- uncertain
- insufficient_evidence

Use "matched" only when the available evidence sufficiently
establishes the identity. Otherwise use "uncertain" or
"insufficient_evidence".

If no candidate is sufficiently supported, best_match may be null.
"""


# ---------------------------------------------------------------------
# NAME MATCHING
# ---------------------------------------------------------------------

def normalize_name_tokens(value):
    """Normalize case, punctuation and whitespace without fuzzy matching."""
    if not isinstance(value, str):
        return []

    # Treat punctuation (including periods in initials) as separators.
    return re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE)


def names_match_exactly(candidate_name, upwork_name):
    """
    Match when all normalized tokens of the Upwork name appear
    consecutively in the LinkedIn profile name.
    """
    candidate = normalize_name_tokens(candidate_name)
    upwork = normalize_name_tokens(upwork_name)

    if not candidate or not upwork:
        return False

    candidate_text = " ".join(candidate)
    upwork_text = " ".join(upwork)

    return upwork_text in candidate_text


def collect_upwork_names(case):
    """Collect the known Upwork client name and any extracted name candidates."""
    client = case.get("upwork_client") or {}
    names = []

    def add_name(value):
        if isinstance(value, str) and value.strip():
            cleaned = value.strip()
            if cleaned not in names:
                names.append(cleaned)
        elif isinstance(value, dict):
            for key in ("name", "candidate_name", "client_name", "value"):
                add_name(value.get(key))

    for key in ("client_name", "client_name_most_likely", "most_likely_name"):
        add_name(client.get(key))
        add_name(case.get(key))

    for key in ("client_name_candidates", "name_candidates", "upwork_names"):
        value = client.get(key, case.get(key))
        if isinstance(value, list):
            for item in value:
                add_name(item)
        else:
            add_name(value)

    return names


def filter_candidates_by_exact_name(case):
    """Return eligible candidates and a record of candidates excluded by name."""
    upwork_names = collect_upwork_names(case)
    all_candidates = case.get("linkedin_candidates") or []

    eligible = []
    excluded = []

    for candidate in all_candidates:
        profile = candidate.get("profile_details") or {}
        linkedin_name = profile.get("name", "")

        matched_names = [
            name for name in upwork_names
            if names_match_exactly(linkedin_name, name)
        ]

        if matched_names:
            eligible.append(candidate)
        else:
            excluded.append({
                "candidate_id": candidate.get("candidate_id"),
                "name": linkedin_name,
                "linkedin_profile_url": candidate.get("linkedin_profile_url"),
                "reason": "No exact first-and-last-name match with the Upwork name(s)."
            })

    filtered_case = dict(case)
    filtered_case["linkedin_candidates"] = eligible

    return filtered_case, {
        "upwork_names_checked": upwork_names,
        "original_candidate_count": len(all_candidates),
        "eligible_candidate_count": len(eligible),
        "excluded_candidates": excluded
    }


def is_company_search(case):
    """Detect company-search metadata from the case or its search metadata."""
    search_metadata = (
        case.get("linkedin_search")
        or case.get("linkedin_search_metadata")
        or {}
    )

    search_type = (
        case.get("search_type")
        or case.get("linkedin_search_type")
        or search_metadata.get("search_type")
        or search_metadata.get("type")
        or ""
    )

    return str(search_type).strip().casefold() == "company"


# ---------------------------------------------------------------------
# GEMINI
# ---------------------------------------------------------------------

def ask_gemini(case, tries=3):
    contents = (
        PROMPT
        + "\n\nINPUT DATA:\n"
        + json.dumps(case, ensure_ascii=False, indent=2)
    )

    for attempt in range(tries):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json"
                )
            )

            return json.loads(response.text)

        except Exception as exc:
            if attempt == tries - 1:
                raise

            print(f"Attempt {attempt + 1} failed: {exc}")
            time.sleep(3 * (attempt + 1))


# ---------------------------------------------------------------------
# CASE PROCESSING
# ---------------------------------------------------------------------

def process_case(case):
        # Preserve company-search profiles that were deliberately not scraped.
    skipped_profiles = [
        candidate
        for candidate in case.get("linkedin_candidates", [])
        if candidate.get("scrape_status")
        == "skipped_single_profile_company_search"
    ]

    if skipped_profiles:
        candidate = skipped_profiles[0]
        note = candidate.get("note", "")

        print(
            f"\n[SKIP] Profile scraping was skipped for "
            f"company search: {candidate.get('linkedin_profile_url')}"
        )
        print("[SKIP] Gemini not called.")

        return {
            "id": case.get("id", "unknown"),
            "input_client": (
                case.get("upwork_client") or {}
            ).get("client_name", ""),
            "name_filter": None,
            "saved_profile": candidate,
            "result": {
                "best_match": {
                    "candidate_id": candidate.get("candidate_id", ""),
                    "name": "",
                    "linkedin_profile_url": candidate.get(
                        "linkedin_profile_url", ""
                    ),
                    "confidence": None
                },
                "alternative_candidates": [],
                "candidate_analysis": [],
                "identity_verification": {
                    "established": False,
                    "evidence": [],
                    "explanation": note
                },
                "final_reasoning": note,
                "match_status": "profile_scraping_skipped"
            }
        }

    filtered_case, filtering = filter_candidates_by_exact_name(case)

    case_id = case.get("id", "unknown")
    client_name = (case.get("upwork_client") or {}).get("client_name", "")

    output = {
        "id": case_id,
        "input_client": client_name,
        "name_filter": filtering,
        "result": None,
        "saved_profile": None
    }

    candidates = filtered_case["linkedin_candidates"]

    print("\n" + "=" * 75)
    print(f"CASE: {case_id} | Upwork client: {client_name}")
    print(
        f"Name filter: {filtering['eligible_candidate_count']}/"
        f"{filtering['original_candidate_count']} candidates retained"
    )

    if not candidates:
        output["result"] = {
            "best_match": None,
            "match_status": "no_exact_name_candidates",
            "final_reasoning": (
                "No LinkedIn candidate passed the exact Upwork-name filter. "
                "Gemini was not called."
            )
        }

        print("[SKIP] No exact-name candidates. Gemini not called.")
        return output

    # Special branch: company search with exactly one eligible profile.
    if is_company_search(case) and len(candidates) == 1:
        candidate = candidates[0]
        profile = candidate.get("profile_details") or {}

        output["saved_profile"] = candidate

        output["result"] = {
            "best_match": {
                "candidate_id": candidate.get("candidate_id", ""),
                "name": profile.get("name", ""),
                "linkedin_profile_url": candidate.get("linkedin_profile_url", ""),
                "confidence": None
            },
            "alternative_candidates": [],
            "candidate_analysis": [],
            "identity_verification": {
                "established": False,
                "evidence": [],
                "explanation": (
                    "This profile was saved directly because the company "
                    "search produced exactly one candidate passing the "
                    "exact-name filter. Gemini was not called."
                )
            },
            "final_reasoning": (
                "Single exact-name profile from a company search; saved "
                "without Gemini ranking."
            ),
            "match_status": "single_company_search_profile_saved"
        }

        print("[SAVE] Company search has exactly one eligible profile.")
        print("[SKIP] Gemini not called.")
        print("Saved profile:", profile.get("name", ""))

        return output

    # Company search with 2+ exact-name profiles, and all other searches:
    # pass the retained candidates through the existing Gemini analysis.
    print(f"[GEMINI] Sending {len(candidates)} eligible candidate(s)...")

    output["result"] = ask_gemini(filtered_case)

    print("[DONE] Gemini matching completed.")

    return output


# ---------------------------------------------------------------------
# INPUT FILE LOADING AND CASE BUILDING
# ---------------------------------------------------------------------

def _load_json_file(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _as_records(data, label):
    """Normalize a JSON object/list into a list of records."""
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("jobs", "results", "data", "profiles", "records"):
            if isinstance(data.get(key), list):
                return data[key]

        return [data]

    raise ValueError(f"{label} must contain a JSON object or list.")


def _normalise_job_id(value):
    return str(value).strip() if value is not None else ""


def _get_client_location(upwork_record, linkedin_records):
    location = upwork_record.get("client_location")

    if location:
        return location

    client_info = upwork_record.get("client_info") or {}

    if isinstance(client_info, dict):
        location = (
            client_info.get("location")
            or client_info.get("client_location")
        )

        if location:
            return location

    for record in linkedin_records:
        if record.get("city"):
            return record["city"]

    return ""


def _get_client_name(upwork_record, linkedin_records):
    for key in (
        "client_name_final",
        "client_name_most_likely",
        "most_likely_name"
    ):
        value = upwork_record.get(key)

        if isinstance(value, str) and value.strip():
            return value.strip()

    client_info = upwork_record.get("client_info") or {}

    if isinstance(client_info, dict):
        for key in ("client_name", "name"):
            value = client_info.get(key)

            if isinstance(value, str) and value.strip():
                return value.strip()

    for record in linkedin_records:
        value = record.get("client_name")

        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def build_cases_from_pipeline_files(
    upwork_path=UPWORK_FILE,
    linkedin_path=LINKEDIN_FILE
):
    """Join Upwork records to LinkedIn profiles using job_id."""

    if not upwork_path.exists():
        raise FileNotFoundError(
            f"Upwork input file not found: {upwork_path}"
        )

    if not linkedin_path.exists():
        raise FileNotFoundError(
            f"LinkedIn profile output file not found: {linkedin_path}"
        )

    upwork_records = _as_records(
        _load_json_file(upwork_path),
        "Upwork input"
    )

    linkedin_records = _as_records(
        _load_json_file(linkedin_path),
        "LinkedIn profile output"
    )

    linkedin_by_job = defaultdict(list)

    for record in linkedin_records:
        if not isinstance(record, dict):
            continue

        job_id = _normalise_job_id(record.get("job_id"))

        if job_id:
            linkedin_by_job[job_id].append(record)

    cases = []

    for index, upwork in enumerate(upwork_records, start=1):
        if not isinstance(upwork, dict):
            continue

        job_id = _normalise_job_id(
            upwork.get("job_id") or upwork.get("id")
        )

        linked_records = (
            linkedin_by_job.get(job_id, [])
            if job_id
            else []
        )

        candidates = []

        for candidate_index, record in enumerate(
            linked_records,
            start=1
        ):
            # Failed profile scrapes should not be sent to Gemini.
            if record.get("error"):
                continue

            profile_details = record.get("profile_details") or {}

            profile_url = (
                record.get("linkedin_profile_url")
                or profile_details.get("profile_url")
                or ""
            )

            # if not profile_url or not profile_details:
            #     continue

            # candidates.append({
            #     "candidate_id": (
            #         f"{job_id or index}_C{candidate_index:03d}"
            #     ),
            #     "linkedin_profile_url": profile_url,
            #     "profile_details": profile_details
            # })

            skipped_company_profile = (
                record.get("scrape_status")
                == "skipped_single_profile_company_search"
            )

            if not profile_url:
                continue

            if not profile_details and not skipped_company_profile:
                continue

            candidate = {
                "candidate_id": (
                    f"{job_id or index}_C{candidate_index:03d}"
                ),
                "linkedin_profile_url": profile_url,
                "profile_details": profile_details
            }

            if skipped_company_profile:
                candidate["scrape_status"] = record.get("scrape_status")
                candidate["note"] = record.get("note")
                candidate["company_name"] = record.get("company_name")

            candidates.append(candidate)

        client_name = _get_client_name(
            upwork,
            linked_records
        )

        client_location = _get_client_location(
            upwork,
            linked_records
        )

        case = {
            "id": (
                job_id
                or upwork.get("url")
                or f"upwork_case_{index}"
            ),

            "job_id": job_id,

            "upwork_client": {
                "client_name": client_name,

                "client_name_final": upwork.get(
                    "client_name_final"
                ),

                "client_name_most_likely": upwork.get(
                    "client_name_most_likely"
                ),

                "client_name_candidates": upwork.get(
                    "client_name_candidates",
                    []
                ),

                "client_location": client_location,

                "client_info": upwork.get(
                    "client_info",
                    {}
                ),

                "client_name_confidence": upwork.get(
                    "client_name_confidence",
                    upwork.get("confidence")
                )
            },

            "original_job": {
                "title": upwork.get("title", ""),
                "description": upwork.get("description", ""),
                "url": upwork.get("url", "")
            },

            "work_history": upwork.get(
                "work_history",
                []
            ),

            "company": upwork.get(
                "company",
                upwork.get("company_info", {})
            ),

            "industry": upwork.get(
                "industry_final",
                upwork.get("industry", {})
            ),

            "linkedin_candidates": candidates,

            # Preserve the complete source record as additional context.
            "upwork_source_record": upwork
        }

        # Carry through search metadata when present so company-search
        # handling can continue to work.
        for key in (
            "search_type",
            "linkedin_search_type",
            "linkedin_search",
            "linkedin_search_metadata"
        ):
            if key in upwork:
                case[key] = upwork[key]

        cases.append(case)

        print(
            f"[INPUT] job_id={job_id or 'missing'} | "
            f"client={client_name or 'unknown'} | "
            f"LinkedIn profiles={len(candidates)}"
        )

    return cases


def load_cases():
    """Use manual cases if enabled; otherwise use pipeline output files."""

    if USE_MANUAL_INPUT:
        if not MANUAL_INPUT_FILE.exists():
            raise FileNotFoundError(
                f"Manual input file not found: {MANUAL_INPUT_FILE}"
            )

        print(
            f"[INPUT] Using manual matching file: "
            f"{MANUAL_INPUT_FILE.name}"
        )

        return _as_records(
            _load_json_file(MANUAL_INPUT_FILE),
            "matching_cases.json"
        )

    print(
        "[INPUT] Building cases from Upwork and LinkedIn "
        "scraper outputs."
    )

    return build_cases_from_pipeline_files()


# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------

def main():
    load_dotenv(BASE_DIR / ".env")

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is missing. Set it in your .env file."
        )

    global client
    client = genai.Client(api_key=api_key)

    cases = load_cases()

    # Resume: keep earlier successful matches, only (re)process the rest.
    outputs = []
    already_done = set()
    if RESULT_FILE.exists():
        try:
            for previous in json.loads(RESULT_FILE.read_text(encoding="utf-8")):
                best = ((previous.get("result") or {}).get("best_match") or {})
                if not previous.get("error") and best.get("linkedin_profile_url"):
                    outputs.append(previous)
                    already_done.add(str(previous.get("id")))
        except Exception as exc:
            print(f"[WARN] Could not read earlier results ({exc}); starting fresh.")
    cases = [case for case in cases if str(case.get("id")) not in already_done]
    print(f"[RESUME] {len(already_done)} case(s) already matched; {len(cases)} to process.")

    for index, case in enumerate(cases, start=1):
        print(
            f"\nProcessing case {index}/{len(cases)}"
        )

        try:
            outputs.append(
                process_case(case)
            )

        except Exception as exc:
            print(
                f"[ERROR] Case {case.get('id', 'unknown')} failed: {exc}"
            )

            outputs.append({
                "id": case.get("id", "unknown"),

                "input_client": (
                    case.get("upwork_client") or {}
                ).get("client_name", ""),

                "error": str(exc)
            })

        if index < len(cases):
            time.sleep(DELAY)

    RESULT_FILE.write_text(
        json.dumps(
            outputs,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("\n[DONE]")
    print("Saved results to:", RESULT_FILE)


if __name__ == "__main__":
    main()
