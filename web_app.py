"""
Web UI for Amazon Brand Scraper
Interface for configuring and running Amazon product/brand research with real-time monitoring
"""

from flask import Flask, render_template, request, jsonify, Response, send_file, redirect, url_for, flash
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import asyncio
import json
import os
import threading
from datetime import datetime
from queue import Queue
import time
import math
import csv
import zipfile
from io import BytesIO
import pandas as pd
import sqlite3

from amazon_scraper import AmazonScraper
from amazon_categories import get_all_categories, get_category
from amazon_presets import get_all_presets, get_preset_full
from amazon_filters import ProductFilter
from bsr_calculator import estimate_monthly_sales, estimate_monthly_revenue
from brand_aggregator import BrandAggregator
from proxy_manager import ProxyManager

app = Flask(__name__, static_folder='static')
app.secret_key = os.environ.get('SECRET_KEY', 'amazon-scraper-secret-key-change-in-production')
CORS(app)

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

# Database setup
DATABASE = 'users.db'

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database with users, settings, and scrape_configs tables"""
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS scrape_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            config_json TEXT NOT NULL,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()

    # Create default admin user if not exists
    try:
        cursor = conn.execute('SELECT * FROM users WHERE username = ?', ('mike',))
        if cursor.fetchone() is None:
            password_hash = generate_password_hash('102134Mh@')
            conn.execute(
                'INSERT OR IGNORE INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)',
                ('mike', password_hash, True)
            )
            conn.commit()
            print("Created default admin user: mike")
    except Exception as e:
        print(f"Note: Admin user may already exist: {e}")

    conn.close()

def get_setting(key, default=None):
    """Get a setting value from the database"""
    conn = get_db()
    cursor = conn.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    return row['value'] if row else default

def set_setting(key, value):
    """Set a setting value in the database"""
    conn = get_db()
    conn.execute('''
        INSERT OR REPLACE INTO settings (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
    ''', (key, value))
    conn.commit()
    conn.close()

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, id, username, password_hash, is_admin):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.is_admin = is_admin

    @staticmethod
    def get_by_id(user_id):
        conn = get_db()
        cursor = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return User(row['id'], row['username'], row['password_hash'], row['is_admin'])
        return None

    @staticmethod
    def get_by_username(username):
        conn = get_db()
        cursor = conn.execute('SELECT * FROM users WHERE username = ?', (username,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return User(row['id'], row['username'], row['password_hash'], row['is_admin'])
        return None

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return User.get_by_id(int(user_id))

# Initialize database on startup
init_db()

# File-based state for multi-worker support
STATE_FILE = "/tmp/amazon_scraper_state.json"
LOG_FILE = "/tmp/amazon_scraper_logs.json"

def get_shared_state():
    """Read shared state from file with retry logic"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r') as f:
                    content = f.read()
                    if content.strip():
                        return json.loads(content)
        except (json.JSONDecodeError, IOError) as e:
            if attempt < max_retries - 1:
                time.sleep(0.1)
                continue
            print(f"Error reading state file (attempt {attempt + 1}): {e}")
        except Exception as e:
            print(f"Unexpected error reading state: {e}")

    return {
        "running": False,
        "progress": {},
        "last_output_file": None,
        "output_files": [],
        "phase": "idle"
    }

def set_shared_state(state):
    """Write shared state to file atomically with fsync"""
    temp_file = STATE_FILE + '.tmp'
    try:
        with open(temp_file, 'w') as f:
            json.dump(state, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, STATE_FILE)
    except Exception as e:
        print(f"Error saving state: {e}")
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except:
            pass

def add_log_entry(entry):
    """Add a log entry to the shared log file"""
    try:
        logs = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r') as f:
                logs = json.load(f)
        logs.append(entry)
        if len(logs) > 500:
            logs = logs[-500:]
        with open(LOG_FILE, 'w') as f:
            json.dump(logs, f)
    except:
        pass

def get_log_entries(after_index=0):
    """Get log entries after a certain index"""
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r') as f:
                logs = json.load(f)
                return logs[after_index:]
    except:
        pass
    return []

def clear_logs():
    """Clear all log entries"""
    try:
        with open(LOG_FILE, 'w') as f:
            json.dump([], f)
    except:
        pass

# Global state
scraper_state = {
    "running": False,
    "progress": {},
    "log_queue": Queue(),
    "proxy_manager": None,
    "current_scraper": None,
    "last_output_file": None,
    "output_files": [],
    "phase": "idle"
}

