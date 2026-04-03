"""
Selenium-based browser automation for Jarvis.
Provides real interaction with web apps: WhatsApp Web, YouTube, Google, etc.
Uses a persistent Chrome profile so logins (e.g. WhatsApp QR) are remembered.
"""

import atexit
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.webdriver import WebDriver as ChromeDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

log = logging.getLogger("Jarvis.BrowserAutomation")

BASE_DIR = Path(__file__).resolve().parent.parent
CHROME_PROFILE = str(BASE_DIR / "Data" / "JarvisBrowser")

_driver: Optional[ChromeDriver] = None
_lock = threading.Lock()
_tabs: dict[str, str] = {}
_cached_driver_path: Optional[str] = None
MAX_TABS = 8


# -- Driver management -----------------------------------------------------

def _get_driver() -> ChromeDriver:
    """Return the singleton Chrome instance, creating it if needed."""
    global _driver, _cached_driver_path
    if _driver is not None:
        try:
            _ = _driver.current_url
            return _driver
        except WebDriverException:
            log.warning("Chrome driver is stale, recreating")
            _driver = None

    log.info("Starting Chrome for browser automation")
    opts = Options()
    opts.add_argument(f"--user-data-dir={CHROME_PROFILE}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-background-networking")
    opts.add_argument("--disable-sync")
    opts.add_argument("--disable-translate")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        if _cached_driver_path is None:
            _cached_driver_path = ChromeDriverManager().install()
        svc = ChromeService(_cached_driver_path)
        _driver = ChromeDriver(service=svc, options=opts)
    except Exception:
        _driver = ChromeDriver(options=opts)

    driver = _driver
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    log.info("Chrome started successfully")
    return driver


def close_browser() -> None:
    """Shut down the managed Chrome instance."""
    global _driver
    with _lock:
        if _driver:
            log.info("Closing Chrome browser automation instance")
            try:
                _driver.quit()
            except Exception:
                pass
            _driver = None
        _tabs.clear()


def kill_orphaned_chromedriver() -> None:
    """Kill leftover chromedriver.exe processes from previous crashed sessions.

    Safe to call at startup before creating a new driver.
    """
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "chromedriver.exe"],
            capture_output=True, timeout=5,
        )
        log.info("Cleaned up orphaned chromedriver processes")
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.debug("Orphan cleanup: %s", exc)


atexit.register(close_browser)


# -- Tab management ---------------------------------------------------------

def _switch_or_open_tab(domain: str, url: str) -> ChromeDriver:
    """Re-use an existing tab for domain or open a new one."""
    driver = _get_driver()

    # Evict oldest tab if at capacity
    if len(_tabs) >= MAX_TABS and domain not in _tabs:
        oldest_domain = next(iter(_tabs))
        log.info("Tab limit reached (%d), closing oldest: %s", MAX_TABS, oldest_domain)
        try:
            driver.switch_to.window(_tabs[oldest_domain])
            driver.close()
        except WebDriverException:
            pass
        _tabs.pop(oldest_domain, None)
        if driver.window_handles:
            driver.switch_to.window(driver.window_handles[-1])

    if domain in _tabs:
        try:
            driver.switch_to.window(_tabs[domain])
            if domain not in driver.current_url:
                driver.get(url)
            return driver
        except WebDriverException:
            _tabs.pop(domain, None)

    if driver.current_url not in ("data:,", "about:blank", ""):
        driver.execute_script("window.open('');")
        driver.switch_to.window(driver.window_handles[-1])

    driver.get(url)
    _tabs[domain] = driver.current_window_handle
    return driver


# -- Element helpers --------------------------------------------------------

def _find(driver, selectors: list[tuple[str, str]], timeout: int = 10):
    """Try selectors in order; return first clickable match."""
    for by, sel in selectors:
        try:
            return WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((by, sel))
            )
        except (TimeoutException, NoSuchElementException):
            continue
    raise TimeoutException(f"No selector matched: {selectors}")


def _clear_and_type(element, text: str) -> None:
    """Select-all, delete, then type into a contenteditable element."""
    element.click()
    time.sleep(0.2)
    element.send_keys(Keys.CONTROL + "a")
    time.sleep(0.1)
    element.send_keys(Keys.DELETE)
    time.sleep(0.1)
    element.send_keys(text)


# -- WhatsApp Web -----------------------------------------------------------

_WA_SEARCH = [
    (By.CSS_SELECTOR, 'div[contenteditable="true"][data-tab="3"]'),
    (By.CSS_SELECTOR, '#side div[contenteditable="true"][role="textbox"]'),
    (By.CSS_SELECTOR, '#side div[contenteditable="true"]'),
    (By.XPATH, '//div[@id="side"]//div[@contenteditable="true"]'),
]

_WA_MSGBOX = [
    (By.CSS_SELECTOR, 'div[contenteditable="true"][data-tab="10"]'),
    (By.CSS_SELECTOR, 'footer div[contenteditable="true"][role="textbox"]'),
    (By.CSS_SELECTOR, 'footer div[contenteditable="true"]'),
    (By.XPATH, '//footer//div[@contenteditable="true"]'),
    (By.CSS_SELECTOR, 'div[title="Type a message"]'),
]


