from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
import sqlite3
from datetime import datetime, timedelta
import yfinance as yf
import hashlib
import os
import requests
import base64
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from indicators import (
    calculate_sma, calculate_ema, calculate_rsi, 
    calculate_macd, calculate_bollinger_bands, 
    get_signal, generate_sample_prices
)
from ict_methods import analyze_ict
from ml_predictor import predict_forex
from arima_predictor import (
    get_arima_prediction, calculate_arima_metrics,
    calculate_forecast_confidence, backtest_arima, get_trading_signal
)
from trading_strategies import (
    MeanReversionStrategy, MomentumStrategy, BreakoutStrategy,
    VolatilityBreakoutStrategy, EnsembleStrategy, analyze_all_strategies
)
from auto_execution import AutoExecutor, get_execution_signals, simulate_auto_portfolio
from auto_scheduler import (
    init_auto_tables, start_scheduler, get_user_stats, get_user_executions,
    get_user_logs, get_user_settings, save_user_settings, scan_markets_for_user,
    log_action, fetch_pair_price, close_position
)

# Yahoo Finance ticker symbols for forex pairs
FOREX_TICKERS = {
    # Major Pairs
    'EUR/USD': 'EURUSD=X',
    'GBP/USD': 'GBPUSD=X',
    'USD/JPY': 'USDJPY=X',
    'USD/CHF': 'USDCHF=X',
    'AUD/USD': 'AUDUSD=X',
    'USD/CAD': 'USDCAD=X',
    'NZD/USD': 'NZDUSD=X',
    
    # Cross Pairs
    'EUR/GBP': 'EURGBP=X',
    'EUR/JPY': 'EURJPY=X',
    'EUR/CHF': 'EURCHF=X',
    'EUR/AUD': 'EURAUD=X',
    'EUR/CAD': 'EURCAD=X',
    'EUR/NZD': 'EURNZD=X',
    'GBP/JPY': 'GBPJPY=X',
    'GBP/CHF': 'GBPCHF=X',
    'GBP/AUD': 'GBPAUD=X',
    'GBP/CAD': 'GBPCAD=X',
    'GBP/NZD': 'GBPNZD=X',
    'AUD/JPY': 'AUDJPY=X',
    'AUD/CHF': 'AUDCHF=X',
    'AUD/CAD': 'AUDCAD=X',
    'AUD/NZD': 'AUDNZD=X',
    'CAD/JPY': 'CADJPY=X',
    'CAD/CHF': 'CADCHF=X',
    'CHF/JPY': 'CHFJPY=X',
    'NZD/JPY': 'NZDJPY=X',
    'NZD/CHF': 'NZDCHF=X',
    'NZD/CAD': 'NZDCAD=X',
    
    # Metals
    'XAU/USD': 'GC=F',      # Gold
    'XAG/USD': 'SI=F',      # Silver
    'XPT/USD': 'PL=F',      # Platinum
    
    # Crypto
    'BTC/USD': 'BTC-USD',
    'ETH/USD': 'ETH-USD',
    'XRP/USD': 'XRP-USD',
    'SOL/USD': 'SOL-USD',
    'BNB/USD': 'BNB-USD',
    'ADA/USD': 'ADA-USD',
    'DOGE/USD': 'DOGE-USD',
    
    # Indices
    'US30': 'YM=F',         # Dow Jones
    'US100': 'NQ=F',        # Nasdaq
    'US500': 'ES=F',        # S&P 500
    'UK100': '^FTSE',       # FTSE 100
    'GER40': '^GDAXI',      # DAX
    'JPN225': '^N225',      # Nikkei
    
    # Oil
    'WTI': 'CL=F',          # Crude Oil
    'BRENT': 'BZ=F',        # Brent Oil
    'NATGAS': 'NG=F',       # Natural Gas
}

app = Flask(__name__)
app.secret_key = 'forex-risk-manager-secret-key-2024'
DATABASE = 'database.db'

# Telegram Configuration (User can set their own bot token and chat ID)
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

# Subscription Plans
SUBSCRIPTION_PLANS = {
    'free': {'name': 'Free', 'price': 0, 'days': 0, 'features': ['Dashboard', 'Calculator', '5 trades/month']},
    'basic': {'name': 'Basic', 'price': 9.99, 'days': 30, 'features': ['All Free features', 'ICT Analysis', 'Unlimited trades']},
    'pro': {'name': 'Pro', 'price': 29.99, 'days': 30, 'features': ['All Basic features', 'ML Predictions', 'Priority support']}
}


def hash_password(password):
    """Hash password with salt"""
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    return salt + key


def verify_password(stored_password, provided_password):
    """Verify password against hash"""
    salt = stored_password[:32]
    stored_key = stored_password[32:]
    new_key = hashlib.pbkdf2_hmac('sha256', provided_password.encode(), salt, 100000)
    return stored_key == new_key


def login_required(f):
    """Decorator to require user authentication"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def subscription_required(plan_level='basic'):
    """Decorator to require subscription level"""
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('user_id'):
                return redirect(url_for('login'))
            
            conn = get_db()
            user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
            conn.close()
            
            if not user:
                return redirect(url_for('login'))
            
            # Check subscription
            plan_hierarchy = {'free': 0, 'basic': 1, 'pro': 2}
            user_plan = user['subscription_plan'] or 'free'
            
            # Check if subscription expired
            if user['subscription_expires']:
                try:
                    expires = datetime.strptime(user['subscription_expires'][:19], '%Y-%m-%d %H:%M:%S')
                    if expires < datetime.now():
                        user_plan = 'free'
                except:
                    pass
            
            if plan_hierarchy.get(user_plan, 0) < plan_hierarchy.get(plan_level, 0):
                flash(f'This feature requires {plan_level.title()} subscription or higher.', 'warning')
                return redirect(url_for('subscription'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def get_current_user():
    """Get current logged in user"""
    if not session.get('user_id'):
        return None
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    return user


def check_free_tier_limit(user_id, action_type, limit=5):
    """Check if free tier user has exceeded monthly limit"""
    conn = get_db()
    
    # Get user's subscription
    user = conn.execute('SELECT subscription_plan, subscription_expires FROM users WHERE id = ?', (user_id,)).fetchone()
    
    if not user:
        conn.close()
        return False, 0
    
    plan = user['subscription_plan'] or 'free'
    
    # Check if subscription expired
    if user['subscription_expires'] and plan != 'free':
        try:
            expires = datetime.strptime(user['subscription_expires'][:19], '%Y-%m-%d %H:%M:%S')
            if expires < datetime.now():
                plan = 'free'
        except:
            pass
    
    # Paid users have unlimited access
    if plan in ['basic', 'pro']:
        conn.close()
        return True, -1  # -1 means unlimited
    
    # Count usage this month for free users
    first_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    count = conn.execute('''
        SELECT COUNT(*) FROM usage_tracking 
        WHERE user_id = ? AND action_type = ? AND created_at >= ?
    ''', (user_id, action_type, first_of_month)).fetchone()[0]
    
    conn.close()
    
    remaining = limit - count
    return remaining > 0, remaining


def track_usage(user_id, action_type):
    """Track usage for free tier limits"""
    conn = get_db()
    conn.execute('INSERT INTO usage_tracking (user_id, action_type) VALUES (?, ?)', (user_id, action_type))
    conn.commit()
    conn.close()


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('index'))
    
    error = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        
        if user and verify_password(user['password'], password):
            session['user_id'] = user['id']
            session['user_email'] = user['email']
            session['user_name'] = user['name']
            session['is_admin'] = user['is_admin'] == 1
            return redirect(url_for('index'))
        else:
            error = 'Invalid email or password.'
    
    return render_template('login.html', error=error)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if session.get('user_id'):
        return redirect(url_for('index'))
    
    error = None
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if not name or not email or not password:
            error = 'All fields are required.'
        elif len(password) < 6:
            error = 'Password must be at least 6 characters.'
        elif password != confirm_password:
            error = 'Passwords do not match.'
        else:
            conn = get_db()
            existing = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
            
            if existing:
                error = 'Email already registered.'
                conn.close()
            else:
                hashed = hash_password(password)
                conn.execute('''
                    INSERT INTO users (name, email, password, subscription_plan) 
                    VALUES (?, ?, ?, 'free')
                ''', (name, email, hashed))
                conn.commit()
                
                user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
                conn.close()
                
                session['user_id'] = user['id']
                session['user_email'] = user['email']
                session['user_name'] = user['name']
                flash('Registration successful! Welcome to Forex Risk Manager.', 'success')
                return redirect(url_for('index'))
    
    return render_template('register.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/subscription')
@login_required
def subscription():
    user = get_current_user()
    return render_template('subscription.html', plans=SUBSCRIPTION_PLANS, user=user)


@app.route('/settings')
@login_required
def settings():
    user = get_current_user()
    return render_template('settings.html', user=user)


@app.route('/save_telegram_settings', methods=['POST'])
@login_required
def save_telegram_settings():
    bot_token = request.form.get('telegram_bot_token', '').strip()
    chat_id = request.form.get('telegram_chat_id', '').strip()
    
    conn = get_db()
    conn.execute('UPDATE users SET telegram_bot_token = ?, telegram_chat_id = ? WHERE id = ?',
                (bot_token, chat_id, session['user_id']))
    conn.commit()
    conn.close()
    
    flash('Telegram settings saved successfully!', 'success')
    return redirect(url_for('settings'))


@app.route('/test_telegram', methods=['POST'])
@login_required
def test_telegram():
    """Send a test message to Telegram"""
    try:
        conn = get_db()
        user = conn.execute('SELECT telegram_bot_token, telegram_chat_id, name, subscription_plan FROM users WHERE id = ?', 
                           (session['user_id'],)).fetchone()
        conn.close()
        
        bot_token = user['telegram_bot_token'] if user else None
        chat_id = user['telegram_chat_id'] if user else None
        
        if not bot_token or not chat_id:
            return jsonify({'error': 'Telegram not configured. Please set Bot Token and Chat ID first.'}), 400
        
        # Send test message
        message = f"""
