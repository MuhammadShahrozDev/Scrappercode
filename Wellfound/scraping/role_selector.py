import random


def _is_job_search_payload(payload):
    try:
        return bool(
            payload.get("data", {})
            .get("talent", {})
            .get("jobSearchResults")
        )
    except Exception:
        return False


def select_role(page, role_name):
    page.keyboard.press("Escape")
    page.mouse.click(10, 10)
    page.wait_for_timeout(400)

    button = page.locator(
        '[data-test="SearchBar-RoleSelect-FocusButton"]'
    )

    count = button.count()
    print("Role button count:", count)

    if count < 1:
        raise RuntimeError(
            "Wellfound role selector button was not found."
        )

    responses = []

    def on_response(response):
        if "/graphql" in response.url:
            responses.append(response)

    page.on("response", on_response)

    try:
        button.click()
        page.wait_for_timeout(
            random.uniform(300, 600)
        )

        # Clear the current role/search text.
        page.keyboard.press("Meta+A")
        page.keyboard.press("Backspace")
        page.wait_for_timeout(
            random.uniform(200, 400)
        )

        page.keyboard.type(
            role_name,
            delay=random.randint(25, 60),
        )

        page.wait_for_timeout(
            random.uniform(500, 900)
        )

        # Prefer an explicit matching option if Wellfound renders one.
        option = page.get_by_text(
            role_name,
            exact=True
        )

        if option.count() > 0:
            try:
                option.last.click()
            except Exception:
                page.keyboard.press("Enter")
        else:
            page.keyboard.press("Enter")

        # Give the UI/network time to emit the search request.
        for _ in range(20):
            page.wait_for_timeout(500)

            for response in reversed(responses):
                try:
                    if response.status != 200:
                        continue

                    payload = response.json()

                    if _is_job_search_payload(payload):
                        print(
                            "[*] Captured Wellfound job search response."
                        )
                        return payload

                except Exception:
                    continue

        raise RuntimeError(
            f"No Wellfound job-search GraphQL response "
            f"captured for role '{role_name}'."
        )

    finally:
        try:
            page.remove_listener(
                "response",
                on_response
            )
        except Exception:
            pass
