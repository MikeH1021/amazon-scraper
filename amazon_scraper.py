"""
Amazon Product Scraper
Playwright-based scraper for Amazon product/brand research
Two-phase: search pages -> product detail pages
"""

import asyncio
import csv
import json
import logging
import random
import re
from datetime import datetime
from typing import List, Dict, Optional
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from bs4 import BeautifulSoup

from amazon_categories import get_search_url, get_category
from proxy_manager import ProxyManager

logger = logging.getLogger(__name__)

# User-Agent rotation pool
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
]

# CAPTCHA detection selectors
CAPTCHA_SELECTORS = [
    "form[action='/errors/validateCaptcha']",
    "#captchacharacters",
    "img[src*='captcha']",
    ".a-box-inner h4",  # "Enter the characters you see below"
]

# Viewport sizes for randomization
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 720},
    {"width": 1600, "height": 900},
]

# Decoy URLs for anti-detection
DECOY_URLS = [
    "https://www.amazon.com",
    "https://www.amazon.com/gp/bestsellers/",
    "https://www.amazon.com/gp/new-releases/",
    "https://www.amazon.com/deals",
]

# Product type classification patterns
PRODUCT_TYPE_PATTERNS = {
    "capsule": r'\b(capsule|veggie cap|vcap|vegetable capsule)\b',
    "tablet": r'\b(tablet|tab)\b',
    "softgel": r'\b(soft\s*gel|softgel)\b',
    "gummy": r'\b(gumm|gummies|gummy)\b',
    "powder": r'\b(powder|mix|scoop)\b',
    "liquid": r'\b(liquid|drops|tincture|syrup|elixir)\b',
    "cream": r'\b(cream|lotion|ointment|balm|salve)\b',
    "spray": r'\b(spray|mist)\b',
    "patch": r'\b(patch|transdermal)\b',
    "oil": r'\b(oil|essential oil)\b',
    "bar": r'\b(bar|chew)\b',
}


def classify_product_type(title, bullet_points=None):
    """Classify product type from title and bullet points."""
    text = (title or "").lower()
    if bullet_points:
        if isinstance(bullet_points, list):
            text += " " + " ".join(bullet_points).lower()
        else:
            text += " " + str(bullet_points).lower()

    for ptype, pattern in PRODUCT_TYPE_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            return ptype
    return ""


def parse_bsr_text(text):
    """
    Parse BSR from various Amazon HTML formats.

    Handles:
    - "#1,234 in Health & Household"
    - "#1234 in Health & Household (See Top 100 in Health & Household)"
    - "1,234 in Health & Household"
    """
    if not text:
        return 0
    # Extract number after #
    match = re.search(r'#?([\d,]+)\s+in\s+', text)
    if match:
        return int(match.group(1).replace(',', ''))
    return 0


