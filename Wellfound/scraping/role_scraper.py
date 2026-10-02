import random

from storage import append_job
from time import time



def get_recent_job_ids(search_results, days=3):
    """
    Returns the IDs of jobs posted within the last `days` days.
    """

    cutoff = time() - (days * 24 * 60 * 60)

    recent = set()

    edges = (
        search_results["data"]["talent"]["jobSearchResults"]["startups"]["edges"]
    )

    print(f"Found {len(edges)} startups in search response")

    for edge in edges:


        startup = edge["node"]

        # for job in startup["highlightedJobListings"]:
        for job in startup.get("highlightedJobListings", []):

            if job["liveStartAt"] >= cutoff:
                recent.add(job["id"])

    return recent

####


def get_job_cards(page):
    """
    Returns locator objects for all visible job cards.
    """

    cards = page.locator("a.styles_jobLink__US40J")

    return [cards.nth(i) for i in range(cards.count())]


def scroll_for_more_jobs(page, previous_count):
    """
    Scrolls to load the next page.

    Returns:
        (False, None) -> no more jobs
        (True, response_json) -> another page loaded
    """

    cards = get_job_cards(page)

    if not cards:
        return False, None

    last_card = cards[-1]

    try:

        with page.expect_response(
            lambda r: (
                "/graphql" in r.url
                and r.request.post_data
                and '"operationName":"JobSearchResultsX"' in r.request.post_data
            ),
            timeout=15000,
        ) as response_info:

            last_card.scroll_into_view_if_needed()

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
    return href.split("/jobs/")[1].split("-")[0]


def capture_job(page, card):
    """
    Opens a job modal, captures the GraphQL response,
    closes the modal, and returns the JobListing.
    """

    with page.expect_response(
        lambda r: (
            "/graphql" in r.url
            and r.request.post_data
            and '"operationName":"JobListingModalQuery"' in r.request.post_data
        ),
        timeout=30000,
    ) as response_info:

        card.click()

    response = response_info.value

    if response.status != 200:
        raise Exception(f"GraphQL returned {response.status}")

    data = response.json()

    job = data["data"]["jobListing"]

    job["url"] = (
        f"https://wellfound.com/jobs/"
        f"{job['id']}-{job['slug']}"
    )

    page.keyboard.press("Escape")
    page.keyboard.press("Escape")

    overlay = page.locator(".ReactModal__Overlay")

    if overlay.count() > 0:
        overlay.first.wait_for(state="hidden", timeout=5000)

    page.wait_for_timeout(random.uniform(500, 1500))

    return job

def scrape_role(
    page,
    role,
    seen_job_ids,
    search_results,
    days
):
    """
    Scrapes one role.
    Only opens jobs posted within the last 3 days.
    """

    print(f"\nScraping role: {role['title']}")

    processed = 0


    while True:

        recent_job_ids = get_recent_job_ids(
            search_results,
            days,
        )
        if not recent_job_ids:
            print(f"No jobs newer than {days} days. Moving to next role.")
            break

        cards = get_job_cards(page)

        print(f"Loaded {len(cards)} jobs")

        while processed < len(cards):

            card = cards[processed]

            href = card.get_attribute("href")
            job_id = job_id_from_href(href)

            print(f"[{processed + 1}/{len(cards)}] {job_id}")

            if job_id not in recent_job_ids:
                print(f"Older than {days} days")

                processed += 1
                continue

            if job_id in seen_job_ids:
                print("Already scraped")

                processed += 1
                continue

            try:

                job = capture_job(page, card)

                # append_job(job)
                append_job(
                    job,
                    role["title"],
                )

                seen_job_ids.add(job["id"])

                print(f"Saved {job['id']}")

            except Exception as e:

                print(f"Failed: {e}")

            processed += 1

            page.wait_for_timeout(
                random.uniform(1200, 2500)
            )

            if processed % 5 == 0:

                page.mouse.wheel(
                    0,
                    random.randint(300, 700),
                )

                page.wait_for_timeout(
                    random.uniform(800, 1500)
                )

            if processed % 10 == 0:

                pause = random.uniform(15, 30)

                print(f"Sleeping {pause:.1f}s")

                page.wait_for_timeout(
                    pause * 1000
                )

        print("Reached end of loaded jobs.")

        loaded, search_results = scroll_for_more_jobs(
            page,
            len(cards),
        )

        if not loaded:

            print("No more jobs for this role.")

            break

        recent_job_ids = get_recent_job_ids(
            search_results,
            days=3,
        )