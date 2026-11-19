
"""
Search Google for LinkedIn person profile URLs using Upwork client details.

Search priority:
1. Person name + company name (if company is available)
2. Person name + city + country (if no company is available)
3. Person name + country (if no company or city is available)
4. Person name + city (if country is unavailable)
"""

import asyncio
import json
import os
import random
import re
from pathlib import Path
from urllib.parse import (
    quote_plus,
    urlparse,
    parse_qs,
    unquote,
    urlunparse,
)

from patchright.async_api import async_playwright


# ---------- CONFIGURATION ----------

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

INPUT_FILE = DATA_DIR / "upwork_agentic_ai_jobs_industry.json"
OUTPUT_FILE = DATA_DIR / "linkedin_client_profiles.json"

HEADLESS = os.getenv("UPWORK_GOOGLE_HEADLESS", "0").strip().lower() in {"1", "true", "yes"}
MAX_RESULTS_PER_CLIENT = 10

# "google"  -> browser search (falls back to DuckDuckGo when Google shows a CAPTCHA)
# "ddgs"    -> DuckDuckGo only (no browser); default on CI, where Google blocks datacenter IPs
SEARCH_ENGINE = (
    os.getenv("UPWORK_SEARCH_ENGINE")
    or ("ddgs" if os.getenv("CI") else "google")
).strip().lower()

MIN_SEARCH_DELAY = 5
MAX_SEARCH_DELAY = 10
PAGE_LOAD_DELAY = 4

# ----------------------------------


def normalize_city(value):
    if not value:
        return None

    return str(value).strip() or None


def extract_clients(jobs):
    """Extract client details and prepare unique Google searches."""

    clients = []
    seen = set()

    for job in jobs:
        name = job.get("client_name_final")
        company = normalize_city(job.get("company_name_final"))

        location = job.get("client_location") or {}

        city = normalize_city(location.get("city"))
        country = normalize_city(location.get("country"))

        industry = job.get("industry_final") or {}
        sector = industry.get("search_label") or industry.get("project_domain")

        if not name or not str(name).strip():
            print(f"[SKIP] No final client name: {job.get('job_id')}")
            continue

        name = str(name).strip()

        # Company search takes priority over location search.
        if company:
            search_type = "company"

            key = (
                "company",
                name.casefold(),
                company.casefold(),
            )

        elif country:
            search_type = "location"

            key = (
                "location",
                name.casefold(),
                (city or "").casefold(),
                country.casefold(),
            )

        elif city:
            search_type = "location"

            key = (
                "location",
                name.casefold(),
                city.casefold(),
            )

        else:
            print(
                f"[SKIP] No company or usable location: "
                f"{job.get('job_id')}"
            )
            continue

        if key in seen:
            print(f"[SKIP] Duplicate client search: {name}")
            continue

        seen.add(key)

        clients.append({
            "job_id": job.get("job_id"),
            "client_name": name,
            "company_name": company,
            "city": city,
            "country": country,
            "sector": sector,
            "search_type": search_type,
        })

    return clients