# Auto-load proxies on startup
def load_proxies_on_startup():
    """Load proxies from proxies.txt if it exists"""
    proxy_file = "proxies.txt"
    if os.path.exists(proxy_file):
        scraper_state["proxy_manager"] = ProxyManager.from_file(proxy_file, validate=False)
        print(f"Auto-loaded {len(scraper_state['proxy_manager'].proxies)} proxies from {proxy_file}")

# Daily cleanup scheduler
def cleanup_old_results():
    """Delete result files older than 1 day"""
    try:
        deleted = 0
        now = time.time()
        one_day_ago = now - (24 * 60 * 60)

        for file in os.listdir('.'):
            is_result = (
                (file.startswith('products_') and file.endswith('.csv'))
                or (file.startswith('brands_') and file.endswith('.csv'))
                or (file.startswith('results_') and file.endswith('.json'))
                or (file.startswith('scrape_results_') and file.endswith('.csv'))
            )
            if is_result:
                file_mtime = os.path.getmtime(file)
                if file_mtime < one_day_ago:
                    os.remove(file)
                    deleted += 1
                    print(f"Auto-cleanup: deleted {file}")

        if deleted > 0:
            print(f"Auto-cleanup: removed {deleted} old result file(s)")
    except Exception as e:
        print(f"Auto-cleanup error: {e}")

def start_cleanup_scheduler():
    """Start background thread for daily cleanup"""
    import time as time_module

    def scheduler_loop():
        while True:
            cleanup_old_results()
            time_module.sleep(24 * 60 * 60)

    cleanup_thread = threading.Thread(target=scheduler_loop, daemon=True)
    cleanup_thread.start()
    print("Auto-cleanup scheduler started (runs every 24 hours)")

load_proxies_on_startup()
start_cleanup_scheduler()


class WebLogger:
    """Logger that pushes to web UI via file-based shared state"""
    def __init__(self, log_queue=None):
        self.log_queue = log_queue

    def _add_log(self, level, message):
        entry = {
            "level": level,
            "message": message,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }
        add_log_entry(entry)
        if self.log_queue:
            self.log_queue.put(entry)

    def info(self, message):
        self._add_log("info", message)

    def error(self, message):
        self._add_log("error", message)

    def success(self, message):
        self._add_log("success", message)


# ============================================================
# Page Routes
# ============================================================

@app.route('/')
@login_required
def index():
    """Main scraper interface"""
    return render_template('scraper.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.get_by_username(username)
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page if next_page else url_for('index'))
        else:
            flash('Invalid username or password', 'error')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """Logout user"""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/admin')
@login_required
def admin():
    """Admin page for user management"""
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('index'))

    conn = get_db()
    cursor = conn.execute('SELECT id, username, is_admin, created_at FROM users ORDER BY created_at')
    users = cursor.fetchall()
    conn.close()

    return render_template('admin.html', users=users)

@app.route('/admin/add-user', methods=['POST'])
@login_required
def add_user():
    """Add a new user"""
    if not current_user.is_admin:
        return jsonify({'error': 'Access denied'}), 403

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    is_admin = request.form.get('is_admin') == 'on'

    if not username or not password:
        flash('Username and password are required', 'error')
        return redirect(url_for('admin'))

    if len(password) < 6:
        flash('Password must be at least 6 characters', 'error')
        return redirect(url_for('admin'))

    existing = User.get_by_username(username)
    if existing:
        flash('Username already exists', 'error')
        return redirect(url_for('admin'))

    try:
        conn = get_db()
        password_hash = generate_password_hash(password)
        conn.execute(
            'INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)',
            (username, password_hash, is_admin)
        )
        conn.commit()
        conn.close()
        flash(f'User "{username}" created successfully', 'success')
    except Exception as e:
        flash(f'Error creating user: {str(e)}', 'error')

    return redirect(url_for('admin'))

@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    """Delete a user"""
    if not current_user.is_admin:
        return jsonify({'error': 'Access denied'}), 403

    if user_id == current_user.id:
        flash('Cannot delete your own account', 'error')
        return redirect(url_for('admin'))

    try:
        conn = get_db()
        conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
        conn.close()
        flash('User deleted successfully', 'success')
    except Exception as e:
        flash(f'Error deleting user: {str(e)}', 'error')

    return redirect(url_for('admin'))

