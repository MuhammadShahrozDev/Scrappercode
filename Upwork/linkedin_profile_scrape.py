
import json
import os
import random
import time
import re
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


# ---------- CONFIGURATION ----------

# TEST_PROFILE_URL = "https://www.linkedin.com/in/manishhdmittal/"

# TEST_PROFILE_URL = "https://www.linkedin.com/in/manish-rai21/"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

INPUT_FILE = DATA_DIR / "linkedin_client_profiles.json"
OUTPUT_FILE = DATA_DIR / "linkedin_client_profile_details.json"

HEADLESS = os.getenv("UPWORK_LINKEDIN_HEADLESS", "1" if os.getenv("CI") else "0").strip().lower() in {"1", "true", "yes"}

# Set to 1 for an initial test; set to None to process every profile.
MAX_PROFILES = int(os.getenv("UPWORK_MAX_PROFILES", "0")) or None

MIN_PROFILE_DELAY = 4
MAX_PROFILE_DELAY = 7

PAGE_LOAD_TIMEOUT = 30

# ----------------------------------


load_dotenv()


class LinkedInProfileScraper:

    def __init__(self):
        self.driver = self._init_driver()

    # ----------------------------------
    # DRIVER / AUTHENTICATION
    # ----------------------------------

    def _init_driver(self):

        options = webdriver.ChromeOptions()

        if HEADLESS:
            options.add_argument("--headless=new")

        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")

        options.add_argument(
            "--disable-blink-features=AutomationControlled"
        )

        options.add_experimental_option(
            "excludeSwitches",
            ["enable-automation"]
        )

        options.add_experimental_option(
            "useAutomationExtension",
            False
        )

        print("[*] Launching Chrome...")

        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)

        print("[*] Injecting LinkedIn session cookie...")

        driver.get("https://www.linkedin.com")

        cookie_value = os.getenv("LINKEDIN_LI_AT")

        if not cookie_value:
            driver.quit()
            raise ValueError(
                "LINKEDIN_LI_AT was not found in your .env file."
            )

        driver.add_cookie({
            "name": "li_at",
            "value": cookie_value,
            "domain": ".linkedin.com",
            "path": "/"
        })

        driver.refresh()

        time.sleep(3)

        # A logged-out browser is redirected away from /feed/.
        driver.get("https://www.linkedin.com/feed/")

        time.sleep(3)

        current_url = driver.current_url.lower()

        if any(
            marker in current_url
            for marker in ("/login", "authwall", "checkpoint", "/uas/", "signup")
        ):
            driver.quit()
            raise RuntimeError(
                "LinkedIn session is not valid (li_at expired or blocked): "
                f"{current_url}"
            )

        return driver

    # ----------------------------------
    # GENERAL HELPERS
    # ----------------------------------

    def _soup(self):
        return BeautifulSoup(
            self.driver.page_source,
            "html.parser"
        )

    @staticmethod
    def _clean_text(value):
        if not value:
            return ""

        return " ".join(value.split()).strip()

    @staticmethod
    def _save_results(results):

        temp_file = str(OUTPUT_FILE) + ".tmp"

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(
                results,
                f,
                indent=2,
                ensure_ascii=False
            )

        os.replace(temp_file, OUTPUT_FILE)

        print(f"    [saved] {len(results)} profiles")

    @staticmethod
    def _load_existing_results():

        if not OUTPUT_FILE.exists():
            return []

        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            return data if isinstance(data, list) else []

        except Exception as exc:
            print(f"[!] Could not load previous output: {exc}")
            return []

    # ----------------------------------
    # PAGE LOADING
    # ----------------------------------

    def _load_profile(self, profile_url):

        print(f"\n[PROFILE] Opening {profile_url}")

        self.driver.get(profile_url)

        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "main")
            )
        )

        time.sleep(3)

        if "linkedin.com/login" in self.driver.current_url:
            raise RuntimeError(
                "LinkedIn redirected to login. Check your session cookie."
            )

        # Scroll down to trigger lazy-loaded profile sections.
        previous_height = 0

        print("    [scroll] Loading full profile...")

        workspace = self.driver.find_element(By.ID, "workspace")

        previous_height = 0
        stable_count = 0

        while stable_count < 3:

            self.driver.execute_script("""
                arguments[0].scrollTop += arguments[0].clientHeight * 0.8;
            """, workspace)

            time.sleep(2)

            metrics = self.driver.execute_script("""
                return {
                    scrollTop: arguments[0].scrollTop,
                    scrollHeight: arguments[0].scrollHeight,
                    clientHeight: arguments[0].clientHeight
                };
            """, workspace)

            print(
                f"    [scroll] Position: {metrics['scrollTop']:.0f} / "
                f"{metrics['scrollHeight']}"
            )

            current_height = metrics["scrollHeight"]

            if (
                metrics["scrollTop"] + metrics["clientHeight"]
                >= current_height - 5
                and current_height == previous_height
            ):
                stable_count += 1
            else:
                stable_count = 0

            previous_height = current_height

        self.driver.execute_script(
            "arguments[0].scrollTop = 0;",
            workspace
        )

        time.sleep(2)

        print("    [scroll] Finished loading profile")

    # ----------------------------------
    # EXPAND COLLAPSED TEXT
    # ----------------------------------

    def _expand_about(self):

        """
        Find the About heading, locate its expandable text box,
        and click its More button if present.
        """

        try:

            clicked = self.driver.execute_script("""
                const headings = [...document.querySelectorAll("h2")];

                const heading = headings.find(
                    h => h.innerText.trim() === "About"
                );

                if (!heading) return false;

                let current = heading;

                while (current && current !== document.body) {

                    const box = current.querySelector(
                        '[data-testid="expandable-text-box"]'
                    );

                    if (box) {

                        const button = box.querySelector(
                            '[data-testid="expandable-text-button"]'
                        );

                        if (button) {
                            button.click();
                            return true;
                        }

                        return false;
                    }

                    current = current.parentElement;
                }

                return false;
            """)

            if clicked:
                time.sleep(1)
                print("    [about] Expanded")

        except Exception as exc:
            print(f"    [about] Could not expand: {exc}")

    def _expand_experience_descriptions(self):

        """
        Expand descriptions inside the Experience section only.
        """

        try:

            clicked = self.driver.execute_script("""
                const section = document.querySelector(
                    '[data-testid^="profile_ExperienceTopLevelSection"]'
                );

                if (!section) return 0;

                const buttons = section.querySelectorAll(
                    '[data-testid="expandable-text-button"]'
                );

                buttons.forEach(button => button.click());

                return buttons.length;
            """)

            if clicked:
                time.sleep(1)

            print(
                f"    [experience] Expanded {clicked} description(s)"
            )

        except Exception as exc:
            print(f"    [experience] Could not expand: {exc}")

    # ----------------------------------
    # BASIC PROFILE DETAILS
    # ----------------------------------

    def _extract_basic_details(self, soup, profile_url):

        details = {
            "name": "",
            "headline": "",
            "current_company": "",
            "top_education_institution": "",
            "location": "",
            "profile_url": profile_url,
        }

        # LinkedIn profile name is rendered directly inside an h2.
        name_heading = soup.select_one("main h2")

        if name_heading:
            details["name"] = self._clean_text(
                name_heading.get_text(" ", strip=True)
            )
        else:
            print("    [basic] Profile name heading not found")

        # Find the surrounding profile header containing the
        # headline, affiliation and location paragraphs.
        header = None

        for parent in name_heading.parents:

            paragraphs = parent.find_all("p")

            paragraph_texts = [
                self._clean_text(p.get_text(" ", strip=True))
                for p in paragraphs
            ]

            useful = [
                text for text in paragraph_texts
                if text
                and text not in ["·", "Contact info"]
                and "connection" not in text.lower()
            ]

            if len(useful) >= 3:
                header = parent
                break

        if not header:
            return details

        paragraphs = header.find_all("p")

        values = []

        for paragraph in paragraphs:

            value = self._clean_text(
                paragraph.get_text(" ", strip=True)
            )

            if not value:
                continue

            if value == "·" or value == "Contact info":
                continue

            if "connection" in value.lower():
                continue

            if value.startswith("·") and len(value) < 15:
                continue

            values.append(value)

        if len(values) >= 1:
            details["headline"] = values[0]

        if len(values) >= 2:

            affiliation_parts = [
                part.strip()
                for part in values[1].split("·")
            ]

            if affiliation_parts:
                details["current_company"] = affiliation_parts[0]

            if len(affiliation_parts) > 1:
                details["top_education_institution"] = (
                    affiliation_parts[1]
                )

        if len(values) >= 3:
            details["location"] = values[2]

        return details

    # ----------------------------------
    # ABOUT
    # ----------------------------------

    def _extract_about(self, soup):

        about_box = soup.select_one(
            '[data-testid="expandable-text-box"]'
        )

        if not about_box:
            return ""

        return self._clean_text(
            about_box.get_text(" ", strip=True)
        ).removesuffix("more")

    # ----------------------------------
    # EXPERIENCE
    # ----------------------------------


    def _extract_experience(self, soup):

        experiences = []

        section = soup.select_one(
            '[data-testid^="profile_ExperienceTopLevelSection"]'
        )

        if not section:
            print("    [experience] Section not found")
            return experiences

        entries = section.select(
            '[componentkey^="entity-collection-item"]'
        )

        def clean_paragraphs(container):

            return [
                self._clean_text(p.get_text(" ", strip=True))
                for p in container.find_all("p")
                if self._clean_text(p.get_text(" ", strip=True))
                and self._clean_text(p.get_text(" ", strip=True)).lower() != "more"
            ]

        def extract_description(container):

            description_box = container.select_one(
                '[data-testid="expandable-text-box"]'
            )

            if not description_box:
                return ""

            return self._clean_text(
                description_box.get_text(" ", strip=True)
            ).removesuffix("more")

        def extract_skills(container):

            skills = []

            for link in container.select('a[href*="/skill-associations-details/"], a[href*="/skill-insights/"]'):

                skill_text = self._clean_text(
                    link.get_text(" ", strip=True)
                )

                if skill_text:
                    skills.append(skill_text)

            return skills

        def make_experience(paragraphs, container, company=""):

            if not paragraphs:
                return None

            experience = {
                "title": paragraphs[0],
                "company": company,
                "employment_type": "",
                "dates": "",
                "location": "",
                "description": extract_description(container),
                "skills": extract_skills(container),
            }

            if company:
                # Grouped company: employment type is optional.
                if len(paragraphs) > 1:

                    second = paragraphs[1]

                    # LinkedIn sometimes omits employment type.
                    # In that case, the second paragraph contains dates.
                    is_date = bool(
                        re.search(
                            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b.*\b\d{4}\b|Present",
                            second,
                            re.IGNORECASE
                        )
                    )

                    if is_date:
                        experience["dates"] = second

                        if len(paragraphs) > 2:
                            experience["location"] = paragraphs[2]

                    else:
                        experience["employment_type"] = second

                        if len(paragraphs) > 2:
                            experience["dates"] = paragraphs[2]

                        if len(paragraphs) > 3:
                            experience["location"] = paragraphs[3]


            else:
                # Ordinary experience entry.
                if len(paragraphs) > 1:

                    company_parts = [
                        part.strip()
                        for part in paragraphs[1].split("·")
                    ]

                    experience["company"] = company_parts[0]

                    if len(company_parts) > 1:
                        experience["employment_type"] = company_parts[1]

                if len(paragraphs) > 2:
                    experience["dates"] = paragraphs[2]

                if len(paragraphs) > 3:
                    experience["location"] = paragraphs[3]

            return experience

        for entry in entries:

            # Check whether this company contains multiple positions.
            grouped_positions = entry.find("ul", recursive=False)

            if grouped_positions:

                # Get the parent company name from its header.
                company = ""

                for link in entry.find_all("a", href=True):

                    header_paragraphs = clean_paragraphs(link)

                    if header_paragraphs:
                        company = header_paragraphs[0]
                        break

                # Extract each individual position separately.
                for position in grouped_positions.find_all(
                    "li", recursive=False
                ):

                    metadata_container = next(
                        (
                            link for link in position.find_all("a", href=True)
                            if link.find("p")
                        ),
                        None
                    )

                    # Some positions have metadata directly inside a div,
                    # rather than inside an anchor.
                    if metadata_container is None:
                        metadata_container = position

                    paragraphs = clean_paragraphs(metadata_container)

                    experience = make_experience(
                        paragraphs,
                        position,
                        company
                    )

                    if experience and experience["title"]:
                        experiences.append(experience)

            else:

                # Ordinary, non-grouped experience entry.
                paragraphs = clean_paragraphs(entry)

                experience = make_experience(
                    paragraphs,
                    entry
                )

                if experience and (
                    experience["title"] or experience["company"]
                ):
                    experiences.append(experience)

        print(f"    [experience] Found {len(experiences)} entries")

        return experiences

    # ----------------------------------
    # EDUCATION
    # ----------------------------------

    def _extract_education(self, soup):

        education = []

        section = soup.select_one(
            '[data-testid^="profile_EducationTopLevelSection"]'
        )

        if not section:
            print("    [education] Section not found")
            return education

        entries = section.select(
            '[componentkey^="entity-collection-item"]'
        )

        for entry in entries:

            paragraphs = [
                self._clean_text(p.get_text(" ", strip=True))
                for p in entry.find_all("p")
            ]

            paragraphs = [p for p in paragraphs if p]

            if not paragraphs:
                continue

            school_link = entry.select_one(
                'a[href*="/school/"]'
            )

            item = {
                "institution": paragraphs[0],
                "degree": paragraphs[1] if len(paragraphs) > 1 else "",
                "institution_url": (
                    school_link.get("href", "")
                    if school_link else ""
                ),
            }

            education.append(item)

        print(f"    [education] Found {len(education)} entries")

        return education

    # ----------------------------------
    # SKILLS
    # ----------------------------------

    def _extract_skills(self, soup):

        skills = []

        section = soup.select_one(
            '[data-testid^="profile_Skills"]'
        )

        if not section:
            print("    [skills] Section not found")
            return skills

        entries = section.select(
            '[id^="com.linkedin.sdui.profile.skill"]'
        )

        for entry in entries:

            name_element = entry.select_one("p span")

            if not name_element:
                continue

            skill_name = self._clean_text(
                name_element.get_text(" ", strip=True)
            )

            if not skill_name:
                continue

            associated_experiences = []

            for item in entry.select('[role="listitem"]'):

                text = self._clean_text(
                    item.get_text(" ", strip=True)
                )

                if text:
                    associated_experiences.append(text)

            skills.append({
                "name": skill_name,
                "associated_experiences": associated_experiences,
            })

        show_all_link = section.select_one(
            'a[aria-label="Show all"]'
        )

        print(f"    [skills] Found {len(skills)} visible skills")

        if show_all_link:
            print(
                "    [skills] Full skills page: "
                f"{show_all_link.get('href', '')}"
            )

        return skills

    # ----------------------------------
    # SCRAPE ONE PROFILE
    # ----------------------------------

    def scrape_profile(self, profile_url):

        self._load_profile(profile_url)

        self._expand_about()
        self._expand_experience_descriptions()

        soup = self._soup()

        profile = self._extract_basic_details(
            soup,
            profile_url
        )

        profile["about"] = self._extract_about(soup)

        profile["experience"] = self._extract_experience(soup)

        profile["education"] = self._extract_education(soup)

        profile["skills"] = self._extract_skills(soup)

        return profile

    # ----------------------------------
    # MAIN WORKFLOW
    # ----------------------------------

    def run(self):

        if not INPUT_FILE.exists():
            raise FileNotFoundError(
                f"Input file not found: {INPUT_FILE}"
            )

        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            clients = json.load(f)

        if not isinstance(clients, list):
            raise ValueError(
                "Input JSON must contain a list of client records."
            )

        results = self._load_existing_results()

        completed_urls = {
            item.get("linkedin_profile_url")
            for item in results
            if item.get("linkedin_profile_url")
            and not item.get("error")
        }

        tasks = []

        for client in clients:

            profile_urls = client.get("linkedin_profiles", [])

            # Skip scraping company searches that returned zero or one profile.
            if (
                client.get("search_type") == "company"
                and len(profile_urls) <= 1
            ):
                if len(profile_urls) == 1:
                    profile_url = profile_urls[0]

                    already_recorded = any(
                        item.get("job_id") == client.get("job_id")
                        and item.get("linkedin_profile_url") == profile_url
                        for item in results
                    )

                    if not already_recorded:
                        results.append({
                            "job_id": client.get("job_id"),
                            "client_name": client.get("client_name"),
                            "company_name": client.get("company_name"),
                            "linkedin_profile_url": profile_url,
                            "search_type": "company",
                            "profile_details": None,
                            "scrape_status": "skipped_single_profile_company_search",
                            "note": "Profile scraping was skipped because the company search returned exactly one LinkedIn profile."
                        })

                        self._save_results(results)

                print(
                    f"[SKIP] Company search returned "
                    f"{len(profile_urls)} profile(s): "
                    f"{client.get('client_name')}"
                )
                continue

            for profile_url in profile_urls:

                if not profile_url:
                    continue

                if profile_url in completed_urls:
                    print(f"[SKIP] Already scraped: {profile_url}")
                    continue

                tasks.append({
                    "job_id": client.get("job_id"),
                    "client_name": client.get("client_name"),
                    "company_name": client.get("company_name"),
                    "city": client.get("city"),
                    "country": client.get("country"),
                    "search_type": client.get("search_type"),
                    "linkedin_profile_url": profile_url,
                })

        if MAX_PROFILES is not None:
            tasks = tasks[:MAX_PROFILES]

        print(f"\n[*] Profiles to scrape: {len(tasks)}")

        try:

            for index, task in enumerate(tasks, start=1):

                profile_url = task["linkedin_profile_url"]

                print(f"\n[*] Profile {index}/{len(tasks)}")

                result = {
                    **task,
                    "profile_details": None,
                    "error": None,
                }

                try:

                    result["profile_details"] = self.scrape_profile(
                        profile_url
                    )

                    print(
                        f"    [done] "
                        f"{result['profile_details']['name'] or 'Name not found'}"
                    )

                except Exception as exc:

                    result["error"] = str(exc)
                    print(f"    [ERROR] {exc}")

                results.append(result)

                self._save_results(results)

                if index < len(tasks):
                    delay = random.uniform(
                        MIN_PROFILE_DELAY,
                        MAX_PROFILE_DELAY
                    )

                    print(f"    [wait] {delay:.1f} seconds")
                    time.sleep(delay)

        except KeyboardInterrupt:
            print("\n[!] Interrupted. Completed results are saved.")

        finally:
            self.driver.quit()

        print("\n[DONE]")
        print(f"Output: {OUTPUT_FILE}")
        print(f"Total saved profiles: {len(results)}")

    # ---------------TEST VERSION------------------

    # def run(self):    # TEST RUN

    #     print("\n[*] Running single-profile test")
    #     print(f"[*] Test URL: {TEST_PROFILE_URL}")

    #     results = []

    #     try:

    #         result = {
    #             "linkedin_profile_url": TEST_PROFILE_URL,
    #             "profile_details": None,
    #             "error": None,
    #         }

    #         try:

    #             result["profile_details"] = self.scrape_profile(
    #                 TEST_PROFILE_URL
    #             )

    #             print(
    #                 f"\n[done] Scraped: "
    #                 f"{result['profile_details']['name'] or 'Name not found'}"
    #             )

    #         except Exception as exc:

    #             result["error"] = str(exc)
    #             print(f"\n[ERROR] {exc}")

    #         results.append(result)

    #         self._save_results(results)

    #     finally:
    #         self.driver.quit()

    #     print("\n[DONE]")
    #     print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":

    scraper = LinkedInProfileScraper()
    scraper.run()
