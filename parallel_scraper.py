"""
Parallel Amazon Scraper with Worker Pool
High-performance scraping with browser pooling, proxy rotation, and retry logic
"""

import asyncio
import logging
import random
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from playwright.async_api import async_playwright, Browser, BrowserContext
from proxy_manager import ProxyManager, Proxy
from amazon_scraper import AmazonScraper

logger = logging.getLogger(__name__)


@dataclass
class ScrapeTask:
    """A single scrape task"""
    category_key: str
    keyword: str
    max_pages: int = 3
    detail_pages: bool = True
    task_id: int = 0


@dataclass
class ScrapeResult:
    """Result of a scrape task"""
    task: ScrapeTask
    products: List[Dict] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None
    retries: int = 0
    captchas_hit: int = 0


class BrowserPool:
    """Pool of browser instances for reuse"""

    def __init__(self, size: int, headless: bool = True):
        self.size = size
        self.headless = headless
        self.browsers: List[Browser] = []
        self.available: asyncio.Queue = asyncio.Queue()
        self.playwright = None
        self._initialized = False

    async def initialize(self):
        """Initialize the browser pool"""
        if self._initialized:
            return

        self.playwright = await async_playwright().start()

        logger.info(f"Initializing browser pool with {self.size} instances...")

        for i in range(self.size):
            browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                ]
            )
            self.browsers.append(browser)
            await self.available.put(browser)
            logger.debug(f"  Browser {i+1}/{self.size} initialized")

        self._initialized = True
        logger.info(f"Browser pool ready with {self.size} instances")

    async def acquire(self) -> Browser:
        """Get a browser from the pool"""
        return await self.available.get()

    async def release(self, browser: Browser):
        """Return a browser to the pool"""
        await self.available.put(browser)

    async def close(self):
        """Close all browsers and cleanup"""
        for browser in self.browsers:
            try:
                await browser.close()
            except Exception:
                pass

        if self.playwright:
            await self.playwright.stop()

        self.browsers = []
        self._initialized = False


