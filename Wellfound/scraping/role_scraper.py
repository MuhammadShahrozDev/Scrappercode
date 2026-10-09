import random
from time import time

from storage import append_job


def get_recent_job_ids(search_results, days=3):
    cutoff = time() - (days * 24 * 60 * 60)
    recent = set()

    edges = (
        search_results.get("data", {})
        .get("talent", {})
        .get("jobSearchResults", {})
        .get("startups", {})
        .get("edges", [])
    )

    print(f"Found {len(edges)} startups in search response")

    for edge in edges:
        startup = edge.get("node") or {}

        for job in startup.get("highlightedJobListings", []):
            job_id = job.get("id")
            live_start = job.get("liveStartAt")

            if (
                job_id is not None
                and live_start is not None
                and live_start >= cutoff
            ):
                recent.add(str(job_id))

    return recent


def get_job_cards(page):
    cards = page.locator("a.styles_jobLink__US40J")
    return [cards.nth(i) for i in range(cards.count())]


def scroll_for_more_jobs(page, previous_count):
    cards = get_job_cards(page)

    if not cards:
        return False, None

    last_card = cards[-1]

    try:
        with page.expect_response(
            lambda r: (
                "/graphql" in r.url
                and r.request.post_data
                and '"operationName":"JobSearchResultsX"'
                in r.request.post_data
            ),
            timeout=15000,
        ) as response_info:
            last_card.scroll_into_view_if_needed()
            page.wait_for_timeout(random.uniform(300, 700))
            page.mouse.wheel(
                0,
                random.randint(800, 1500),
            )

        response = response_info.value
        page.wait_for_timeout(random.uniform(1200, 2200))

        current_count = len(get_job_cards(page))

        if current_count <= previous_count:
            return False, None

        return True, response.json()

    except Exception:
        return False, None


def job_id_from_href(href):
    if not href or "/jobs/" not in href:
        return None

    return href.split("/jobs/", 1)[1].split("-", 1)[0]


def capture_job(page, card):
    with page.expect_response(
        lambda r: (
            "/graphql" in r.url
            and r.request.post_data
            and '"operationName":"JobListingModalQuery"'
            in r.request.post_data
        ),
        timeout=30000,
    ) as response_info:
        card.click()

    response = response_info.value

    if response.status != 200:
        raise RuntimeError(
            f"GraphQL returned {response.status}"
        )

    data = response.json()
    job = data.get("data", {}).get("jobListing")

    if not job:
        raise RuntimeError(
            "JobListingModalQuery returned no job"
        )

    job["url"] = (
        f"https://wellfound.com/jobs/"
        f"{job['id']}-{job['slug']}"
    )

    page.keyboard.press("Escape")
    page.keyboard.press("Escape")

    overlay = page.locator(".ReactModal__Overlay")

    if overlay.count() > 0:
        try:
            overlay.first.wait_for(
                state="hidden",
                timeout=5000,
            )
        except Exception:
            pass

    page.wait_for_timeout(random.uniform(500, 1200))

    return job


def scrape_role(
    page,
    role,
    seen_job_ids,
    search_results,
    days,
    max_new_jobs=None,
):
    print(f"\nScraping role: {role['title']}")

    processed = 0
    saved = 0

    while True:
        if (
            max_new_jobs is not None
            and saved >= max_new_jobs
        ):
            return saved

        recent_job_ids = get_recent_job_ids(
            search_results,
            days,
        )

        if not recent_job_ids:
            print(
                f"No jobs newer than {days} days. "
                "Moving to next role."
            )
            break

        cards = get_job_cards(page)

        if not cards and recent_job_ids:
            print(
                "Search response has recent jobs but cards are not rendered yet; "
                "waiting for the UI."
            )

            for _ in range(12):
                page.wait_for_timeout(500)
                cards = get_job_cards(page)

                if cards:
                    break

        print(f"Loaded {len(cards)} jobs")

        if not cards and recent_job_ids:
            raise RuntimeError(
                "Wellfound returned recent jobs in GraphQL "
                "but rendered 0 job cards."
            )

        while processed < len(cards):
            if (
                max_new_jobs is not None
                and saved >= max_new_jobs
            ):
                return saved

            card = cards[processed]
            processed += 1

            href = card.get_attribute("href")
            job_id = job_id_from_href(href)

            if not job_id:
                continue

            print(f"[{processed}/{len(cards)}] {job_id}")

            if job_id not in recent_job_ids:
                print(f"Older than {days} days")
                continue

            if job_id in seen_job_ids:
                print("Already scraped")
                continue

            try:
                job = capture_job(page, card)

                append_job(
                    job,
                    role["title"],
                )

                seen_job_ids.add(
                    str(job["id"])
                )

                saved += 1

                print(
                    f"Saved {job['id']} "
                    f"({saved} new)"
                )

            except Exception as exc:
                print(f"Failed: {exc}")

        print("Reached end of loaded jobs.")

        loaded, search_results = scroll_for_more_jobs(
            page,
            len(cards),
        )

        if not loaded:
            print("No more jobs for this role.")
            break

    return saved
