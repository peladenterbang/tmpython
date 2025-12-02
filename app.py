from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import sqlite3
from datetime import datetime
import yfinance as yf

# ============== PIN SECURITY ==============
SECRET_PIN = "9793"  # Change this to your desired PIN
from indicators import (
    calculate_sma, calculate_ema, calculate_rsi, 
    calculate_macd, calculate_bollinger_bands, 
    get_signal, generate_sample_prices
)
from ict_methods import analyze_ict
from ml_predictor import predict_forex

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
app.secret_key = 'forex-risk-manager-secret-key-2024'  # Required for session
DATABASE = 'database.db'


def login_required(f):
    """Decorator to require PIN authentication"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        pin = request.form.get('pin', '')
        if pin == SECRET_PIN:
            session['authenticated'] = True
            return redirect(url_for('index'))
        else:
            error = 'Invalid PIN. Please try again.'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('login'))

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY,
            initial_balance REAL NOT NULL,
            current_balance REAL NOT NULL,
            max_drawdown_percent REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY,
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
            closed_at TIMESTAMP
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
    account = conn.execute('SELECT * FROM account LIMIT 1').fetchone()
    trades = conn.execute('SELECT * FROM trades ORDER BY created_at DESC LIMIT 10').fetchall()
    
    # Calculate stats
    all_trades = conn.execute('SELECT * FROM trades WHERE status = "closed"').fetchall()
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
    conn.execute('UPDATE account SET initial_balance = ?, current_balance = ? WHERE id = 1',
                (initial_balance, current_balance))
    conn.commit()
    conn.close()
    
    return redirect(url_for('index'))

@app.route('/calculator')
@login_required
def calculator():
    return render_template('calculator.html')

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
    risk_percent = float(request.form.get('risk_percent', 1)) if request.form.get('risk_percent') else None
    
    conn = get_db()
    conn.execute('''
        INSERT INTO trades (pair, trade_type, lot_size, entry_price, stop_loss, take_profit, risk_percent)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (pair, trade_type, lot_size, entry_price, stop_loss, take_profit, risk_percent))
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
        conn.execute('UPDATE account SET current_balance = current_balance + ? WHERE id = 1', (profit_loss,))
        conn.commit()
    
    conn.close()
    return redirect(url_for('index'))

@app.route('/delete_trade/<int:trade_id>', methods=['POST'])
@login_required
def delete_trade(trade_id):
    conn = get_db()
    conn.execute('DELETE FROM trades WHERE id = ?', (trade_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/trades')
@login_required
def trades():
    conn = get_db()
    trades = conn.execute('SELECT * FROM trades ORDER BY created_at DESC').fetchall()
    conn.close()
    return render_template('trades.html', trades=trades)

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
        
        # Get signal analysis
        result = get_signal(prices)
        result['prices'] = prices
        result['dates'] = dates
        result['pair'] = pair
        result['period'] = period
        result['interval'] = interval
        result['data_points'] = len(prices)
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/available_pairs')
def available_pairs():
    """Return list of available forex pairs"""
    return jsonify(list(FOREX_TICKERS.keys()))

@app.route('/ict')
@login_required
def ict():
    """ICT Analysis Page"""
    return render_template('ict.html')

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
        
        if len(closes) < 20:
            return jsonify({'error': 'Not enough data'}), 400
        
        # Run ICT analysis
        result = analyze_ict(opens, highs, lows, closes, balance, risk_percent, interval)
        
        # Add chart data
        result['pair'] = pair
        result['dates'] = dates
        result['ohlc'] = {
            'opens': opens,
            'highs': highs,
            'lows': lows,
            'closes': closes
        }
        
        return jsonify(result)
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500

@app.route('/ml_predict')
@login_required
def ml_predict():
    """ML Prediction Page"""
    return render_template('ml_predict.html')

@app.route('/analyze_ml', methods=['POST'])
@login_required
def analyze_ml():
    """
    ML-based Entry, TP, SL Prediction
    Uses technical indicators and pattern recognition
    """
    data = request.get_json()
    pair = data.get('pair', 'EUR/USD')
    period = data.get('period', '1mo')
    interval = data.get('interval', '1h')
    balance = float(data.get('balance', 10000))
    risk_percent = float(data.get('risk_percent', 1.0))
    
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
        
        # Run ML prediction
        result = predict_forex(opens, highs, lows, closes, balance, risk_percent)
        
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
        
        return jsonify(result)
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
