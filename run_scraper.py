"""
Run the Yellow Pages scraper using settings from config.py
This is the main entry point for the scraper

Supports both sequential and parallel modes:
- Sequential: Single browser, one search at a time (default if WORKERS=1)
- Parallel: Multiple browser workers, much faster (default if WORKERS>1)
"""

import asyncio
import argparse
import os
import sys
from datetime import datetime
from yellowpages_scraper import YellowPagesScraper
from proxy_manager import ProxyManager, create_paid_proxy_pool
from parallel_scraper import run_parallel_scrape
import config


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Yellow Pages Scraper - Fast parallel business listing scraper',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with 10 workers and proxy file
  python run_scraper.py --workers 10 --proxies my_proxies.txt

  # Run in sequential mode (1 worker)
  python run_scraper.py --workers 1

  # Run headless with custom delay
  python run_scraper.py --headless --delay 3.0

  # Specify max pages per search
  python run_scraper.py --max-pages 10 --workers 5
        """
    )

    parser.add_argument(
        '-w', '--workers',
        type=int,
        default=None,
        help=f'Number of parallel workers (default: {getattr(config, "WORKERS", 5)})'
    )

    parser.add_argument(
        '-p', '--proxies',
        type=str,
        default=None,
        help='Path to proxy list file (one proxy per line)'
    )

    parser.add_argument(
        '--max-pages',
        type=int,
        default=None,
        help=f'Max pages per search (default: {config.MAX_PAGES_PER_SEARCH})'
    )

    parser.add_argument(
        '--delay',
        type=float,
        default=None,
        help=f'Delay between page loads in seconds (default: {config.DELAY_BETWEEN_PAGES})'
    )

    parser.add_argument(
        '--headless',
        action='store_true',
        default=None,
        help='Run browsers in headless mode'
    )

    parser.add_argument(
        '--no-validate',
        action='store_true',
        help='Skip proxy validation (faster startup)'
    )

    parser.add_argument(
        '--retries',
        type=int,
        default=None,
        help=f'Max retries for failed requests (default: {getattr(config, "MAX_RETRIES", 3)})'
    )

    return parser.parse_args()


async def run_parallel(proxy_manager):
    """Run scraper in parallel mode with multiple workers"""

    workers = getattr(config, 'WORKERS', 5)
    max_retries = getattr(config, 'MAX_RETRIES', 3)
    retry_delay = getattr(config, 'RETRY_DELAY', 5.0)

    print(f"\n  Mode: PARALLEL ({workers} workers)")
    print(f"  Max retries: {max_retries}")
    print(f"  Retry delay: {retry_delay}s (exponential backoff)")

    if proxy_manager:
        print(f"  Proxies: {len(proxy_manager.proxies)} available")
    print("=" * 60)

    # Run parallel scrape
    all_businesses, stats = await run_parallel_scrape(
        searches=config.SEARCH_CATEGORIES,
        workers=workers,
        max_pages=config.MAX_PAGES_PER_SEARCH,
        headless=config.HEADLESS_MODE,
        delay=config.DELAY_BETWEEN_PAGES,
        proxy_manager=proxy_manager,
        max_retries=max_retries,
        retry_delay=retry_delay
    )

    # Save results
    if all_businesses:
        scraper = YellowPagesScraper()  # Just for save methods

        # Save individual category results if configured
        if config.SAVE_INDIVIDUAL_CATEGORIES:
            # Group by category
            by_category = {}
            for business in all_businesses:
                cat = business.get('search_category', 'unknown')
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(business)

            for category, businesses in by_category.items():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                category_name = category.replace(' ', '_')
                filename = f"{category_name}_{timestamp}.csv"

                if config.OUTPUT_DIR:
                    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
                    filename = os.path.join(config.OUTPUT_DIR, filename)

                scraper.save_to_csv(businesses, filename)

        # Save combined results
        if config.SAVE_COMBINED_RESULTS:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"all_businesses_{timestamp}.csv"

            if config.OUTPUT_DIR:
                filename = os.path.join(config.OUTPUT_DIR, filename)

            scraper.save_to_csv(all_businesses, filename)

        # Filter and save eastern states
        if config.SAVE_EASTERN_STATES_ONLY:
            eastern_businesses = scraper.filter_eastern_states(all_businesses)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"eastern_businesses_{timestamp}.csv"

            if config.OUTPUT_DIR:
                filename = os.path.join(config.OUTPUT_DIR, filename)

            scraper.save_to_csv(eastern_businesses, filename)

    # Print summary
    print(f"\n{'='*60}")
    print("SCRAPING COMPLETE!")
    print(f"{'='*60}")
    print(f"Total tasks: {stats['total_tasks']}")
    print(f"Successful: {stats['completed_tasks'] - stats['failed_tasks']}")
    print(f"Failed: {stats['failed_tasks']}")
    print(f"Success rate: {stats['success_rate']:.1f}%")
    print(f"Total businesses: {stats['total_businesses']}")
    print(f"Duration: {stats['duration_seconds']:.1f}s")
    print(f"Speed: {stats['tasks_per_minute']:.1f} tasks/min")
    print(f"Workers used: {stats['workers_used']}")
    print(f"{'='*60}\n")

    return all_businesses


async def run_sequential(proxy_manager):
    """Run scraper in sequential mode (single browser)"""

    print(f"\n  Mode: SEQUENTIAL (1 worker)")
    print("=" * 60)

    scraper = YellowPagesScraper(
        headless=config.HEADLESS_MODE,
        delay=config.DELAY_BETWEEN_PAGES,
        proxy_manager=proxy_manager
    )

    try:
        await scraper.start_browser()

        all_businesses = []

        for i, category in enumerate(config.SEARCH_CATEGORIES, 1):
            print(f"\n{'='*60}")
            print(f"[{i}/{len(config.SEARCH_CATEGORIES)}] Scraping: {category['term']}")
            print(f"Location: {category['location']}")
            print(f"{'='*60}\n")

            businesses = await scraper.scrape_search(
                search_term=category['term'],
                location=category['location'],
                max_pages=config.MAX_PAGES_PER_SEARCH
            )

            for business in businesses:
                business['search_category'] = category['term']

            all_businesses.extend(businesses)
            print(f"Found {len(businesses)} businesses for '{category['term']}'")

            if config.SAVE_INDIVIDUAL_CATEGORIES:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                category_name = category['term'].replace(' ', '_')
                filename = f"{category_name}_{timestamp}.csv"

                if config.OUTPUT_DIR:
                    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
                    filename = os.path.join(config.OUTPUT_DIR, filename)

                scraper.save_to_csv(businesses, filename)

        if config.SAVE_COMBINED_RESULTS and all_businesses:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"all_businesses_{timestamp}.csv"

            if config.OUTPUT_DIR:
                filename = os.path.join(config.OUTPUT_DIR, filename)

            scraper.save_to_csv(all_businesses, filename)

        if config.SAVE_EASTERN_STATES_ONLY and all_businesses:
            eastern_businesses = scraper.filter_eastern_states(all_businesses)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"eastern_businesses_{timestamp}.csv"

            if config.OUTPUT_DIR:
                filename = os.path.join(config.OUTPUT_DIR, filename)

            scraper.save_to_csv(eastern_businesses, filename)
            print(f"{len(eastern_businesses)} businesses in eastern states")

        print(f"\n{'='*60}")
        print("SCRAPING COMPLETE!")
        print(f"{'='*60}")
        print(f"Total businesses found: {len(all_businesses)}")
        print(f"Categories scraped: {len(config.SEARCH_CATEGORIES)}")
        print(f"{'='*60}\n")

        return all_businesses

    finally:
        await scraper.close_browser()


async def main():
    """Main execution function using config settings"""

    args = parse_args()

    # Override config with command line args
    workers = args.workers if args.workers is not None else getattr(config, 'WORKERS', 5)
    headless = args.headless if args.headless is not None else config.HEADLESS_MODE
    delay = args.delay if args.delay is not None else config.DELAY_BETWEEN_PAGES
    max_pages = args.max_pages if args.max_pages is not None else config.MAX_PAGES_PER_SEARCH
    max_retries = args.retries if args.retries is not None else getattr(config, 'MAX_RETRIES', 3)
    validate_proxies = not args.no_validate and config.VALIDATE_PROXIES

    # Update config values for functions that read from config
    config.HEADLESS_MODE = headless
    config.DELAY_BETWEEN_PAGES = delay
    config.MAX_PAGES_PER_SEARCH = max_pages
    config.WORKERS = workers
    config.MAX_RETRIES = max_retries
    config.VALIDATE_PROXIES = validate_proxies

    print("=" * 60)
    print("Yellow Pages Scraper")
    print("=" * 60)
    print(f"\nConfiguration:")
    print(f"  Headless mode: {headless}")
    print(f"  Delay between pages: {delay}s")
    print(f"  Max pages per search: {max_pages}")
    print(f"  Categories to scrape: {len(config.SEARCH_CATEGORIES)}")
    print(f"  Workers: {workers}")
    print(f"  Max retries: {max_retries}")

    # Setup proxy manager if enabled
    proxy_manager = None
    proxy_file = args.proxies  # Command line proxy file takes priority

    if proxy_file:
        # Command line proxy file specified
        if not os.path.exists(proxy_file):
            print(f"\nERROR: Proxy file not found: {proxy_file}")
            return

        print(f"  Proxy mode: File-based ({proxy_file})")
        proxy_manager = ProxyManager.from_file(proxy_file, validate=False)

        if validate_proxies and proxy_manager.proxies:
            print(f"\nValidating {len(proxy_manager.proxies)} proxies...")
            await proxy_manager.validate_all_proxies()

            if not proxy_manager.proxies:
                print("\nERROR: No working proxies found!")
                return

        print(f"  Proxies loaded: {len(proxy_manager.proxies)}")

    elif config.USE_PAID_PROXY_SERVICE:
        print(f"  Proxy mode: Paid service")
        service = os.getenv('PROXY_SERVICE') or config.PROXY_SERVICE
        username = os.getenv('PROXY_USERNAME') or config.PROXY_USERNAME
        password = os.getenv('PROXY_PASSWORD') or config.PROXY_PASSWORD

        if not all([service, username, password]):
            print("\nERROR: Proxy service credentials not set!")
            print("Set environment variables:")
            print("  export PROXY_SERVICE='smartproxy'")
            print("  export PROXY_USERNAME='your-username'")
            print("  export PROXY_PASSWORD='your-password'")
            return

        # Create more proxy instances for parallel mode
        proxy_count = max(workers, 5)
        proxy_manager = create_paid_proxy_pool(
            service=service,
            username=username,
            password=password,
            count=proxy_count
        )
        print(f"  Service: {service} ({proxy_count} instances)")

    elif config.USE_PROXIES:
        print(f"  Proxy mode: File-based ({config.PROXY_FILE})")
        proxy_manager = ProxyManager.from_file(
            config.PROXY_FILE,
            validate=False
        )

        if validate_proxies and proxy_manager.proxies:
            print(f"\nValidating {len(proxy_manager.proxies)} proxies...")
            await proxy_manager.validate_all_proxies()

            if not proxy_manager.proxies:
                print("\nERROR: No working proxies found!")
                print(f"Check your {config.PROXY_FILE} file")
                return

        print(f"  Proxies loaded: {len(proxy_manager.proxies)}")

    else:
        print(f"  Proxy mode: None (may risk IP ban)")

    try:
        # Choose execution mode based on worker count
        if workers > 1:
            await run_parallel(proxy_manager)
        else:
            await run_sequential(proxy_manager)

    except KeyboardInterrupt:
        print("\n\nScraping interrupted by user")

    except Exception as e:
        print(f"\n\nError occurred: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
