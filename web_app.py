"""
Web UI for Yellow Pages Scraper
Simple interface for configuring and running scrapes with real-time monitoring
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
import pandas as pd
import sqlite3

from yellowpages_scraper import YellowPagesScraper
from proxy_manager import ProxyManager

app = Flask(__name__, static_folder='static')
app.secret_key = os.environ.get('SECRET_KEY', 'yp-scraper-secret-key-change-in-production')  # Required for session management
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
    """Initialize the database with users and settings tables"""
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

    # Settings table for storing API keys and other configuration
    conn.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()

    # Create default admin user if not exists (use INSERT OR IGNORE to handle race conditions)
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
STATE_FILE = "/tmp/yp_scraper_state.json"
LOG_FILE = "/tmp/yp_scraper_logs.json"

def get_shared_state():
    """Read shared state from file with retry logic"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r') as f:
                    content = f.read()
                    if content.strip():  # Only parse if file has content
                        return json.loads(content)
        except (json.JSONDecodeError, IOError) as e:
            if attempt < max_retries - 1:
                time.sleep(0.1)  # Brief pause before retry
                continue
            print(f"Error reading state file (attempt {attempt + 1}): {e}")
        except Exception as e:
            print(f"Unexpected error reading state: {e}")

    return {
        "running": False,
        "progress": {},
        "last_output_file": None,
        "output_files": []
    }

def set_shared_state(state):
    """Write shared state to file atomically with fsync"""
    temp_file = STATE_FILE + '.tmp'
    try:
        # Write to temp file first
        with open(temp_file, 'w') as f:
            json.dump(state, f)
            f.flush()
            os.fsync(f.fileno())  # Force write to disk

        # Atomic rename
        os.replace(temp_file, STATE_FILE)
    except Exception as e:
        print(f"Error saving state: {e}")
        # Cleanup temp file if it exists
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
        # Keep only last 500 logs
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

