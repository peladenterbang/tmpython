from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3
from datetime import datetime, timedelta
import yfinance as yf
import hashlib
import os
import requests
import base64
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
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

# Upload configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'ico'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB max

# Create upload folder if not exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Fix for reverse proxy (Nginx) - ensures correct URL generation
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Add datetime and site settings to Jinja2 templates
@app.context_processor
def inject_globals():
    site_logo = get_app_setting('site_logo') or '/static/default-logo.png'
    site_name = get_app_setting('site_name') or 'Forex Risk Manager'
    site_favicon = get_app_setting('site_favicon') or '/static/favicon.ico'
    return {
        'now': datetime.now,
        'site_logo': site_logo,
        'site_name': site_name,
        'site_favicon': site_favicon
    }

# Telegram Configuration (User can set their own bot token and chat ID)
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

# Default exchange rate (USD to IDR) - will be updated dynamically
DEFAULT_USD_TO_IDR = 15500


def get_app_setting(key, default=None):
    """Get app setting from database"""
    try:
        conn = sqlite3.connect(DATABASE)
        def _dict_factory(cursor, row):
            return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}
        conn.row_factory = _dict_factory
        result = conn.execute('SELECT setting_value FROM app_settings WHERE setting_key = ?', (key,)).fetchone()
        conn.close()
        return result['setting_value'] if result else default
    except:
        return default


def set_app_setting(key, value):
    """Set app setting in database"""
    try:
        conn = sqlite3.connect(DATABASE)
        conn.execute('''
            INSERT OR REPLACE INTO app_settings (setting_key, setting_value, updated_at) 
            VALUES (?, ?, ?)
        ''', (key, value, datetime.now()))
        conn.commit()
        conn.close()
        return True
    except:
        return False


def get_midtrans_config():
    """Get Midtrans configuration from database"""
    server_key = get_app_setting('midtrans_server_key', 'SB-Mid-server-YOUR_SERVER_KEY')
    client_key = get_app_setting('midtrans_client_key', 'SB-Mid-client-YOUR_CLIENT_KEY')
    is_production = get_app_setting('midtrans_is_production', 'false').lower() == 'true'
    
    if is_production:
        api_url = 'https://app.midtrans.com/snap/v1'
        snap_url = 'https://app.midtrans.com/snap/snap.js'
    else:
        api_url = 'https://app.sandbox.midtrans.com/snap/v1'
        snap_url = 'https://app.sandbox.midtrans.com/snap/snap.js'
    
    return {
        'server_key': server_key,
        'client_key': client_key,
        'is_production': is_production,
        'api_url': api_url,
        'snap_url': snap_url
    }

# Subscription Plans
SUBSCRIPTION_PLANS = {
    'free': {
        'name': 'Free', 
        'price_usd': 0, 
        'days': 0, 
        'features': ['Dashboard Access', 'Position Calculator', '5 Analyses/Day', 'Basic Charts']
    },
    'basic': {
        'name': 'Basic', 
        'price_usd': 9.99, 
        'days': 30, 
        'features': ['All Free Features', 'ICT Analysis', 'ML Predictions', 'Unlimited Analyses', 'Auto Execution (5 pairs)']
    },
    'pro': {
        'name': 'Pro', 
        'price_usd': 29.99, 
        'days': 30, 
        'features': ['All Basic Features', 'ARIMA Forecasting', 'Auto Execution (All pairs)', 'PDF Reports', 'Telegram Alerts', 'Priority Support']
    }
}

# Input validation constants
VALID_PERIODS = {'1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max'}
VALID_INTERVALS = {'1m', '2m', '5m', '15m', '30m', '60m', '90m', '1h', '4h', '1d', '5d', '1wk', '1mo', '3mo'}
VALID_PLANS = {'free', 'basic', 'pro'}
VALID_TRADE_TYPES = {'BUY', 'SELL', 'buy', 'sell'}
VALID_TRADE_STATUS = {'open', 'closed'}


def get_email_config():
    """Get email configuration from database"""
    conn = get_db()
    settings = {}
    rows = conn.execute('SELECT setting_key, setting_value FROM app_settings WHERE setting_key LIKE "smtp_%" OR setting_key = "email_enabled"').fetchall()
    conn.close()
    for row in rows:
        settings[row['setting_key']] = row['setting_value']
    return settings


def get_site_url():
    """Get site URL from database setting or use request host"""
    site_url = get_app_setting('site_url')
    if site_url:
        return site_url.rstrip('/')
    # Fallback: try to get from request (works with ProxyFix)
    try:
        return request.host_url.rstrip('/')
    except:
        return 'http://localhost:5000'


def send_email(to_email, subject, html_content, text_content=None, attachment=None, attachment_name=None):
    """Send email via SMTP (Zoho Mail or other provider)"""
    config = get_email_config()
    
    if config.get('email_enabled', 'false') != 'true':
        return {'success': False, 'message': 'Email sending is disabled'}
    
    smtp_host = config.get('smtp_host', 'smtp.zoho.com')
    smtp_port = int(config.get('smtp_port', '587'))
    smtp_email = config.get('smtp_email', '')
    smtp_password = config.get('smtp_password', '')
    sender_name = config.get('smtp_sender_name', 'Forex Risk Manager')
    
    if not smtp_email or not smtp_password:
        return {'success': False, 'message': 'SMTP credentials not configured'}
    
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = f"{sender_name} <{smtp_email}>"
        msg['To'] = to_email
        msg['Subject'] = subject
        
        if text_content:
            msg.attach(MIMEText(text_content, 'plain'))
        msg.attach(MIMEText(html_content, 'html'))
        
        if attachment and attachment_name:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment)
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{attachment_name}"')
            msg.attach(part)
        
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            server.starttls()
        
        server.login(smtp_email, smtp_password)
        server.sendmail(smtp_email, to_email, msg.as_string())
        server.quit()
        
        return {'success': True, 'message': f'Email sent to {to_email}'}
    except smtplib.SMTPAuthenticationError:
        return {'success': False, 'message': 'SMTP authentication failed. Check email and password.'}
    except smtplib.SMTPException as e:
        return {'success': False, 'message': f'SMTP error: {str(e)}'}
    except Exception as e:
        return {'success': False, 'message': f'Error: {str(e)}'}


