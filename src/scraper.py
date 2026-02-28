import asyncio
import html as html_module
import json
import logging
import random
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.manyvids.com"

# Regex to find all RSC push script payloads
_RSC_PATTERN = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.DOTALL)

# Regex to extract video objects from decoded RSC string.
# Anchored to {"id":"...","title":"..."} so we match video objects specifically
# (not the creator URL object which has "id" followed by "slug"/"mainSection").
_VIDEO_PATTERN = re.compile(
    r'\{"id":"(\d+)"'         # group 1: numeric video ID (at start of object)
    r',"title":"(.*?)"'       # group 2: title (HTML-encoded, immediately follows id)
    r'.*?"slug":"([^"]+)"'    # group 3: URL slug
    r'.*?"regular":"([^"]*)"' # group 4: regular price (may be empty string)
    r'.*?"duration":"([^"]*)"', # group 5: duration string (e.g. "02:13")
    re.DOTALL,
)

# Regex to find total pages from RSC pagination metadata
_TOTAL_PAGES_PATTERN = re.compile(r'"totalPages":(\d+)')


@dataclass
class VideoData:
    video_id: str
    title: str
    slug: str
    url: str
    price_regular: Optional[str]
    duration: Optional[str]

    def to_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "title": self.title,
            "slug": self.slug,
            "url": self.url,
            "price_regular": self.price_regular,
            "duration": self.duration,
        }


@dataclass
class CreatorResult:
    creator_id: str
    creator_name: str
    videos: list[VideoData]
    total_pages: int
    error: Optional[str] = None


class ScraperError(Exception):
    pass


class ScraperBlockedError(ScraperError):
    pass


def _build_page_url(creator_id: str, creator_name: str, page: int) -> str:
    base = f"{BASE_URL}/Profile/{creator_id}/{creator_name}/Store/Videos"
    params = {"sort": "newest"}
    if page > 1:
        params["page"] = str(page)
    return f"{base}?{urlencode(params)}"


def _extract_rsc_video_data(html_content: str) -> tuple[list[VideoData], int]:
    """
    Extract video data from Next.js RSC streaming payload.

    The page embeds video data in self.__next_f.push([1, "..."]) script tags.
    The specific script containing 'isVideosStore' and 'swrFallback' holds
    the full video list for this page.

    Returns: (list of VideoData, total_pages)
    """
    for match in _RSC_PATTERN.finditer(html_content):
        raw = match.group(1)
        try:
            # The payload is a JSON-encoded string — decode one level of escaping
            decoded = json.loads('"' + raw + '"')
        except (json.JSONDecodeError, ValueError):
            continue

        if "isVideosStore" not in decoded or "swrFallback" not in decoded:
            continue

        # Extract total pages (first occurrence is the video pages count)
        total_pages = 1
        tp_match = _TOTAL_PAGES_PATTERN.search(decoded)
        if tp_match:
            total_pages = int(tp_match.group(1))

        # Extract video objects, deduplicating by video ID
        seen_ids: set[str] = set()
        videos: list[VideoData] = []

        for vm in _VIDEO_PATTERN.finditer(decoded):
            vid_id = vm.group(1)
            if vid_id in seen_ids:
                continue
            seen_ids.add(vid_id)

            title = html_module.unescape(vm.group(2))
            slug = vm.group(3)
            price_raw = vm.group(4).strip()
            price = price_raw if price_raw else None
            duration_raw = vm.group(5).strip()
            duration = duration_raw if duration_raw else None

            videos.append(
                VideoData(
                    video_id=vid_id,
                    title=title,
                    slug=slug,
                    url=f"{BASE_URL}/Video/{vid_id}/{slug}",
                    price_regular=price,
                    duration=duration,
                )
            )

        logger.debug(
            f"RSC extraction: {len(videos)} unique videos, {total_pages} total pages"
        )
        return videos, total_pages

    logger.warning("RSC video payload not found in page HTML")
    return [], 1


