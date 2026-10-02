import random
import time
from selenium.webdriver.common.action_chains import ActionChains


class BotEvasion:

  @staticmethod
  def human_delay(min_sec=3.0, max_sec=6.0):
      delay = random.triangular(
          min_sec,
          max_sec,
          (min_sec + max_sec) / 2
      )
      time.sleep(delay)


  @staticmethod
  def random_action_delay():
      delay = random.triangular(1.5, 3.5, 2.2)
      time.sleep(delay)


  @staticmethod
  def random_page_delay():
      delay = random.triangular(6.0, 12.0, 8.0)
      time.sleep(delay)


  @staticmethod
  def random_company_visit_delay():
      delay = random.triangular(3.0, 6.0, 4.0)
      time.sleep(delay)


  @staticmethod
  def random_people_search_delay():
      delay = random.triangular(3.0, 6.0, 4.0)
      time.sleep(delay)


  @staticmethod
  def random_micro_delay():
      delay = random.uniform(0.5, 1.5)
      time.sleep(delay)


  @staticmethod
  def long_break(min_sec=60, max_sec=120):
    """Long break every N companies to avoid bot detection on large runs (1-2 min)."""
    delay = random.uniform(min_sec, max_sec)
    print(f"    [break] Taking a {delay:.0f}s break to avoid detection...")
    time.sleep(delay)

  # @staticmethod
  # def simulate_human_scroll(driver, intensity="normal"):
  #   """Performs erratic, human-like scrolling actions to trigger lazy loading safely.

  #   Args:
  #     driver: Selenium webdriver instance.
  #     intensity: 'light' for quick scroll, 'normal' for standard, 'deep' for thorough.
  #   """
  #   total_height = driver.execute_script("return document.body.scrollHeight")
  #   current_height = 0

  #   # Vary scroll behavior based on intensity
  #   if intensity == "light":
  #     chunk_range = (600, 1200)
  #     pause_range = (0.2, 0.6)
  #     backscroll_chance = 0.05
  #   elif intensity == "deep":
  #     chunk_range = (300, 700)
  #     pause_range = (0.5, 1.2)
  #     backscroll_chance = 0.15
  #   else:
  #     chunk_range = (500, 900)
  #     pause_range = (0.3, 0.9)
  #     backscroll_chance = 0.1

  #   while current_height < total_height:
  #     scroll_chunk = random.randint(*chunk_range)
  #     current_height += scroll_chunk
  #     driver.execute_script(f"window.scrollTo(0, {current_height});")
  #     time.sleep(random.uniform(*pause_range))

  #     # Occasionally scroll up slightly (like a user rereading something)
  #     if random.random() < backscroll_chance:
  #       backscroll = random.randint(50, 200)
  #       driver.execute_script(
  #           f"window.scrollTo(0, {current_height - backscroll});"
  #       )
  #       time.sleep(random.uniform(0.3, 0.8))

  #     # Occasionally pause longer (like reading content)
  #     if random.random() < 0.05:
  #       time.sleep(random.uniform(0.8, 1.5))

  #     total_height = driver.execute_script("return document.body.scrollHeight")

  @staticmethod
  def simulate_human_scroll(driver, intensity="normal"):
      """
      Scroll a limited amount rather than traversing the entire page.
      This avoids jumping through the entire page during extraction.
      """

      if intensity == "light":
          scrolls = random.randint(1, 2)
          chunk_range = (300, 500)
          pause_range = (0.8, 1.5)

      elif intensity == "deep":
          scrolls = random.randint(3, 5)
          chunk_range = (400, 700)
          pause_range = (1.0, 2.0)

      else:
          scrolls = random.randint(2, 3)
          chunk_range = (350, 600)
          pause_range = (0.8, 1.6)

      current_position = driver.execute_script(
          "return window.pageYOffset;"
      )

      for _ in range(scrolls):

          scroll_amount = random.randint(*chunk_range)
          current_position += scroll_amount

          driver.execute_script(
              "window.scrollTo({top: arguments[0], behavior: 'smooth'});",
              current_position
          )

          time.sleep(random.uniform(*pause_range))

          # Occasionally move slightly back up
          if random.random() < 0.15:
              current_position = max(
                  0,
                  current_position - random.randint(50, 150)
              )

              driver.execute_script(
                  "window.scrollTo({top: arguments[0], behavior: 'smooth'});",
                  current_position
              )

              time.sleep(random.uniform(0.5, 1.0))

  @staticmethod
  def human_mouse_jitter(driver, element):
    """Hovers the mouse cursor organically over an element before interacting."""
    try:
      actions = ActionChains(driver)
      actions.move_to_element(element).pause(random.uniform(0.3, 0.9)).perform()
    except Exception:
      pass

  @staticmethod
  def random_tab_behavior(driver):
    """Occasionally opens a new tab and closes it, mimicking multitasking."""
    if random.random() < 0.1:
      try:
        original_window = driver.current_window_handle
        driver.execute_script("window.open('about:blank','_blank');")
        time.sleep(random.uniform(1.0, 3.0))
        driver.switch_to.window(driver.window_handles[-1])
        driver.close()
        driver.switch_to.window(original_window)
        time.sleep(random.uniform(0.5, 1.0))
      except Exception:
        pass