def send_password_reset_email(to_email, user_name, reset_url):
    """Send password reset email"""
    site_name = get_app_setting('site_name') or 'Forex Risk Manager'
    subject = f"Reset Your Password - {site_name}"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: #1f2937; color: white; padding: 30px; text-align: center; }}
            .content {{ padding: 30px; background: #f9fafb; }}
            .button {{ display: inline-block; background: #2563eb; color: white; padding: 12px 30px; text-decoration: none; margin: 20px 0; }}
            .footer {{ padding: 20px; text-align: center; color: #6b7280; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin:0;">{site_name}</h1>
            </div>
            <div class="content">
                <h2>Password Reset Request</h2>
                <p>Hello {user_name},</p>
                <p>We received a request to reset your password. Click the button below to create a new password:</p>
                <p style="text-align: center;">
                    <a href="{reset_url}" class="button" style="color: white;">Reset Password</a>
                </p>
                <p>This link will expire in <strong>1 hour</strong>.</p>
                <p>If you didn't request this, you can safely ignore this email.</p>
                <p style="margin-top: 30px;">
                    <small>Or copy this link: {reset_url}</small>
                </p>
            </div>
            <div class="footer">
                <p>{site_name}</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    text_content = f"""
    Password Reset Request
    
    Hello {user_name},
    
    We received a request to reset your password. Click the link below:
    {reset_url}
    
    This link will expire in 1 hour.
    
    If you didn't request this, you can safely ignore this email.
    """
    
    return send_email(to_email, subject, html_content, text_content)


def send_email_change_notification(to_email, user_name, new_email):
    """Send notification about email change"""
    site_name = get_app_setting('site_name') or 'Forex Risk Manager'
    subject = f"Email Address Changed - {site_name}"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: #1f2937; color: white; padding: 30px; text-align: center; }}
            .content {{ padding: 30px; background: #f9fafb; }}
            .alert {{ background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; margin: 20px 0; }}
            .footer {{ padding: 20px; text-align: center; color: #6b7280; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin:0;">{site_name}</h1>
            </div>
            <div class="content">
                <h2>Email Address Changed</h2>
                <p>Hello {user_name},</p>
                <p>Your account email has been changed to: <strong>{new_email}</strong></p>
                <div class="alert">
                    <strong>Security Notice:</strong> If you did not make this change, please contact support immediately.
                </div>
                <p>You can now use your new email address to log in.</p>
            </div>
            <div class="footer">
                <p>{site_name}</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return send_email(to_email, subject, html_content)


def send_invoice_email(to_email, user_name, order_id, plan_name, amount_usd, amount_idr, payment_date):
    """Send invoice email after successful payment"""
    site_name = get_app_setting('site_name') or 'Forex Risk Manager'
    subject = f"Payment Confirmation - Order #{order_id}"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: #1f2937; color: white; padding: 30px; text-align: center; }}
            .content {{ padding: 30px; background: #f9fafb; }}
            .invoice {{ background: white; border: 1px solid #e5e7eb; padding: 20px; margin: 20px 0; }}
            .invoice-header {{ border-bottom: 2px solid #2563eb; padding-bottom: 10px; margin-bottom: 15px; }}
            .invoice-row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #f3f4f6; }}
            .invoice-total {{ font-size: 18px; font-weight: bold; color: #2563eb; }}
            .success {{ background: #d1fae5; color: #065f46; padding: 15px; text-align: center; margin: 20px 0; }}
            .footer {{ padding: 20px; text-align: center; color: #6b7280; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin:0;">{site_name}</h1>
            </div>
            <div class="content">
                <div class="success">
                    <strong>Payment Successful!</strong>
                </div>
                
                <p>Hello {user_name},</p>
                <p>Thank you for your purchase. Your subscription has been activated.</p>
                
                <div class="invoice">
                    <div class="invoice-header">
                        <strong>INVOICE</strong><br>
                        <small>Order ID: {order_id}</small>
                    </div>
                    <table style="width: 100%;">
                        <tr>
                            <td>Plan</td>
                            <td style="text-align: right;"><strong>{plan_name}</strong></td>
                        </tr>
                        <tr>
                            <td>Date</td>
                            <td style="text-align: right;">{payment_date}</td>
                        </tr>
                        <tr>
                            <td>Amount (USD)</td>
                            <td style="text-align: right;">${amount_usd:.2f}</td>
                        </tr>
                        <tr>
                            <td>Amount (IDR)</td>
                            <td style="text-align: right;">Rp {amount_idr:,.0f}</td>
                        </tr>
                        <tr style="border-top: 2px solid #e5e7eb;">
                            <td><strong>Total Paid</strong></td>
                            <td style="text-align: right;" class="invoice-total">Rp {amount_idr:,.0f}</td>
                        </tr>
                    </table>
                </div>
                
                <p>Your {plan_name} subscription is now active. Enjoy all the premium features!</p>
            </div>
            <div class="footer">
                <p>{site_name}</p>
                <p>This is an automated email. Please do not reply.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return send_email(to_email, subject, html_content)


def sanitize_string(value, max_length=100, allowed_chars=None):
    """Sanitize string input to prevent injection attacks"""
    if value is None:
        return None
    value = str(value).strip()
    if len(value) > max_length:
        value = value[:max_length]
    if allowed_chars:
        value = ''.join(c for c in value if c in allowed_chars)
    return value


def validate_pair(pair):
    """Validate trading pair against whitelist"""
    if not pair or not isinstance(pair, str):
        return None
    pair = pair.strip().upper().replace('_', '/')
    # Check if pair exists in our ticker list
    for valid_pair in FOREX_TICKERS.keys():
        if pair == valid_pair.upper():
            return valid_pair
    return None


def validate_period(period):
    """Validate period against whitelist"""
    if period and period.lower() in VALID_PERIODS:
        return period.lower()
    return '1mo'


def validate_interval(interval):
    """Validate interval against whitelist"""
    if interval and interval.lower() in VALID_INTERVALS:
        return interval.lower()
    return '1h'


def validate_number(value, min_val=None, max_val=None, default=0):
    """Validate and sanitize numeric input"""
    try:
        num = float(value)
        if min_val is not None and num < min_val:
            return min_val
        if max_val is not None and num > max_val:
            return max_val
        return num
    except (TypeError, ValueError):
        return default


def validate_int(value, min_val=None, max_val=None, default=0):
    """Validate and sanitize integer input"""
    try:
        num = int(value)
        if min_val is not None and num < min_val:
            return min_val
        if max_val is not None and num > max_val:
            return max_val
        return num
    except (TypeError, ValueError):
        return default


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
                site_name = get_app_setting('site_name') or 'Forex Risk Manager'
                flash(f'Registration successful! Welcome to {site_name}.', 'success')
                return redirect(url_for('index'))
    
    return render_template('register.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Request password reset"""
    if session.get('user_id'):
        return redirect(url_for('index'))
    
    message = None
    error = None
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        
        if not email:
            error = 'Please enter your email address.'
        else:
            conn = get_db()
            user = conn.execute('SELECT id, name FROM users WHERE email = ?', (email,)).fetchone()
            
            if user:
                # Generate secure token
                import secrets
                token = secrets.token_urlsafe(32)
                expires = datetime.now() + timedelta(hours=1)
                
                conn.execute('UPDATE users SET reset_token = ?, reset_token_expires = ? WHERE id = ?',
                           (token, expires, user['id']))
                conn.commit()
                
                # Generate reset URL using site_url setting or ProxyFix headers
                site_url = get_site_url()
                reset_url = f"{site_url}/reset-password/{token}"
                
                # Try to send email
                email_result = send_password_reset_email(email, user['name'], reset_url)
                
                if email_result['success']:
                    message = 'Password reset link has been sent to your email.'
                else:
                    # If email fails, show the link directly (for development/testing)
                    message = 'Email sending failed. Please use the link below:'
                    flash(f'Reset link: {reset_url}', 'info')
            else:
                # Don't reveal if email exists or not (security)
                message = 'If an account with that email exists, a reset link has been sent.'
            
            conn.close()
    
    return render_template('forgot_password.html', message=message, error=error)


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Reset password using token"""
    if session.get('user_id'):
        return redirect(url_for('index'))
    
    conn = get_db()
    user = conn.execute('''
        SELECT id, email, name FROM users 
        WHERE reset_token = ? AND reset_token_expires > ?
    ''', (token, datetime.now())).fetchone()
    
    if not user:
        conn.close()
        flash('Invalid or expired reset link. Please request a new one.', 'error')
        return redirect(url_for('forgot_password'))
    
    error = None
    
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if len(password) < 6:
            error = 'Password must be at least 6 characters.'
        elif password != confirm_password:
            error = 'Passwords do not match.'
        else:
            hashed = hash_password(password)
            conn.execute('UPDATE users SET password = ?, reset_token = NULL, reset_token_expires = NULL WHERE id = ?',
                        (hashed, user['id']))
            conn.commit()
            conn.close()
            
            flash('Password has been reset successfully. You can now login.', 'success')
            return redirect(url_for('login'))
    
    conn.close()
    return render_template('reset_password.html', token=token, email=user['email'])


@app.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """Change password for logged in user"""
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')
    
    conn = get_db()
    user = conn.execute('SELECT password FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    if not verify_password(user['password'], current_password):
        conn.close()
        flash('Current password is incorrect.', 'error')
        return redirect(url_for('settings'))
    
    if len(new_password) < 6:
        conn.close()
        flash('New password must be at least 6 characters.', 'error')
        return redirect(url_for('settings'))
    
    if new_password != confirm_password:
        conn.close()
        flash('New passwords do not match.', 'error')
        return redirect(url_for('settings'))
    
    hashed = hash_password(new_password)
    conn.execute('UPDATE users SET password = ? WHERE id = ?', (hashed, session['user_id']))
    conn.commit()
    conn.close()
    
    flash('Password changed successfully!', 'success')
    return redirect(url_for('settings'))


@app.route('/change-email', methods=['POST'])
@login_required
def change_email():
    """Change email for logged in user"""
    new_email = request.form.get('new_email', '').strip().lower()
    password = request.form.get('password', '')
    
    if not new_email:
        flash('Please enter a new email address.', 'error')
        return redirect(url_for('settings'))
    
    # Basic email validation
    import re
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', new_email):
        flash('Please enter a valid email address.', 'error')
        return redirect(url_for('settings'))
    
    conn = get_db()
    user = conn.execute('SELECT password, email FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    if not verify_password(user['password'], password):
        conn.close()
        flash('Password is incorrect.', 'error')
        return redirect(url_for('settings'))
    
    if new_email == user['email']:
        conn.close()
        flash('New email is the same as current email.', 'error')
        return redirect(url_for('settings'))
    
    # Check if email already exists
    existing = conn.execute('SELECT id FROM users WHERE email = ? AND id != ?', 
                           (new_email, session['user_id'])).fetchone()
    if existing:
        conn.close()
        flash('Email address is already in use.', 'error')
        return redirect(url_for('settings'))
    
    old_email = user['email']
    user_name = session.get('user_name', 'User')
    
    conn.execute('UPDATE users SET email = ? WHERE id = ?', (new_email, session['user_id']))
    conn.commit()
    conn.close()
    
    # Send notification to old email
    send_email_change_notification(old_email, user_name, new_email)
    
    session['user_email'] = new_email
    flash('Email changed successfully!', 'success')
    return redirect(url_for('settings'))


@app.route('/subscription')
@login_required
def subscription():
    """Redirect to pricing page"""
    return redirect(url_for('pricing'))


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
    price_usd = plan_info.get('price_usd', plan_info.get('price', 0))
    conn.execute('''
        INSERT INTO payments (user_id, amount, amount_usd, plan, status, payment_method, transaction_id)
        VALUES (?, ?, ?, ?, 'pending', ?, ?)
    ''', (session['user_id'], price_usd, price_usd, plan, payment_method, transaction_id))
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


def fetch_midtrans_transaction(order_id):
    """Fetch transaction status from Midtrans API"""
    config = get_midtrans_config()
    
    if config['is_production']:
        api_url = f"https://api.midtrans.com/v2/{order_id}/status"
    else:
        api_url = f"https://api.sandbox.midtrans.com/v2/{order_id}/status"
    
    auth_string = base64.b64encode(f"{config['server_key']}:".encode()).decode()
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Basic {auth_string}'
    }
    
    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            return {'error': f'Status {response.status_code}', 'message': response.text[:200]}
    except Exception as e:
        return {'error': str(e)}


@app.route('/admin/payments')
@admin_required
def admin_payments():
    conn = get_db()
    payments = conn.execute('''
        SELECT p.*, u.name, u.email 
        FROM payments p 
        LEFT JOIN users u ON p.user_id = u.id 
        ORDER BY p.created_at DESC
    ''').fetchall()
    conn.close()
    
    config = get_midtrans_config()
    return render_template('admin/payments.html', payments=payments, midtrans_config=config)


@app.route('/admin/payments/sync/<order_id>')
@admin_required
def admin_sync_payment(order_id):
    """Sync single payment status from Midtrans"""
    result = fetch_midtrans_transaction(order_id)
    
    if 'error' in result:
        flash(f'Error fetching from Midtrans: {result.get("error")}', 'error')
        return redirect(url_for('admin_payments'))
    
    # Update local database with Midtrans data
    transaction_status = result.get('transaction_status', '')
    fraud_status = result.get('fraud_status', 'accept')
    payment_type = result.get('payment_type', '')
    transaction_id = result.get('transaction_id', '')
    
    # Determine status
    if transaction_status == 'capture':
        status = 'paid' if fraud_status == 'accept' else 'fraud'
    elif transaction_status == 'settlement':
        status = 'paid'
    elif transaction_status in ['cancel', 'deny', 'expire']:
        status = 'failed'
    elif transaction_status == 'pending':
        status = 'pending'
    else:
        status = transaction_status or 'unknown'
    
    conn = get_db()
    payment = conn.execute('SELECT * FROM payments WHERE order_id = ?', (order_id,)).fetchone()
    
    if payment:
        conn.execute('''
            UPDATE payments SET 
                status = ?, payment_type = ?, midtrans_transaction_id = ?,
                midtrans_status = ?, fraud_status = ?,
                paid_at = CASE WHEN ? = 'paid' AND paid_at IS NULL THEN ? ELSE paid_at END
            WHERE order_id = ?
        ''', (status, payment_type, transaction_id, transaction_status, fraud_status,
              status, datetime.now(), order_id))
        
        # If payment successful, upgrade user subscription
        if status == 'paid' and payment['status'] != 'paid':
            plan = payment['plan']
            days = SUBSCRIPTION_PLANS.get(plan, {}).get('days', 30)
            expires = datetime.now() + timedelta(days=days)
            conn.execute('''
                UPDATE users SET subscription_plan = ?, subscription_expires = ?
                WHERE id = ?
            ''', (plan, expires, payment['user_id']))
        
        conn.commit()
        flash(f'Payment {order_id} synced: {status}', 'success')
    else:
        flash(f'Payment {order_id} not found in database', 'error')
    
    conn.close()
    return redirect(url_for('admin_payments'))


@app.route('/admin/payments/sync-all')
@admin_required
def admin_sync_all_payments():
    """Sync all pending payments from Midtrans"""
    conn = get_db()
    pending_payments = conn.execute('''
        SELECT order_id FROM payments 
        WHERE status = 'pending' AND order_id IS NOT NULL AND order_id != ''
    ''').fetchall()
    conn.close()
    
    synced = 0
    errors = 0
    
    for payment in pending_payments:
        order_id = payment['order_id']
        result = fetch_midtrans_transaction(order_id)
        
        if 'error' not in result:
            transaction_status = result.get('transaction_status', '')
            fraud_status = result.get('fraud_status', 'accept')
            payment_type = result.get('payment_type', '')
            transaction_id = result.get('transaction_id', '')
            
            if transaction_status == 'capture':
                status = 'paid' if fraud_status == 'accept' else 'fraud'
            elif transaction_status == 'settlement':
                status = 'paid'
            elif transaction_status in ['cancel', 'deny', 'expire']:
                status = 'failed'
            elif transaction_status == 'pending':
                status = 'pending'
            else:
                status = transaction_status or 'unknown'
            
            conn = get_db()
            conn.execute('''
                UPDATE payments SET 
                    status = ?, payment_type = ?, midtrans_transaction_id = ?,
                    midtrans_status = ?, fraud_status = ?,
                    paid_at = CASE WHEN ? = 'paid' AND paid_at IS NULL THEN ? ELSE paid_at END
                WHERE order_id = ?
            ''', (status, payment_type, transaction_id, transaction_status, fraud_status,
                  status, datetime.now(), order_id))
            
            # Upgrade subscription if paid
            if status == 'paid':
                payment_data = conn.execute('SELECT * FROM payments WHERE order_id = ?', (order_id,)).fetchone()
                if payment_data:
                    plan = payment_data['plan']
                    days = SUBSCRIPTION_PLANS.get(plan, {}).get('days', 30)
                    expires = datetime.now() + timedelta(days=days)
                    conn.execute('''
                        UPDATE users SET subscription_plan = ?, subscription_expires = ?
                        WHERE id = ?
                    ''', (plan, expires, payment_data['user_id']))
            
            conn.commit()
            conn.close()
            synced += 1
        else:
            errors += 1
    
    flash(f'Synced {synced} payments, {errors} errors', 'success' if errors == 0 else 'warning')
    return redirect(url_for('admin_payments'))


@app.route('/admin/payments/check/<order_id>')
@admin_required  
def admin_check_midtrans(order_id):
    """Check payment status from Midtrans API (returns JSON)"""
    result = fetch_midtrans_transaction(order_id)
    return jsonify(result)


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


@app.route('/admin/payments/<int:payment_id>/resend-invoice')
@admin_required
def admin_resend_invoice(payment_id):
    """Resend invoice email for a payment"""
    conn = get_db()
    
    # Get payment with user info
    payment = conn.execute('''
        SELECT p.*, u.name, u.email 
        FROM payments p 
        JOIN users u ON p.user_id = u.id 
        WHERE p.id = ?
    ''', (payment_id,)).fetchone()
    
    if not payment:
        conn.close()
        flash('Payment not found.', 'error')
        return redirect(url_for('admin_payments'))
    
    if payment['status'] not in ['paid', 'completed']:
        conn.close()
        flash('Can only resend invoice for paid/completed payments.', 'error')
        return redirect(url_for('admin_payments'))
    
    # Get plan info
    plan = payment['plan'] or 'basic'
    plan_info = SUBSCRIPTION_PLANS.get(plan, {})
    
    # Send invoice email
    result = send_invoice_email(
        to_email=payment['email'],
        user_name=payment['name'],
        order_id=payment['order_id'] or f"INV-{payment['id']}",
        plan_name=plan_info.get('name', plan.title()),
        amount_usd=payment['amount_usd'] or payment['amount'] or 0,
        amount_idr=payment['amount_idr'] or 0,
        payment_date=payment['paid_at'][:16] if payment['paid_at'] else payment['created_at'][:16] if payment['created_at'] else datetime.now().strftime('%Y-%m-%d %H:%M')
    )
    
    conn.close()
    
    if result['success']:
        flash(f'Invoice sent to {payment["email"]}', 'success')
    else:
        flash(f'Failed to send invoice: {result["message"]}', 'error')
    
    return redirect(url_for('admin_payments'))


@app.route('/admin/settings')
@admin_required
def admin_settings():
    """Admin settings page for Midtrans and other configurations"""
    # Get all settings
    conn = get_db()
    settings_rows = conn.execute('SELECT * FROM app_settings').fetchall()
    conn.close()
    
    # Convert to dictionary
    settings = {row['setting_key']: row['setting_value'] for row in settings_rows}
    
    # Get current exchange rate
    current_rate = get_exchange_rate()
    
    return render_template('admin/settings.html', settings=settings, current_rate=current_rate)


@app.route('/admin/settings/update', methods=['POST'])
@admin_required
def admin_update_settings():
    """Update admin settings"""
    settings_type = request.form.get('settings_type', 'midtrans')
    
    if settings_type == 'email':
        # Email settings
        set_app_setting('email_enabled', 'true' if request.form.get('email_enabled') else 'false')
        set_app_setting('smtp_host', request.form.get('smtp_host', 'smtp.zoho.com'))
        set_app_setting('smtp_port', request.form.get('smtp_port', '587'))
        set_app_setting('smtp_email', request.form.get('smtp_email', ''))
        set_app_setting('smtp_password', request.form.get('smtp_password', ''))
        set_app_setting('smtp_sender_name', request.form.get('smtp_sender_name', 'Forex Risk Manager'))
        flash('Email settings updated successfully!', 'success')
    elif settings_type == 'site':
        # Site settings
        site_url = request.form.get('site_url', '').strip().rstrip('/')
        site_name = request.form.get('site_name', 'Forex Risk Manager').strip()
        set_app_setting('site_url', site_url)
        set_app_setting('site_name', site_name)
        flash('Site settings updated successfully!', 'success')
    elif settings_type == 'branding':
        # Branding settings (logo, favicon)
        site_name = request.form.get('site_name', 'Forex Risk Manager').strip()
        set_app_setting('site_name', site_name)
        
        # Handle logo upload
        if 'site_logo' in request.files:
            file = request.files['site_logo']
            if file and file.filename and allowed_file(file.filename):
                from werkzeug.utils import secure_filename
                import uuid
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"logo_{uuid.uuid4().hex[:8]}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                set_app_setting('site_logo', f'/static/uploads/{filename}')
        
        # Handle favicon upload
        if 'site_favicon' in request.files:
            file = request.files['site_favicon']
            if file and file.filename and allowed_file(file.filename):
                from werkzeug.utils import secure_filename
                import uuid
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"favicon_{uuid.uuid4().hex[:8]}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                set_app_setting('site_favicon', f'/static/uploads/{filename}')
        
        flash('Branding settings updated successfully!', 'success')
    else:
        # Midtrans settings
        set_app_setting('midtrans_server_key', request.form.get('midtrans_server_key', ''))
        set_app_setting('midtrans_client_key', request.form.get('midtrans_client_key', ''))
        set_app_setting('midtrans_is_production', 'true' if request.form.get('midtrans_is_production') else 'false')
        
        # Exchange rate settings
        set_app_setting('use_live_exchange_rate', 'true' if request.form.get('use_live_exchange_rate') else 'false')
        set_app_setting('usd_to_idr_rate', request.form.get('usd_to_idr_rate', '15500'))
        flash('Midtrans settings updated successfully!', 'success')
    
    return redirect(url_for('admin_settings'))


@app.route('/admin/settings/test-midtrans')
@admin_required
def admin_test_midtrans():
    """Test Midtrans connection"""
    config = get_midtrans_config()
    
    # Test API connection
    try:
        auth_string = base64.b64encode(f"{config['server_key']}:".encode()).decode()
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Basic {auth_string}'
        }
        
        # Try to get merchant info (simple API call)
        test_url = config['api_url'].replace('/snap/v1', '/v2/point_of_sales')
        response = requests.get(test_url, headers=headers, timeout=10)
        
        if response.status_code in [200, 401, 404]:
            # 401 means auth worked but endpoint doesn't exist (OK for testing)
            # 404 means server responded (connection works)
            return jsonify({
                'success': True, 
                'message': 'Midtrans connection successful!',
                'mode': 'Production' if config['is_production'] else 'Sandbox',
                'server_key_preview': config['server_key'][:20] + '...' if len(config['server_key']) > 20 else config['server_key']
            })
        else:
            return jsonify({
                'success': False, 
                'message': f'Midtrans responded with status {response.status_code}',
                'details': response.text[:200]
            })
    except Exception as e:
        return jsonify({
            'success': False, 
            'message': f'Connection error: {str(e)}'
        })


@app.route('/admin/settings/test-email')
@admin_required
def admin_test_email():
    """Send test email to admin"""
    try:
        config = get_email_config()
        
        if config.get('email_enabled', 'false') != 'true':
            return jsonify({
                'success': False,
                'message': 'Email sending is disabled. Enable it first.'
            })
        
        smtp_email = config.get('smtp_email', '')
        if not smtp_email:
            return jsonify({
                'success': False,
                'message': 'SMTP email not configured.'
            })
        
        # Send test email to the admin
        admin_email = session.get('user_email', smtp_email)
        site_name = get_app_setting('site_name') or 'Forex Risk Manager'
        
        html_content = """
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: #1f2937; color: white; padding: 30px; text-align: center;">
                <h1 style="margin:0;">{}</h1>
            </div>
            <div style="padding: 30px; background: #f9fafb;">
                <h2 style="color: #10b981;">Email Configuration Test</h2>
                <p>If you're reading this, your email settings are working correctly!</p>
                <p>Your SMTP configuration has been successfully tested.</p>
                <p style="margin-top: 20px;">
                    <strong>Host:</strong> {}<br>
                    <strong>Port:</strong> {}<br>
                    <strong>From:</strong> {}
                </p>
            </div>
            <div style="padding: 20px; text-align: center; color: #6b7280; font-size: 12px;">
                <p>{}</p>
            </div>
        </div>
        """.format(site_name, config.get('smtp_host', 'N/A'), config.get('smtp_port', 'N/A'), smtp_email, site_name)
        
        result = send_email(admin_email, f"Test Email - {site_name}", html_content)
        
        if result['success']:
            return jsonify({
                'success': True,
                'message': f'Test email sent to {admin_email}'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to send email',
                'error': result.get('message', 'Unknown error')
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        })


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
    def _dict_factory(cursor, row):
        return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}
    conn.row_factory = _dict_factory
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
    
    # Add password reset columns
    try:
        conn.execute('ALTER TABLE users ADD COLUMN reset_token VARCHAR(100)')
    except:
        pass
    try:
        conn.execute('ALTER TABLE users ADD COLUMN reset_token_expires TIMESTAMP')
    except:
        pass
    
    # Payments table (Midtrans integration)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            order_id VARCHAR(100),
            plan VARCHAR(20) DEFAULT 'basic',
            amount REAL DEFAULT 0,
            amount_usd REAL DEFAULT 0,
            amount_idr INTEGER DEFAULT 0,
            exchange_rate REAL DEFAULT 15500,
            status VARCHAR(20) DEFAULT 'pending',
            payment_type VARCHAR(50),
            payment_method VARCHAR(50),
            transaction_id VARCHAR(100),
            midtrans_transaction_id VARCHAR(100),
            midtrans_status VARCHAR(50),
            fraud_status VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            paid_at TIMESTAMP,
            expires_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Add new columns if they don't exist (for existing databases)
    payment_columns = [
        ('order_id', 'VARCHAR(100)'),
        ('amount_usd', 'REAL DEFAULT 0'),
        ('amount_idr', 'INTEGER DEFAULT 0'),
        ('exchange_rate', 'REAL DEFAULT 15500'),
        ('midtrans_transaction_id', 'VARCHAR(100)'),
        ('midtrans_status', 'VARCHAR(50)'),
        ('fraud_status', 'VARCHAR(50)'),
        ('paid_at', 'TIMESTAMP'),
        ('expires_at', 'TIMESTAMP'),
        ('payment_type', 'VARCHAR(50)')
    ]
    for col_name, col_type in payment_columns:
        try:
            conn.execute(f'ALTER TABLE payments ADD COLUMN {col_name} {col_type}')
        except:
            pass
    
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
    
    # App settings table (for Midtrans, etc.)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY,
            setting_key VARCHAR(100) UNIQUE NOT NULL,
            setting_value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Insert default Midtrans settings if not exists
    default_settings = [
        ('midtrans_server_key', 'SB-Mid-server-YOUR_SERVER_KEY'),
        ('midtrans_client_key', 'SB-Mid-client-YOUR_CLIENT_KEY'),
        ('midtrans_is_production', 'false'),
        ('usd_to_idr_rate', '15500'),
        ('use_live_exchange_rate', 'true')
    ]
    for key, value in default_settings:
        try:
            conn.execute('INSERT OR IGNORE INTO app_settings (setting_key, setting_value) VALUES (?, ?)', (key, value))
        except:
            pass
    
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

def get_market_summary():
    """Get market summary for dashboard - forex, crypto, stocks/indices"""
    summary = {
        'forex': [],
        'crypto': [],
        'indices': []
    }
    
    # Forex pairs to track
    forex_pairs = [
        ('EUR/USD', 'EURUSD=X'),
        ('GBP/USD', 'GBPUSD=X'),
        ('USD/JPY', 'USDJPY=X'),
        ('AUD/USD', 'AUDUSD=X'),
        ('USD/CHF', 'USDCHF=X'),
        ('USD/CAD', 'USDCAD=X'),
    ]
    
    # Crypto to track
    crypto_pairs = [
        ('BTC/USD', 'BTC-USD'),
        ('ETH/USD', 'ETH-USD'),
        ('XRP/USD', 'XRP-USD'),
        ('SOL/USD', 'SOL-USD'),
    ]
    
    # Indices/Stocks to track
    indices = [
        ('S&P 500', '^GSPC'),
        ('NASDAQ', '^IXIC'),
        ('DOW 30', '^DJI'),
        ('Gold', 'GC=F'),
        ('Oil', 'CL=F'),
    ]
    
    try:
        # Fetch forex data
        for name, symbol in forex_pairs:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period='2d')
                if len(hist) >= 2:
                    prev_close = hist['Close'].iloc[-2]
                    current = hist['Close'].iloc[-1]
                    change = ((current - prev_close) / prev_close) * 100
                    summary['forex'].append({
                        'name': name,
                        'price': round(current, 5),
                        'change': round(change, 2),
                        'direction': 'up' if change > 0 else 'down' if change < 0 else 'neutral'
                    })
            except:
                pass
        
        # Fetch crypto data
        for name, symbol in crypto_pairs:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period='2d')
                if len(hist) >= 2:
                    prev_close = hist['Close'].iloc[-2]
                    current = hist['Close'].iloc[-1]
                    change = ((current - prev_close) / prev_close) * 100
                    summary['crypto'].append({
                        'name': name,
                        'price': round(current, 2),
                        'change': round(change, 2),
                        'direction': 'up' if change > 0 else 'down' if change < 0 else 'neutral'
                    })
            except:
                pass
        
        # Fetch indices data
        for name, symbol in indices:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period='2d')
                if len(hist) >= 2:
                    prev_close = hist['Close'].iloc[-2]
                    current = hist['Close'].iloc[-1]
                    change = ((current - prev_close) / prev_close) * 100
                    summary['indices'].append({
                        'name': name,
                        'price': round(current, 2),
                        'change': round(change, 2),
                        'direction': 'up' if change > 0 else 'down' if change < 0 else 'neutral'
                    })
            except:
                pass
    except Exception as e:
        print(f"Error fetching market summary: {e}")
    
    return summary


@app.route('/')
@login_required
def index():
    conn = get_db()
    
    # Get market summary
    market_summary = get_market_summary()
    
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
                         current_drawdown=round(current_drawdown, 2),
                         market_summary=market_summary)

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
    # Validate and sanitize inputs
    pair = sanitize_string(request.form.get('pair', 'EUR/USD'), max_length=20)
    trade_type = request.form.get('trade_type', 'buy').lower()
    if trade_type not in VALID_TRADE_TYPES:
        trade_type = 'buy'
    
    lot_size = validate_number(request.form.get('lot_size', 0.1), min_val=0.01, max_val=1000, default=0.1)
    entry_price = validate_number(request.form.get('entry_price', 0), min_val=0, default=0)
    stop_loss = validate_number(request.form.get('stop_loss'), min_val=0) if request.form.get('stop_loss') else None
    take_profit = validate_number(request.form.get('take_profit'), min_val=0) if request.form.get('take_profit') else None
    risk_percent = validate_number(request.form.get('risk_percent'), min_val=0, max_val=100) if request.form.get('risk_percent') else None
    profit_loss = validate_number(request.form.get('profit_loss')) if request.form.get('profit_loss') else None
    
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
    # Validate and sanitize inputs
    entry_price = validate_number(request.form.get('entry_price', 0), min_val=0, default=0)
    lot_size = validate_number(request.form.get('lot_size', 0.1), min_val=0.01, max_val=1000, default=0.1)
    stop_loss = validate_number(request.form.get('stop_loss'), min_val=0) if request.form.get('stop_loss') else None
    take_profit = validate_number(request.form.get('take_profit'), min_val=0) if request.form.get('take_profit') else None
    risk_percent = validate_number(request.form.get('risk_percent'), min_val=0, max_val=100) if request.form.get('risk_percent') else None
    new_profit_loss = validate_number(request.form.get('profit_loss')) if request.form.get('profit_loss') else None
    
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
    # Validate input
    exit_price = validate_number(request.form.get('exit_price', 0), min_val=0, default=0)
    
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
    
    # Validate and sanitize inputs
    pair = validate_pair(data.get('pair', 'EUR/USD'))
    if not pair:
        return jsonify({'error': 'Invalid trading pair'}), 400
    
    period = validate_period(data.get('period', '1mo'))
    interval = validate_interval(data.get('interval', '15m'))
    balance = validate_number(data.get('balance', 10000), min_val=0, max_val=100000000, default=10000)
    risk_percent = validate_number(data.get('risk_percent', 1.0), min_val=0.1, max_val=10, default=1.0)
    user_id = session.get('user_id')
    
    ticker_symbol = FOREX_TICKERS.get(pair)
    if not ticker_symbol:
        return jsonify({'error': 'Invalid trading pair'}), 400
    
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
    
    # Validate and sanitize inputs
    pair = validate_pair(data.get('pair', 'EUR/USD'))
    if not pair:
        return jsonify({'error': 'Invalid trading pair'}), 400
    
    period = validate_period(data.get('period', '1mo'))
    interval = validate_interval(data.get('interval', '1h'))
    balance = validate_number(data.get('balance', 10000), min_val=0, max_val=100000000, default=10000)
    risk_percent = validate_number(data.get('risk_percent', 1.0), min_val=0.1, max_val=10, default=1.0)
    user_id = session.get('user_id')
    
    ticker_symbol = FOREX_TICKERS.get(pair)
    if not ticker_symbol:
        return jsonify({'error': 'Invalid trading pair'}), 400
    
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
    
    # Validate and sanitize inputs
    pair = validate_pair(data.get('pair', 'EUR/USD'))
    if not pair:
        return jsonify({'error': 'Invalid trading pair'}), 400
    
    period = validate_period(data.get('period', '3mo'))
    interval = validate_interval(data.get('interval', '1d'))
    forecast_periods = validate_int(data.get('forecast_periods', 5), min_val=1, max_val=30, default=5)
    
    ticker_symbol = FOREX_TICKERS.get(pair)
    if not ticker_symbol:
        return jsonify({'error': 'Invalid trading pair'}), 400
    
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
    VALID_STRATEGIES = {'ensemble', 'mean_reversion', 'momentum', 'breakout', 'volatility', 'all'}
    
    data = request.get_json()
    
    # Validate and sanitize inputs
    pair = validate_pair(data.get('pair', 'EUR/USD'))
    if not pair:
        return jsonify({'error': 'Invalid trading pair'}), 400
    
    period = validate_period(data.get('period', '1mo'))
    interval = validate_interval(data.get('interval', '1h'))
    balance = validate_number(data.get('balance', 10000), min_val=0, max_val=100000000, default=10000)
    risk_percent = validate_number(data.get('risk_percent', 1.0), min_val=0.1, max_val=10, default=1.0)
    
    strategy = data.get('strategy', 'ensemble')
    if strategy not in VALID_STRATEGIES:
        strategy = 'ensemble'
    
    ticker_symbol = FOREX_TICKERS.get(pair)
    if not ticker_symbol:
        return jsonify({'error': 'Invalid trading pair'}), 400
    
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


# ==================== PAYMENT ROUTES (MIDTRANS) ====================

def get_exchange_rate():
    """Get current USD to IDR exchange rate"""
    use_live = get_app_setting('use_live_exchange_rate', 'true').lower() == 'true'
    
    if use_live:
        try:
            response = requests.get('https://api.exchangerate-api.com/v4/latest/USD', timeout=10)
            if response.status_code == 200:
                return response.json()['rates']['IDR']
        except:
            pass
    
    # Use manual rate from settings
    manual_rate = get_app_setting('usd_to_idr_rate', str(DEFAULT_USD_TO_IDR))
    try:
        return float(manual_rate)
    except:
        return DEFAULT_USD_TO_IDR


def create_midtrans_token(order_id, amount_idr, user_email, user_name, plan_name):
    """Create Midtrans Snap token for payment"""
    config = get_midtrans_config()
    url = f"{config['api_url']}/transactions"
    
    auth_string = base64.b64encode(f"{config['server_key']}:".encode()).decode()
    
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': f'Basic {auth_string}'
    }
    
    payload = {
        'transaction_details': {
            'order_id': order_id,
            'gross_amount': int(amount_idr)
        },
        'credit_card': {
            'secure': True
        },
        'customer_details': {
            'email': user_email,
            'first_name': user_name
        },
        'item_details': [{
            'id': plan_name.lower(),
            'price': int(amount_idr),
            'quantity': 1,
            'name': f'{plan_name} Subscription (30 days)'
        }],
        'callbacks': {
            'finish': url_for('payment_finish', _external=True)
        }
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code == 201:
            return response.json()
        else:
            print(f"Midtrans error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Midtrans request error: {e}")
        return None


def verify_midtrans_signature(order_id, status_code, gross_amount, signature_key):
    """Verify Midtrans webhook signature"""
    import hashlib
    config = get_midtrans_config()
    raw = f"{order_id}{status_code}{gross_amount}{config['server_key']}"
    calculated_signature = hashlib.sha512(raw.encode()).hexdigest()
    return calculated_signature == signature_key


@app.route('/pricing')
@login_required
def pricing():
    """Show pricing page with subscription plans"""
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    # Get recent payments
    payments = conn.execute('''
        SELECT * FROM payments WHERE user_id = ? ORDER BY created_at DESC LIMIT 5
    ''', (session['user_id'],)).fetchall()
    conn.close()
    
    # Get exchange rate
    exchange_rate = get_exchange_rate()
    
    # Calculate IDR prices
    plans_with_idr = {}
    for key, plan in SUBSCRIPTION_PLANS.items():
        plans_with_idr[key] = {
            **plan,
            'price_idr': int(plan['price_usd'] * exchange_rate) if plan['price_usd'] > 0 else 0
        }
    
    config = get_midtrans_config()
    return render_template('pricing.html', 
                          user=user, 
                          plans=plans_with_idr,
                          exchange_rate=exchange_rate,
                          payments=payments,
                          midtrans_client_key=config['client_key'],
                          is_production=config['is_production'],
                          snap_url=config['snap_url'])


@app.route('/create-payment', methods=['POST'])
@login_required
def create_payment():
    """Create a new payment transaction"""
    try:
        data = request.get_json()
        plan = data.get('plan', 'basic')
        
        if plan not in SUBSCRIPTION_PLANS or plan == 'free':
            return jsonify({'error': 'Invalid plan selected'}), 400
        
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        
        # Get plan details
        plan_info = SUBSCRIPTION_PLANS[plan]
        price_usd = plan_info['price_usd']
        
        # Get exchange rate and calculate IDR amount
        exchange_rate = get_exchange_rate()
        amount_idr = int(price_usd * exchange_rate)
        
        # Generate unique order ID
        order_id = f"FRM-{session['user_id']}-{plan.upper()}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Create Midtrans token
        midtrans_response = create_midtrans_token(
            order_id=order_id,
            amount_idr=amount_idr,
            user_email=user['email'],
            user_name=user['name'],
            plan_name=plan_info['name']
        )
        
        if not midtrans_response:
            conn.close()
            return jsonify({'error': 'Failed to create payment. Please try again.'}), 500
        
        # Save payment record
        conn.execute('''
            INSERT INTO payments (user_id, order_id, plan, amount, amount_usd, amount_idr, exchange_rate, status, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        ''', (session['user_id'], order_id, plan, price_usd, price_usd, amount_idr, exchange_rate,
              datetime.now() + timedelta(hours=24)))
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'token': midtrans_response.get('token'),
            'redirect_url': midtrans_response.get('redirect_url'),
            'order_id': order_id
        })
        
    except Exception as e:
        print(f"Create payment error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/payment-notification', methods=['POST'])
def payment_notification():
    """Handle Midtrans webhook notification"""
    try:
        data = request.get_json()
        
        order_id = data.get('order_id')
        transaction_status = data.get('transaction_status')
        fraud_status = data.get('fraud_status', 'accept')
        transaction_id = data.get('transaction_id')
        payment_type = data.get('payment_type')
        status_code = data.get('status_code')
        gross_amount = data.get('gross_amount')
        signature_key = data.get('signature_key')
        
        # Verify signature
        if signature_key and not verify_midtrans_signature(order_id, status_code, gross_amount, signature_key):
            return jsonify({'error': 'Invalid signature'}), 403
        
        conn = get_db()
        payment = conn.execute('SELECT * FROM payments WHERE order_id = ?', (order_id,)).fetchone()
        
        if not payment:
            conn.close()
            return jsonify({'error': 'Payment not found'}), 404
        
        # Determine payment status
        if transaction_status == 'capture':
            if fraud_status == 'accept':
                status = 'paid'
            else:
                status = 'fraud'
        elif transaction_status == 'settlement':
            status = 'paid'
        elif transaction_status in ['cancel', 'deny', 'expire']:
            status = 'failed'
        elif transaction_status == 'pending':
            status = 'pending'
        else:
            status = transaction_status
        
        # Update payment record
        conn.execute('''
            UPDATE payments SET 
                status = ?,
                payment_type = ?,
                midtrans_transaction_id = ?,
                midtrans_status = ?,
                fraud_status = ?,
                paid_at = CASE WHEN ? = 'paid' THEN ? ELSE paid_at END
            WHERE order_id = ?
        ''', (status, payment_type, transaction_id, transaction_status, 
              fraud_status, status, datetime.now(), order_id))
        
        # If payment successful, upgrade user subscription
        if status == 'paid':
            plan = payment['plan']
            plan_info = SUBSCRIPTION_PLANS.get(plan, {})
            days = plan_info.get('days', 30)
            
            # Calculate new expiry date
            current_expires = conn.execute(
                'SELECT subscription_expires FROM users WHERE id = ?', 
                (payment['user_id'],)
            ).fetchone()
            
            if current_expires and current_expires['subscription_expires']:
                try:
                    current_date = datetime.strptime(current_expires['subscription_expires'], '%Y-%m-%d %H:%M:%S.%f')
                    if current_date > datetime.now():
                        new_expires = current_date + timedelta(days=days)
                    else:
                        new_expires = datetime.now() + timedelta(days=days)
                except:
                    new_expires = datetime.now() + timedelta(days=days)
            else:
                new_expires = datetime.now() + timedelta(days=days)
            
            conn.execute('''
                UPDATE users SET subscription_plan = ?, subscription_expires = ?
                WHERE id = ?
            ''', (plan, new_expires, payment['user_id']))
            
            # Send invoice email
            user = conn.execute('SELECT name, email FROM users WHERE id = ?', (payment['user_id'],)).fetchone()
            if user:
                send_invoice_email(
                    to_email=user['email'],
                    user_name=user['name'],
                    order_id=order_id,
                    plan_name=plan_info.get('name', plan.title()),
                    amount_usd=payment['amount_usd'] or payment['amount'] or 0,
                    amount_idr=payment['amount_idr'] or 0,
                    payment_date=datetime.now().strftime('%Y-%m-%d %H:%M')
                )
        
        conn.commit()
        conn.close()
        
        return jsonify({'status': 'ok'})
        
    except Exception as e:
        print(f"Payment notification error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/payment-finish')
@login_required
def payment_finish():
    """Handle payment completion redirect"""
    order_id = request.args.get('order_id')
    status = request.args.get('transaction_status', 'unknown')
    
    conn = get_db()
    payment = None
    if order_id:
        payment = conn.execute('SELECT * FROM payments WHERE order_id = ?', (order_id,)).fetchone()
    conn.close()
    
    return render_template('payment_finish.html', 
                          order_id=order_id, 
                          status=status,
                          payment=payment)


@app.route('/payment-history')
@login_required
def payment_history():
    """Show user's payment history"""
    conn = get_db()
    payments = conn.execute('''
        SELECT * FROM payments WHERE user_id = ? ORDER BY created_at DESC
    ''', (session['user_id'],)).fetchall()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    
    return render_template('payment_history.html', payments=payments, user=user)


@app.route('/check-payment-status/<order_id>')
@login_required
def check_payment_status(order_id):
    """Check payment status"""
    conn = get_db()
    payment = conn.execute('''
        SELECT * FROM payments WHERE order_id = ? AND user_id = ?
    ''', (order_id, session['user_id'])).fetchone()
    conn.close()
    
    if not payment:
        return jsonify({'error': 'Payment not found'}), 404
    
    return jsonify({
        'status': payment['status'],
        'plan': payment['plan'],
        'amount_usd': payment['amount_usd'],
        'amount_idr': payment['amount_idr'],
        'paid_at': payment['paid_at']
    })


if __name__ == '__main__':
    init_db()
    init_auto_tables()
    start_scheduler(app)
    app.run(debug=True, port=4976)