# Global state (for in-process items that don't need sharing)
scraper_state = {
    "running": False,
    "progress": {},
    "log_queue": Queue(),
    "proxy_manager": None,
    "current_scraper": None,
    "last_output_file": None,
    "output_files": []  # For chunked output
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
        one_day_ago = now - (24 * 60 * 60)  # 24 hours in seconds

        for file in os.listdir('.'):
            if file.startswith('scrape_results_') and file.endswith('.csv'):
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
            # Run cleanup at startup and then every 24 hours
            cleanup_old_results()
            time_module.sleep(24 * 60 * 60)  # Sleep for 24 hours

    cleanup_thread = threading.Thread(target=scheduler_loop, daemon=True)
    cleanup_thread.start()
    print("Auto-cleanup scheduler started (runs every 24 hours)")

load_proxies_on_startup()
start_cleanup_scheduler()


def save_chunked_csv(businesses, base_filename, chunk_size=50000):
    """Save businesses to multiple CSV files if over chunk_size rows"""
    if not businesses:
        return []

    output_files = []
    total_rows = len(businesses)
    num_chunks = math.ceil(total_rows / chunk_size)

    if num_chunks == 1:
        # Single file
        df = pd.DataFrame(businesses)
        df.to_csv(base_filename, index=False, encoding='utf-8')
        output_files.append(base_filename)
    else:
        # Multiple chunks
        for i in range(num_chunks):
            start_idx = i * chunk_size
            end_idx = min((i + 1) * chunk_size, total_rows)
            chunk_businesses = businesses[start_idx:end_idx]

            # Create filename with chunk number
            name_parts = base_filename.rsplit('.', 1)
            chunk_filename = f"{name_parts[0]}_part{i+1}of{num_chunks}.csv"

            df = pd.DataFrame(chunk_businesses)
            df.to_csv(chunk_filename, index=False, encoding='utf-8')
            output_files.append(chunk_filename)

    return output_files

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
        # Add to file-based shared logs
        add_log_entry(entry)
        # Also add to queue for backward compatibility
        if self.log_queue:
            self.log_queue.put(entry)

    def info(self, message):
        self._add_log("info", message)

    def error(self, message):
        self._add_log("error", message)

    def success(self, message):
        self._add_log("success", message)

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

    # Check if user exists
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

    # Get current settings (mask API key for display)
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
    """Get AI-powered keyword and location suggestions from OpenAI"""
    try:
        import requests

        data = request.json
        icp = data.get('icp', '').strip()

        if not icp:
            return jsonify({"error": "Please provide an Ideal Customer Profile"}), 400

        # Get OpenAI API key from settings
        api_key = get_setting('openai_api_key')
        if not api_key:
            return jsonify({"error": "OpenAI API key not configured. Please add it in Settings."}), 400

        # Call OpenAI API
        prompt = f"""Based on the following Ideal Customer Profile (ICP), suggest business categories/keywords and US locations to search on Yellow Pages for lead generation.

ICP: {icp}

Provide your response in this exact JSON format:
{{
    "keywords": ["keyword1", "keyword2", ...],
    "locations": ["City ST", "City ST", ...]
}}

Rules:
- Keywords should be Yellow Pages business categories (e.g., "plumbers", "roofing contractors", "HVAC services")
- Provide up to 50 relevant keywords
- Locations should be in "City ST" format (e.g., "Miami FL", "Chicago IL")
- Provide up to 50 US locations that match the ICP's target market
- Focus on locations where the ICP's target customers are likely to be
- Only return the JSON object, no other text"""

        response = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            json={
                'model': 'gpt-4o-mini',
                'messages': [
                    {'role': 'system', 'content': 'You are a helpful assistant that provides business lead generation suggestions. Always respond with valid JSON only.'},
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

        # Get arrays from response
        keywords = suggestions.get('keywords', [])
        locations = suggestions.get('locations', [])

        # Ensure they are lists
        if not isinstance(keywords, list):
            keywords = []
        if not isinstance(locations, list):
            locations = []

        return jsonify({
            "success": True,
            "keywords": keywords,
            "locations": locations,
            "keyword_count": len(keywords),
            "location_count": len(locations)
        })

    except json.JSONDecodeError as e:
        return jsonify({"error": f"Failed to parse AI response: {str(e)}"}), 500
    except requests.exceptions.Timeout:
        return jsonify({"error": "OpenAI API request timed out. Please try again."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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

        # Save to proxies.txt
        file.save('proxies.txt')

        # Reload proxy manager
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

@app.route('/api/start-scrape', methods=['POST'])
@login_required
def start_scrape():
    """Start a new scraping job"""
    try:
        data = request.json

        # Parse comma-separated inputs
        keywords = [k.strip() for k in data.get('keywords', '').split(',') if k.strip()]
        locations = [l.strip() for l in data.get('locations', '').split(',') if l.strip()]

        if not keywords or not locations:
            return jsonify({"error": "Please provide keywords and locations"}), 400

        max_pages = int(data.get('max_pages', 10))
        max_businesses = int(data.get('max_businesses', 0))  # 0 = unlimited
        use_proxies = data.get('use_proxies', True)
        concurrent = int(data.get('concurrent', 1))
        chunk_output = data.get('chunk_output', False)  # New: chunked output option

        # Build search list
        searches = []
        for location in locations:
            for keyword in keywords:
                searches.append({
                    "term": keyword,
                    "location": location
                })

        # Update state
        scraper_state["running"] = True
        scraper_state["progress"] = {
            "total_searches": len(searches),
            "completed": 0,
            "businesses_found": 0,
            "max_businesses": max_businesses,
            "limit_reached": False
        }
        scraper_state["output_files"] = []  # Reset output files

        # Update shared state for multi-worker support
        set_shared_state({
            "running": True,
            "progress": scraper_state["progress"],
            "last_output_file": None,
            "output_files": []
        })

        # Clear logs
        clear_logs()

        # Clear log queue
        while not scraper_state["log_queue"].empty():
            scraper_state["log_queue"].get()

        # Start scraper in background thread
        thread = threading.Thread(
            target=run_scraper_async,
            args=(searches, max_pages, use_proxies, concurrent, chunk_output, max_businesses)
        )
        thread.daemon = True
        thread.start()

        return jsonify({
            "success": True,
            "total_searches": len(searches),
            "message": f"Started scraping {len(searches)} searches"
        })

    except Exception as e:
        scraper_state["running"] = False
        return jsonify({"error": str(e)}), 500

@app.route('/api/stop-scrape', methods=['POST'])
@login_required
def stop_scrape():
    """Stop current scraping job"""
    scraper_state["running"] = False
    # Update shared state
    shared = get_shared_state()
    shared["running"] = False
    set_shared_state(shared)
    return jsonify({"success": True, "message": "Scraper stopped"})

@app.route('/api/progress')
@login_required
def get_progress():
    """Get current scraping progress from shared state"""
    # Read from shared state for multi-worker support
    shared = get_shared_state()
    return jsonify({
        "running": shared.get("running", False),
        "progress": shared.get("progress", {}),
        "last_output_file": shared.get("last_output_file"),
        "output_files": shared.get("output_files", [])
    })

@app.route('/api/download')
@login_required
def download_results():
    """Download CSV file - either specific file or last generated"""
    try:
        # Check if specific file requested
        filename = request.args.get('file')

        if filename:
            # Download specific file - allow scrape_results patterns including chunked
            if not (filename.startswith('scrape_results_') and filename.endswith('.csv')):
                return jsonify({"error": "Invalid filename"}), 400

            if not os.path.exists(filename):
                return jsonify({"error": "File not found"}), 404

            output_file = filename
        else:
            # Download last generated file
            output_file = scraper_state.get("last_output_file")

            if not output_file:
                return jsonify({"error": "No results available to download"}), 404

            if not os.path.exists(output_file):
                return jsonify({"error": "Result file not found"}), 404

        return send_file(
            output_file,
            as_attachment=True,
            download_name=os.path.basename(output_file),
            mimetype='text/csv'
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/download-all')
@login_required
def download_all_results():
    """Download all chunked CSV files as a zip"""
    try:
        import zipfile
        from io import BytesIO

        output_files = scraper_state.get("output_files", [])

        if not output_files:
            return jsonify({"error": "No results available to download"}), 404

        if len(output_files) == 1:
            # Just return the single file
            return send_file(
                output_files[0],
                as_attachment=True,
                download_name=os.path.basename(output_files[0]),
                mimetype='text/csv'
            )

        # Create zip file with all chunks
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for filepath in output_files:
                if os.path.exists(filepath):
                    zip_file.write(filepath, os.path.basename(filepath))

        zip_buffer.seek(0)

        return send_file(
            zip_buffer,
            as_attachment=True,
            download_name=f"scrape_results_{timestamp}.zip",
            mimetype='application/zip'
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/list-results')
@login_required
def list_results():
    """List all available CSV result files"""
    try:
        csv_files = []
        for file in os.listdir('.'):
            if file.startswith('scrape_results_') and file.endswith('.csv'):
                stat = os.stat(file)
                # Count rows in file (excluding header)
                try:
                    with open(file, 'r', encoding='utf-8') as f:
                        row_count = sum(1 for _ in f) - 1  # Subtract header
                except:
                    row_count = 0

                csv_files.append({
                    "filename": file,
                    "size": stat.st_size,
                    "rows": max(0, row_count),
                    "created": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                })

        # Sort by creation time, newest first
        csv_files.sort(key=lambda x: x['created'], reverse=True)

        return jsonify({"files": csv_files})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/delete-result', methods=['POST'])
@login_required
def delete_result():
    """Delete a specific result file"""
    try:
        data = request.json
        filename = data.get('filename', '')

        # Security: only allow deleting scrape_results_*.csv files
        if not filename.startswith('scrape_results_') or not filename.endswith('.csv'):
            return jsonify({"error": "Invalid filename"}), 400

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
        for file in os.listdir('.'):
            if file.startswith('scrape_results_') and file.endswith('.csv'):
                os.remove(file)
                deleted += 1

        return jsonify({"success": True, "deleted": deleted})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/logs')
@login_required
def stream_logs():
    """Server-Sent Events endpoint for real-time logs"""
    def generate():
        last_index = 0
        while True:
            # Read new logs from shared file
            logs = get_log_entries(last_index)
            if logs:
                for log in logs:
                    yield f"data: {json.dumps(log)}\n\n"
                last_index += len(logs)
            else:
                # Send heartbeat
                yield f"data: {json.dumps({'heartbeat': True})}\n\n"
            time.sleep(0.2)

    return Response(generate(), mimetype='text/event-stream')

def run_scraper_async(searches, max_pages, use_proxies, concurrent=1, chunk_output=False, max_businesses=0):
    """Run scraper in async context"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_scraper(searches, max_pages, use_proxies, concurrent, chunk_output, max_businesses))

async def run_single_search(search, max_pages, proxy_manager, search_num, total_searches, stagger_index=0, request_semaphore=None):
    """Run a single search (used for parallel processing)"""
    import random
    logger = WebLogger(scraper_state["log_queue"])

    try:
        # Staggered startup: spread out worker starts to avoid burst requests
        stagger_delay = stagger_index * 0.3 + random.uniform(0, 1.0)
        await asyncio.sleep(stagger_delay)

        # Create separate scraper instance for this search
        scraper = YellowPagesScraper(
            headless=True,
            delay=3.0 + random.uniform(0, 1.0),  # Add jitter to delay
            proxy_manager=proxy_manager
        )

        await scraper.start_browser()

        logger.info(f"[{search_num}/{total_searches}] {search['term']} in {search['location']} (stagger: {stagger_delay:.1f}s)")

        businesses = await scraper.scrape_search(
            search_term=search['term'],
            location=search['location'],
            max_pages=max_pages
        )

        # Tag with search info
        for biz in businesses:
            biz['search_category'] = search['term']
            biz['search_location'] = search['location']

        logger.success(f"✓ [{search_num}/{total_searches}] Found {len(businesses)} businesses")

        await scraper.close_browser()

        return businesses

    except Exception as e:
        logger.error(f"❌ [{search_num}/{total_searches}] Error: {str(e)}")
        return []

async def run_scraper(searches, max_pages, use_proxies, concurrent=1, chunk_output=False, max_businesses=0):
    """Main scraping logic - supports both sequential and parallel"""
    logger = WebLogger(scraper_state["log_queue"])
    all_businesses = []

    try:
        logger.info(f"Starting scraper... (Concurrency: {concurrent})")
        if max_businesses > 0:
            logger.info(f"Business limit set: will stop after {max_businesses:,} businesses")
        if chunk_output:
            logger.info("Chunked output enabled - will split into 50k row files")

        # Setup proxy manager
        proxy_manager = None
        if use_proxies:
            if scraper_state["proxy_manager"] and scraper_state["proxy_manager"].proxies:
                proxy_manager = scraper_state["proxy_manager"]
                logger.success(f"✅ Using {len(proxy_manager.proxies)} proxies")
            else:
                logger.error("⚠️ No proxies loaded - running without proxies")

        if concurrent == 1:
            # Sequential mode (original behavior)
            scraper = YellowPagesScraper(
                headless=True,
                delay=3.0,
                proxy_manager=proxy_manager
            )

            scraper_state["current_scraper"] = scraper

            await scraper.start_browser()
            logger.success("✅ Browser started")

            # Run searches sequentially
            for i, search in enumerate(searches, 1):
                if not scraper_state["running"]:
                    logger.info("⚠️ Scraper stopped by user")
                    break

                logger.info(f"[{i}/{len(searches)}] {search['term']} in {search['location']}")

                businesses = await scraper.scrape_search(
                    search_term=search['term'],
                    location=search['location'],
                    max_pages=max_pages
                )

                # Tag with search info
                for biz in businesses:
                    biz['search_category'] = search['term']
                    biz['search_location'] = search['location']

                all_businesses.extend(businesses)

                # Update progress
                scraper_state["progress"]["completed"] = i
                scraper_state["progress"]["businesses_found"] = len(all_businesses)

                logger.success(f"✓ Found {len(businesses)} businesses (Total: {len(all_businesses)})")

                # Check if we've reached the business limit
                if max_businesses > 0 and len(all_businesses) >= max_businesses:
                    logger.success(f"🎯 Reached business limit ({max_businesses:,}) - stopping scraper")
                    all_businesses = all_businesses[:max_businesses]  # Trim to exact limit
                    scraper_state["progress"]["limit_reached"] = True
                    break

            await scraper.close_browser()

        else:
            # Parallel mode
            logger.success(f"✅ Running {concurrent} searches in parallel")

            import asyncio

            # Limit concurrent requests to avoid rate limiting
            max_concurrent_requests = min(20, concurrent)  # Cap at 20 simultaneous requests
            request_semaphore = asyncio.Semaphore(max_concurrent_requests)
            logger.info(f"Rate limiting: max {max_concurrent_requests} concurrent requests (staggered startup)")

            # Process searches in batches
            for batch_num, i in enumerate(range(0, len(searches), concurrent), 1):
                # Check both local and shared state for stop signal
                shared = get_shared_state()
                if not scraper_state["running"] or not shared.get("running", True):
                    scraper_state["running"] = False
                    logger.info("⚠️ Scraper stopped by user")
                    break

                batch = searches[i:i + concurrent]
                batch_size = len(batch)

                logger.info(f"📦 Batch {batch_num}: Processing {batch_size} searches in parallel (staggered)...")

                # Create tasks for parallel execution with staggered starts
                tasks = [
                    run_single_search(
                        search=search,
                        max_pages=max_pages,
                        proxy_manager=proxy_manager,
                        search_num=i + j + 1,
                        total_searches=len(searches),
                        stagger_index=j,
                        request_semaphore=request_semaphore
                    )
                    for j, search in enumerate(batch)
                ]

                # Run all searches in this batch concurrently (with staggered starts)
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                # Collect results
                for result in batch_results:
                    if isinstance(result, list):
                        all_businesses.extend(result)
                        # Check limit after each result to stop early if possible
                        if max_businesses > 0 and len(all_businesses) >= max_businesses:
                            break

                # Update progress
                scraper_state["progress"]["completed"] = min(i + concurrent, len(searches))
                scraper_state["progress"]["businesses_found"] = len(all_businesses)

                # Update shared state for multi-worker support
                shared = get_shared_state()
                shared["progress"] = scraper_state["progress"].copy()
                set_shared_state(shared)

                logger.success(f"✓ Batch {batch_num} complete! Total businesses: {len(all_businesses)}")

                # Check if we've reached the business limit
                if max_businesses > 0 and len(all_businesses) >= max_businesses:
                    logger.success(f"🎯 Reached business limit ({max_businesses:,}) - stopping scraper")
                    all_businesses = all_businesses[:max_businesses]  # Trim to exact limit
                    scraper_state["progress"]["limit_reached"] = True
                    # Update shared state
                    shared = get_shared_state()
                    shared["progress"] = scraper_state["progress"].copy()
                    set_shared_state(shared)
                    break

        # Update final count after potential trimming
        scraper_state["progress"]["businesses_found"] = len(all_businesses)

        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_filename = f"scrape_results_{timestamp}.csv"

        if chunk_output and len(all_businesses) > 0:
            # Save as chunked files
            output_files = save_chunked_csv(all_businesses, base_filename, chunk_size=50000)
            scraper_state["output_files"] = output_files
            scraper_state["last_output_file"] = output_files[0] if output_files else None

            if len(output_files) > 1:
                logger.success(f"COMPLETE! Saved {len(all_businesses)} businesses to {len(output_files)} files")
                for f in output_files:
                    logger.info(f"  - {f}")
            else:
                logger.success(f"COMPLETE! Saved {len(all_businesses)} businesses to {base_filename}")
        else:
            # Save as single file
            from yellowpages_scraper import YellowPagesScraper
            temp_scraper = YellowPagesScraper()
            temp_scraper.save_to_csv(all_businesses, base_filename)
            scraper_state["last_output_file"] = base_filename
            scraper_state["output_files"] = [base_filename]
            logger.success(f"COMPLETE! Saved {len(all_businesses)} businesses to {base_filename}")

        # Update shared state with output files
        shared = get_shared_state()
        shared["output_files"] = scraper_state["output_files"]
        shared["last_output_file"] = scraper_state["last_output_file"]
        set_shared_state(shared)

        logger.success(f"Click 'Download Results' to save to your computer")

    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()

    finally:
        if concurrent == 1 and scraper_state.get("current_scraper"):
            await scraper_state["current_scraper"].close_browser()
        scraper_state["running"] = False
        # Update shared state
        shared = get_shared_state()
        shared["running"] = False
        set_shared_state(shared)

if __name__ == '__main__':
    import socket

    # Get local IP address
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except:
        local_ip = "your-vm-ip"

    print("=" * 60)
    print("Yellow Pages Scraper Web UI")
    print("=" * 60)
    print(f"\nServer running on: http://0.0.0.0:5001")
    print(f"Access via: http://{local_ip}:5001")
    print("=" * 60)

    app.run(host='0.0.0.0', debug=True, port=5001, threaded=True)