class AmazonScraper:
    """
    Amazon product scraper with Playwright browser automation.

    Features:
    - Two-phase scraping: search results -> detail pages
    - Multi-selector fallback for data extraction
    - Stealth browser configuration
    - User-Agent rotation
    - CAPTCHA detection and handling
    - Decoy requests
    """

    def __init__(
        self,
        headless=True,
        delay=3.0,
        proxy_manager=None,
        max_pages=3,
        detail_pages=True,
    ):
        self.headless = headless
        self.delay = delay
        self.proxy_manager = proxy_manager
        self.max_pages = max_pages
        self.detail_pages = detail_pages

        self.playwright = None
        self.browser = None
        self.captcha_count = 0
        self.request_count = 0
        self.decoy_interval = 10  # Do a decoy request every N requests

    async def start_browser(self):
        """Launch Playwright browser with stealth settings."""
        if self.browser:
            return

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
            ]
        )
        logger.info("Browser started")

    async def close_browser(self):
        """Close browser and cleanup."""
        try:
            if self.browser:
                await self.browser.close()
                self.browser = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
        except Exception as e:
            logger.error(f"Error closing browser: {e}")

    def _get_context_options(self, proxy=None):
        """Build stealth browser context options."""
        viewport = random.choice(VIEWPORTS)
        user_agent = random.choice(USER_AGENTS)

        options = {
            "user_agent": user_agent,
            "viewport": viewport,
            "locale": "en-US",
            "timezone_id": random.choice([
                "America/New_York", "America/Chicago",
                "America/Denver", "America/Los_Angeles",
            ]),
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1",
            }
        }

        if proxy:
            options["proxy"] = proxy.to_playwright_dict()

        return options

    async def _apply_stealth(self, page):
        """Apply stealth JavaScript to hide automation markers."""
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            window.chrome = {runtime: {}};
        """)

    async def _check_captcha(self, page):
        """Check if page has a CAPTCHA challenge."""
        for selector in CAPTCHA_SELECTORS:
            try:
                elem = await page.query_selector(selector)
                if elem:
                    self.captcha_count += 1
                    logger.warning(f"CAPTCHA detected (total: {self.captcha_count})")
                    return True
            except Exception:
                pass
        return False

    async def _handle_captcha(self, page, context, proxy=None):
        """Handle CAPTCHA by pausing and optionally rotating proxy."""
        logger.warning("Pausing for CAPTCHA cooldown (30s)...")
        await asyncio.sleep(30)

        # Rotate proxy if available
        if self.proxy_manager:
            new_proxy = self.proxy_manager.get_next_proxy()
            if new_proxy and proxy and new_proxy != proxy:
                if proxy:
                    proxy.record_failure(is_block=True)
                logger.info(f"Rotating proxy to {new_proxy.host}:{new_proxy.port}")
                return new_proxy

        return proxy

    async def _do_decoy_request(self, context):
        """Visit a random Amazon page as a decoy."""
        try:
            url = random.choice(DECOY_URLS)
            page = await context.new_page()
            await self._apply_stealth(page)
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            # Simulate browsing
            await asyncio.sleep(random.uniform(1, 3))
            await page.close()
            logger.debug(f"Decoy request: {url}")
        except Exception:
            pass

    async def _random_delay(self):
        """Wait with random jitter."""
        jitter = random.uniform(1, 4)
        wait = self.delay + jitter
        await asyncio.sleep(wait)

    # ---- Phase 1: Search Page Scraping ----

    async def scrape_search(self, category_key, keyword, max_pages=None):
        """
        Scrape Amazon search results for a category + keyword.

        Args:
            category_key: Key from AMAZON_CATEGORIES
            keyword: Search keyword
            max_pages: Override max pages to scrape

        Returns:
            List of product dicts with basic info (ASIN, title, price, rating, reviews, image, prime)
        """
        if max_pages is None:
            max_pages = self.max_pages

        proxy = None
        if self.proxy_manager:
            proxy = self.proxy_manager.get_next_proxy()
            if proxy:
                logger.info(f"Search using proxy: {proxy.host}:{proxy.port}")
        else:
            logger.info("Running without proxy")

        context_options = self._get_context_options(proxy)
        context = await self.browser.new_context(**context_options)
        page = await context.new_page()
        await self._apply_stealth(page)

        all_products = []

        try:
            for page_num in range(1, max_pages + 1):
                url = get_search_url(category_key, keyword, page_num)
                logger.info(f"Search: '{keyword}' page {page_num}/{max_pages}")

                try:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                except Exception as e:
                    logger.error(f"Navigation error: {e}")
                    break

                # Check response
                if response and response.status in (429, 503):
                    logger.warning(f"Rate limited ({response.status}), pausing...")
                    await asyncio.sleep(15)
                    break

                # Check for CAPTCHA
                if await self._check_captcha(page):
                    proxy = await self._handle_captcha(page, context, proxy)
                    break

                # Wait for content
                try:
                    await page.wait_for_selector(
                        'div[data-component-type="s-search-result"], .s-result-item',
                        timeout=10000
                    )
                except Exception:
                    logger.warning(f"No search results found on page {page_num}")
                    break

                # Extract products
                html = await page.content()
                products = self._parse_search_results(html, category_key, keyword)

                if not products:
                    logger.info(f"No more products on page {page_num}")
                    break

                all_products.extend(products)
                logger.info(f"Found {len(products)} products on page {page_num} (total: {len(all_products)})")

                self.request_count += 1

                # Decoy request periodically
                if self.request_count % self.decoy_interval == 0:
                    await self._do_decoy_request(context)

                # Delay between pages
                if page_num < max_pages:
                    await self._random_delay()

        finally:
            await context.close()

        # Deduplicate by ASIN
        seen_asins = set()
        unique_products = []
        for p in all_products:
            asin = p.get("asin", "")
            if asin and asin not in seen_asins:
                seen_asins.add(asin)
                unique_products.append(p)

        return unique_products

    def _parse_search_results(self, html, category_key, keyword):
        """Parse search result page HTML into product dicts."""
        soup = BeautifulSoup(html, "lxml")
        products = []

        # Multiple selector strategies for search results
        result_items = soup.select('div[data-component-type="s-search-result"]')
        if not result_items:
            result_items = soup.select('.s-result-item[data-asin]')

        for item in result_items:
            try:
                product = self._parse_search_item(item, category_key, keyword)
                if product and product.get("asin"):
                    products.append(product)
            except Exception as e:
                logger.debug(f"Error parsing search item: {e}")

        return products

    def _parse_search_item(self, item, category_key, keyword):
        """Parse a single search result item."""
        product = {}

        # ASIN
        product["asin"] = item.get("data-asin", "").strip()
        if not product["asin"]:
            return None

        # Skip sponsored ads without real ASIN
        if product["asin"] == "":
            return None

        # Title - multiple selector fallback
        title_elem = (
            item.select_one('h2 a span')
            or item.select_one('h2 span')
            or item.select_one('.a-text-normal')
        )
        product["title"] = title_elem.get_text(strip=True) if title_elem else ""
        if not product["title"]:
            return None

        # Price
        price_whole = item.select_one('.a-price .a-price-whole')
        price_fraction = item.select_one('.a-price .a-price-fraction')
        if price_whole:
            whole = price_whole.get_text(strip=True).replace(',', '').replace('.', '')
            fraction = price_fraction.get_text(strip=True) if price_fraction else "00"
            try:
                product["price"] = float(f"{whole}.{fraction}")
            except ValueError:
                product["price"] = 0
        else:
            # Fallback: look for price in offscreen span
            price_elem = item.select_one('.a-price .a-offscreen')
            if price_elem:
                price_text = price_elem.get_text(strip=True).replace('$', '').replace(',', '')
                try:
                    product["price"] = float(price_text)
                except ValueError:
                    product["price"] = 0
            else:
                product["price"] = 0

        # Rating
        rating_elem = (
            item.select_one('i.a-icon-star-small span.a-icon-alt')
            or item.select_one('span.a-icon-alt')
        )
        if rating_elem:
            rating_text = rating_elem.get_text(strip=True)
            match = re.search(r'([\d.]+)', rating_text)
            product["rating"] = float(match.group(1)) if match else 0
        else:
            product["rating"] = 0

        # Review count
        review_elem = (
            item.select_one('span.a-size-base.s-underline-text')
            or item.select_one('a[href*="#customerReviews"] span')
            or item.select_one('.a-size-base[dir="auto"]')
        )
        if review_elem:
            review_text = review_elem.get_text(strip=True).replace(',', '')
            match = re.search(r'([\d]+)', review_text)
            product["review_count"] = int(match.group(1)) if match else 0
        else:
            product["review_count"] = 0

        # Brand - extract from search result "by BrandName" line
        brand_elem = (
            item.select_one('.a-row .a-size-base-plus.a-color-base')
            or item.select_one('.a-row .a-size-base.a-link-normal[href*="brandtextbin"]')
            or item.select_one('.a-row .a-size-base.a-link-normal[href*="/s?"]')
            or item.select_one('h2 + .a-row .a-size-base')
        )
        if brand_elem:
            brand_text = brand_elem.get_text(strip=True)
            # Clean up "by BrandName" prefix if present
            brand_text = re.sub(r'^by\s+', '', brand_text, flags=re.IGNORECASE)
            product["brand"] = brand_text.strip()
        else:
            product["brand"] = ""

        # Image
        img_elem = item.select_one('img.s-image')
        product["image_url"] = img_elem.get("src", "") if img_elem else ""

        # Prime badge (indicates FBA)
        prime_elem = (
            item.select_one('i.a-icon-prime')
            or item.select_one('.a-icon-prime')
            or item.select_one('[aria-label="Amazon Prime"]')
        )
        product["is_prime"] = prime_elem is not None

        # Product URL
        link_elem = item.select_one('h2 a') or item.select_one('a.a-link-normal[href*="/dp/"]')
        if link_elem:
            href = link_elem.get("href", "")
            if href.startswith("/"):
                href = "https://www.amazon.com" + href
            product["url"] = href
        else:
            product["url"] = f"https://www.amazon.com/dp/{product['asin']}"

        # Metadata
        product["category_key"] = category_key
        product["search_keyword"] = keyword
        product["scraped_at"] = datetime.now().isoformat()

        # Classify product type from title
        product["product_type"] = classify_product_type(product["title"])

        # Placeholders for detail page data (brand already extracted above)
        if not product.get("brand"):
            product["brand"] = ""
        product["bsr"] = 0
        product["bullet_points"] = []
        product["seller"] = ""
        product["is_fba"] = product["is_prime"]
        product["date_first_available"] = ""
        product["variations"] = 0
        product["category_breadcrumb"] = ""
        product["estimated_monthly_units"] = 0
        product["estimated_monthly_revenue"] = 0

        return product

    # ---- Phase 2: Detail Page Scraping ----

    async def scrape_detail_pages(self, products, category_key="default"):
        """
        Scrape detail pages for a list of products to get BSR, brand, etc.

        Args:
            products: List of product dicts (must have 'asin' field)
            category_key: Category for BSR estimation

        Returns:
            Updated product list with detail page data
        """
        if not products:
            return products

        consecutive_captchas = 0
        max_consecutive_captchas = 3
        rotate_every = 5  # Fresh proxy+context every N products

        proxy = None
        context = None

        try:
            for i, product in enumerate(products):
                asin = product.get("asin", "")
                if not asin:
                    continue

                # Rotate proxy and context periodically
                if context is None or (self.proxy_manager and i % rotate_every == 0):
                    if context:
                        await context.close()
                    proxy = self.proxy_manager.get_next_proxy() if self.proxy_manager else None
                    if proxy:
                        logger.info(f"Detail pages using proxy: {proxy.host}:{proxy.port}")
                    context_options = self._get_context_options(proxy)
                    context = await self.browser.new_context(**context_options)

                url = f"https://www.amazon.com/dp/{asin}"
                logger.info(f"Detail [{i+1}/{len(products)}]: {asin}")

                page = await context.new_page()
                await self._apply_stealth(page)

                try:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)

                    if response and response.status in (429, 503):
                        logger.warning(f"Rate limited on detail page ({response.status})")
                        await page.close()
                        consecutive_captchas += 1
                        if consecutive_captchas >= max_consecutive_captchas:
                            logger.warning(f"Hit {max_consecutive_captchas} consecutive blocks, stopping detail scraping")
                            break
                        # Force context rotation on next iteration
                        await context.close()
                        context = None
                        await asyncio.sleep(15)
                        continue

                    if await self._check_captcha(page):
                        await page.close()
                        consecutive_captchas += 1
                        if consecutive_captchas >= max_consecutive_captchas:
                            logger.warning(f"Hit {max_consecutive_captchas} consecutive CAPTCHAs, stopping detail scraping")
                            break
                        if proxy:
                            proxy.record_failure(is_block=True)
                        # Force context rotation on next iteration
                        await context.close()
                        context = None
                        await asyncio.sleep(10)
                        continue

                    # Wait for product detail content
                    try:
                        await page.wait_for_selector('#productTitle, #title', timeout=10000)
                    except Exception:
                        pass

                    html = await page.content()
                    detail = self._parse_detail_page(html)

                    # Merge detail data into product
                    for key, value in detail.items():
                        if value:  # Only update non-empty values
                            product[key] = value

                    # Re-classify product type with bullet points
                    if detail.get("bullet_points"):
                        product["product_type"] = classify_product_type(
                            product["title"], detail["bullet_points"]
                        )

                    self.request_count += 1
                    consecutive_captchas = 0

                    # Record proxy success
                    if proxy:
                        proxy.record_success()

                except Exception as e:
                    logger.error(f"Error on detail page {asin}: {e}")
                    if proxy:
                        proxy.record_failure()

                finally:
                    await page.close()

                # Decoy request periodically
                if self.request_count % self.decoy_interval == 0:
                    await self._do_decoy_request(context)

                # Delay between detail pages
                await self._random_delay()

        finally:
            if context:
                await context.close()

        return products

    def _parse_detail_page(self, html):
        """Parse Amazon product detail page HTML."""
        soup = BeautifulSoup(html, "lxml")
        detail = {}

        # Brand
        brand_elem = (
            soup.select_one('#bylineInfo')
            or soup.select_one('a#bylineInfo')
            or soup.select_one('.po-brand .a-span9 span')
        )
        if brand_elem:
            brand_text = brand_elem.get_text(strip=True)
            # Remove "Visit the X Store" or "Brand: X"
            brand_text = re.sub(r'^Visit the\s+', '', brand_text)
            brand_text = re.sub(r'\s+Store$', '', brand_text)
            brand_text = re.sub(r'^Brand:\s*', '', brand_text)
            detail["brand"] = brand_text.strip()

        # BSR - multiple formats
        bsr = 0

        # Format 1: Product details table
        detail_bullets = soup.select('#detailBulletsWrapper_feature_div li, #productDetails_detailBullets_sections1 tr')
        for elem in detail_bullets:
            text = elem.get_text()
            if 'Best Sellers Rank' in text or 'Amazon Best Sellers Rank' in text:
                bsr = parse_bsr_text(text)
                break

        # Format 2: Product information section
        if not bsr:
            product_info = soup.select('#productDetails_db_sections tr, .prodDetTable tr')
            for row in product_info:
                header = row.select_one('th, .prodDetSectionEntry')
                if header and 'Best Sellers Rank' in header.get_text():
                    value = row.select_one('td, .prodDetAttrValue')
                    if value:
                        bsr = parse_bsr_text(value.get_text())
                    break

        # Format 3: Direct search in page text
        if not bsr:
            rank_match = re.search(r'#([\d,]+)\s+in\s+[\w\s&]+\s*\(', soup.get_text())
            if rank_match:
                bsr = int(rank_match.group(1).replace(',', ''))

        detail["bsr"] = bsr

        # Bullet points
        bullets = []
        bullet_elems = soup.select('#feature-bullets ul li span.a-list-item')
        if not bullet_elems:
            bullet_elems = soup.select('#feature-bullets li')
        for elem in bullet_elems:
            text = elem.get_text(strip=True)
            if text and not text.startswith('Make sure') and len(text) > 5:
                bullets.append(text)
        detail["bullet_points"] = bullets

        # Seller / Sold by
        seller_elem = (
            soup.select_one('#sellerProfileTriggerId')
            or soup.select_one('#merchant-info a')
            or soup.select_one('.tabular-buybox-text[tabular-attribute-name="Sold by"] span')
        )
        detail["seller"] = seller_elem.get_text(strip=True) if seller_elem else ""

        # FBA - check "Ships from Amazon" or "Fulfilled by Amazon"
        ships_from = soup.select_one(
            '.tabular-buybox-text[tabular-attribute-name="Ships from"] span'
        )
        fulfilled_by = soup.select_one(
            '.tabular-buybox-text[tabular-attribute-name="Fulfilled by"] span'
        )
        is_fba = False
        if ships_from and "amazon" in ships_from.get_text(strip=True).lower():
            is_fba = True
        if fulfilled_by and "amazon" in fulfilled_by.get_text(strip=True).lower():
            is_fba = True
        # Also check for "Fulfilled by Amazon" in page text
        if not is_fba:
            fba_elem = soup.find(string=re.compile(r'Fulfilled by Amazon', re.IGNORECASE))
            if fba_elem:
                is_fba = True
        detail["is_fba"] = is_fba

        # Date first available
        date_elem = None
        for row in soup.select('#productDetails_detailBullets_sections1 tr, #detailBulletsWrapper_feature_div li'):
            text = row.get_text()
            if 'Date First Available' in text:
                # Extract the date value
                match = re.search(r'Date First Available\s*[:\-]?\s*(.+?)(?:\n|$)', text)
                if match:
                    date_elem = match.group(1).strip()
                break
        detail["date_first_available"] = date_elem or ""

        # Variation count
        variation_elems = soup.select('#twister_feature_div .a-dropdown-item, .swatchElement')
        detail["variations"] = len(variation_elems) if variation_elems else 0

        # Category breadcrumb
        breadcrumbs = soup.select('#wayfinding-breadcrumbs_feature_div a, .a-breadcrumb a')
        if breadcrumbs:
            detail["category_breadcrumb"] = " > ".join(
                [a.get_text(strip=True) for a in breadcrumbs]
            )
        else:
            detail["category_breadcrumb"] = ""

        return detail

    # ---- Full Pipeline ----

    async def scrape_keyword(self, category_key, keyword, max_pages=None):
        """
        Full pipeline: search + optional detail pages for one keyword.

        Args:
            category_key: Amazon category key
            keyword: Search keyword
            max_pages: Max search pages

        Returns:
            List of enriched product dicts
        """
        products = await self.scrape_search(category_key, keyword, max_pages)
        logger.info(f"Search complete: {len(products)} products for '{keyword}'")

        if self.detail_pages and products:
            products = await self.scrape_detail_pages(products, category_key)
            logger.info(f"Detail pages complete for '{keyword}'")

        return products

    def save_to_csv(self, products, filename):
        """Save products to CSV."""
        if not products:
            logger.warning("No products to save")
            return

        # Define column order
        fieldnames = [
            "asin", "title", "brand", "price", "rating", "review_count",
            "bsr", "is_prime", "is_fba", "product_type", "seller",
            "estimated_monthly_units", "estimated_monthly_revenue",
            "date_first_available", "variations", "category_breadcrumb",
            "category_key", "search_keyword", "url", "image_url", "scraped_at",
        ]

        # Include any extra fields not in fieldnames
        all_keys = set()
        for p in products:
            all_keys.update(p.keys())
        extra_keys = sorted(all_keys - set(fieldnames) - {"bullet_points"})
        fieldnames.extend(extra_keys)

        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for p in products:
                # Convert lists to strings for CSV
                row = dict(p)
                if "bullet_points" in row:
                    del row["bullet_points"]
                writer.writerow(row)

        logger.info(f"Saved {len(products)} products to {filename}")

    def save_to_json(self, products, filename):
        """Save products to JSON."""
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(products, f, indent=2, default=str)
        logger.info(f"Saved {len(products)} products to {filename}")
