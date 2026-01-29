"""
Parallel Yellow Pages Scraper with Worker Pool
High-performance scraping with browser pooling, proxy rotation, and retry logic
"""

import asyncio
import logging
import random
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from playwright.async_api import async_playwright, Browser, BrowserContext
from proxy_manager import ProxyManager, Proxy
from yellowpages_scraper import YellowPagesScraper

logger = logging.getLogger(__name__)


@dataclass
class ScrapeTask:
    """A single scrape task"""
    search_term: str
    location: str
    max_pages: int = 5
    task_id: int = 0


@dataclass
class ScrapeResult:
    """Result of a scrape task"""
    task: ScrapeTask
    businesses: List[Dict]
    success: bool
    error: Optional[str] = None
    retries: int = 0


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
                args=['--disable-blink-features=AutomationControlled']
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
    High-performance parallel scraper with worker pool pattern

    Features:
    - Browser pooling (reuse browser instances)
    - Per-worker proxy assignment
    - Retry with exponential backoff
    - Progress tracking
    - Graceful error handling
    """

    def __init__(
        self,
        workers: int = 5,
        headless: bool = True,
        delay: float = 2.0,
        proxy_manager: Optional[ProxyManager] = None,
        max_retries: int = 3,
        retry_delay: float = 5.0,
        stagger_delay: float = 0.5,
        jitter: float = 0.5,
        max_concurrent_requests: int = 20
    ):
        self.workers = workers
        self.headless = headless
        self.delay = delay
        self.proxy_manager = proxy_manager
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.stagger_delay = stagger_delay  # Max random delay before worker starts
        self.jitter = jitter  # Random jitter added to delays (0-jitter seconds)
        self.max_concurrent_requests = max_concurrent_requests

        self.browser_pool: Optional[BrowserPool] = None
        self.task_queue: asyncio.Queue = asyncio.Queue()
        self.results: List[ScrapeResult] = []
        self.results_lock = asyncio.Lock()

        # Global semaphore to limit concurrent requests
        self.request_semaphore: Optional[asyncio.Semaphore] = None

        # Progress tracking
        self.total_tasks = 0
        self.completed_tasks = 0
        self.failed_tasks = 0
        self.progress_lock = asyncio.Lock()

        # Worker proxy assignment
        self.worker_proxies: Dict[int, Proxy] = {}

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

        # Staggered startup: random delay before worker begins processing
        startup_delay = random.uniform(0, self.stagger_delay * self.workers / 10)
        await asyncio.sleep(startup_delay)

        if proxy:
            logger.info(f"Worker {worker_id} starting with proxy {proxy.host}:{proxy.port} (delayed {startup_delay:.1f}s)")
        else:
            logger.info(f"Worker {worker_id} starting without proxy (delayed {startup_delay:.1f}s)")

        while True:
            try:
                # Get task from queue (with timeout to allow graceful shutdown)
                try:
                    task = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Check if all tasks are done
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

                    progress = (self.completed_tasks / self.total_tasks) * 100
                    status = "OK" if result.success else "FAIL"
                    logger.info(
                        f"[{self.completed_tasks}/{self.total_tasks}] ({progress:.1f}%) "
                        f"Worker {worker_id}: {task.search_term} in {task.location} - "
                        f"{status} ({len(result.businesses)} businesses)"
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

        for attempt in range(self.max_retries + 1):
            try:
                # Acquire browser from pool
                browser = await self.browser_pool.acquire()

                try:
                    businesses = await self._scrape_with_browser(browser, task, proxy)

                    # Record success if using proxy
                    if proxy:
                        proxy.record_success()

                    return ScrapeResult(
                        task=task,
                        businesses=businesses,
                        success=True,
                        retries=attempt
                    )

                finally:
                    # Always release browser back to pool
                    await self.browser_pool.release(browser)

            except Exception as e:
                last_error = str(e)

                # Record failure if using proxy
                if proxy:
                    is_block = "429" in last_error or "403" in last_error
                    proxy.record_failure(is_block=is_block)

                    # If blocked, try to get a different proxy
                    if is_block and self.proxy_manager:
                        new_proxy = self.proxy_manager.get_next_proxy()
                        if new_proxy and new_proxy != proxy:
                            proxy = new_proxy
                            self.worker_proxies[worker_id] = proxy
                            logger.info(f"Worker {worker_id} switched to proxy {proxy.host}")

                if attempt < self.max_retries:
                    # Exponential backoff
                    wait_time = self.retry_delay * (2 ** attempt)
                    logger.warning(
                        f"Worker {worker_id}: Attempt {attempt + 1} failed for "
                        f"'{task.search_term}' - retrying in {wait_time}s"
                    )
                    await asyncio.sleep(wait_time)

        return ScrapeResult(
            task=task,
            businesses=[],
            success=False,
            error=last_error,
            retries=self.max_retries
        )

    async def _scrape_with_browser(
        self,
        browser: Browser,
        task: ScrapeTask,
        proxy: Optional[Proxy]
    ) -> List[Dict]:
        """Scrape using a browser from the pool"""

        # Create scraper instance (shares browser)
        scraper = YellowPagesScraper(
            headless=self.headless,
            delay=self.delay
        )

        # Use the pooled browser
        scraper.browser = browser

        # Create context with proxy if available
        context_options = {
            'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

        if proxy:
            context_options['proxy'] = proxy.to_playwright_dict()

        context = await browser.new_context(**context_options)
        page = await context.new_page()

        businesses = []

        try:
            for page_num in range(1, task.max_pages + 1):
                url = scraper._build_url(task.search_term, task.location, page_num)

                # Use semaphore to limit concurrent requests globally
                async with self.request_semaphore:
                    response = await page.goto(url, wait_until='networkidle', timeout=30000)

                    # Check for rate limiting
                    if response:
                        status = response.status
                        if status == 429:
                            raise Exception(f"Rate limited (429) on page {page_num}")
                        elif status == 403:
                            raise Exception(f"Forbidden (403) on page {page_num}")

                # Add jitter to delay to prevent synchronized requests
                jittered_delay = self.delay + random.uniform(0, self.jitter)
                await asyncio.sleep(jittered_delay)

                page_businesses = await scraper._extract_businesses(page)

                if not page_businesses:
                    break

                businesses.extend(page_businesses)

        finally:
            await context.close()

        return businesses

    async def scrape_all(
        self,
        tasks: List[Dict],
        max_pages: int = 5
    ) -> Tuple[List[Dict], Dict]:
        """
        Scrape all tasks in parallel

        Args:
            tasks: List of {"term": str, "location": str} dicts
            max_pages: Max pages per search

        Returns:
            Tuple of (all_businesses, stats_dict)
        """
        start_time = datetime.now()

        # Initialize browser pool
        pool_size = min(self.workers, len(tasks))
        self.browser_pool = BrowserPool(pool_size, self.headless)
        await self.browser_pool.initialize()

        # Initialize global request semaphore to limit concurrent requests
        self.request_semaphore = asyncio.Semaphore(self.max_concurrent_requests)
        logger.info(f"Rate limiting: max {self.max_concurrent_requests} concurrent requests")

        # Assign proxies to workers
        self._assign_proxies_to_workers()

        # Create tasks
        self.total_tasks = len(tasks)
        self.completed_tasks = 0
        self.failed_tasks = 0
        self.results = []

        for i, task_dict in enumerate(tasks):
            scrape_task = ScrapeTask(
                search_term=task_dict['term'],
                location=task_dict['location'],
                max_pages=max_pages,
                task_id=i
            )
            await self.task_queue.put(scrape_task)

        logger.info(f"Starting {self.workers} workers to process {len(tasks)} tasks...")

        # Start workers
        workers = [
            asyncio.create_task(self._worker(i))
            for i in range(min(self.workers, len(tasks)))
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
        all_businesses = []
        for result in self.results:
            for business in result.businesses:
                business['search_category'] = result.task.search_term
            all_businesses.extend(result.businesses)

        # Calculate stats
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        stats = {
            'total_tasks': self.total_tasks,
            'completed_tasks': self.completed_tasks,
            'failed_tasks': self.failed_tasks,
            'success_rate': ((self.completed_tasks - self.failed_tasks) / self.total_tasks * 100) if self.total_tasks > 0 else 0,
            'total_businesses': len(all_businesses),
            'duration_seconds': duration,
            'tasks_per_minute': (self.total_tasks / duration * 60) if duration > 0 else 0,
            'workers_used': min(self.workers, len(tasks))
        }

        # Log proxy health if using proxies
        if self.proxy_manager:
            health = self.proxy_manager.get_health_report()
            stats['proxy_health'] = health
            logger.info(f"Proxy health: {health['available_proxies']}/{health['total_proxies']} available, "
                       f"{health['success_rate']*100:.1f}% success rate")

        return all_businesses, stats


async def run_parallel_scrape(
    searches: List[Dict],
    workers: int = 5,
    max_pages: int = 5,
    headless: bool = True,
    delay: float = 2.0,
    proxy_manager: Optional[ProxyManager] = None,
    max_retries: int = 3,
    retry_delay: float = 5.0,
    stagger_delay: float = 0.5,
    jitter: float = 0.5,
    max_concurrent_requests: int = 20
) -> Tuple[List[Dict], Dict]:
    """
    Convenience function to run parallel scraping

    Args:
        searches: List of {"term": str, "location": str} dicts
        workers: Number of parallel workers
        max_pages: Max pages per search
        headless: Run browsers in headless mode
        delay: Delay between page loads
        proxy_manager: Optional ProxyManager for IP rotation
        max_retries: Number of retries for failed requests
        retry_delay: Base delay for exponential backoff
        stagger_delay: Max random delay factor before workers start
        jitter: Random jitter (0 to jitter seconds) added to delays
        max_concurrent_requests: Max simultaneous requests across all workers

    Returns:
        Tuple of (all_businesses, stats_dict)
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
        max_concurrent_requests=max_concurrent_requests
    )

    return await scraper.scrape_all(searches, max_pages)
