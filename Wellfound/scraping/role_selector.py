import random

def select_role(page, role_name):
    page.keyboard.press("Escape")
    page.mouse.click(10, 10)
    page.wait_for_timeout(500)

    print("Role button count:",
          page.locator('[data-test="SearchBar-RoleSelect-FocusButton"]').count())

    button = page.locator(
        '[data-test="SearchBar-RoleSelect-FocusButton"]'
    )

    button.click()
    page.wait_for_timeout(random.uniform(300, 600))

    # Remove the currently selected role
    page.keyboard.press("Backspace")
    page.wait_for_timeout(random.uniform(200, 400))

    # Type the new role
    page.keyboard.type(
        role_name,
        delay=random.randint(30, 70),
    )

    page.wait_for_timeout(random.uniform(400, 800))

    with page.expect_response(
        lambda r: (
            "/graphql" in r.url
            and r.request.post_data
            and '"operationName":"JobSearchResultsX"' in r.request.post_data
        ),
        timeout=30000,
    ) as response_info:

        page.keyboard.press("Enter")

    page.wait_for_timeout(random.uniform(800, 1500))

    return response_info.value.json()