def extract_linkedin_profile_url(href):
    """Extract a LinkedIn person profile URL from direct or redirected links."""

    if not href:
        return None

    href = unquote(href.strip())

    # Unwrap Google redirect links.
    parsed = urlparse(href)

    if parsed.path == "/url":
        params = parse_qs(parsed.query)
        href = params.get("q", params.get("url", [None]))[0]

    if not href:
        return None

    href = unquote(href)

    # Accept person profiles, not company pages or LinkedIn search pages.
    match = re.search(
        r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[^/?#&\s]+",
        href,
        re.IGNORECASE,
    )

    if not match:
        return None

    profile_url = match.group(0).rstrip("/")

    if "/pub/dir/" in profile_url.lower():
        return None

    # Normalize URL.
    parsed = urlparse(profile_url)

    return urlunparse((
        "https",
        "www.linkedin.com",
        parsed.path.rstrip("/") + "/",
        "",
        "",
        "",
    ))


def ddgs_profiles(client):
    """Find LinkedIn /in/ profile URLs with DuckDuckGo (no browser, works from datacenter IPs)."""
    try:
        from ddgs import DDGS
    except Exception as exc:
        print(f"[DDGS] ddgs is not installed: {exc}")
        return []

    name = client["client_name"]

    if client["search_type"] == "company":
        query = f'site:linkedin.com/in "{name}" {client["company_name"]}'
    else:
        location = ", ".join(
            part for part in [client.get("city"), client.get("country")] if part
        )
        query = f'site:linkedin.com/in "{name}" {location}'.strip()

    print(f"[DDGS] {query}")

    profiles = []

    try:
        results = DDGS().text(query, max_results=MAX_RESULTS_PER_CLIENT) or []
    except Exception as exc:
        print(f"[DDGS] search failed: {exc}")
        return []

    for item in results:
        profile_url = extract_linkedin_profile_url(item.get("href") or item.get("url"))
        if profile_url and profile_url not in profiles:
            profiles.append(profile_url)

    print(f"[DDGS] {len(profiles)} profile(s)")

    return profiles[:MAX_RESULTS_PER_CLIENT]


async def search_linkedin(page, client):
    if SEARCH_ENGINE == "ddgs" or page is None:
        return await asyncio.to_thread(ddgs_profiles, client)

    name = client["client_name"]

    # Build the query according to the available client information.
    if client["search_type"] == "company":
        company = client["company_name"]

        query = f'"{name}" {company} LinkedIn'

        print(f"\n[SEARCH] {name} | Company: {company}")

    else:
        city = client.get("city")
        country = client.get("country")

        location_parts = [
            part for part in [city, country] if part
        ]

        location = ", ".join(location_parts)

        # query = f'"{name}" {location} LinkedIn'
        query = f'"{name}" {client.get("sector") or ""} {location} LinkedIn'

        print(f"\n[SEARCH] {name} | Location: {location}")

    search_url = (
        "https://www.google.com/search?q=" + quote_plus(query)
    )

    print(f"[QUERY] {query}")

    response = await page.goto(
        search_url,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    if response:
        print(f"[HTTP] Google status: {response.status}")

    print(f"[URL] {page.url}")

    await page.wait_for_timeout(PAGE_LOAD_DELAY * 1000)

    # Detect a possible CAPTCHA or unusual Google response.
    page_title = await page.title()

    print(f"[PAGE TITLE] {page_title}")

    profiles = []

    # Prefer links inside Google's main search results.
    result_links = page.locator("div#search a")
    links = await result_links.all()

    print("\n[DEBUG] Search result link details:")

    print(
        await page.locator("#search a").evaluate_all(
            """els => els.map(a => ({
                text: a.innerText,
                href: a.href,
                raw_href: a.getAttribute('href')
            }))"""
        )
    )

    # Resolve the first Google result for debugging.
    first_result = page.locator(
        "#search a[jsname='UWckNb']"
    ).first

    href = await first_result.get_attribute("href")

    if href:
        if href.startswith("/"):
            href = "https://www.google.com" + href

        print("\n[DEBUG] Resolving first Google result...")

        try:
            response = await page.request.get(
                href,
                max_redirects=10,
                timeout=15000,
            )

            final_url = response.url

            print("[DEBUG] Final URL:", final_url)

            parsed = urlparse(final_url)
            params = parse_qs(parsed.query)

            profile_url = extract_linkedin_profile_url(final_url)

            if not profile_url and "sessionRedirect" in params:
                redirect_url = unquote(
                    params["sessionRedirect"][0]
                )

                profile_url = extract_linkedin_profile_url(
                    redirect_url
                )

            print("[DEBUG] Extracted profile URL:", profile_url)

        except Exception as exc:
            print(
                f"[DEBUG] Could not resolve first result: {exc}"
            )

    else:
        print("[DEBUG] No first Google result link found.")

    print(f"[DEBUG] Links inside search results: {len(links)}")

    # Fallback to all page links if Google changes its markup.
    if not links:
        links = await page.locator("a").all()

    print(f"[DEBUG] Total links on page: {len(links)}")

    # Also inspect the rendered page text for LinkedIn profile URLs.
    page_text = await page.locator("body").inner_text()

    text_urls = re.findall(
        r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[^\s<>\"']+",
        page_text,
        re.IGNORECASE,
    )

    for url in text_urls:
        profile_url = extract_linkedin_profile_url(url)

        if profile_url and profile_url not in profiles:
            profiles.append(profile_url)

    for link in links:
        try:
            href = await link.get_attribute("href")

            if not href:
                continue

            # Make relative Google URLs absolute.
            if href.startswith("/"):
                href = "https://www.google.com" + href

            # First try extracting a profile URL directly.
            profile_url = extract_linkedin_profile_url(href)

            # Google /goto links need to be resolved first.
            if not profile_url and "google.com/goto" in href:
                try:
                    response = await page.request.get(
                        href,
                        max_redirects=10,
                        timeout=15000,
                    )

                    final_url = response.url

                    profile_url = extract_linkedin_profile_url(
                        final_url
                    )

                    # LinkedIn may redirect to an authwall with the
                    # actual profile URL inside sessionRedirect.
                    if not profile_url:
                        parsed = urlparse(final_url)
                        params = parse_qs(parsed.query)

                        redirect_url = params.get(
                            "sessionRedirect",
                            [None],
                        )[0]

                        if redirect_url:
                            profile_url = extract_linkedin_profile_url(
                                unquote(redirect_url)
                            )

                except Exception as exc:
                    print(
                        f"[DEBUG] Could not resolve Google URL: {exc}"
                    )
                    continue

            if profile_url:
                try:
                    link_text = (await link.inner_text()).strip()
                except Exception:
                    link_text = ""

                print(
                    f"[PROFILE CANDIDATE] "
                    f"{link_text[:80]} -> {profile_url}"
                )

                if profile_url not in profiles:
                    profiles.append(profile_url)

                if len(profiles) >= MAX_RESULTS_PER_CLIENT:
                    break

        except Exception as exc:
            print(f"[DEBUG] Could not inspect link: {exc}")

    if not profiles:
        print("[DEBUG] No profile URLs extracted. Sample page links:")

        for link in links[:25]:
            try:
                href = await link.get_attribute("href")

                if href:
                    print(f"    {href[:300]}")

            except Exception:
                pass

        if "captcha" in page.url.lower() or "unusual traffic" in (
            page_title.lower()
        ):
            print("[WARNING] Google may be showing a CAPTCHA.")
            profiles = await asyncio.to_thread(ddgs_profiles, client)

    print(f"[FOUND] {len(profiles)} profile(s)")

    return profiles


async def main():
    # Resolve input relative to this script, not the terminal's current folder.
    input_path = INPUT_FILE
    output_path = OUTPUT_FILE

    if not input_path.exists():
        raise FileNotFoundError(
            f"Input file not found: {input_path}\n"
            "Update INPUT_FILE at the top of the script."
        )

    with input_path.open("r", encoding="utf-8") as file:
        jobs = json.load(file)

    if not isinstance(jobs, list):
        raise ValueError(
            "Input JSON must contain a list of job objects."
        )

    clients = extract_clients(jobs)

    # Resume: keep earlier results, search only clients that are new (or errored).
    results = []
    if output_path.exists():
        try:
            results = [
                row for row in json.loads(output_path.read_text(encoding="utf-8"))
                if not row.get("error")
            ]
        except Exception as exc:
            print(f"[WARN] Could not read earlier results ({exc}); starting fresh.")
            results = []
    done_job_ids = {str(row.get("job_id")) for row in results}
    clients = [c for c in clients if str(c.get("job_id")) not in done_job_ids]

    print(f"\n[INFO] Jobs loaded: {len(jobs)}")
    print(f"[INFO] Unique clients to search: {len(clients)}")

    async with async_playwright() as p:
        browser = None
        page = None
        if SEARCH_ENGINE != "ddgs":
            browser = await p.chromium.launch(headless=HEADLESS)
            context = await browser.new_context()
            page = await context.new_page()

        try:
            for index, client in enumerate(clients):
                if index > 0:
                    delay = random.uniform(
                        MIN_SEARCH_DELAY,
                        MAX_SEARCH_DELAY,
                    )

                    print(
                        f"\n[WAIT] Waiting {delay:.1f} seconds..."
                    )

                    await asyncio.sleep(delay)

                try:
                    profiles = await search_linkedin(page, client)

                    results.append({
                        **client,
                        "linkedin_profiles": profiles,
                    })

                except Exception as exc:
                    print(
                        f"[ERROR] Search failed for "
                        f"{client['client_name']}: {exc}"
                    )

                    results.append({
                        **client,
                        "linkedin_profiles": [],
                        "error": str(exc),
                    })

                # Save progress after each client so partial results survive.
                with output_path.open("w", encoding="utf-8") as file:
                    json.dump(
                        results,
                        file,
                        indent=2,
                        ensure_ascii=False,
                    )

        finally:
            if browser is not None:
                await browser.close()

    print(f"\n[DONE] Saved results to {output_path}")
    print(f"[INFO] Clients searched: {len(results)}")


if __name__ == "__main__":
    asyncio.run(main())