✅ *TELEGRAM TEST SUCCESSFUL*
━━━━━━━━━━━━━━━━━━

👤 *User:* {user['name']}
📊 *Plan:* {(user['subscription_plan'] or 'free').upper()}
⏰ *Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Your Telegram alerts are working! 🎉
You will receive ICT analysis alerts here.
"""
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown'}
        
        response = requests.post(url, json=payload, timeout=30)
        
        if response.status_code == 200:
            return jsonify({'success': True, 'message': 'Test message sent successfully!'})
        else:
            error_data = response.json()
            return jsonify({'error': f"Telegram error: {error_data.get('description', 'Unknown error')}"}), 400
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/subscribe/<plan>', methods=['POST'])
@login_required
def subscribe(plan):
    if plan not in SUBSCRIPTION_PLANS:
        flash('Invalid subscription plan.', 'error')
        return redirect(url_for('subscription'))
    
    plan_info = SUBSCRIPTION_PLANS[plan]
    transaction_id = request.form.get('transaction_id', '').strip()
    payment_method = request.form.get('payment_method', 'manual')
    
    if not transaction_id:
        flash('Transaction ID is required.', 'error')
        return redirect(url_for('subscription'))
    
    conn = get_db()
    
    # Create payment record with transaction ID (pending - admin will verify)
    conn.execute('''
        INSERT INTO payments (user_id, amount, plan, status, payment_method, transaction_id)
        VALUES (?, ?, ?, 'pending', ?, ?)
    ''', (session['user_id'], plan_info['price'], plan, payment_method, transaction_id))
    conn.commit()
    conn.close()
    
    flash(f'Payment submitted for {plan_info["name"]} plan! Transaction ID: {transaction_id}. Waiting for admin verification.', 'success')
    return redirect(url_for('subscription'))


@app.route('/profile')
@login_required
def profile():
    user = get_current_user()
    
    conn = get_db()
    payments = conn.execute('''
        SELECT * FROM payments 
        WHERE user_id = ? 
        ORDER BY created_at DESC
    ''', (session['user_id'],)).fetchall()
    conn.close()
    
    return render_template('profile.html', user=user, payments=payments)


# ============== ADMIN SECTION ==============

def admin_required(f):
    """Decorator to require admin authentication"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        
        conn = get_db()
        user = conn.execute('SELECT is_admin FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()
        
        if not user or not user['is_admin']:
            flash('Admin access required.', 'error')
            return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function


@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = get_db()
    
    # Get stats
    total_users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    total_payments = conn.execute('SELECT COUNT(*) FROM payments').fetchone()[0]
    total_revenue = conn.execute('SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = "completed"').fetchone()[0]
    
    # Get subscription counts
    free_users = conn.execute('SELECT COUNT(*) FROM users WHERE subscription_plan = "free" OR subscription_plan IS NULL').fetchone()[0]
    basic_users = conn.execute('SELECT COUNT(*) FROM users WHERE subscription_plan = "basic"').fetchone()[0]
    pro_users = conn.execute('SELECT COUNT(*) FROM users WHERE subscription_plan = "pro"').fetchone()[0]
    
    # Recent users
    recent_users = conn.execute('SELECT * FROM users ORDER BY created_at DESC LIMIT 10').fetchall()
    
    # Recent payments
    recent_payments = conn.execute('''
        SELECT p.*, u.name, u.email 
        FROM payments p 
        JOIN users u ON p.user_id = u.id 
        ORDER BY p.created_at DESC LIMIT 10
    ''').fetchall()
    
    conn.close()
    
    return render_template('admin/dashboard.html', 
        total_users=total_users,
        total_payments=total_payments,
        total_revenue=total_revenue,
        free_users=free_users,
        basic_users=basic_users,
        pro_users=pro_users,
        recent_users=recent_users,
        recent_payments=recent_payments
    )


@app.route('/admin/users')
@admin_required
def admin_users():
    conn = get_db()
    users = conn.execute('SELECT * FROM users ORDER BY created_at DESC').fetchall()
    conn.close()
    return render_template('admin/users.html', users=users)


@app.route('/admin/user/<int:user_id>/update', methods=['POST'])
@admin_required
def admin_update_user(user_id):
    plan = request.form.get('subscription_plan', 'free')
    days = int(request.form.get('days', 30))
    is_admin = 1 if request.form.get('is_admin') else 0
    
    expires = datetime.now() + timedelta(days=days) if plan != 'free' else None
    
    conn = get_db()
    conn.execute('''
        UPDATE users SET subscription_plan = ?, subscription_expires = ?, is_admin = ?
        WHERE id = ?
    ''', (plan, expires, is_admin, user_id))
    conn.commit()
    conn.close()
    
    flash(f'User updated successfully.', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    # Don't allow deleting yourself
    if user_id == session.get('user_id'):
        flash('Cannot delete your own account.', 'error')
        return redirect(url_for('admin_users'))
    
    conn = get_db()
    conn.execute('DELETE FROM payments WHERE user_id = ?', (user_id,))
    conn.execute('DELETE FROM trades WHERE user_id = ?', (user_id,))
    conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    
    flash('User deleted.', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/payments')
@admin_required
def admin_payments():
    conn = get_db()
    payments = conn.execute('''
        SELECT p.*, u.name, u.email 
        FROM payments p 
        JOIN users u ON p.user_id = u.id 
        ORDER BY p.created_at DESC
    ''').fetchall()
    conn.close()
    return render_template('admin/payments.html', payments=payments)


@app.route('/admin/payment/<int:payment_id>/update', methods=['POST'])
@admin_required
def admin_update_payment(payment_id):
    status = request.form.get('status', 'pending')
    
    conn = get_db()
    payment = conn.execute('SELECT * FROM payments WHERE id = ?', (payment_id,)).fetchone()
    
    if payment:
        conn.execute('UPDATE payments SET status = ? WHERE id = ?', (status, payment_id))
        
        # If payment completed, update user subscription
        if status == 'completed' and payment['status'] != 'completed':
            plan = payment['plan']
            days = SUBSCRIPTION_PLANS.get(plan, {}).get('days', 30)
            expires = datetime.now() + timedelta(days=days)
            conn.execute('''
                UPDATE users SET subscription_plan = ?, subscription_expires = ?
                WHERE id = ?
            ''', (plan, expires, payment['user_id']))
        
        conn.commit()
    
    conn.close()
    flash('Payment updated.', 'success')
    return redirect(url_for('admin_payments'))


@app.route('/admin/create-admin', methods=['GET', 'POST'])
def create_first_admin():
    """Create first admin account - only works if no admin exists"""
    conn = get_db()
    admin_exists = conn.execute('SELECT COUNT(*) FROM users WHERE is_admin = 1').fetchone()[0]
    
    if admin_exists:
        conn.close()
        flash('Admin already exists.', 'error')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        name = request.form.get('name', 'Admin')
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        if not email or not password:
            flash('Email and password required.', 'error')
            return render_template('admin/create_admin.html')
        
        hashed = hash_password(password)
        conn.execute('''
            INSERT INTO users (name, email, password, is_admin, subscription_plan)
            VALUES (?, ?, ?, 1, 'pro')
        ''', (name, email, hashed))
        conn.commit()
        conn.close()
        
        flash('Admin account created! Please login.', 'success')
        return redirect(url_for('login'))
    
    conn.close()
    return render_template('admin/create_admin.html')


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    
    # Users table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL,
            password BLOB NOT NULL,
            is_admin INTEGER DEFAULT 0,
            subscription_plan VARCHAR(20) DEFAULT 'free',
            subscription_expires TIMESTAMP,
            telegram_bot_token VARCHAR(100),
            telegram_chat_id VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Add Telegram columns if they don't exist (for existing databases)
    try:
        conn.execute('ALTER TABLE users ADD COLUMN telegram_bot_token VARCHAR(100)')
    except:
        pass
    try:
        conn.execute('ALTER TABLE users ADD COLUMN telegram_chat_id VARCHAR(50)')
    except:
        pass
    
    # Payments table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            amount REAL NOT NULL,
            plan VARCHAR(20) NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            payment_method VARCHAR(50),
            transaction_id VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            initial_balance REAL NOT NULL,
            current_balance REAL NOT NULL,
            max_drawdown_percent REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            pair VARCHAR(20) NOT NULL,
            trade_type VARCHAR(10) NOT NULL,
            lot_size REAL NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            stop_loss REAL,
            take_profit REAL,
            profit_loss REAL DEFAULT 0,
            risk_percent REAL,
            status VARCHAR(20) DEFAULT 'open',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Usage tracking table for free tier limits
    conn.execute('''
        CREATE TABLE IF NOT EXISTS usage_tracking (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            action_type VARCHAR(50) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Analysis cache table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS analysis_cache (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            analysis_type VARCHAR(20) NOT NULL,
            pair VARCHAR(20) NOT NULL,
            timeframe VARCHAR(10) NOT NULL,
            signal VARCHAR(10),
            strength INTEGER,
            entry_price REAL,
            stop_loss REAL,
            take_profit REAL,
            trend_score REAL,
            rsi REAL,
            confidence INTEGER,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Insert default account if not exists
    cursor = conn.execute('SELECT COUNT(*) FROM account')
    if cursor.fetchone()[0] == 0:
        conn.execute('INSERT INTO account (initial_balance, current_balance) VALUES (?, ?)', (10000.0, 10000.0))
    conn.commit()
    conn.close()

def calculate_drawdown(initial_balance, current_balance, peak_balance=None):
    if peak_balance is None:
        peak_balance = initial_balance
    if peak_balance <= 0:
        return 0
    drawdown = ((peak_balance - current_balance) / peak_balance) * 100
    return max(0, drawdown)

def calculate_position_size(balance, risk_percent, stop_loss_pips, pip_value=10):
    risk_amount = balance * (risk_percent / 100)
    position_size = risk_amount / (stop_loss_pips * pip_value)
    return round(position_size, 2)

@app.route('/')
@login_required
def index():
    conn = get_db()
    
    # Get or create account for user
    account = conn.execute('SELECT * FROM account WHERE user_id = ?', (session['user_id'],)).fetchone()
    if not account:
        conn.execute('INSERT INTO account (user_id, initial_balance, current_balance) VALUES (?, ?, ?)', 
                    (session['user_id'], 10000.0, 10000.0))
        conn.commit()
        account = conn.execute('SELECT * FROM account WHERE user_id = ?', (session['user_id'],)).fetchone()
    
    trades = conn.execute('SELECT * FROM trades WHERE user_id = ? ORDER BY created_at DESC LIMIT 10', 
                         (session['user_id'],)).fetchall()
    
    # Calculate stats
    all_trades = conn.execute('SELECT * FROM trades WHERE user_id = ? AND status = "closed"', 
                             (session['user_id'],)).fetchall()
    total_trades = len(all_trades)
    winning_trades = len([t for t in all_trades if t['profit_loss'] > 0])
    losing_trades = len([t for t in all_trades if t['profit_loss'] < 0])
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    total_profit = sum([t['profit_loss'] for t in all_trades if t['profit_loss'] > 0])
    total_loss = abs(sum([t['profit_loss'] for t in all_trades if t['profit_loss'] < 0]))
    
    # Calculate drawdown
    current_drawdown = calculate_drawdown(account['initial_balance'], account['current_balance'])
    
    conn.close()
    
    return render_template('index.html', 
                         account=account,
                         trades=trades,
                         total_trades=total_trades,
                         winning_trades=winning_trades,
                         losing_trades=losing_trades,
                         win_rate=round(win_rate, 2),
                         total_profit=round(total_profit, 2),
                         total_loss=round(total_loss, 2),
                         current_drawdown=round(current_drawdown, 2))

@app.route('/update_balance', methods=['POST'])
@login_required
def update_balance():
    initial_balance = float(request.form.get('initial_balance', 10000))
    current_balance = float(request.form.get('current_balance', 10000))
    
    conn = get_db()
    conn.execute('UPDATE account SET initial_balance = ?, current_balance = ? WHERE user_id = ?',
                (initial_balance, current_balance, session['user_id']))
    conn.commit()
    conn.close()
    
    return redirect(url_for('index'))

@app.route('/calculator')
@login_required
def calculator():
    conn = get_db()
    account = conn.execute('SELECT * FROM account WHERE user_id = ?', (session['user_id'],)).fetchone()
    conn.close()
    balance = account['current_balance'] if account else 10000
    return render_template('calculator.html', balance=balance)

@app.route('/calculate_position', methods=['POST'])
@login_required
def calculate_position():
    data = request.get_json()
    balance = float(data.get('balance', 10000))
    risk_percent = float(data.get('risk_percent', 1))
    stop_loss_pips = float(data.get('stop_loss_pips', 50))
    pip_value = float(data.get('pip_value', 10))
    
    position_size = calculate_position_size(balance, risk_percent, stop_loss_pips, pip_value)
    risk_amount = balance * (risk_percent / 100)
    
    return jsonify({
        'position_size': position_size,
        'risk_amount': round(risk_amount, 2),
        'lot_size': position_size
    })

@app.route('/add_trade', methods=['POST'])
@login_required
def add_trade():
    pair = request.form.get('pair', 'EUR/USD')
    trade_type = request.form.get('trade_type', 'buy')
    lot_size = float(request.form.get('lot_size', 0.1))
    entry_price = float(request.form.get('entry_price', 0))
    stop_loss = float(request.form.get('stop_loss', 0)) if request.form.get('stop_loss') else None
    take_profit = float(request.form.get('take_profit', 0)) if request.form.get('take_profit') else None
    risk_percent = float(request.form.get('risk_percent', 0)) if request.form.get('risk_percent') else None
    profit_loss = float(request.form.get('profit_loss', 0)) if request.form.get('profit_loss') else None
    
    conn = get_db()
    conn.execute('''
        INSERT INTO trades (user_id, pair, trade_type, lot_size, entry_price, stop_loss, take_profit, risk_percent, profit_loss)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (session['user_id'], pair, trade_type, lot_size, entry_price, stop_loss, take_profit, risk_percent, profit_loss))
    
    # Update balance if P/L is provided
    if profit_loss:
        conn.execute('UPDATE account SET current_balance = current_balance + ? WHERE user_id = ?', 
                    (profit_loss, session['user_id']))
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('index'))


@app.route('/update_trade/<int:trade_id>', methods=['POST'])
@login_required
def update_trade(trade_id):
    entry_price = float(request.form.get('entry_price', 0))
    lot_size = float(request.form.get('lot_size', 0.1))
    stop_loss = float(request.form.get('stop_loss', 0)) if request.form.get('stop_loss') else None
    take_profit = float(request.form.get('take_profit', 0)) if request.form.get('take_profit') else None
    risk_percent = float(request.form.get('risk_percent', 0)) if request.form.get('risk_percent') else None
    new_profit_loss = float(request.form.get('profit_loss', 0)) if request.form.get('profit_loss') else None
    
    conn = get_db()
    
    # Get old P/L to calculate balance difference
    old_trade = conn.execute('SELECT profit_loss FROM trades WHERE id = ?', (trade_id,)).fetchone()
    old_pl = old_trade['profit_loss'] if old_trade and old_trade['profit_loss'] else 0
    
    # Update trade
    conn.execute('''
        UPDATE trades SET entry_price = ?, lot_size = ?, stop_loss = ?, take_profit = ?, 
        risk_percent = ?, profit_loss = ? WHERE id = ?
    ''', (entry_price, lot_size, stop_loss, take_profit, risk_percent, new_profit_loss, trade_id))
    
    # Update balance with difference
    pl_diff = (new_profit_loss or 0) - old_pl
    if pl_diff != 0:
        conn.execute('UPDATE account SET current_balance = current_balance + ? WHERE user_id = ?', 
                    (pl_diff, session['user_id']))
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('index'))

@app.route('/close_trade/<int:trade_id>', methods=['POST'])
@login_required
def close_trade(trade_id):
    exit_price = float(request.form.get('exit_price', 0))
    
    conn = get_db()
    trade = conn.execute('SELECT * FROM trades WHERE id = ?', (trade_id,)).fetchone()
    
    if trade:
        # Calculate P/L (simplified calculation)
        pip_difference = exit_price - trade['entry_price']
        if trade['trade_type'] == 'sell':
            pip_difference = -pip_difference
        
        # Assuming standard lot (100,000 units) and pip value of $10 per standard lot
        profit_loss = pip_difference * 10000 * trade['lot_size']
        
        conn.execute('''
            UPDATE trades SET exit_price = ?, profit_loss = ?, status = 'closed', closed_at = ?
            WHERE id = ?
        ''', (exit_price, profit_loss, datetime.now(), trade_id))
        
        # Update account balance
        conn.execute('UPDATE account SET current_balance = current_balance + ? WHERE user_id = ?', 
                    (profit_loss, session['user_id']))
        conn.commit()
    
    conn.close()
    return redirect(url_for('index'))

@app.route('/delete_trade/<int:trade_id>', methods=['POST'])
@login_required
def delete_trade(trade_id):
    conn = get_db()
    
    # Get P/L to reverse from balance
    trade = conn.execute('SELECT profit_loss FROM trades WHERE id = ?', (trade_id,)).fetchone()
    if trade and trade['profit_loss']:
        conn.execute('UPDATE account SET current_balance = current_balance - ? WHERE user_id = ?', 
                    (trade['profit_loss'], session['user_id']))
    
    conn.execute('DELETE FROM trades WHERE id = ?', (trade_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/prediction')
@login_required
def prediction():
    return render_template('prediction.html')

@app.route('/analyze', methods=['POST'])
@login_required
def analyze():
    data = request.get_json()
    prices_str = data.get('prices', '')
    
    # Parse prices from comma-separated string or use sample data
    if prices_str.strip():
        try:
            prices = [float(p.strip()) for p in prices_str.split(',') if p.strip()]
        except ValueError:
            return jsonify({'error': 'Invalid price format. Use comma-separated numbers.'}), 400
    else:
        # Generate sample data for demo
        base_price = float(data.get('base_price', 1.1000))
        prices = generate_sample_prices(base_price, 50)
    
    if len(prices) < 2:
        return jsonify({'error': 'Need at least 2 price points'}), 400
    
    # Get signal analysis
    result = get_signal(prices)
    result['prices'] = prices
    
    return jsonify(result)

@app.route('/calculate_indicators', methods=['POST'])
@login_required
def calculate_indicators():
    data = request.get_json()
    prices_str = data.get('prices', '')
    
    try:
        prices = [float(p.strip()) for p in prices_str.split(',') if p.strip()]
    except ValueError:
        return jsonify({'error': 'Invalid price format'}), 400
    
    if len(prices) < 20:
        return jsonify({'error': 'Need at least 20 price points for indicators'}), 400
    
    # Calculate individual indicators
    sma_20 = calculate_sma(prices, 20)
    ema_12 = calculate_ema(prices, 12)
    rsi = calculate_rsi(prices, 14)
    macd, signal, histogram = calculate_macd(prices)
    upper_bb, middle_bb, lower_bb = calculate_bollinger_bands(prices)
    
    return jsonify({
        'current_price': prices[-1],
        'sma_20': sma_20,
        'ema_12': ema_12,
        'rsi': rsi,
        'macd': macd,
        'macd_signal': signal,
        'macd_histogram': histogram,
        'bollinger_upper': upper_bb,
        'bollinger_middle': middle_bb,
        'bollinger_lower': lower_bb
    })

@app.route('/fetch_prices', methods=['POST'])
@login_required
def fetch_prices():
    """Fetch live price data from Yahoo Finance"""
    data = request.get_json()
    pair = data.get('pair', 'EUR/USD')
    period = data.get('period', '1mo')  # 1d, 5d, 1mo, 3mo, 6mo, 1y
    interval = data.get('interval', '1h')  # 1m, 5m, 15m, 30m, 1h, 1d
    
    ticker_symbol = FOREX_TICKERS.get(pair)
    if not ticker_symbol:
        return jsonify({'error': f'Unknown pair: {pair}'}), 400
    
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period=period, interval=interval)
        
        if df.empty:
            return jsonify({'error': 'No data available for this pair'}), 400
        
        prices = df['Close'].tolist()
        dates = df.index.strftime('%Y-%m-%d %H:%M').tolist()
        
        # Get current info
        current_price = prices[-1] if prices else 0
        high = df['High'].max()
        low = df['Low'].min()
        
        return jsonify({
            'pair': pair,
            'ticker': ticker_symbol,
            'prices': prices,
            'dates': dates,
            'current_price': round(current_price, 5),
            'high': round(high, 5),
            'low': round(low, 5),
            'data_points': len(prices),
            'period': period,
            'interval': interval
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/analyze_live', methods=['POST'])
@login_required
def analyze_live():
    """Fetch live data and analyze with technical indicators"""
    
    # Check free tier limit (5 analyses per month)
    can_use, remaining = check_free_tier_limit(session['user_id'], 'prediction_analyze', 5)
    if not can_use:
        return jsonify({
            'error': 'Monthly limit reached (5/5). Upgrade to Basic or Pro for unlimited analyses.',
            'limit_reached': True,
            'remaining': 0
        }), 403
    
    data = request.get_json()
    pair = data.get('pair', 'EUR/USD')
    period = data.get('period', '1mo')
    interval = data.get('interval', '1h')
    
    ticker_symbol = FOREX_TICKERS.get(pair)
    if not ticker_symbol:
        return jsonify({'error': f'Unknown pair: {pair}'}), 400
    
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period=period, interval=interval)
        
        if df.empty:
            return jsonify({'error': 'No data available'}), 400
        
        prices = df['Close'].tolist()
        dates = df.index.strftime('%Y-%m-%d %H:%M').tolist()
        
        if len(prices) < 30:
            return jsonify({'error': 'Not enough data points for analysis (need 30+)'}), 400
        
        # Track usage for free tier
        track_usage(session['user_id'], 'prediction_analyze')
        
        # Get signal analysis
        result = get_signal(prices)
        result['prices'] = prices
        result['dates'] = dates
        result['pair'] = pair
        result['period'] = period
        result['interval'] = interval
        result['data_points'] = len(prices)
        result['remaining_analyses'] = remaining - 1 if remaining > 0 else -1
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/available_pairs')
def available_pairs():
    """Return list of available forex pairs"""
    return jsonify(list(FOREX_TICKERS.keys()))


@app.route('/get_current_price', methods=['POST'])
@login_required
def get_current_price():
    """Get current price for a trading pair"""
    data = request.get_json()
    pair = data.get('pair', 'EUR/USD')
    
    ticker_symbol = FOREX_TICKERS.get(pair)
    if not ticker_symbol:
        return jsonify({'error': f'Unknown pair: {pair}'}), 400
    
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period='1d', interval='1m')
        
        if df.empty:
            # Try with longer period
            df = ticker.history(period='5d', interval='1h')
        
        if df.empty:
            return jsonify({'error': 'No data available'}), 400
        
        current_price = df['Close'].iloc[-1]
        
        return jsonify({
            'pair': pair,
            'price': round(current_price, 5),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/ict')
@login_required
@subscription_required('basic')
def ict():
    """ICT Analysis Page"""
    conn = get_db()
    account = conn.execute('SELECT * FROM account WHERE user_id = ?', (session['user_id'],)).fetchone()
    user = conn.execute('SELECT subscription_plan FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    balance = account['current_balance'] if account else 10000
    subscription = (user['subscription_plan'] or 'free').upper() if user else 'FREE'
    return render_template('ict.html', balance=balance, subscription=subscription)

@app.route('/analyze_ict', methods=['POST'])
@login_required
def analyze_ict_route():
    """
    Simple ICT Weekly Bias Analysis
    1. Get Previous Week High/Low
    2. Determine bias
    3. Find OB/FVG on LTF for entry
    """
    data = request.get_json()
    pair = data.get('pair', 'EUR/USD')
    period = data.get('period', '1mo')
    interval = data.get('interval', '15m')
    balance = float(data.get('balance', 10000))
    risk_percent = float(data.get('risk_percent', 1.0))
    user_id = session.get('user_id')
    
    ticker_symbol = FOREX_TICKERS.get(pair)
    if not ticker_symbol:
        return jsonify({'error': f'Unknown pair: {pair}'}), 400
    
    try:
        # Get previous analysis from cache
        conn = get_db()
        prev_analysis = conn.execute('''
            SELECT signal, strength, entry_price, trend_score, created_at 
            FROM analysis_cache 
            WHERE user_id = ? AND analysis_type = 'ict' AND pair = ? AND timeframe = ?
            ORDER BY created_at DESC LIMIT 1
        ''', (user_id, pair, interval)).fetchone()
        
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period=period, interval=interval)
        
        if df.empty:
            conn.close()
            return jsonify({'error': 'No data available'}), 400
        
        opens = df['Open'].tolist()
        highs = df['High'].tolist()
        lows = df['Low'].tolist()
        closes = df['Close'].tolist()
        dates = df.index.strftime('%Y-%m-%d %H:%M').tolist()
        
        if len(closes) < 20:
            conn.close()
            return jsonify({'error': 'Not enough data'}), 400
        
        # Run ICT analysis
        result = analyze_ict(opens, highs, lows, closes, balance, risk_percent, interval)
        
        # Extract signal for caching
        bias = result.get('bias', {})
        signal = bias.get('direction', 'NEUTRAL')
        if signal == 'BULLISH':
            signal = 'BUY'
        elif signal == 'BEARISH':
            signal = 'SELL'
        else:
            signal = 'WAIT'
        
        strength = bias.get('confidence', 0)
        entry_price = result.get('trade_setup', {}).get('entry', 0)
        
        # Save to cache
        conn.execute('''
            INSERT INTO analysis_cache 
            (user_id, analysis_type, pair, timeframe, signal, strength, entry_price, trend_score, confidence)
            VALUES (?, 'ict', ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, pair, interval, signal, strength, entry_price, strength, strength))
        conn.commit()
        
        # Add previous analysis to result
        if prev_analysis:
            result['previous'] = {
                'signal': prev_analysis['signal'],
                'strength': prev_analysis['strength'],
                'entry_price': prev_analysis['entry_price'],
                'analyzed_at': prev_analysis['created_at']
            }
            result['signal_changed'] = (prev_analysis['signal'] != signal)
        else:
            result['previous'] = None
            result['signal_changed'] = False
        
        conn.close()
        
        # Add chart data
        result['pair'] = pair
        result['dates'] = dates
        result['ohlc'] = {
            'opens': opens,
            'highs': highs,
            'lows': lows,
            'closes': closes
        }
        result['current_signal'] = signal
        result['analyzed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify(result)
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


@app.route('/send_telegram_alert', methods=['POST'])
@login_required
def send_telegram_alert():
    """Send ICT analysis alert to Telegram with chart"""
    try:
        data = request.get_json()
        
        # Get user's Telegram settings
        conn = get_db()
        user = conn.execute('SELECT telegram_bot_token, telegram_chat_id, subscription_plan FROM users WHERE id = ?', 
                           (session['user_id'],)).fetchone()
        conn.close()
        
        bot_token = user['telegram_bot_token'] if user and user['telegram_bot_token'] else TELEGRAM_BOT_TOKEN
        chat_id = user['telegram_chat_id'] if user and user['telegram_chat_id'] else TELEGRAM_CHAT_ID
        
        if not bot_token or not chat_id:
            return jsonify({'error': 'Telegram not configured. Please set your Bot Token and Chat ID in settings.'}), 400
        
        # Build the message
        pair = data.get('pair', 'N/A')
        bias = data.get('bias', 'N/A')
        confidence = data.get('confidence', 0)
        current_price = data.get('current_price', 'N/A')
        pwh = data.get('pwh', 'N/A')
        pwl = data.get('pwl', 'N/A')
        signal = data.get('signal', 'N/A')
        entry = data.get('entry', 'N/A')
        sl = data.get('stop_loss', 'N/A')
        tp = data.get('take_profit', 'N/A')
        rr = data.get('risk_reward', 'N/A')
        subscription = (user['subscription_plan'] or 'free').upper() if user else 'FREE'
        
        # Format message
        message = f"""
🔔 *ICT ANALYSIS ALERT*
━━━━━━━━━━━━━━━━━━

📊 *Pair:* `{pair}`
📈 *Bias:* `{bias}` ({confidence}%)
💰 *Current Price:* `{current_price}`

📉 *Weekly Levels:*
   • PWH: `{pwh}`
   • PWL: `{pwl}`

🎯 *Trade Setup:*
   • Signal: `{signal}`
   • Entry: `{entry}`
   • Stop Loss: `{sl}`
   • Take Profit: `{tp}`
   • Risk/Reward: `{rr}`

━━━━━━━━━━━━━━━━━━
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
👤 {subscription} Plan
"""
        
        # Check if image data is provided
        image_data = data.get('image')
        
        if image_data:
            # Remove data URL prefix if present
            if ',' in image_data:
                image_data = image_data.split(',')[1]
            
            # Decode base64 image
            image_bytes = base64.b64decode(image_data)
            
            # Send photo with caption
            url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            files = {'photo': ('chart.png', io.BytesIO(image_bytes), 'image/png')}
            payload = {'chat_id': chat_id, 'caption': message, 'parse_mode': 'Markdown'}
            
            response = requests.post(url, data=payload, files=files, timeout=30)
        else:
            # Send text only
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown'}
            
            response = requests.post(url, json=payload, timeout=30)
        
        if response.status_code == 200:
            return jsonify({'success': True, 'message': 'Alert sent to Telegram!'})
        else:
            return jsonify({'error': f'Telegram API error: {response.text}'}), 400
            
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


@app.route('/send_ml_telegram_alert', methods=['POST'])
@login_required
def send_ml_telegram_alert():
    """Send ML Predict analysis alert to Telegram with chart"""
    try:
        data = request.get_json()
        
        # Get user's Telegram settings
        conn = get_db()
        user = conn.execute('SELECT telegram_bot_token, telegram_chat_id, subscription_plan FROM users WHERE id = ?', 
                           (session['user_id'],)).fetchone()
        conn.close()
        
        bot_token = user['telegram_bot_token'] if user and user['telegram_bot_token'] else TELEGRAM_BOT_TOKEN
        chat_id = user['telegram_chat_id'] if user and user['telegram_chat_id'] else TELEGRAM_CHAT_ID
        
        if not bot_token or not chat_id:
            return jsonify({'error': 'Telegram not configured. Please set your Bot Token and Chat ID in settings.'}), 400
        
        # Build the message
        pair = data.get('pair', 'N/A')
        signal = data.get('signal', 'WAIT')
        confidence = data.get('confidence', 0)
        current_price = data.get('current_price', 'N/A')
        entry = data.get('entry', 'N/A')
        sl = data.get('stop_loss', 'N/A')
        tp = data.get('take_profit', 'N/A')
        rr = data.get('risk_reward', 'N/A')
        lots = data.get('lots', 'N/A')
        trend_score = data.get('trend_score', 0)
        rsi = data.get('rsi', 'N/A')
        reason = data.get('reason', 'N/A')
        subscription = (user['subscription_plan'] or 'free').upper() if user else 'FREE'
        
        # Signal emoji
        signal_emoji = '🟢' if signal == 'BUY' else '🔴' if signal == 'SELL' else '🟡'
        
        # Format message
        message = f"""
🤖 *ML PREDICT ALERT*
━━━━━━━━━━━━━━━━━━

📊 *Pair:* `{pair}`
{signal_emoji} *Signal:* `{signal}` ({confidence}%)
💰 *Current Price:* `{current_price}`

📈 *Indicators:*
   • Trend Score: `{trend_score}`
   • RSI: `{rsi}`

🎯 *Trade Setup:*
   • Entry: `{entry}`
   • Stop Loss: `{sl}`
   • Take Profit: `{tp}`
   • Risk/Reward: `{rr}`
   • Lot Size: `{lots}`

📝 *Reason:* _{reason}_

━━━━━━━━━━━━━━━━━━
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
👤 {subscription} Plan
"""
        
        # Check if image data is provided
        image_data = data.get('image')
        
        if image_data:
            # Remove data URL prefix if present
            if ',' in image_data:
                image_data = image_data.split(',')[1]
            
            # Decode base64 image
            image_bytes = base64.b64decode(image_data)
            
            # Send photo with caption
            url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            files = {'photo': ('chart.png', io.BytesIO(image_bytes), 'image/png')}
            payload = {'chat_id': chat_id, 'caption': message, 'parse_mode': 'Markdown'}
            
            response = requests.post(url, data=payload, files=files, timeout=30)
        else:
            # Send text only
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown'}
            
            response = requests.post(url, json=payload, timeout=30)
        
        if response.status_code == 200:
            return jsonify({'success': True, 'message': 'Alert sent to Telegram!'})
        else:
            return jsonify({'error': f'Telegram API error: {response.text}'}), 400
            
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


@app.route('/ml_predict')
@login_required
@subscription_required('pro')
def ml_predict():
    """ML Prediction Page"""
    conn = get_db()
    account = conn.execute('SELECT * FROM account WHERE user_id = ?', (session['user_id'],)).fetchone()
    user = conn.execute('SELECT subscription_plan FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    balance = account['current_balance'] if account else 10000
    subscription = (user['subscription_plan'] or 'free').upper() if user else 'FREE'
    return render_template('ml_predict.html', balance=balance, subscription=subscription)

@app.route('/analyze_ml', methods=['POST'])
@login_required
def analyze_ml():
    """
    ML-based Entry, TP, SL Prediction
    Uses technical indicators and pattern recognition
    """
    import json as json_lib
    
    data = request.get_json()
    pair = data.get('pair', 'EUR/USD')
    period = data.get('period', '1mo')
    interval = data.get('interval', '1h')
    balance = float(data.get('balance', 10000))
    risk_percent = float(data.get('risk_percent', 1.0))
    user_id = session.get('user_id')
    
    ticker_symbol = FOREX_TICKERS.get(pair)
    if not ticker_symbol:
        return jsonify({'error': f'Unknown pair: {pair}'}), 400
    
    try:
        # Get previous analysis from cache
        conn = get_db()
        prev_analysis = conn.execute('''
            SELECT signal, strength, entry_price, trend_score, rsi, created_at 
            FROM analysis_cache 
            WHERE user_id = ? AND analysis_type = 'ml' AND pair = ? AND timeframe = ?
            ORDER BY created_at DESC LIMIT 1
        ''', (user_id, pair, interval)).fetchone()
        
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period=period, interval=interval)
        
        if df.empty:
            conn.close()
            return jsonify({'error': 'No data available'}), 400
        
        opens = df['Open'].tolist()
        highs = df['High'].tolist()
        lows = df['Low'].tolist()
        closes = df['Close'].tolist()
        dates = df.index.strftime('%Y-%m-%d %H:%M').tolist()
        
        if len(closes) < 50:
            conn.close()
            return jsonify({'error': 'Not enough data (need at least 50 candles)'}), 400
        
        # Run ML prediction
        result = predict_forex(opens, highs, lows, closes, balance, risk_percent)
        
        # Extract main prediction for caching
        main_pred = result['predictions'][0] if result.get('predictions') else {}
        signal = main_pred.get('direction', 'WAIT')
        strength = main_pred.get('confidence', 0)
        entry_price = main_pred.get('entry', 0)
        stop_loss = main_pred.get('stop_loss', 0)
        take_profit = main_pred.get('take_profit', 0)
        trend_score = result.get('trend_score', 0)
        rsi = result.get('features', {}).get('rsi', 0)
        
        # Save to cache
        conn.execute('''
            INSERT INTO analysis_cache 
            (user_id, analysis_type, pair, timeframe, signal, strength, entry_price, stop_loss, take_profit, trend_score, rsi, confidence)
            VALUES (?, 'ml', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, pair, interval, signal, strength, entry_price, stop_loss, take_profit, trend_score, rsi, strength))
        conn.commit()
        
        # Add previous analysis to result
        if prev_analysis:
            result['previous'] = {
                'signal': prev_analysis['signal'],
                'strength': prev_analysis['strength'],
                'entry_price': prev_analysis['entry_price'],
                'trend_score': prev_analysis['trend_score'],
                'rsi': prev_analysis['rsi'],
                'analyzed_at': prev_analysis['created_at']
            }
            # Check signal consistency
            result['signal_changed'] = (prev_analysis['signal'] != signal)
        else:
            result['previous'] = None
            result['signal_changed'] = False
        
        conn.close()
        
        # Add chart data
        result['pair'] = pair
        result['dates'] = dates
        result['ohlc'] = {
            'opens': opens,
            'highs': highs,
            'lows': lows,
            'closes': closes
        }
        result['period'] = period
        result['interval'] = interval
        result['analyzed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify(result)
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500

@app.route('/arima')
@login_required
@subscription_required('pro')
def arima_page():
    """ARIMA Analysis Page"""
    conn = get_db()
    account = conn.execute('SELECT * FROM account WHERE user_id = ?', (session['user_id'],)).fetchone()
    conn.close()
    balance = account['current_balance'] if account else 10000
    return render_template('arima.html', balance=balance)

@app.route('/analyze_arima', methods=['POST'])
@login_required
def analyze_arima():
    """
    ARIMA Time Series Analysis and Prediction
    """
    data = request.get_json()
    pair = data.get('pair', 'EUR/USD')
    period = data.get('period', '3mo')
    interval = data.get('interval', '1d')
    forecast_periods = int(data.get('forecast_periods', 5))
    
    ticker_symbol = FOREX_TICKERS.get(pair)
    if not ticker_symbol:
        return jsonify({'error': f'Unknown pair: {pair}'}), 400
    
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period=period, interval=interval)
        
        if df.empty:
            return jsonify({'error': 'No data available'}), 400
        
        closes = df['Close'].tolist()
        dates = df.index.strftime('%Y-%m-%d %H:%M').tolist()
        
        if len(closes) < 30:
            return jsonify({'error': 'Not enough data (need at least 30 candles)'}), 400
        
        # Calculate ARIMA metrics
        metrics = calculate_arima_metrics(closes)
        
        # Get predictions
        predictions, error = get_arima_prediction(closes, periods=forecast_periods)
        if error:
            return jsonify({'error': error}), 400
        
        # Calculate confidence intervals
        confidence = calculate_forecast_confidence(closes, predictions)
        
        # Backtest
        backtest, bt_error = backtest_arima(closes)
        
        # Trading signal
        signal = get_trading_signal(closes, predictions)
        
        # Generate forecast dates
        last_date = df.index[-1]
        forecast_dates = []
        for i in range(1, forecast_periods + 1):
            if interval == '1d':
                next_date = last_date + timedelta(days=i)
            elif interval == '1h':
                next_date = last_date + timedelta(hours=i)
            elif interval == '4h':
                next_date = last_date + timedelta(hours=4*i)
            elif interval == '1wk':
                next_date = last_date + timedelta(weeks=i)
            else:
                next_date = last_date + timedelta(days=i)
            forecast_dates.append(next_date.strftime('%Y-%m-%d %H:%M'))
        
        return jsonify({
            'pair': pair,
            'period': period,
            'interval': interval,
            'current_price': round(closes[-1], 5),
            'metrics': metrics,
            'predictions': predictions,
            'confidence': confidence,
            'forecast_dates': forecast_dates,
            'backtest': backtest,
            'signal': signal,
            'historical': {
                'dates': dates,
                'prices': closes
            }
        })
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


@app.route('/generate_macro_report', methods=['POST'])
@login_required
@subscription_required('pro')
def generate_macro_report():
    """Generate Macroeconomic Review PDF Report"""
    try:
        data = request.get_json()
        pair = data.get('pair', 'EUR/USD')
        chart_image = data.get('chart_image')  # Base64 chart image
        
        # Get user info
        user = get_current_user()
        
        # Fetch economic data from Yahoo Finance
        ticker_symbol = FOREX_TICKERS.get(pair)
        if not ticker_symbol:
            return jsonify({'error': f'Unknown pair: {pair}'}), 400
        
        # Get historical data for analysis
        ticker = yf.Ticker(ticker_symbol)
        df_daily = ticker.history(period='6mo', interval='1d')
        df_weekly = ticker.history(period='2y', interval='1wk')
        
        if df_daily.empty:
            return jsonify({'error': 'No data available'}), 400
        
        closes_daily = df_daily['Close'].tolist()
        closes_weekly = df_weekly['Close'].tolist()
        
        # Fetch major indices for macro context
        indices_data = {}
        indices = {
            'DXY': 'DX-Y.NYB',  # US Dollar Index
            'Gold': 'GC=F',
            'Oil': 'CL=F',
            'S&P500': '^GSPC',
            'VIX': '^VIX'
        }
        
        for name, symbol in indices.items():
            try:
                idx = yf.Ticker(symbol)
                hist = idx.history(period='1mo')
                if not hist.empty:
                    current = hist['Close'].iloc[-1]
                    prev = hist['Close'].iloc[0]
                    change_pct = ((current - prev) / prev) * 100
                    indices_data[name] = {
                        'current': round(current, 2),
                        'change': round(change_pct, 2)
                    }
            except:
                pass
        
        # Calculate technical metrics
        from arima_predictor import get_arima_prediction, get_trading_signal, backtest_arima
        
        predictions, _ = get_arima_prediction(closes_daily, periods=5)
        signal = get_trading_signal(closes_daily, predictions)
        backtest, _ = backtest_arima(closes_daily)
        
        # Calculate additional metrics
        current_price = closes_daily[-1]
        price_1w = closes_daily[-5] if len(closes_daily) >= 5 else closes_daily[0]
        price_1m = closes_daily[-22] if len(closes_daily) >= 22 else closes_daily[0]
        price_3m = closes_daily[-66] if len(closes_daily) >= 66 else closes_daily[0]
        
        change_1w = ((current_price - price_1w) / price_1w) * 100
        change_1m = ((current_price - price_1m) / price_1m) * 100
        change_3m = ((current_price - price_3m) / price_3m) * 100
        
        # Calculate volatility
        import numpy as np
        returns = np.diff(closes_daily) / closes_daily[:-1]
        volatility = np.std(returns) * np.sqrt(252) * 100  # Annualized
        
        # Support/Resistance levels
        high_3m = max(closes_daily[-66:]) if len(closes_daily) >= 66 else max(closes_daily)
        low_3m = min(closes_daily[-66:]) if len(closes_daily) >= 66 else min(closes_daily)
        
        # Generate PDF
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1*cm, bottomMargin=1*cm)
        
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name='MainTitle', fontSize=22, spaceAfter=10, alignment=TA_CENTER, textColor=colors.HexColor('#1a365d')))
        styles.add(ParagraphStyle(name='SectionTitle', fontSize=12, spaceAfter=4, spaceBefore=8, textColor=colors.HexColor('#2c5282'), fontName='Helvetica-Bold'))
        styles.add(ParagraphStyle(name='SubTitle', fontSize=10, spaceAfter=4, textColor=colors.HexColor('#4a5568'), fontName='Helvetica-Bold'))
        styles.add(ParagraphStyle(name='CustomBody', fontSize=9, spaceAfter=3, textColor=colors.HexColor('#2d3748')))
        styles.add(ParagraphStyle(name='SmallText', fontSize=8, textColor=colors.HexColor('#718096')))
        styles.add(ParagraphStyle(name='Disclaimer', fontSize=7, textColor=colors.HexColor('#a0aec0'), alignment=TA_CENTER))
        
        elements = []
        
        # Header
        elements.append(Paragraph("MACROECONOMIC REVIEW", styles['MainTitle']))
        elements.append(Paragraph(f"{pair} Analysis Report", styles['SubTitle']))
        elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | User: {user['name']} | Plan: {(user['subscription_plan'] or 'free').upper()}", styles['SmallText']))
        elements.append(Spacer(1, 10))
        
        # Executive Summary
        elements.append(Paragraph("1. EXECUTIVE SUMMARY", styles['SectionTitle']))
        
        signal_text = signal.get('direction', 'NEUTRAL')
        signal_color = '#38a169' if signal_text == 'BUY' else '#e53e3e' if signal_text == 'SELL' else '#d69e2e'
        
        summary = f"""
        <b>Current Price:</b> {current_price:.5f}<br/>
        <b>Trading Signal:</b> <font color="{signal_color}"><b>{signal_text}</b></font> (Confidence: {signal.get('confidence', 0)}%)<br/>
        <b>Trend:</b> {signal.get('trend', 'N/A')}<br/>
        <b>Annualized Volatility:</b> {volatility:.2f}%<br/>
        """
        elements.append(Paragraph(summary, styles['CustomBody']))
        elements.append(Spacer(1, 5))
        
        # Add Chart Image if provided
        if chart_image:
            try:
                # Remove data URL prefix if present
                if ',' in chart_image:
                    chart_image = chart_image.split(',')[1]
                
                # Decode base64 image
                chart_bytes = base64.b64decode(chart_image)
                chart_buffer = io.BytesIO(chart_bytes)
                
                # Add chart to PDF
                elements.append(Paragraph("PRICE CHART", styles['SectionTitle']))
                chart_img = Image(chart_buffer, width=14*cm, height=6*cm)
                chart_img.hAlign = 'CENTER'
                elements.append(chart_img)
                elements.append(Spacer(1, 8))
            except Exception as e:
                pass  # Skip chart if error
        
        # Price Performance Table
        elements.append(Paragraph("2. PRICE PERFORMANCE", styles['SectionTitle']))
        
        perf_data = [
            ['Period', 'Price', 'Change %'],
            ['Current', f'{current_price:.5f}', '-'],
            ['1 Week Ago', f'{price_1w:.5f}', f'{change_1w:+.2f}%'],
            ['1 Month Ago', f'{price_1m:.5f}', f'{change_1m:+.2f}%'],
            ['3 Months Ago', f'{price_3m:.5f}', f'{change_3m:+.2f}%'],
        ]
        
        perf_table = Table(perf_data, colWidths=[3*cm, 4*cm, 3*cm])
        perf_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#edf2f7')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
        ]))
        elements.append(perf_table)
        elements.append(Spacer(1, 8))
        
        # Key Levels
        elements.append(Paragraph("3. KEY TECHNICAL LEVELS", styles['SectionTitle']))
        
        levels_data = [
            ['Level Type', 'Price'],
            ['3-Month High (Resistance)', f'{high_3m:.5f}'],
            ['3-Month Low (Support)', f'{low_3m:.5f}'],
            ['Entry Point', f'{signal.get("entry", "N/A")}'],
            ['Stop Loss', f'{signal.get("stop_loss", "N/A")}'],
            ['Take Profit', f'{signal.get("take_profit", "N/A")}'],
        ]
        
        levels_table = Table(levels_data, colWidths=[5*cm, 5*cm])
        levels_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#edf2f7')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
        ]))
        elements.append(levels_table)
        elements.append(Spacer(1, 8))
        
        # Market Context
        elements.append(Paragraph("4. MARKET CONTEXT (Macro Indicators)", styles['SectionTitle']))
        
        if indices_data:
            macro_data = [['Indicator', 'Current', 'Monthly Change']]
            for name, vals in indices_data.items():
                change_color = 'green' if vals['change'] >= 0 else 'red'
                macro_data.append([name, f"{vals['current']}", f"{vals['change']:+.2f}%"])
            
            macro_table = Table(macro_data, colWidths=[4*cm, 3*cm, 3*cm])
            macro_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#edf2f7')),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
            ]))
            elements.append(macro_table)
        else:
            elements.append(Paragraph("Market data temporarily unavailable.", styles['CustomBody']))
        elements.append(Spacer(1, 8))
        
        # Page break before ARIMA Forecast
        elements.append(PageBreak())
        
        # ARIMA Forecast
        elements.append(Paragraph("5. ARIMA FORECAST (5-Day Projection)", styles['SectionTitle']))
        
        if predictions:
            forecast_data = [['Day', 'Predicted Price', 'Direction']]
            for i, pred in enumerate(predictions[:5], 1):
                direction = '↑' if pred > current_price else '↓' if pred < current_price else '→'
                forecast_data.append([f'Day {i}', f'{pred:.5f}', direction])
            
            forecast_table = Table(forecast_data, colWidths=[3*cm, 4*cm, 3*cm])
            forecast_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#edf2f7')),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
            ]))
            elements.append(forecast_table)
        elements.append(Spacer(1, 8))
        
        # Backtest Results
        elements.append(Paragraph("6. MODEL PERFORMANCE (Backtest)", styles['SectionTitle']))
        
        if backtest:
            bt_text = f"""
            <b>Direction Accuracy:</b> {backtest.get('accuracy', 0):.1f}%<br/>
            <b>RMSE:</b> {backtest.get('rmse', 0):.5f}<br/>
            <b>MAPE:</b> {backtest.get('mape', 0):.2f}%<br/>
            <b>Test Period:</b> {backtest.get('test_size', 0)} candles<br/>
            """
            elements.append(Paragraph(bt_text, styles['CustomBody']))
        elements.append(Spacer(1, 8))
        
        # Analysis & Recommendation
        elements.append(Paragraph("7. ANALYSIS & RECOMMENDATION", styles['SectionTitle']))
        
        # Generate analysis text based on data
        if signal_text == 'BUY':
            analysis = f"""
            Based on our ARIMA model analysis, {pair} shows <b>bullish momentum</b>. 
            The price is trending upward with a {signal.get('confidence', 0)}% confidence level.
            Key support at {low_3m:.5f} provides a solid floor, while resistance at {high_3m:.5f} 
            is the next target. Consider entering long positions with proper risk management.
            """
        elif signal_text == 'SELL':
            analysis = f"""
            Based on our ARIMA model analysis, {pair} shows <b>bearish pressure</b>. 
            The price is trending downward with a {signal.get('confidence', 0)}% confidence level.
            Key resistance at {high_3m:.5f} caps upside, while support at {low_3m:.5f} 
            is the next target. Consider short positions with proper risk management.
            """
        else:
            analysis = f"""
            Based on our ARIMA model analysis, {pair} is in a <b>consolidation phase</b>. 
            The market shows mixed signals with no clear directional bias.
            Wait for a breakout above {high_3m:.5f} for bullish confirmation, 
            or below {low_3m:.5f} for bearish confirmation. Avoid trading until clearer signals emerge.
            """
        
        elements.append(Paragraph(analysis, styles['CustomBody']))
        elements.append(Spacer(1, 10))
        
        # Disclaimer
        elements.append(Paragraph("─" * 60, styles['SmallText']))
        elements.append(Paragraph(
            "DISCLAIMER: This report is for educational purposes only and does not constitute financial advice. "
            "Trading forex involves significant risk of loss. Past performance is not indicative of future results. "
            "Always conduct your own research and consult with a licensed financial advisor before making investment decisions.",
            styles['Disclaimer']
        ))
        
        # Build PDF
        doc.build(elements)
        
        # Get PDF content
        pdf_content = buffer.getvalue()
        buffer.close()
        
        # Return PDF as base64
        pdf_base64 = base64.b64encode(pdf_content).decode('utf-8')
        
        return jsonify({
            'success': True,
            'pdf': pdf_base64,
            'filename': f'{pair.replace("/", "_")}_Macro_Report_{datetime.now().strftime("%Y%m%d")}.pdf'
        })
        
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