@app.route('/settings')
@login_required
def settings():
    """Settings page for API keys and configuration"""
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('index'))

    openai_key = get_setting('openai_api_key', '')
    masked_key = ''
    if openai_key:
        masked_key = openai_key[:8] + '...' + openai_key[-4:] if len(openai_key) > 12 else '***'

    return render_template('settings.html', openai_key_masked=masked_key, has_openai_key=bool(openai_key))

@app.route('/settings/save', methods=['POST'])
@login_required
def save_settings():
    """Save settings"""
    if not current_user.is_admin:
        return jsonify({'error': 'Access denied'}), 403

    openai_key = request.form.get('openai_api_key', '').strip()

    if openai_key:
        set_setting('openai_api_key', openai_key)
        flash('Settings saved successfully', 'success')
    else:
        flash('No changes made', 'info')

    return redirect(url_for('settings'))


@app.route('/api/ai-suggestions', methods=['POST'])
@login_required
def ai_suggestions():
    """Get AI-powered keyword and category suggestions from OpenAI"""
    try:
        import requests as req

        data = request.json
        icp = data.get('icp', '').strip()

        if not icp:
            return jsonify({"error": "Please provide a product research goal"}), 400

        api_key = get_setting('openai_api_key')
        if not api_key:
            return jsonify({"error": "OpenAI API key not configured. Please add it in Settings."}), 400

        # Get available category keys for context
        from amazon_categories import get_all_categories
        available_cats = list(get_all_categories().keys())

        prompt = f"""Based on the following Amazon product research goal, suggest search keywords and Amazon categories to scrape.

Research Goal: {icp}

Available Amazon categories: {', '.join(available_cats)}

Provide your response in this exact JSON format:
{{
    "keywords": ["keyword1", "keyword2", ...],
    "categories": ["category_key1", "category_key2", ...]
}}

Rules:
- Keywords should be Amazon product search terms (e.g., "ashwagandha supplement", "turmeric curcumin", "resistance bands")
- Provide up to 30 relevant keywords
- Categories must be from the available categories list above
- Provide 1-5 matching categories
- Focus on keywords that would reveal competitive landscape and brand opportunities
- Only return the JSON object, no other text"""

        response = req.post(
            'https://api.openai.com/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            json={
                'model': 'gpt-4o-mini',
                'messages': [
                    {'role': 'system', 'content': 'You are a helpful assistant that provides Amazon product research suggestions. Always respond with valid JSON only.'},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.7,
                'max_tokens': 2000
            },
            timeout=60
        )

        if response.status_code != 200:
            error_msg = response.json().get('error', {}).get('message', 'Unknown error')
            return jsonify({"error": f"OpenAI API error: {error_msg}"}), 500

        result = response.json()
        content = result['choices'][0]['message']['content'].strip()

        # Parse JSON from response (handle markdown code blocks)
        if content.startswith('```'):
            content = content.split('```')[1]
            if content.startswith('json'):
                content = content[4:]
        content = content.strip()

        suggestions = json.loads(content)

        keywords = suggestions.get('keywords', [])
        categories = suggestions.get('categories', [])

        if not isinstance(keywords, list):
            keywords = []
        if not isinstance(categories, list):
            categories = []

        # Validate categories against available ones
        categories = [c for c in categories if c in available_cats]

        return jsonify({
            "success": True,
            "keywords": keywords,
            "categories": categories,
            "keyword_count": len(keywords),
            "category_count": len(categories)
        })

    except json.JSONDecodeError as e:
        return jsonify({"error": f"Failed to parse AI response: {str(e)}"}), 500
    except Exception as e:
        if 'Timeout' in str(type(e).__name__):
            return jsonify({"error": "OpenAI API request timed out. Please try again."}), 500
        return jsonify({"error": str(e)}), 500


# ============================================================
# Amazon-specific API Routes
# ============================================================

@app.route('/api/categories')
@login_required
def api_categories():
    """Get all Amazon categories and subcategories"""
    return jsonify(get_all_categories())

@app.route('/api/presets')
@login_required
def api_presets():
    """Get list of available presets"""
    return jsonify(get_all_presets())

@app.route('/api/preset/<name>')
@login_required
def api_preset(name):
    """Get full preset configuration"""
    preset = get_preset_full(name)
    if not preset:
        return jsonify({"error": "Preset not found"}), 404
    return jsonify(preset)

