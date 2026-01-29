# Yellow Pages Scraper - Current Issue Context

## Problem
The scraper's Playwright browser fails to launch with this error:
```
libXcomposite.so.1: cannot open shared object file: No such file or directory
```

## Root Cause
The VM is missing X11/GUI libraries that Chromium requires even in headless mode.

## Solution
Run ONE of these commands (requires sudo password):

**Option 1 - Install specific missing libs:**
```bash
sudo apt-get update && sudo apt-get install -y libxcomposite1 libxdamage1 libxrandr2 libgbm1 libxkbcommon0 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 libcups2 libdrm2 libgtk-3-0 libnss3 libxss1
```

**Option 2 - Let Playwright install all its deps:**
```bash
sudo npx playwright install-deps chromium
```

## Troubleshooting: Command Line Breaks
If you copy/paste Option 1 and it breaks across multiple lines, you may see errors like:
```
libxrandr2: command not found
libatspi2.0-0: command not found
```
This means only some packages were installed. Run the remaining packages:
```bash
sudo apt-get install -y libxrandr2 libgbm1 libxkbcommon0 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 libcups2 libdrm2 libgtk-3-0 libnss3 libxss1
```

Or just use Option 2 which is simpler and handles everything automatically.

## After Installing Dependencies
1. Start the web server: `python3 web_app.py`
2. Access at: http://192.168.1.115:5001/
3. The scraper should now work

## What Was Working
- Web UI loads fine at http://192.168.1.115:5001/
- 150 proxies auto-loaded from proxies.txt
- Scraper starts but browser crashes immediately due to missing libs

## Files
- `web_app.py` - Flask web UI (runs on port 5001)
- `yellowpages_scraper.py` - Main scraper using Playwright
- `proxy_manager.py` - Proxy rotation
- `proxies.txt` - 150 proxies loaded