@app.route('/strategies')
@login_required
@subscription_required('pro')
def strategies_page():
    """Jim Simons Inspired Trading Strategies Page"""
    conn = get_db()
    account = conn.execute('SELECT * FROM account WHERE user_id = ?', (session['user_id'],)).fetchone()
    user = conn.execute('SELECT subscription_plan FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    balance = account['current_balance'] if account else 10000
    subscription = (user['subscription_plan'] or 'free').upper() if user else 'FREE'
    return render_template('strategies.html', balance=balance, subscription=subscription)


@app.route('/analyze_strategies', methods=['POST'])
@login_required
def analyze_strategies_route():
    """
    Analyze using Jim Simons inspired quantitative strategies
    """
    data = request.get_json()
    pair = data.get('pair', 'EUR/USD')
    period = data.get('period', '1mo')
    interval = data.get('interval', '1h')
    balance = float(data.get('balance', 10000))
    risk_percent = float(data.get('risk_percent', 1.0))
    strategy = data.get('strategy', 'ensemble')  # Which strategy to use
    
    ticker_symbol = FOREX_TICKERS.get(pair)
    if not ticker_symbol:
        return jsonify({'error': f'Unknown pair: {pair}'}), 400
    
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period=period, interval=interval)
        
        if df.empty:
            return jsonify({'error': 'No data available'}), 400
        
        opens = df['Open'].tolist()
        highs = df['High'].tolist()
        lows = df['Low'].tolist()
        closes = df['Close'].tolist()
        dates = df.index.strftime('%Y-%m-%d %H:%M').tolist()
        
        if len(closes) < 50:
            return jsonify({'error': 'Not enough data (need at least 50 candles)'}), 400
        
        # Run selected strategy
        if strategy == 'all':
            result = analyze_all_strategies(opens, highs, lows, closes, balance, risk_percent)
        elif strategy == 'mean_reversion':
            strat = MeanReversionStrategy()
            result = strat.analyze(opens, highs, lows, closes, balance, risk_percent)
        elif strategy == 'momentum':
            strat = MomentumStrategy()
            result = strat.analyze(opens, highs, lows, closes, balance, risk_percent)
        elif strategy == 'breakout':
            strat = BreakoutStrategy()
            result = strat.analyze(opens, highs, lows, closes, balance, risk_percent)
        elif strategy == 'volatility':
            strat = VolatilityBreakoutStrategy()
            result = strat.analyze(opens, highs, lows, closes, balance, risk_percent)
        else:  # ensemble (default)
            strat = EnsembleStrategy()
            result = strat.analyze(opens, highs, lows, closes, balance, risk_percent)
        
        # Add chart data
        result['pair'] = pair
        result['dates'] = dates
        result['ohlc'] = {
            'opens': opens,
            'highs': highs,
            'lows': lows,
            'closes': closes
        }
        result['period'] = period
        result['interval'] = interval
        result['analyzed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify(result)
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


@app.route('/send_strategy_telegram_alert', methods=['POST'])
@login_required
def send_strategy_telegram_alert():
    """Send Strategy analysis alert to Telegram"""
    try:
        data = request.get_json()
        
        conn = get_db()
        user = conn.execute('SELECT telegram_bot_token, telegram_chat_id, subscription_plan FROM users WHERE id = ?', 
                           (session['user_id'],)).fetchone()
        conn.close()
        
        bot_token = user['telegram_bot_token'] if user and user['telegram_bot_token'] else TELEGRAM_BOT_TOKEN
        chat_id = user['telegram_chat_id'] if user and user['telegram_chat_id'] else TELEGRAM_CHAT_ID
        
        if not bot_token or not chat_id:
            return jsonify({'error': 'Telegram not configured. Please set your Bot Token and Chat ID in settings.'}), 400
        
        pair = data.get('pair', 'N/A')
        strategy_name = data.get('strategy', 'Ensemble')
        signal = data.get('signal', 'WAIT')
        confidence = data.get('confidence', 0)
        current_price = data.get('current_price', 'N/A')
        entry = data.get('entry', 'N/A')
        sl = data.get('stop_loss', 'N/A')
        tp = data.get('take_profit', 'N/A')
        rr = data.get('risk_reward', 'N/A')
        reason = data.get('reason', 'N/A')
        subscription = (user['subscription_plan'] or 'free').upper() if user else 'FREE'
        
        signal_emoji = '🟢' if signal == 'BUY' else '🔴' if signal == 'SELL' else '🟡'
        
        message = f"""
🧠 *QUANT STRATEGY ALERT*
━━━━━━━━━━━━━━━━━━

📊 *Pair:* `{pair}`
📈 *Strategy:* `{strategy_name}`
{signal_emoji} *Signal:* `{signal}` ({confidence}%)
💰 *Current Price:* `{current_price}`

🎯 *Trade Setup:*
   • Entry: `{entry}`
   • Stop Loss: `{sl}`
   • Take Profit: `{tp}`
   • Risk/Reward: `{rr}`

📝 *Reason:* _{reason}_

━━━━━━━━━━━━━━━━━━
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
👤 {subscription} Plan
"""
        
        image_data = data.get('image')
        
        if image_data:
            if ',' in image_data:
                image_data = image_data.split(',')[1]
            
            image_bytes = base64.b64decode(image_data)
            
            url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            files = {'photo': ('chart.png', io.BytesIO(image_bytes), 'image/png')}
            payload = {'chat_id': chat_id, 'caption': message, 'parse_mode': 'Markdown'}
            
            response = requests.post(url, data=payload, files=files, timeout=30)
        else:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown'}
            
            response = requests.post(url, json=payload, timeout=30)
        
        if response.status_code == 200:
            return jsonify({'success': True, 'message': 'Alert sent to Telegram!'})
        else:
            return jsonify({'error': f'Telegram API error: {response.text}'}), 400
            
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


@app.route('/auto_execution')
@login_required
@subscription_required('pro')
def auto_execution_page():
    """Auto Execution Portfolio Page"""
    user_id = session['user_id']
    
    conn = get_db()
    account = conn.execute('SELECT * FROM account WHERE user_id = ?', (user_id,)).fetchone()
    conn.close()
    
    balance = account['current_balance'] if account else 10000
    
    # Get user stats, settings, executions, and logs
    stats = get_user_stats(user_id)
    settings = get_user_settings(user_id)
    executions = get_user_executions(user_id, 50)
    logs = get_user_logs(user_id, 50)
    
    # Get open positions
    open_positions = [e for e in executions if e.get('status') == 'open']
    
    return render_template('auto_execution.html', 
                          balance=balance,
                          stats=stats,
                          settings=settings,
                          executions=executions,
                          open_positions=open_positions,
                          logs=logs)


@app.route('/scan_execution', methods=['POST'])
@login_required
def scan_execution():
    """Scan markets for execution signals"""
    data = request.get_json()
    pairs = data.get('pairs', ['EUR/USD'])
    period = data.get('period', '1mo')
    interval = data.get('interval', '1h')
    balance = float(data.get('balance', 10000))
    risk_percent = float(data.get('risk_percent', 1.0))
    
    pairs_dict = {}
    for pair in pairs:
        if pair in FOREX_TICKERS:
            pairs_dict[pair] = FOREX_TICKERS[pair]
    
    if not pairs_dict:
        return jsonify({'error': 'No valid pairs selected'}), 400
    
    try:
        signals = get_execution_signals(pairs_dict, period, interval, balance, risk_percent)
        return jsonify({
            'signals': signals,
            'total': len(signals),
            'scanned_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


@app.route('/simulate_portfolio', methods=['POST'])
@login_required
def simulate_portfolio_route():
    """Simulate portfolio performance"""
    data = request.get_json()
    initial_balance = float(data.get('initial_balance', 10000))
    risk_percent = float(data.get('risk_percent', 1.0))
    period = data.get('period', '3mo')
    
    try:
        result = simulate_auto_portfolio(initial_balance, risk_percent, period)
        return jsonify(result)
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


@app.route('/save_auto_settings', methods=['POST'])
@login_required
def save_auto_settings():
    """Save auto execution settings for user"""
    data = request.get_json()
    user_id = session['user_id']
    
    try:
        save_user_settings(user_id, data)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/trigger_manual_scan', methods=['POST'])
@login_required
def trigger_manual_scan():
    """Trigger a manual market scan"""
    user_id = session['user_id']
    
    try:
        scan_markets_for_user(user_id)
        return jsonify({'success': True, 'message': 'Scan completed'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/execute_auto_trade', methods=['POST'])
@login_required
def execute_auto_trade():
    """Execute a trade manually from scan results"""
    data = request.get_json()
    user_id = session['user_id']
    
    try:
        conn = get_db()
        
        # Insert the trade
        conn.execute('''
            INSERT INTO auto_executions 
            (user_id, pair, direction, entry_price, current_price, stop_loss, take_profit, lots, probability, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
        ''', (
            user_id,
            data.get('pair'),
            data.get('direction'),
            data.get('entry'),
            data.get('entry'),
            data.get('stop_loss'),
            data.get('take_profit'),
            data.get('lots', 0.01),
            data.get('probability', 0)
        ))
        
        conn.commit()
        conn.close()
        
        log_action(user_id, 'MANUAL_TRADE_EXECUTED', data.get('pair'),
                  f"{data.get('direction')} @ {data.get('entry')}")
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/close_auto_position/<int:position_id>', methods=['POST'])
@login_required
def close_auto_position(position_id):
    """Close an open position manually"""
    user_id = session['user_id']
    
    try:
        conn = get_db()
        
        # Get the position
        position = conn.execute('''
            SELECT * FROM auto_executions WHERE id = ? AND user_id = ?
        ''', (position_id, user_id)).fetchone()
        
        if not position:
            conn.close()
            return jsonify({'error': 'Position not found'}), 404
        
        # Get current price
        current_price = fetch_pair_price(position['pair'])
        if current_price is None:
            current_price = position['current_price'] or position['entry_price']
        
        direction = position['direction']
        entry_price = position['entry_price']
        lots = position['lots']
        
        # Determine if direction was correct
        if direction == 'BUY':
            is_correct = 1 if current_price > entry_price else 0
            pnl_pips = (current_price - entry_price) / entry_price * 10000
        else:
            is_correct = 1 if current_price < entry_price else 0
            pnl_pips = (entry_price - current_price) / entry_price * 10000
        
        # Calculate P&L
        lot_value = lots * 100000
        pnl = round(pnl_pips * lot_value / 10000, 2)
        
        # Update position
        conn.execute('''
            UPDATE auto_executions 
            SET status = 'closed', exit_price = ?, exit_reason = 'MANUAL', 
                pnl = ?, is_correct = ?, closed_at = ?
            WHERE id = ?
        ''', (current_price, pnl, is_correct, datetime.now(), position_id))
        
        # Update balance
        conn.execute('''
            UPDATE account SET current_balance = current_balance + ? WHERE user_id = ?
        ''', (pnl, user_id))
        
        conn.commit()
        conn.close()
        
        log_action(user_id, 'POSITION_CLOSED_MANUAL', position['pair'],
                  f"Exit: {current_price}, P&L: ${pnl}")
        
        return jsonify({'success': True, 'pnl': pnl, 'is_correct': is_correct})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    init_db()
    init_auto_tables()
    start_scheduler(app)
    app.run(debug=True, port=4976)