@app.route('/api/save-config', methods=['POST'])
@login_required
def save_config():
    """Save a scrape configuration"""
    try:
        data = request.json
        name = data.get('name', '').strip()
        if not name:
            return jsonify({"error": "Configuration name is required"}), 400

        config_json = json.dumps(data.get('config', {}))

        conn = get_db()
        conn.execute('''
            INSERT OR REPLACE INTO scrape_configs (name, config_json, created_by, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ''', (name, config_json, current_user.username))
        conn.commit()
        conn.close()

        return jsonify({"success": True, "message": f"Configuration '{name}' saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/load-config/<name>')
@login_required
def load_config(name):
    """Load a saved scrape configuration"""
    try:
        conn = get_db()
        cursor = conn.execute('SELECT config_json FROM scrape_configs WHERE name = ?', (name,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return jsonify({"error": "Configuration not found"}), 404

        config = json.loads(row['config_json'])
        return jsonify({"success": True, "config": config})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/list-configs')
@login_required
def list_configs():
    """List all saved configurations"""
    try:
        conn = get_db()
        cursor = conn.execute('SELECT name, created_by, created_at, updated_at FROM scrape_configs ORDER BY updated_at DESC')
        configs = [{"name": r['name'], "created_by": r['created_by'],
                    "created_at": r['created_at'], "updated_at": r['updated_at']}
                   for r in cursor.fetchall()]
        conn.close()
        return jsonify({"configs": configs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/delete-config/<name>', methods=['DELETE'])
@login_required
def delete_config(name):
    """Delete a saved configuration"""
    try:
        conn = get_db()
        conn.execute('DELETE FROM scrape_configs WHERE name = ?', (name,))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": f"Configuration '{name}' deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/preview-results')
@login_required
def preview_results():
    """Preview the latest scrape results (brand-level summary)"""
    try:
        shared = get_shared_state()
        output_files = shared.get("output_files", [])

        # Try to find the brands CSV
        brands_file = None
        for f in output_files:
            if f.startswith('brands_') and f.endswith('.csv'):
                brands_file = f
                break

        if not brands_file or not os.path.exists(brands_file):
            return jsonify({"brands": [], "total": 0})

        # Read the brands CSV
        brands = []
        with open(brands_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                brands.append(row)

        return jsonify({"brands": brands[:100], "total": len(brands)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# Proxy Routes
# ============================================================

@app.route('/api/upload-proxies', methods=['POST'])
@login_required
def upload_proxies():
    """Handle proxy file upload"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400

        file.save('proxies.txt')
        scraper_state["proxy_manager"] = ProxyManager.from_file('proxies.txt', validate=False)
        proxy_count = len(scraper_state["proxy_manager"].proxies)

        return jsonify({
            "success": True,
            "proxy_count": proxy_count,
            "message": f"Loaded {proxy_count} proxies"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/proxy-status')
@login_required
def proxy_status():
    """Get current proxy health status"""
    if not scraper_state["proxy_manager"]:
        return jsonify({"proxies": []})

    proxies = []
    for proxy in scraper_state["proxy_manager"].proxies:
        proxies.append({
            "host": proxy.host,
            "port": proxy.port,
            "success_count": proxy.success_count,
            "fail_count": proxy.fail_count,
            "success_rate": proxy.get_success_rate(),
            "is_blocked": proxy.is_blocked,
            "last_used": proxy.last_used.strftime("%H:%M:%S") if proxy.last_used else "Never"
        })

    return jsonify({"proxies": proxies})


# ============================================================
# Scrape Control Routes
# ============================================================

@app.route('/api/start-scrape', methods=['POST'])
@login_required
def start_scrape():
    """Start a new Amazon scraping job"""
    try:
        data = request.json

        # Parse inputs
        categories = data.get('categories', ['health'])
        keywords_raw = data.get('keywords', '')
        if isinstance(keywords_raw, str):
            keywords = [k.strip() for k in keywords_raw.split('\n') if k.strip()]
            if not keywords:
                keywords = [k.strip() for k in keywords_raw.split(',') if k.strip()]
        else:
            keywords = keywords_raw

        if not keywords:
            return jsonify({"error": "Please provide at least one keyword"}), 400

        max_pages = int(data.get('max_pages', 3))
        detail_pages = data.get('detail_pages', True)
        use_proxies = data.get('use_proxies', True)
        concurrent = int(data.get('concurrent', 3))
        output_format = data.get('output_format', 'both')
        filters_config = data.get('filters', {})

        # Build search list: each keyword x each category
        searches = []
        for keyword in keywords:
            for cat_key in categories:
                searches.append({
                    "category_key": cat_key,
                    "keyword": keyword,
                })

        # Update state
        scraper_state["running"] = True
        scraper_state["phase"] = "search"
        scraper_state["progress"] = {
            "total_searches": len(searches),
            "completed": 0,
            "products_found": 0,
            "brands_found": 0,
            "captchas_hit": 0,
            "phase": "search",
        }
        scraper_state["output_files"] = []

        set_shared_state({
            "running": True,
            "progress": scraper_state["progress"],
            "last_output_file": None,
            "output_files": [],
            "phase": "search"
        })

        clear_logs()

        while not scraper_state["log_queue"].empty():
            scraper_state["log_queue"].get()

        # Start scraper in background thread
        thread = threading.Thread(
            target=run_scraper_async,
            args=(searches, max_pages, detail_pages, use_proxies, concurrent,
                  output_format, filters_config, categories)
        )
        thread.daemon = True
        thread.start()

        return jsonify({
            "success": True,
            "total_searches": len(searches),
            "message": f"Started scraping {len(searches)} searches ({len(keywords)} keywords x {len(categories)} categories)"
        })

    except Exception as e:
        scraper_state["running"] = False
        return jsonify({"error": str(e)}), 500

@app.route('/api/stop-scrape', methods=['POST'])
@login_required
def stop_scrape():
    """Stop current scraping job"""
    scraper_state["running"] = False
    scraper_state["phase"] = "idle"
    if scraper_state.get("current_scraper"):
        try:
            scraper_state["current_scraper"].should_stop = True
        except:
            pass
    shared = get_shared_state()
    shared["running"] = False
    shared["phase"] = "idle"
    set_shared_state(shared)
    return jsonify({"success": True, "message": "Scraper stopped"})

@app.route('/api/progress')
@login_required
def get_progress():
    """Get current scraping progress from shared state"""
    shared = get_shared_state()
    return jsonify({
        "running": shared.get("running", False),
        "progress": shared.get("progress", {}),
        "phase": shared.get("phase", "idle"),
        "last_output_file": shared.get("last_output_file"),
        "output_files": shared.get("output_files", [])
    })


# ============================================================
# Download & Results Routes
# ============================================================

@app.route('/api/download')
@login_required
def download_results():
    """Download a specific result file"""
    try:
        filename = request.args.get('file')
        if not filename:
            output_file = scraper_state.get("last_output_file")
            if not output_file:
                return jsonify({"error": "No results available"}), 404
            filename = output_file

        # Security: validate filename pattern
        valid_prefixes = ('products_', 'brands_', 'results_', 'scrape_results_')
        valid_suffixes = ('.csv', '.json', '.zip')
        if not any(filename.startswith(p) for p in valid_prefixes):
            return jsonify({"error": "Invalid filename"}), 400
        if not any(filename.endswith(s) for s in valid_suffixes):
            return jsonify({"error": "Invalid file type"}), 400

        if not os.path.exists(filename):
            return jsonify({"error": "File not found"}), 404

        mimetype = 'text/csv'
        if filename.endswith('.json'):
            mimetype = 'application/json'
        elif filename.endswith('.zip'):
            mimetype = 'application/zip'

        return send_file(
            filename,
            as_attachment=True,
            download_name=os.path.basename(filename),
            mimetype=mimetype
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/delete-file', methods=['DELETE'])
@login_required
def delete_file():
    """Delete a specific result file"""
    try:
        filename = request.args.get('file')
        if not filename:
            return jsonify({"error": "No filename specified"}), 400

        # Security: validate filename pattern
        valid_prefixes = ('products_', 'brands_', 'results_', 'scrape_results_')
        valid_suffixes = ('.csv', '.json', '.zip')
        if not any(filename.startswith(p) for p in valid_prefixes):
            return jsonify({"error": "Invalid filename"}), 400
        if not any(filename.endswith(s) for s in valid_suffixes):
            return jsonify({"error": "Invalid file type"}), 400

        filepath = os.path.join(os.getcwd(), os.path.basename(filename))
        if os.path.exists(filepath):
            os.remove(filepath)
            return jsonify({"success": True, "message": f"Deleted {filename}"})
        else:
            return jsonify({"error": "File not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/download-all')
@login_required
def download_all_results():
    """Download all result files as a zip"""
    try:
        shared = get_shared_state()
        output_files = shared.get("output_files", [])

        if not output_files:
            return jsonify({"error": "No results available"}), 404

        if len(output_files) == 1:
            f = output_files[0]
            if os.path.exists(f):
                mimetype = 'application/json' if f.endswith('.json') else 'text/csv'
                return send_file(f, as_attachment=True, download_name=os.path.basename(f), mimetype=mimetype)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for filepath in output_files:
                if os.path.exists(filepath):
                    zf.write(filepath, os.path.basename(filepath))

        zip_buffer.seek(0)

        return send_file(
            zip_buffer,
            as_attachment=True,
            download_name=f"amazon_results_{timestamp}.zip",
            mimetype='application/zip'
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/list-results')
@login_required
def list_results():
    """List all available result files"""
    try:
        result_files = []
        valid_prefixes = ('products_', 'brands_', 'results_', 'scrape_results_')
        valid_suffixes = ('.csv', '.json')

        for file in os.listdir('.'):
            is_result = any(file.startswith(p) for p in valid_prefixes) and any(file.endswith(s) for s in valid_suffixes)
            if is_result:
                stat = os.stat(file)
                row_count = 0
                if file.endswith('.csv'):
                    try:
                        with open(file, 'r', encoding='utf-8') as f:
                            row_count = sum(1 for _ in f) - 1
                    except:
                        pass

                result_files.append({
                    "filename": file,
                    "size": stat.st_size,
                    "rows": max(0, row_count),
                    "type": "json" if file.endswith('.json') else "csv",
                    "created": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                })

        result_files.sort(key=lambda x: x['created'], reverse=True)
        return jsonify({"files": result_files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/delete-result', methods=['POST'])
@login_required
def delete_result():
    """Delete a specific result file"""
    try:
        data = request.json
        filename = data.get('filename', '')

        valid_prefixes = ('products_', 'brands_', 'results_', 'scrape_results_')
        valid_suffixes = ('.csv', '.json')
        if not any(filename.startswith(p) for p in valid_prefixes):
            return jsonify({"error": "Invalid filename"}), 400
        if not any(filename.endswith(s) for s in valid_suffixes):
            return jsonify({"error": "Invalid file type"}), 400

        if not os.path.exists(filename):
            return jsonify({"error": "File not found"}), 404

        os.remove(filename)
        return jsonify({"success": True, "message": f"Deleted {filename}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/clear-results', methods=['POST'])
@login_required
def clear_results():
    """Delete all result files"""
    try:
        deleted = 0
        valid_prefixes = ('products_', 'brands_', 'results_', 'scrape_results_')
        for file in os.listdir('.'):
            if any(file.startswith(p) for p in valid_prefixes) and (file.endswith('.csv') or file.endswith('.json')):
                os.remove(file)
                deleted += 1

        return jsonify({"success": True, "deleted": deleted})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# SSE Logs
# ============================================================

@app.route('/api/logs')
@login_required
def stream_logs():
    """Server-Sent Events endpoint for real-time logs"""
    def generate():
        last_index = 0
        while True:
            logs = get_log_entries(last_index)
            if logs:
                for log in logs:
                    yield f"data: {json.dumps(log)}\n\n"
                last_index += len(logs)
            else:
                yield f"data: {json.dumps({'heartbeat': True})}\n\n"
            time.sleep(0.2)

    return Response(generate(), mimetype='text/event-stream')


# ============================================================
# Scraper Engine
# ============================================================

def run_scraper_async(searches, max_pages, detail_pages, use_proxies, concurrent,
                      output_format, filters_config, categories):
    """Run scraper in async context"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(
        run_scraper(searches, max_pages, detail_pages, use_proxies, concurrent,
                    output_format, filters_config, categories)
    )


async def run_single_search(search, max_pages, detail_pages, proxy_manager,
                            search_num, total_searches, stagger_index=0):
    """Run a single Amazon search (used for parallel processing)"""
    import random
    logger = WebLogger(scraper_state["log_queue"])

    try:
        stagger_delay = stagger_index * 0.5 + random.uniform(0, 2.0)
        await asyncio.sleep(stagger_delay)

        scraper = AmazonScraper(
            headless=True,
            delay=3.0 + random.uniform(0, 2.0),
            proxy_manager=proxy_manager,
            max_pages=max_pages,
            detail_pages=detail_pages,
        )

        await scraper.start_browser()

        logger.info(f"[{search_num}/{total_searches}] '{search['keyword']}' in {search['category_key']}")

        products = await scraper.scrape_keyword(
            category_key=search['category_key'],
            keyword=search['keyword'],
            max_pages=max_pages,
        )

        for p in products:
            p['search_keyword'] = search['keyword']
            p['category_key'] = search['category_key']

        logger.success(f"[{search_num}/{total_searches}] Found {len(products)} products")

        await scraper.close_browser()

        return products

    except Exception as e:
        logger.error(f"[{search_num}/{total_searches}] Error: {str(e)}")
        return []


async def run_scraper(searches, max_pages, detail_pages, use_proxies, concurrent,
                      output_format, filters_config, categories):
    """Main scraping logic - supports both sequential and parallel"""
    logger = WebLogger(scraper_state["log_queue"])
    all_products = []

    try:
        logger.info(f"Starting Amazon scraper... (Concurrency: {concurrent})")
        logger.info(f"Searches: {len(searches)} | Pages/search: {max_pages} | Detail pages: {detail_pages}")

        # Setup proxy manager
        proxy_manager = None
        if use_proxies:
            if scraper_state["proxy_manager"] and scraper_state["proxy_manager"].proxies:
                proxy_manager = scraper_state["proxy_manager"]
                logger.success(f"Using {len(proxy_manager.proxies)} proxies")
            else:
                logger.error("No proxies loaded - running without proxies")

        if concurrent <= 1:
            # Sequential mode
            scraper = AmazonScraper(
                headless=True,
                delay=3.0,
                proxy_manager=proxy_manager,
                max_pages=max_pages,
                detail_pages=detail_pages,
            )

            scraper_state["current_scraper"] = scraper

            await scraper.start_browser()
            logger.success("Browser started")

            for i, search in enumerate(searches, 1):
                if not scraper_state["running"]:
                    logger.info("Scraper stopped by user")
                    break

                logger.info(f"[{i}/{len(searches)}] '{search['keyword']}' in {search['category_key']}")

                products = await scraper.scrape_keyword(
                    category_key=search['category_key'],
                    keyword=search['keyword'],
                    max_pages=max_pages,
                )

                for p in products:
                    p['search_keyword'] = search['keyword']
                    p['category_key'] = search['category_key']

                all_products.extend(products)

                # Update progress
                scraper_state["progress"]["completed"] = i
                scraper_state["progress"]["products_found"] = len(all_products)
                scraper_state["progress"]["captchas_hit"] = scraper.captcha_count

                logger.success(f"Found {len(products)} products (Total: {len(all_products)})")

                # Sync shared state
                shared = get_shared_state()
                shared["progress"] = scraper_state["progress"].copy()
                set_shared_state(shared)

            await scraper.close_browser()

        else:
            # Parallel mode
            logger.success(f"Running {concurrent} searches in parallel")

            max_concurrent = min(10, concurrent)
            logger.info(f"Rate limiting: max {max_concurrent} concurrent (staggered startup)")

            for batch_num, i in enumerate(range(0, len(searches), concurrent), 1):
                shared = get_shared_state()
                if not scraper_state["running"] or not shared.get("running", True):
                    scraper_state["running"] = False
                    logger.info("Scraper stopped by user")
                    break

                batch = searches[i:i + concurrent]

                logger.info(f"Batch {batch_num}: Processing {len(batch)} searches in parallel...")

                tasks = [
                    run_single_search(
                        search=search,
                        max_pages=max_pages,
                        detail_pages=detail_pages,
                        proxy_manager=proxy_manager,
                        search_num=i + j + 1,
                        total_searches=len(searches),
                        stagger_index=j,
                    )
                    for j, search in enumerate(batch)
                ]

                batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in batch_results:
                    if isinstance(result, list):
                        all_products.extend(result)

                scraper_state["progress"]["completed"] = min(i + concurrent, len(searches))
                scraper_state["progress"]["products_found"] = len(all_products)

                shared = get_shared_state()
                shared["progress"] = scraper_state["progress"].copy()
                set_shared_state(shared)

                logger.success(f"Batch {batch_num} complete! Total products: {len(all_products)}")

        # ---- Phase 3: Post-Processing ----
        scraper_state["phase"] = "processing"
        shared = get_shared_state()
        shared["phase"] = "processing"
        shared["progress"] = scraper_state["progress"].copy()
        set_shared_state(shared)

        logger.info(f"Post-processing {len(all_products)} products...")

        # Calculate BSR-based sales estimates on ALL products first
        primary_category = categories[0] if categories else "default"
        for p in all_products:
            bsr = p.get("bsr", 0)
            price = p.get("price", 0)
            cat = p.get("category_key", primary_category)
            if isinstance(bsr, int) and bsr > 0:
                p["estimated_monthly_units"] = estimate_monthly_sales(bsr, cat)
                p["estimated_monthly_revenue"] = estimate_monthly_revenue(bsr, cat, price)

        # Save ALL unfiltered products first
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_files = []
        fieldnames = [
            "asin", "title", "brand", "price", "rating", "review_count",
            "bsr", "is_prime", "is_fba", "product_type", "seller",
            "estimated_monthly_units", "estimated_monthly_revenue",
            "date_first_available", "variations", "category_breadcrumb",
            "category_key", "search_keyword", "url", "image_url", "scraped_at",
        ]

        if output_format in ("csv", "both"):
            products_file = f"products_{timestamp}.csv"
            if all_products:
                with open(products_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                    writer.writeheader()
                    for p in all_products:
                        row = {k: v for k, v in p.items() if k != 'bullet_points'}
                        writer.writerow(row)
                output_files.append(products_file)
                logger.success(f"Saved {len(all_products)} products to {products_file}")

        # Apply filters (only affects brand aggregation, not product CSV)
        filtered_products = all_products
        product_filter = ProductFilter(filters_config)
        if product_filter.is_active():
            before_count = len(filtered_products)
            filtered_products = product_filter.apply(filtered_products)
            logger.info(f"Filters applied: {before_count} -> {len(filtered_products)} products (for brand aggregation)")

        # Update progress
        scraper_state["progress"]["products_found"] = len(all_products)
        shared = get_shared_state()
        shared["progress"] = scraper_state["progress"].copy()
        set_shared_state(shared)

        # Aggregate by brand (uses filtered products)
        aggregator = BrandAggregator(category_key=primary_category)
        aggregator.add_products(filtered_products)
        brand_stats = aggregator.get_brand_stats()

        scraper_state["progress"]["brands_found"] = len(brand_stats)
        shared = get_shared_state()
        shared["progress"] = scraper_state["progress"].copy()
        set_shared_state(shared)

        logger.info(f"Aggregated into {len(brand_stats)} brands")

        if output_format in ("csv", "both"):
            # Brands CSV
            brands_file = f"brands_{timestamp}.csv"
            aggregator.save_brands_csv(brands_file)
            output_files.append(brands_file)
            logger.success(f"Saved {len(brand_stats)} brands to {brands_file}")

        if output_format in ("json", "both"):
            # Full JSON with nested brands/products
            json_file = f"results_{timestamp}.json"
            output_data = {
                "metadata": {
                    "scraped_at": datetime.now().isoformat(),
                    "total_products": len(all_products),
                    "total_brands": len(brand_stats),
                    "categories": categories,
                    "filters": filters_config,
                },
                "brands": aggregator.to_nested_json(),
            }
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, default=str)
            output_files.append(json_file)
            logger.success(f"Saved results to {json_file}")

        # Update state with output files
        scraper_state["output_files"] = output_files
        scraper_state["last_output_file"] = output_files[0] if output_files else None

        shared = get_shared_state()
        shared["output_files"] = output_files
        shared["last_output_file"] = scraper_state["last_output_file"]
        shared["phase"] = "complete"
        set_shared_state(shared)

        logger.success(f"COMPLETE! {len(all_products)} products, {len(brand_stats)} brands")
        logger.success("Click 'Download Results' to save files")

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()

    finally:
        if concurrent <= 1 and scraper_state.get("current_scraper"):
            try:
                await scraper_state["current_scraper"].close_browser()
            except:
                pass
        scraper_state["running"] = False
        scraper_state["phase"] = "idle"
        shared = get_shared_state()
        shared["running"] = False
        set_shared_state(shared)


if __name__ == '__main__':
    import socket

    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except:
        local_ip = "your-vm-ip"

    print("=" * 60)
    print("Amazon Brand Scraper Web UI")
    print("=" * 60)
    print(f"\nServer running on: http://0.0.0.0:5002")
    print(f"Access via: http://{local_ip}:5002")
    print("=" * 60)

    app.run(host='0.0.0.0', debug=True, port=5002, threaded=True)