class ParallelScraper:
    """
    High-performance parallel Amazon scraper with worker pool pattern

    Features:
    - Browser pooling (reuse browser instances)
    - Per-worker proxy assignment
    - Retry with exponential backoff
    - Progress tracking
    - CAPTCHA detection and handling
    - Detail page semaphore for rate limiting
    """

    def __init__(
        self,
        workers: int = 5,
        headless: bool = True,
        delay: float = 3.0,
        proxy_manager: Optional[ProxyManager] = None,
        max_retries: int = 3,
        retry_delay: float = 10.0,
        stagger_delay: float = 2.0,
        jitter: float = 1.0,
        max_concurrent_requests: int = 10,
        detail_page_concurrency: int = 3
    ):
        self.workers = workers
        self.headless = headless
        self.delay = delay
        self.proxy_manager = proxy_manager
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.stagger_delay = stagger_delay
        self.jitter = jitter
        self.max_concurrent_requests = max_concurrent_requests
        self.detail_page_concurrency = detail_page_concurrency

        self.browser_pool: Optional[BrowserPool] = None
        self.task_queue: asyncio.Queue = asyncio.Queue()
        self.results: List[ScrapeResult] = []
        self.results_lock = asyncio.Lock()

        # Global semaphore to limit concurrent requests
        self.request_semaphore: Optional[asyncio.Semaphore] = None
        # Detail page semaphore (stricter limit)
        self.detail_semaphore: Optional[asyncio.Semaphore] = None

        # Progress tracking
        self.total_tasks = 0
        self.completed_tasks = 0
        self.failed_tasks = 0
        self.total_products = 0
        self.total_captchas = 0
        self.current_phase = "initializing"
        self.progress_lock = asyncio.Lock()

        # Worker proxy assignment
        self.worker_proxies: Dict[int, Proxy] = {}

        # Stop signal
        self.should_stop = False

    def _assign_proxies_to_workers(self):
        """Assign dedicated proxies to each worker for better distribution"""
        if not self.proxy_manager or not self.proxy_manager.proxies:
            return

        proxies = [p for p in self.proxy_manager.proxies if not p.is_blocked]
        if not proxies:
            proxies = self.proxy_manager.proxies

        for worker_id in range(self.workers):
            proxy_index = worker_id % len(proxies)
            self.worker_proxies[worker_id] = proxies[proxy_index]
            logger.debug(f"Worker {worker_id} assigned proxy: {proxies[proxy_index].host}")

    async def _worker(self, worker_id: int):
        """Worker that processes tasks from the queue"""
        proxy = self.worker_proxies.get(worker_id)

        # Staggered startup
        startup_delay = random.uniform(0, self.stagger_delay * min(self.workers, 5) / 5)
        await asyncio.sleep(startup_delay)

        if proxy:
            logger.info(f"Worker {worker_id} starting with proxy {proxy.host}:{proxy.port}")
        else:
            logger.info(f"Worker {worker_id} starting without proxy")

        while not self.should_stop:
            try:
                try:
                    task = await asyncio.wait_for(self.task_queue.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    if self.task_queue.empty():
                        break
                    continue

                # Process the task with retries
                result = await self._process_task_with_retry(worker_id, task, proxy)

                # Store result
                async with self.results_lock:
                    self.results.append(result)

                # Update progress
                async with self.progress_lock:
                    self.completed_tasks += 1
                    if not result.success:
                        self.failed_tasks += 1
                    self.total_products += len(result.products)
                    self.total_captchas += result.captchas_hit

                    progress = (self.completed_tasks / self.total_tasks) * 100
                    status = "OK" if result.success else "FAIL"
                    logger.info(
                        f"[{self.completed_tasks}/{self.total_tasks}] ({progress:.1f}%) "
                        f"Worker {worker_id}: {task.keyword} - "
                        f"{status} ({len(result.products)} products)"
                    )

                self.task_queue.task_done()

            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")

    async def _process_task_with_retry(
        self,
        worker_id: int,
        task: ScrapeTask,
        proxy: Optional[Proxy]
    ) -> ScrapeResult:
        """Process a task with exponential backoff retry"""

        last_error = None
        captchas = 0

        for attempt in range(self.max_retries + 1):
            if self.should_stop:
                return ScrapeResult(task=task, products=[], success=False, error="Stopped by user")

            try:
                browser = await self.browser_pool.acquire()

                try:
                    products, task_captchas = await self._scrape_with_browser(
                        browser, task, proxy
                    )
                    captchas += task_captchas

                    if proxy:
                        proxy.record_success()

                    return ScrapeResult(
                        task=task,
                        products=products,
                        success=True,
                        retries=attempt,
                        captchas_hit=captchas
                    )

                finally:
                    await self.browser_pool.release(browser)

            except Exception as e:
                last_error = str(e)
                captchas += 1 if "captcha" in last_error.lower() else 0

                if proxy:
                    is_block = "429" in last_error or "403" in last_error or "captcha" in last_error.lower()
                    proxy.record_failure(is_block=is_block)

                    if is_block and self.proxy_manager:
                        new_proxy = self.proxy_manager.get_next_proxy()
                        if new_proxy and new_proxy != proxy:
                            proxy = new_proxy
                            self.worker_proxies[worker_id] = proxy
                            logger.info(f"Worker {worker_id} switched to proxy {proxy.host}")

                if attempt < self.max_retries:
                    wait_time = self.retry_delay * (2 ** attempt)
                    logger.warning(
                        f"Worker {worker_id}: Attempt {attempt + 1} failed for "
                        f"'{task.keyword}' - retrying in {wait_time}s"
                    )
                    await asyncio.sleep(wait_time)

        return ScrapeResult(
            task=task,
            products=[],
            success=False,
            error=last_error,
            retries=self.max_retries,
            captchas_hit=captchas
        )

    async def _scrape_with_browser(
        self,
        browser: Browser,
        task: ScrapeTask,
        proxy: Optional[Proxy]
    ) -> Tuple[List[Dict], int]:
        """Scrape using a browser from the pool. Returns (products, captcha_count)."""

        scraper = AmazonScraper(
            headless=self.headless,
            delay=self.delay,
            max_pages=task.max_pages,
            detail_pages=task.detail_pages,
        )

        # Use the pooled browser
        scraper.browser = browser

        if proxy and self.proxy_manager:
            scraper.proxy_manager = self.proxy_manager

        # Use semaphore for search pages
        async with self.request_semaphore:
            products = await scraper.scrape_search(
                category_key=task.category_key,
                keyword=task.keyword,
                max_pages=task.max_pages,
            )

        # Use detail semaphore for detail pages (stricter limit)
        if task.detail_pages and products:
            async with self.detail_semaphore:
                products = await scraper.scrape_detail_pages(
                    products, task.category_key
                )

        captchas = scraper.captcha_count
        return products, captchas

    async def scrape_all(
        self,
        tasks: List[Dict],
        max_pages: int = 3,
        detail_pages: bool = True
    ) -> Tuple[List[Dict], Dict]:
        """
        Scrape all tasks in parallel

        Args:
            tasks: List of {"category_key": str, "keyword": str} dicts
            max_pages: Max pages per search
            detail_pages: Whether to scrape detail pages

        Returns:
            Tuple of (all_products, stats_dict)
        """
        start_time = datetime.now()
        self.should_stop = False
        self.current_phase = "search"

        # Initialize browser pool
        pool_size = min(self.workers, len(tasks))
        self.browser_pool = BrowserPool(pool_size, self.headless)
        await self.browser_pool.initialize()

        # Initialize semaphores
        self.request_semaphore = asyncio.Semaphore(self.max_concurrent_requests)
        self.detail_semaphore = asyncio.Semaphore(self.detail_page_concurrency)
        logger.info(f"Rate limiting: max {self.max_concurrent_requests} concurrent, "
                    f"{self.detail_page_concurrency} detail page concurrent")

        # Assign proxies to workers
        self._assign_proxies_to_workers()

        # Create tasks
        self.total_tasks = len(tasks)
        self.completed_tasks = 0
        self.failed_tasks = 0
        self.total_products = 0
        self.total_captchas = 0
        self.results = []

        for i, task_dict in enumerate(tasks):
            scrape_task = ScrapeTask(
                category_key=task_dict.get('category_key', 'health'),
                keyword=task_dict['keyword'],
                max_pages=max_pages,
                detail_pages=detail_pages,
                task_id=i
            )
            await self.task_queue.put(scrape_task)

        logger.info(f"Starting {pool_size} workers to process {len(tasks)} tasks...")

        # Start workers
        workers = [
            asyncio.create_task(self._worker(i))
            for i in range(pool_size)
        ]

        # Wait for all tasks to complete
        await self.task_queue.join()

        # Stop workers
        for worker in workers:
            worker.cancel()

        await asyncio.gather(*workers, return_exceptions=True)

        # Cleanup
        await self.browser_pool.close()

        # Collect results
        all_products = []
        for result in self.results:
            for product in result.products:
                product['search_keyword'] = result.task.keyword
                product['category_key'] = result.task.category_key
            all_products.extend(result.products)

        # Calculate stats
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        stats = {
            'total_tasks': self.total_tasks,
            'completed_tasks': self.completed_tasks,
            'failed_tasks': self.failed_tasks,
            'success_rate': ((self.completed_tasks - self.failed_tasks) / self.total_tasks * 100) if self.total_tasks > 0 else 0,
            'total_products': len(all_products),
            'total_captchas': self.total_captchas,
            'duration_seconds': duration,
            'tasks_per_minute': (self.total_tasks / duration * 60) if duration > 0 else 0,
            'workers_used': pool_size
        }

        # Log proxy health if using proxies
        if self.proxy_manager:
            health = self.proxy_manager.get_health_report()
            stats['proxy_health'] = health
            logger.info(f"Proxy health: {health['available_proxies']}/{health['total_proxies']} available, "
                       f"{health['success_rate']*100:.1f}% success rate")

        return all_products, stats

    def stop(self):
        """Signal all workers to stop."""
        self.should_stop = True


async def run_parallel_scrape(
    searches: List[Dict],
    workers: int = 5,
    max_pages: int = 3,
    detail_pages: bool = True,
    headless: bool = True,
    delay: float = 3.0,
    proxy_manager: Optional[ProxyManager] = None,
    max_retries: int = 3,
    retry_delay: float = 10.0,
    stagger_delay: float = 2.0,
    jitter: float = 1.0,
    max_concurrent_requests: int = 10,
    detail_page_concurrency: int = 3
) -> Tuple[List[Dict], Dict]:
    """
    Convenience function to run parallel Amazon scraping

    Args:
        searches: List of {"category_key": str, "keyword": str} dicts
        workers: Number of parallel workers
        max_pages: Max pages per search
        detail_pages: Whether to scrape detail pages
        headless: Run browsers in headless mode
        delay: Delay between page loads
        proxy_manager: Optional ProxyManager for IP rotation
        max_retries: Number of retries for failed requests
        retry_delay: Base delay for exponential backoff
        stagger_delay: Max random delay factor before workers start
        jitter: Random jitter added to delays
        max_concurrent_requests: Max simultaneous requests across all workers
        detail_page_concurrency: Max concurrent detail page requests

    Returns:
        Tuple of (all_products, stats_dict)
    """
    scraper = ParallelScraper(
        workers=workers,
        headless=headless,
        delay=delay,
        proxy_manager=proxy_manager,
        max_retries=max_retries,
        retry_delay=retry_delay,
        stagger_delay=stagger_delay,
        jitter=jitter,
        max_concurrent_requests=max_concurrent_requests,
        detail_page_concurrency=detail_page_concurrency
    )

    return await scraper.scrape_all(searches, max_pages, detail_pages)