class ManyVidsScraper:
    def __init__(self, config: dict):
        self.config = config
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self) -> "ManyVidsScraper":
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config["scraping"].get("headless", True),
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        self._context = await self._browser.new_context(
            user_agent=self.config["scraping"]["user_agent"],
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
        )
        # Mask automation signals to reduce bot detection
        await self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        logger.debug("Playwright browser context initialized")
        return self

    async def __aexit__(self, *args) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.debug("Playwright browser context closed")

    async def _load_page(self, page: Page, url: str) -> str:
        """
        Navigate to URL, wait for RSC video payload to appear (confirms the
        WAF challenge has been passed and actual content was served).

        Returns full page HTML.
        Raises ScraperBlockedError if WAF block detected.
        Raises ScraperError on timeout or unexpected failure.
        """
        timeout_ms = self.config["scraping"]["page_timeout"]

        try:
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        except PlaywrightTimeout:
            raise ScraperError(f"Timeout loading {url}")

        title = await page.title()
        title_lower = title.lower()
        if "access denied" in title_lower or "forbidden" in title_lower or "blocked" in title_lower:
            raise ScraperBlockedError(f"WAF block detected: page title={title!r}")

        # Wait for the RSC video payload script to be present in the DOM
        # This is the definitive signal that content was served (not a challenge page)
        try:
            await page.wait_for_function(
                """() => {
                    const scripts = document.querySelectorAll('script:not([src])');
                    for (const s of scripts) {
                        if (s.textContent.includes('isVideosStore')) return true;
                    }
                    return false;
                }""",
                timeout=timeout_ms,
            )
        except PlaywrightTimeout:
            raise ScraperError(
                f"RSC video payload never appeared at {url} — "
                "possible WAF block or page structure change"
            )

        return await page.content()

    async def _scrape_creator(
        self,
        creator_id: str,
        creator_name: str,
        known_video_ids: set[str],
    ) -> CreatorResult:
        page = await self._context.new_page()
        all_videos: list[VideoData] = []
        total_pages = 1

        try:
            for page_num in range(1, 200):  # hard cap to prevent infinite loops
                if page_num > 1:
                    delay = random.uniform(
                        self.config["scraping"]["delay_between_pages_min"],
                        self.config["scraping"]["delay_between_pages_max"],
                    )
                    logger.debug(
                        f"Creator {creator_name}: waiting {delay:.1f}s before page {page_num}"
                    )
                    await asyncio.sleep(delay)

                url = _build_page_url(creator_id, creator_name, page_num)
                logger.debug(f"Creator {creator_name}: fetching page {page_num} — {url}")

                html_content = await self._load_page(page, url)
                page_videos, total_pages = _extract_rsc_video_data(html_content)

                if not page_videos:
                    logger.warning(
                        f"Creator {creator_name}: no videos on page {page_num}, "
                        "stopping pagination"
                    )
                    break

                all_videos.extend(page_videos)

                # Early stop: if every video on this page is already known,
                # all subsequent (older) pages will also be known
                page_ids = {v.video_id for v in page_videos}
                if page_ids.issubset(known_video_ids):
                    logger.info(
                        f"Creator {creator_name}: all videos on page {page_num} already known, "
                        f"stopping (page {page_num}/{total_pages})"
                    )
                    break

                if page_num >= total_pages:
                    break

        finally:
            await page.close()

        # Deduplicate across pages (RSC payloads can overlap)
        seen: set[str] = set()
        unique_videos: list[VideoData] = []
        for v in all_videos:
            if v.video_id not in seen:
                seen.add(v.video_id)
                unique_videos.append(v)

        logger.info(
            f"Creator {creator_name}: scraped {len(unique_videos)} unique videos "
            f"across {min(page_num, total_pages)}/{total_pages} pages"
        )
        return CreatorResult(
            creator_id=creator_id,
            creator_name=creator_name,
            videos=unique_videos,
            total_pages=total_pages,
        )

    async def scrape_creator_with_retry(
        self,
        creator_id: str,
        creator_name: str,
        known_video_ids: set[str],
    ) -> CreatorResult:
        max_retries = self.config["scraping"]["max_retries"]
        backoff_base = self.config["scraping"]["retry_backoff_base"]

        last_error: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                return await self._scrape_creator(creator_id, creator_name, known_video_ids)
            except ScraperBlockedError as e:
                last_error = e
                logger.warning(f"Creator {creator_name}: WAF block on attempt {attempt + 1}: {e}")
            except ScraperError as e:
                last_error = e
                logger.error(f"Creator {creator_name}: scrape error on attempt {attempt + 1}: {e}")
            except Exception as e:
                last_error = e
                logger.exception(
                    f"Creator {creator_name}: unexpected error on attempt {attempt + 1}"
                )

            if attempt < max_retries:
                wait = backoff_base * (2 ** attempt) + random.uniform(0, 5)
                logger.info(f"Creator {creator_name}: retrying in {wait:.0f}s")
                await asyncio.sleep(wait)

        return CreatorResult(
            creator_id=creator_id,
            creator_name=creator_name,
            videos=[],
            total_pages=0,
            error=f"Failed after {max_retries + 1} attempts: {last_error}",
        )
