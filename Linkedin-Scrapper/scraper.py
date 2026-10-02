import json
import os
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, unquote
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from evade import BotEvasion
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

CONFIG_FILE = str(BASE_DIR / "config.json")
INPUT_FILE = str(BASE_DIR / "jobs" / "companies.json")
OUTPUT_FILE = str(BASE_DIR / "output" / "people_links.json")


def _normalize_company_url(url):
  """Canonical company URL: https://www.linkedin.com/company/{slug} (no trailing slash, no query)."""
  if not url:
    return ""
  if not url.startswith("http"):
    url = f"https://www.linkedin.com{url}"
  # Strip query and fragment
  parts = urlparse(url)
  path = parts.path.rstrip("/")
  # Keep only up to /company/{slug}
  m = re.search(r"(/company/[^/]+)", path)
  if m:
    path = m.group(1)
  return f"https://www.linkedin.com{path}"


class LinkedInIntelligenceScraper:

  def __init__(self, config_path=CONFIG_FILE):
    with open(config_path, "r", encoding="utf-8") as f:
      self.config = json.load(f)
    self.target_output = int(os.getenv("TARGET_OUTPUT", 100))
    self.driver = self._init_driver()
    self.today = date.today().strftime("%Y-%m-%d")
    print(f"[*] TARGET_OUTPUT loaded from env: {self.target_output}")

  def _init_driver(self):
    options = webdriver.ChromeOptions()
    # Headless mode configurations
    # options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    # Bypass basic bot detection fingerprints
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    print("[*] Launching Headless Chrome session...")
    driver = webdriver.Chrome(options=options)

    # Inject the session cookie from .env
    print("[*] Injecting LinkedIn session cookie (li_at)...")
    driver.get("https://www.linkedin.com") # Must be on domain before adding cookies
    cookie_value = os.getenv("LINKEDIN_LI_AT")
    if cookie_value:
      driver.add_cookie({
          "name": "li_at",
          "value": cookie_value,
          "domain": ".linkedin.com",
          "path": "/"
      })
      driver.refresh() # Refresh to apply authenticated session state
    else:
      print("[!] WARNING: LINKEDIN_LI_AT not found in environment variables!")

    return driver

  def _wait_for(self, css_selector, timeout=15):
    try:
      WebDriverWait(self.driver, timeout).until(
          EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
      )
      return True
    except Exception:
      return False

  def _soup(self):
    return BeautifulSoup(self.driver.page_source, "html.parser")

  def _parse_number(self, text):
    if not text:
      return 0
    nums = re.findall(r"\d+", text.replace(",", ""))
    return int(nums[0]) if nums else 0

  def _company_slug(self, url):
    m = re.search(r"/company/([^/?#]+)", url)
    return m.group(1) if m else None

  def _parse_cards(self, soup):
    cards = soup.select("div[role='listitem']")
    if cards:
      return cards
    for sel in [
        "li.reusable-search__result-container",
        "div.entity-result",
        "div[data-chameleon-result-urn]",
    ]:
      cards = soup.select(sel)
      if cards:
        return cards
    return []


  def load_input_companies(self):
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        companies = json.load(f)

    valid_companies = []

    for company in companies:
        linkedin_urls = company.get("company_linkedin") or []

        if isinstance(linkedin_urls, str):
            linkedin_urls = [linkedin_urls]

        valid_companies.append({
            "company_id": company.get("company_id"),
            "company_name": company.get("company_name", ""),
            "company_website": company.get("company_website", ""),
            "company_linkedin": linkedin_urls,
            "company_location": company.get("company_location") or [],
            "hiring_contact": company.get("hiring_contact"),
        })

    return valid_companies

    
  def _normalize_website(self, url):
      """Normalize a company website for reliable comparison."""
      if not url:
          return ""

      url = str(url).strip().lower()

      if not url.startswith(("http://", "https://")):
          url = "https://" + url

      parts = urlparse(url)

      hostname = parts.hostname or ""

      if hostname.startswith("www."):
          hostname = hostname[4:]

      return hostname
  

  def _extract_companies_from_page(self):
    """Extract (name, canonical_url) tuples from the current search page."""
    soup = self._soup()
    cards = self._parse_cards(soup)
    companies = []
    seen_slugs = set()
    for card in cards:
      link = card.select_one("a[href*='/company/']")
      if not link:
        continue
      name = link.get_text(strip=True)
      href = link.get("href", "")
      canonical = _normalize_company_url(href)
      slug = self._company_slug(canonical)
      if not slug or slug in seen_slugs:
        continue
      seen_slugs.add(slug)
      companies.append((name, canonical))
    return companies

  def _build_page_url(self, base_url, page_num):
    """Add or replace &page=N on the search URL."""
    parts = urlparse(base_url)
    qs = parse_qs(parts.query)
    qs["page"] = [str(page_num)]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parts._replace(query=new_query))

  def _extract_company_id(self, soup, page_source):
    """Extract the numeric LinkedIn company ID from the page source."""
    patterns = [
        r'"objectUrn":"urn:li:company:(\d+)"',
        r'"companyId":(\d+)',
        r'urn:li:fsd_company:(\d+)',
        r'urn:li:fs_normalized_company:(\d+)',
        r'/voyager/api/.*?/companies/(\d+)',
        r'"entityUrn":"urn:li:fs_miniCompany:(\d+)"',
        r'"numericId":(\d+)',
    ]
    for pattern in patterns:
      match = re.search(pattern, page_source)
      if match:
        return match.group(1)

    link = soup.select_one("a[href*='currentCompany']")
    if link:
      href = link.get("href", "")
      m = re.search(r'currentCompany.*?%22(\d+)%22', href)
      if m:
        return m.group(1)

    return None

  def search_company_on_linkedin(self, company_name):
    """
    Search LinkedIn for a company by name and return candidate
    company URLs.

    The candidates are returned for later website verification.
    """

    candidates = []

    try:
        search_url = (
            "https://www.linkedin.com/search/results/companies/"
            f"?keywords={company_name.replace(' ', '%20')}"
        )

        print(
            f"    [company-search] Searching LinkedIn for: "
            f"{company_name}"
        )

        BotEvasion.random_people_search_delay()

        self.driver.get(search_url)

        self._wait_for(
            "div[role='listitem'], "
            ".reusable-search__result-container, "
            ".entity-result",
            timeout=12,
        )

        BotEvasion.human_delay(2.0, 4.0)

        BotEvasion.simulate_human_scroll(
            self.driver,
            intensity="light"
        )

        soup = self._soup()

        cards = soup.select(
            "div[role='listitem'], "
            ".reusable-search__result-container, "
            ".entity-result"
        )

        seen = set()

        for card in cards:

            link = card.select_one(
                "a[href*='/company/']"
            )

            if not link:
                continue

            href = link.get("href", "").strip()

            if not href:
                continue

            canonical = _normalize_company_url(href)

            if not canonical:
                continue

            if canonical in seen:
                continue

            seen.add(canonical)

            candidates.append(canonical)

            print(
                f"      [candidate] {canonical}"
            )

        print(
            f"    [company-search] Found "
            f"{len(candidates)} candidate(s)"
        )

    except Exception as e:

        print(
            f"    [!] Company LinkedIn search error: {e}"
        )

    return candidates

  def find_verified_company_linkedin(self, company_name, expected_website):
    """
    Search LinkedIn by company name and find a company whose
    LinkedIn About page has a matching website.
    """

    candidates = self.search_company_on_linkedin(company_name)

    if not candidates:
        print(
            f"    [company-search] No LinkedIn company candidates "
            f"found for {company_name}"
        )
        return None

    # for candidate_url in candidates:
    for candidate_url in candidates[:5]:

        print(
            f"    [company-search] Verifying candidate: "
            f"{candidate_url}"
        )

        verification = self.verify_company_website(
            candidate_url,
            expected_website
        )

        if verification["website_match"]:

            print(
                f"    [company-search] VERIFIED: "
                f"{candidate_url}"
            )

            return candidate_url

        print(
            f"    [company-search] Candidate rejected"
        )

        # Small delay before checking another candidate
        BotEvasion.random_action_delay()

    print(
        f"    [company-search] No verified LinkedIn page "
        f"found for {company_name}"
    )

    return None

  def verify_company_website(self, company_url, expected_website):
    """
    Visit the LinkedIn company About page and compare its website
    against the expected company website.
    """
    result = {
        "website_match": False,
        "linkedin_website": "",
    }

    try:
        company_url = _normalize_company_url(company_url)

        if not company_url:
            return result

        about_url = f"{company_url}/about/"
        print(f"    [about] Visiting: {about_url}")

        BotEvasion.random_company_visit_delay()
        self.driver.get(about_url)

        self._wait_for("main", timeout=12)

        BotEvasion.human_delay(3.0, 6.0)

        BotEvasion.simulate_human_scroll(
            self.driver,
            intensity="light"
        )
        BotEvasion.simulate_human_scroll(self.driver, intensity="light")

        soup = self._soup()

        # Find the "Website" section on the About page
        website_link = None

        for element in soup.find_all(["p", "span", "div", "dt", "h3", "h4"]):

            text = element.get_text(" ", strip=True)

            if text.lower() != "website":
                continue

            print("    [debug] Found Website label")

            # Walk upward through the surrounding containers
            container = element

            for _ in range(5):

                container = container.parent

                if not container:
                    break

                links = container.select("a[href]")

                for link in links:

                    href = link.get("href", "").strip()

                    if not href:
                        continue

                    # LinkedIn's external website redirect
                    if "linkedin.com/safety/go" in href.lower():
                        website_link = link
                        break

                    # Direct external URL
                    if (
                        href.startswith("http://")
                        or href.startswith("https://")
                    ) and "linkedin.com" not in href.lower():
                        website_link = link
                        break

                if website_link:
                    break

            if website_link:
                break


        if website_link:

            href = website_link.get("href", "").strip()

            print(f"    [debug] Raw website href: {href}")

            # Extract actual URL from LinkedIn safety redirect
            if "linkedin.com/safety/go" in href.lower():

                parsed = urlparse(href)
                params = parse_qs(parsed.query)

                external_url = params.get("url", [""])[0]

                if external_url:
                    href = unquote(external_url)

            result["linkedin_website"] = href

            print(f"    [debug] Extracted website: {href}")

        else:
            print("    [debug] Could not find Website link in page HTML")


            
        expected_normalized = self._normalize_website(expected_website)
        linkedin_normalized = self._normalize_website(
            result["linkedin_website"]
        )

        print(f"    [website] Expected: {expected_normalized or '-'}")
        print(f"    [website] LinkedIn: {linkedin_normalized or '-'}")

        if (
            expected_normalized
            and linkedin_normalized
            and expected_normalized == linkedin_normalized
        ):
            result["website_match"] = True
            print("    [MATCH] Website matches")
        else:
            print("    [MISMATCH] Website does not match")

    except Exception as e:
        print(f"    [!] Website verification error: {e}")

    return result


  def _names_match(self, expected_name, returned_name):
      """Check whether two names are reasonably likely to match."""
      if not expected_name or not returned_name:
          return False

      def normalize(name):
          name = name.lower().strip()

          # Remove punctuation
          name = re.sub(r"[^a-z0-9\s]", " ", name)

          # Collapse multiple spaces
          name = re.sub(r"\s+", " ", name)

          return name.strip()

      expected = normalize(expected_name)
      returned = normalize(returned_name)

      # Exact normalized match
      if expected == returned:
          return True

      expected_parts = expected.split()
      returned_parts = returned.split()

      if not expected_parts or not returned_parts:
          return False

      # First and last names match
      if (
          expected_parts[0] == returned_parts[0]
          and expected_parts[-1] == returned_parts[-1]
      ):
          return True

      return False

  def scrape_people(self, company_url, hiring_contact=None):
      """
      Search the verified company's LinkedIn People page.

      If hiring_contact exists:
          1. Search for that person.
          2. If not found, fall back to leadership-role searches.

      If hiring_contact does not exist:
          Search CEO, CTO, Founder and Co-Founder.

      Search results are classified by the person's actual title,
      rather than trusting the search keyword.
      """

      slug = self._company_slug(company_url)

      if not slug:
          return []

      found = []
      seen_profiles = set()
      discovered_roles = set()

      fallback_roles = list(
          self.config.get("role_aliases", {}).keys()
      )

      # ---------------------------------------------------------
      # Helper for processing returned people
      # ---------------------------------------------------------

      def process_cards(cards, search_term):

          new_people = []

          for card in cards[:10]:

              # ---------------------------------------------
              # Name
              # ---------------------------------------------

              name = ""

              for sel in [
                  ".org-people-profile-card__profile-title",
                  ".artdeco-entity-lockup__title",
                  "span[aria-hidden='true']",
                  ".entity-result__title-text a span",
                  ".entity-result__title-line a span",
              ]:
                  el = card.select_one(sel)

                  if el:
                      candidate = el.get_text(strip=True)

                      if candidate and candidate != "LinkedIn Member":
                          name = candidate
                          break

              if not name:
                  continue

              # ---------------------------------------------
              # Actual LinkedIn title
              # ---------------------------------------------

              title = ""

              for sel in [
                  ".org-people-profile-card__profile-position",
                  ".artdeco-entity-lockup__subtitle",
                  ".entity-result__primary-subtitle",
                  ".subline-level-1",
                  ".entity-result__summary",
              ]:
                  el = card.select_one(sel)

                  if el:
                      candidate = el.get_text(" ", strip=True)

                      if candidate:
                          title = candidate
                          break

              # ---------------------------------------------
              # Profile URL
              # ---------------------------------------------

              profile_url = ""

              link = card.select_one("a[href*='/in/']")

              if link and link.has_attr("href"):

                  href = link["href"]

                  profile_url = (
                      href
                      if href.startswith("http")
                      else f"https://www.linkedin.com{href}"
                  )

                  profile_url = (
                      profile_url
                      .split("?")[0]
                      .rstrip("/")
                  )

              if not profile_url:
                  continue

              if profile_url in seen_profiles:
                  continue

              # ---------------------------------------------
              # Determine ACTUAL role
              # ---------------------------------------------

              actual_role = self._classify_person_role(title)

              # ---------------------------------------------
              # Person-name search
              # ---------------------------------------------

              if hiring_contact and search_term == hiring_contact:

                  if not self._names_match(
                      hiring_contact,
                      name
                  ):
                      print(
                          f"      [skip] Name mismatch: "
                          f"expected '{hiring_contact}', "
                          f"got '{name}'"
                      )
                      continue

                  # We found the requested person.
                  seen_profiles.add(profile_url)

                  new_people.append({
                      "person_name": name,
                      "person_role": title,
                      "classified_role": actual_role or "",
                      "person_profile_url": profile_url,
                      "search_term": search_term,
                  })

                  print(
                      f"      [person] {name} — "
                      f"{title or 'Unknown role'}"
                  )

                  continue

              # ---------------------------------------------
              # Role search
              # ---------------------------------------------

              if not actual_role:
                  print(
                      f"      [skip] {name} — "
                      f"{title or 'No title'} "
                      f"(could not classify)"
                  )
                  continue

              # Don't save the same role twice
              if actual_role in discovered_roles:
                  print(
                      f"      [skip] {name} — {title} "
                      f"(role already found)"
                  )
                  continue

              seen_profiles.add(profile_url)
              discovered_roles.add(actual_role)

              new_people.append({
                  "person_name": name,
                  "person_role": title,
                  "classified_role": actual_role,
                  "person_profile_url": profile_url,
                  "search_term": search_term,
              })

              print(
                  f"      [person] {name} — {title}"
              )
              print(
                  f"               classified as: {actual_role}"
              )

          return new_people

      # =========================================================
      # STEP 1 — Hiring contact
      # =========================================================

      if hiring_contact:

          BotEvasion.random_people_search_delay()

          try:

              people_url = (
                  f"https://www.linkedin.com/company/{slug}/people/"
                  f"?keywords={hiring_contact.replace(' ', '%20')}"
              )

              print(
                  f"    [people] Searching: {hiring_contact}"
              )

              self.driver.get(people_url)

              self._wait_for(
                  ".org-people-profile-card, "
                  ".scaffold-finite-scroll__content, "
                  "main",
                  timeout=12,
              )

              BotEvasion.human_delay(2.0, 4.0)

              BotEvasion.simulate_human_scroll(
                  self.driver,
                  intensity="light"
              )

              soup = self._soup()

              cards = soup.select(
                  ".org-people-profile-card__card-spacing, "
                  ".org-people-profile-card, "
                  "li.org-people__card-item"
              )

              people = process_cards(
                  cards,
                  hiring_contact
              )

              if people:
                  found.extend(people)

                  # Requested person was found.
                  # No need for fallback role searches.
                  return found

              print(
                  f"    [people] '{hiring_contact}' "
                  f"not found."
              )

              print(
                  "    [people] Falling back to leadership roles."
              )

          except Exception as e:

              print(
                  f"    [!] Person search error: {e}"
              )

              print(
                  "    [people] Falling back to leadership roles."
              )

      # =========================================================
      # STEP 2 — Leadership role searches
      # =========================================================

      for search_term in fallback_roles:

          # -----------------------------------------------------
          # If we already found this role from another search,
          # don't search it again.
          # -----------------------------------------------------

          if search_term in discovered_roles:
              print(
                  f"    [people] Skipping {search_term} "
                  f"(already found)"
              )
              continue

          BotEvasion.random_people_search_delay()

          try:

              people_url = (
                  f"https://www.linkedin.com/company/{slug}/people/"
                  f"?keywords={search_term.replace(' ', '%20')}"
              )

              print(
                  f"    [people] Searching: {search_term}"
              )

              self.driver.get(people_url)

              self._wait_for(
                  ".org-people-profile-card, "
                  ".scaffold-finite-scroll__content, "
                  "main",
                  timeout=12,
              )

              BotEvasion.human_delay(2.0, 4.0)

              BotEvasion.simulate_human_scroll(
                  self.driver,
                  intensity="light"
              )

              soup = self._soup()

              cards = soup.select(
                  ".org-people-profile-card__card-spacing, "
                  ".org-people-profile-card, "
                  "li.org-people__card-item"
              )

              if not cards:
                  print(
                      f"      [people] No results for "
                      f"'{search_term}'"
                  )
                  continue

              people = process_cards(
                  cards,
                  search_term
              )

              found.extend(people)

              if not people:
                  print(
                      f"      [people] No valid people "
                      f"found for '{search_term}'"
                  )

          except Exception as e:

              print(
                  f"    [!] People search error "
                  f"for '{search_term}': {e}"
              )

      return found

  def load_existing_results(self):
    """Load previously completed companies."""
    if not os.path.exists(OUTPUT_FILE):
        return []

    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

    except Exception as e:
        print(f"[!] Could not load existing results: {e}")

    return []


  def save_results(self, results):
      """Save results immediately to disk."""
      os.makedirs(
          os.path.dirname(OUTPUT_FILE),
          exist_ok=True
      )

      temp_file = OUTPUT_FILE + ".tmp"

      try:
          with open(temp_file, "w", encoding="utf-8") as f:
              json.dump(
                  results,
                  f,
                  indent=2,
                  ensure_ascii=False
              )

          # Replace old file only after successful write
          os.replace(temp_file, OUTPUT_FILE)

          print(
              f"    [saved] {len(results)} companies → "
              f"{OUTPUT_FILE}"
          )

      except Exception as e:
          print(f"    [!] Could not save results: {e}")

          if os.path.exists(temp_file):
              os.remove(temp_file)

  
  def _classify_person_role(self, title):
      if not title:
          return None

      title_lower = title.lower()

      role_aliases = self.config.get("role_aliases", {})

      for role, aliases in role_aliases.items():

          for alias in aliases:

              alias_lower = alias.lower().strip()

              if not alias_lower:
                  continue

              pattern = r"\b" + re.escape(alias_lower) + r"\b"

              if re.search(pattern, title_lower):
                  return role

      return None

  def run_workflow(self):
    #   os.makedirs("outputs", exist_ok=True)

      companies = self.load_input_companies()

      print(f"[*] Loaded {len(companies)} companies from {INPUT_FILE}")

      # results = []
      results = self.load_existing_results()

      processed_companies = {
          result.get("company_id")
          for result in results
          if result.get("company_id")
      }

      print(
          f"[*] Loaded {len(results)} previously completed companies."
      )

      new_successful = 0

      try:
          for index, company in enumerate(companies, start=1):

              company_name = company["company_name"]

              company_id = company["company_id"]

              if company_id in processed_companies:
                  print(
                      f"\n[skip] {company_name} "
                      f"(already successfully processed)"
                  )
                  continue
              
              expected_website = company["company_website"]
              linkedin_urls = company["company_linkedin"]
              hiring_contact = company["hiring_contact"]

              print(
                  f"\n[*] --- Company {index}/{len(companies)} ---"
              )
              print(f"    Company: {company_name}")
              print(f"    Website: {expected_website}")
              print(f"    LinkedIn URLs: {len(linkedin_urls)}")
              print(f"    Hiring contact: {hiring_contact or '-'}")

            # --------------------------------------------------
            # Check existing LinkedIn company URLs
            # --------------------------------------------------

              matched_linkedin_url = None
              linkedin_website = ""

              if linkedin_urls:

                for linkedin_url in linkedin_urls:

                    if not linkedin_url:
                        continue

                    print(f"\n    [check] {linkedin_url}")

                    verification = self.verify_company_website(
                        linkedin_url,
                        expected_website
                    )

                    if verification["website_match"]:
                        matched_linkedin_url = linkedin_url
                        linkedin_website = verification["linkedin_website"]
                        break


              # --------------------------------------------------
              # If existing URLs don't work, search LinkedIn
              # by company name
              # --------------------------------------------------

              if not matched_linkedin_url:

                print(
                    f"\n    [fallback] No matching LinkedIn URL "
                    f"found for {company_name}"
                )

                matched_linkedin_url = (
                    self.find_verified_company_linkedin(
                        company_name,
                        expected_website
                    )
                )

                if matched_linkedin_url:
                    # Verify again so we also get the LinkedIn website
                    verification = self.verify_company_website(
                        matched_linkedin_url,
                        expected_website
                    )

                    linkedin_website = verification["linkedin_website"]


              # --------------------------------------------------
              # Nothing found
              # --------------------------------------------------

              if not matched_linkedin_url:

                print(
                    f"    [skip] Could not find a verified LinkedIn "
                    f"company for {company_name}"
                )
                continue

              # --------------------------------------------------
              # Search People on the verified company page
              # --------------------------------------------------
              people = self.scrape_people(
                  matched_linkedin_url,
                  hiring_contact=hiring_contact
              )

              print(
                  f"    [✓] Found {len(people)} people"
              )


              result = {
                  "company_id": company["company_id"],
                  "company_name": company_name,
                  "company_website_url": expected_website,
                  "linkedin_company_url": matched_linkedin_url,
                  "linkedin_website": linkedin_website,
                  "hiring_contact": hiring_contact,
                  "people": people
              }

              results.append(result)

              processed_companies.add(company_id)

              self.save_results(results)
              new_successful += 1

              if new_successful >= self.target_output:
                print(
                    f"\n[+] Completed {self.target_output} new successful companies."
                )
                break

              # input("\nPress Enter to continue to the next company...")

              BotEvasion.random_action_delay()

      except KeyboardInterrupt:
          print("\n[!] Scraper interrupted by user.")

      except Exception as e:
          print(f"\n[!] Workflow error: {e}")

      finally:
          if results:
              print(f"\n[+] Processed {len(results)} verified companies.")
          else:
              print("\n[!] No verified companies found.")

          print("[*] Scraper finished.")

if __name__ == "__main__":
  scraper = LinkedInIntelligenceScraper()
  scraper.run_workflow()