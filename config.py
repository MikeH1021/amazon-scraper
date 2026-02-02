"""
Configuration file for Amazon Brand Scraper
Modify these settings to customize scraper behavior
"""

# Browser settings
HEADLESS_MODE = True  # Set to False to see browser activity
DELAY_BETWEEN_PAGES = 3.0  # Base seconds between page loads (higher for Amazon)
JITTER_MIN = 1.0  # Minimum random jitter added to delay
JITTER_MAX = 4.0  # Maximum random jitter added to delay

# Scraping settings
MAX_PAGES_PER_SEARCH = 3  # Maximum search result pages per keyword
TIMEOUT_MS = 30000  # Page load timeout in milliseconds
DETAIL_PAGES = True  # Scrape product detail pages for BSR/brand data

# Parallel processing settings (conservative for Amazon)
WORKERS = 5  # Number of parallel browser workers
MAX_RETRIES = 3  # Number of retries per failed request
RETRY_DELAY = 10.0  # Base delay for exponential backoff (seconds)
BROWSER_POOL_SIZE = 5  # Number of browser instances in pool
MAX_CONCURRENT_REQUESTS = 10  # Global max concurrent requests (semaphore cap)
DETAIL_PAGE_CONCURRENCY = 3  # Max concurrent detail page requests

# Anti-detection settings
CAPTCHA_PAUSE_SECONDS = 30  # Pause duration when CAPTCHA detected
DECOY_INTERVAL = 10  # Do a decoy request every N requests
STAGGER_DELAY = 2.0  # Max random delay factor before workers start
REQUEST_JITTER = 1.0  # Random jitter for request timing

# Default category and preset
DEFAULT_CATEGORY = "health"
DEFAULT_PRESET = "ally_nutra"

# Output settings
OUTPUT_FORMAT = "both"  # Options: csv, json, both
CHUNK_OUTPUT = False  # Set to True to output CSVs in chunks of 50k rows
CHUNK_SIZE = 50000  # Number of rows per chunk file

# Output directory (leave empty for current directory)
OUTPUT_DIR = ""

# Proxy settings (to avoid IP bans)
USE_PROXIES = True  # Set to True to enable proxy rotation
PROXY_FILE = "proxies.txt"  # Path to proxy list file
VALIDATE_PROXIES = False  # Validate proxies before use (slower startup)

# Paid proxy service settings (alternative to proxy file)
# Set these in environment variables for security:
# export PROXY_SERVICE="smartproxy"  # Options: brightdata, smartproxy, oxylabs, proxyrack
# export PROXY_USERNAME="your-username"
# export PROXY_PASSWORD="your-password"
USE_PAID_PROXY_SERVICE = False
PROXY_SERVICE = None  # Will be read from environment if USE_PAID_PROXY_SERVICE is True
PROXY_USERNAME = None  # Will be read from environment
PROXY_PASSWORD = None  # Will be read from environment