def whatsapp_open() -> bool:
    """Open WhatsApp Web and wait until the main interface loads."""
    with _lock:
        try:
            driver = _switch_or_open_tab(
                "web.whatsapp.com", "https://web.whatsapp.com"
            )
            print("[WhatsApp] Waiting for WhatsApp Web to load...")
            print("[WhatsApp] (Scan QR code in the browser if this is the first time)")
            _find(driver, _WA_SEARCH, timeout=120)
            print("[WhatsApp] WhatsApp Web is ready.")
            return True
        except Exception as exc:
            log.error("[WhatsApp] open failed: %s", exc)
            print(f"[WhatsApp] Could not open: {exc}")
            return False


def whatsapp_send_message(contact_name: str, message: str) -> bool:
    """Find contact_name on WhatsApp Web and send message."""
    with _lock:
        try:
            driver = _switch_or_open_tab(
                "web.whatsapp.com", "https://web.whatsapp.com"
            )
            print("[WhatsApp] Waiting for WhatsApp Web to load...")
            print("[WhatsApp] (Scan QR code if this is the first time)")

            search_box = _find(driver, _WA_SEARCH, timeout=120)
            time.sleep(1)

            _clear_and_type(search_box, contact_name)
            time.sleep(2.5)

            cl = contact_name.lower()
            contact_xpaths = [
                (
                    By.XPATH,
                    f'//span[contains(translate(@title,'
                    f'"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
                    f'"abcdefghijklmnopqrstuvwxyz"),"{cl}")]',
                ),
                (By.XPATH, f'//span[@title and contains(@title,"{contact_name}")]'),
            ]
            contact_el = _find(driver, contact_xpaths, timeout=10)
            contact_el.click()
            time.sleep(1)

            msg_box = _find(driver, _WA_MSGBOX, timeout=10)
            msg_box.click()
            time.sleep(0.3)
            msg_box.send_keys(message)
            time.sleep(0.5)
            msg_box.send_keys(Keys.ENTER)

            log.info("[WhatsApp] Sent to '%s': %s", contact_name, message)
            print(f"[WhatsApp] Message sent to '{contact_name}' successfully!")
            return True

        except TimeoutException:
            log.error("[WhatsApp] Timed out waiting for elements.")
            print(
                "[WhatsApp] Error: timed out. "
                "Make sure WhatsApp Web is loaded and you are logged in."
            )
            return False
        except Exception as exc:
            log.error("[WhatsApp] send failed: %s", exc)
            print(f"[WhatsApp] Error: {exc}")
            return False


# -- YouTube ----------------------------------------------------------------

def youtube_open() -> bool:
    """Open YouTube in the managed browser."""
    with _lock:
        try:
            _switch_or_open_tab("youtube.com", "https://www.youtube.com")
            print("[YouTube] YouTube is ready.")
            return True
        except Exception as exc:
            log.error("[YouTube] open failed: %s", exc)
            return False


def youtube_search(query: str) -> bool:
    """Open YouTube and type query in the search bar."""
    with _lock:
        try:
            driver = _switch_or_open_tab(
                "youtube.com", "https://www.youtube.com"
            )
            sb = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "input#search, input[name='search_query']")
                )
            )
            sb.clear()
            sb.send_keys(query)
            sb.send_keys(Keys.ENTER)
            time.sleep(2)
            log.info("[YouTube] Searched: %s", query)
            print(f"[YouTube] Searched for: {query}")
            return True
        except Exception as exc:
            log.error("[YouTube] search failed: %s", exc)
            print(f"[YouTube] Search error: {exc}")
            return False


def youtube_play(query: str) -> bool:
    """Search YouTube for query and click the first video result."""
    with _lock:
        try:
            driver = _switch_or_open_tab(
                "youtube.com", "https://www.youtube.com"
            )
            sb = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "input#search, input[name='search_query']")
                )
            )
            sb.clear()
            sb.send_keys(query)
            sb.send_keys(Keys.ENTER)
            time.sleep(3)

            vid_selectors = [
                (By.CSS_SELECTOR, "ytd-video-renderer a#video-title"),
                (By.CSS_SELECTOR, "a#video-title"),
                (By.XPATH, '(//a[@id="video-title"])[1]'),
            ]
            vid = _find(driver, vid_selectors, timeout=10)
            vid.click()

            log.info("[YouTube] Playing: %s", query)
            print(f"[YouTube] Now playing: {query}")
            return True
        except Exception as exc:
            log.error("[YouTube] play failed: %s", exc)
            print(f"[YouTube] Could not play: {exc}")
            return False


# -- Google -----------------------------------------------------------------

def google_search(query: str) -> bool:
    """Open Google and search for query."""
    with _lock:
        try:
            driver = _switch_or_open_tab(
                "google.com", "https://www.google.com"
            )
            sb = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "textarea[name='q'], input[name='q']")
                )
            )
            sb.clear()
            sb.send_keys(query)
            sb.send_keys(Keys.ENTER)
            time.sleep(2)
            log.info("[Google] Searched: %s", query)
            print(f"[Google] Searched for: {query}")
            return True
        except Exception as exc:
            log.error("[Google] search failed: %s", exc)
            return False


# -- Generic open -----------------------------------------------------------

def open_website(url: str) -> bool:
    """Open url in the managed Selenium browser."""
    with _lock:
        try:
            if not url.startswith("http"):
                url = f"https://{url}"
            domain = urlparse(url).netloc or url
            _switch_or_open_tab(domain, url)
            print(f"[Browser] Opened: {url}")
            return True
        except Exception as exc:
            log.error("[Browser] open failed: %s", exc)
            return False
