"""
Auto Scheduler - Automated Trade Execution System
Features:
- Scheduled market scanning
- Auto-execute trades based on probability threshold
- Monitor open positions for TP/SL triggers
- Track direction accuracy (true/false)
- Automatic balance updates
- Telegram notifications
"""

import yfinance as yf
import sqlite3
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from trading_strategies import EnsembleStrategy
from ict_methods import analyze_ict
import threading
import time

DATABASE = 'database.db'

# Global scheduler instance
scheduler = None
monitor_thread = None
stop_monitor = False


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_auto_tables():
    """Initialize database tables for auto execution"""
    conn = get_db()
    
    # Auto execution settings per user
    conn.execute('''
        CREATE TABLE IF NOT EXISTS auto_settings (
            id INTEGER PRIMARY KEY,
            user_id INTEGER UNIQUE,
            enabled INTEGER DEFAULT 0,
            scan_interval INTEGER DEFAULT 30,
            probability_threshold REAL DEFAULT 65.0,
            max_open_positions INTEGER DEFAULT 3,
            auto_execute INTEGER DEFAULT 0,
            telegram_alerts INTEGER DEFAULT 1,
            trading_method TEXT DEFAULT 'ML',
            pairs TEXT DEFAULT 'EUR/USD,GBP/USD,XAU/USD',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Add trading_method column if not exists (migration)
    try:
        conn.execute('ALTER TABLE auto_settings ADD COLUMN trading_method TEXT DEFAULT "ML"')
    except:
        pass  # Column already exists
    
    # Auto executed trades with monitoring
    conn.execute('''
        CREATE TABLE IF NOT EXISTS auto_executions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            pair VARCHAR(20) NOT NULL,
            direction VARCHAR(10) NOT NULL,
            entry_price REAL NOT NULL,
            current_price REAL,
            stop_loss REAL NOT NULL,
            take_profit REAL NOT NULL,
            lots REAL DEFAULT 0.01,
            probability REAL,
            status VARCHAR(20) DEFAULT 'open',
            exit_price REAL,
            exit_reason VARCHAR(20),
            pnl REAL DEFAULT 0,
            is_correct INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Execution logs for tracking
    conn.execute('''
        CREATE TABLE IF NOT EXISTS execution_logs (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            action VARCHAR(50) NOT NULL,
            pair VARCHAR(20),
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()


def log_action(user_id, action, pair=None, details=None):
    """Log an action to execution_logs"""
    conn = get_db()
    conn.execute('''
        INSERT INTO execution_logs (user_id, action, pair, details)
        VALUES (?, ?, ?, ?)
    ''', (user_id, action, pair, details))
    conn.commit()
    conn.close()


def send_telegram_notification(user_id, message):
    """Send Telegram notification to user"""
    try:
        conn = get_db()
        user = conn.execute('''
            SELECT telegram_bot_token, telegram_chat_id 
            FROM users WHERE id = ?
        ''', (user_id,)).fetchone()
        conn.close()
        
        if not user or not user['telegram_bot_token'] or not user['telegram_chat_id']:
            return False
        
        url = f"https://api.telegram.org/bot{user['telegram_bot_token']}/sendMessage"
        payload = {
            'chat_id': user['telegram_chat_id'],
            'text': message,
            'parse_mode': 'Markdown'
        }
        
        response = requests.post(url, json=payload, timeout=30)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


FOREX_TICKERS = {
    'EUR/USD': 'EURUSD=X',
    'GBP/USD': 'GBPUSD=X',
    'USD/JPY': 'USDJPY=X',
    'USD/CHF': 'USDCHF=X',
    'AUD/USD': 'AUDUSD=X',
    'USD/CAD': 'USDCAD=X',
    'XAU/USD': 'GC=F',
    'XAG/USD': 'SI=F',
    'BTC/USD': 'BTC-USD',
    'ETH/USD': 'ETH-USD',
    'US500': 'ES=F',
    'US100': 'NQ=F',
}


def fetch_pair_price(pair):
    """Get current price for a pair"""
    ticker_symbol = FOREX_TICKERS.get(pair)
    if not ticker_symbol:
        return None
    
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period='1d', interval='1m')
        if df.empty:
            df = ticker.history(period='5d', interval='1h')
        if df.empty:
            return None
        return df['Close'].iloc[-1]
    except:
        return None


# Alias for backward compatibility
def get_current_price(pair):
    """Alias for fetch_pair_price - Get current price for a pair"""
    return fetch_pair_price(pair)


def analyze_pair_for_signal(pair, balance=10000, risk_percent=1.0, trading_method='ML'):
    """
    Analyze a pair and return signal with probability
    trading_method: 'ML' (Machine Learning), 'ICT' (Smart Money), 'HYBRID' (Both)
    """
    ticker_symbol = FOREX_TICKERS.get(pair)
    if not ticker_symbol:
        return None
    
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period='1mo', interval='1h')
        
        if df.empty or len(df) < 50:
            return None
        
        opens = df['Open'].tolist()
        highs = df['High'].tolist()
        lows = df['Low'].tolist()
        closes = df['Close'].tolist()
        
        signal = None
        probability = 0
        method_used = trading_method
        
        if trading_method == 'ICT':
            # Use ICT (Smart Money) analysis
            result = analyze_ict(opens, highs, lows, closes, balance, risk_percent, '1h')
            
            if 'error' in result:
                return None
            
            # Get ICT signal from weekly bias and trade setups
            bias = result.get('weekly_bias', 'NEUTRAL')
            confidence = result.get('confidence', 50)
            trade_setups = result.get('trade_setups', [])
            
            if bias == 'BULLISH' and confidence >= 50:
                direction = 'BUY'
            elif bias == 'BEARISH' and confidence >= 50:
                direction = 'SELL'
            else:
                direction = 'WAIT'
            
            if direction != 'WAIT':
                # Use trade setup if available
                if trade_setups:
                    setup = trade_setups[0]
                    signal = {
                        'direction': setup.get('type', direction),
                        'entry': setup.get('entry', closes[-1]),
                        'stop_loss': setup.get('stop_loss', closes[-1] * 0.99 if direction == 'BUY' else closes[-1] * 1.01),
                        'take_profit': setup.get('take_profit', closes[-1] * 1.02 if direction == 'BUY' else closes[-1] * 0.98),
                        'lots': setup.get('lots', 0.01),
                        'confidence': confidence
                    }
                else:
                    # Generate basic signal from bias
                    signal = {
                        'direction': direction,
                        'entry': closes[-1],
                        'stop_loss': closes[-1] * 0.995 if direction == 'BUY' else closes[-1] * 1.005,
                        'take_profit': closes[-1] * 1.015 if direction == 'BUY' else closes[-1] * 0.985,
                        'lots': 0.01,
                        'confidence': confidence
                    }
                
                # Calculate probability from ICT confidence factors
                probability = confidence
                
                # Bonus for kill zone
                session = result.get('session', {})
                if session.get('is_kill_zone'):
                    probability = min(95, probability + 10)
                
                # Bonus for structure alignment
                market_structure = result.get('market_structure', {})
                if market_structure.get('trend') == bias:
                    probability = min(95, probability + 5)
        
        elif trading_method == 'ML':
            # Use ML (Ensemble) analysis
            strategy = EnsembleStrategy()
            result = strategy.analyze(opens, highs, lows, closes, balance, risk_percent)
            
            if 'signals' not in result or not result['signals']:
                return None
            
            signal = result['signals'][0]
            
            # Calculate execution probability
            ensemble_scores = result.get('ensemble_scores', {})
            buy_score = ensemble_scores.get('buy_score', 0)
            sell_score = ensemble_scores.get('sell_score', 0)
            
            if signal['direction'] == 'BUY':
                probability = min(95, 40 + buy_score * 0.5)
            elif signal['direction'] == 'SELL':
                probability = min(95, 40 + sell_score * 0.5)
            else:
                probability = 0
        
        elif trading_method == 'HYBRID':
            # Use both ML and ICT, combine signals
            
            # Get ML signal
            strategy = EnsembleStrategy()
            ml_result = strategy.analyze(opens, highs, lows, closes, balance, risk_percent)
            
            ml_signal = None
            ml_probability = 0
            if 'signals' in ml_result and ml_result['signals']:
                ml_signal = ml_result['signals'][0]
                ensemble_scores = ml_result.get('ensemble_scores', {})
                if ml_signal['direction'] == 'BUY':
                    ml_probability = min(95, 40 + ensemble_scores.get('buy_score', 0) * 0.5)
                elif ml_signal['direction'] == 'SELL':
                    ml_probability = min(95, 40 + ensemble_scores.get('sell_score', 0) * 0.5)
            
            # Get ICT signal
            ict_result = analyze_ict(opens, highs, lows, closes, balance, risk_percent, '1h')
            
            ict_bias = ict_result.get('weekly_bias', 'NEUTRAL') if 'error' not in ict_result else 'NEUTRAL'
            ict_confidence = ict_result.get('confidence', 50) if 'error' not in ict_result else 50
            
            ict_direction = 'BUY' if ict_bias == 'BULLISH' else 'SELL' if ict_bias == 'BEARISH' else 'WAIT'
            
            # Check if ML and ICT agree
            if ml_signal and ml_signal['direction'] == ict_direction:
                # Both agree - high confidence
                signal = ml_signal
                probability = min(95, (ml_probability + ict_confidence) / 2 + 15)  # Bonus for agreement
                method_used = 'HYBRID_AGREE'
            elif ml_signal and ml_probability >= 70:
                # ML has strong signal, use it even if ICT disagrees
                signal = ml_signal
                probability = ml_probability * 0.9  # Slight penalty for disagreement
                method_used = 'HYBRID_ML'
            elif ict_direction != 'WAIT' and ict_confidence >= 70:
                # ICT has strong signal
                trade_setups = ict_result.get('trade_setups', [])
                if trade_setups:
                    setup = trade_setups[0]
                    signal = {
                        'direction': setup.get('type', ict_direction),
                        'entry': setup.get('entry', closes[-1]),
                        'stop_loss': setup.get('stop_loss', closes[-1] * 0.99 if ict_direction == 'BUY' else closes[-1] * 1.01),
                        'take_profit': setup.get('take_profit', closes[-1] * 1.02 if ict_direction == 'BUY' else closes[-1] * 0.98),
                        'lots': setup.get('lots', 0.01),
                        'confidence': ict_confidence
                    }
                else:
                    signal = {
                        'direction': ict_direction,
                        'entry': closes[-1],
                        'stop_loss': closes[-1] * 0.995 if ict_direction == 'BUY' else closes[-1] * 1.005,
                        'take_profit': closes[-1] * 1.015 if ict_direction == 'BUY' else closes[-1] * 0.985,
                        'lots': 0.01,
                        'confidence': ict_confidence
                    }
                probability = ict_confidence * 0.9
                method_used = 'HYBRID_ICT'
            elif ml_signal:
                # Use ML signal with lower confidence
                signal = ml_signal
                probability = ml_probability * 0.8
                method_used = 'HYBRID_ML_WEAK'
        
        if not signal or signal.get('direction') == 'WAIT':
            return None
        
        return {
            'pair': pair,
            'direction': signal['direction'],
            'entry': signal.get('entry', closes[-1]),
            'stop_loss': signal.get('stop_loss'),
            'take_profit': signal.get('take_profit'),
            'lots': signal.get('lots', 0.01),
            'probability': round(probability, 1),
            'confidence': signal.get('confidence', 50),
            'current_price': closes[-1],
            'method': method_used
        }
    except Exception as e:
        print(f"Error analyzing {pair} with {trading_method}: {e}")
        return None


def scan_markets_for_user(user_id):
    """Scan markets for a specific user based on their settings"""
    conn = get_db()
    
    # Get user settings
    settings = conn.execute('''
        SELECT * FROM auto_settings WHERE user_id = ?
    ''', (user_id,)).fetchone()
    
    if not settings or not settings['enabled']:
        conn.close()
        return
    
    # Get user account
    account = conn.execute('''
        SELECT current_balance FROM account WHERE user_id = ?
    ''', (user_id,)).fetchone()
    
    balance = account['current_balance'] if account else 10000
    
    # Count today's executions (daily limit)
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_trades = conn.execute('''
        SELECT COUNT(*) FROM auto_executions 
        WHERE user_id = ? AND created_at >= ?
    ''', (user_id, today_start)).fetchone()[0]
    
    if today_trades >= settings['max_open_positions']:
        log_action(user_id, 'SCAN_SKIPPED', details=f'Daily limit reached ({today_trades}/{settings["max_open_positions"]})')
        conn.close()
        return
    
    pairs = settings['pairs'].split(',')
    probability_threshold = settings['probability_threshold']
    auto_execute = settings['auto_execute']
    telegram_alerts = settings['telegram_alerts']
    trading_method = settings.get('trading_method', 'ML')  # Default to ML
    
    conn.close()
    
    log_action(user_id, 'SCAN_STARTED', details=f'Scanning {len(pairs)} pairs with {trading_method} method')
    
    for pair in pairs:
        pair = pair.strip()
        
        # Check if already have position in this pair
        conn = get_db()
        existing = conn.execute('''
            SELECT id FROM auto_executions 
            WHERE user_id = ? AND pair = ? AND status = 'open'
        ''', (user_id, pair)).fetchone()
        conn.close()
        
        if existing:
            continue
        
        signal = analyze_pair_for_signal(pair, balance, 1.0, trading_method)
        
        if not signal:
            continue
        
        if signal['probability'] >= probability_threshold:
            log_action(user_id, 'SIGNAL_FOUND', pair, 
                      f"{signal['direction']} @ {signal['entry']}, Prob: {signal['probability']}%")
            
            if auto_execute:
                execute_trade(user_id, signal)
            
            if telegram_alerts:
                message = f"""
🤖 *AUTO SIGNAL DETECTED*
━━━━━━━━━━━━━━━━━━

📊 *Pair:* `{pair}`
{'🟢' if signal['direction'] == 'BUY' else '🔴'} *Signal:* `{signal['direction']}`
📈 *Probability:* `{signal['probability']}%`

💰 *Entry:* `{signal['entry']}`
🛑 *Stop Loss:* `{signal['stop_loss']}`
🎯 *Take Profit:* `{signal['take_profit']}`
📦 *Lots:* `{signal['lots']}`

{'✅ *Trade Executed Automatically*' if auto_execute else '⏳ *Waiting for manual execution*'}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                send_telegram_notification(user_id, message)
    
    log_action(user_id, 'SCAN_COMPLETED', details=f'Scan finished')


def execute_trade(user_id, signal):
    """Execute a trade and store in database"""
    conn = get_db()
    
    conn.execute('''
        INSERT INTO auto_executions 
        (user_id, pair, direction, entry_price, current_price, stop_loss, take_profit, lots, probability, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
    ''', (
        user_id, signal['pair'], signal['direction'], 
        signal['entry'], signal['current_price'],
        signal['stop_loss'], signal['take_profit'], 
        signal['lots'], signal['probability']
    ))
    
    conn.commit()
    conn.close()
    
    log_action(user_id, 'TRADE_EXECUTED', signal['pair'],
              f"{signal['direction']} @ {signal['entry']}, SL: {signal['stop_loss']}, TP: {signal['take_profit']}")


def check_tp_sl_triggers():
    """Check all open positions for TP/SL triggers"""
    conn = get_db()
    
    open_positions = conn.execute('''
        SELECT * FROM auto_executions WHERE status = 'open'
    ''').fetchall()
    
    conn.close()
    
    for position in open_positions:
        pair = position['pair']
        current_price = get_current_price(pair)
        
        if current_price is None:
            continue
        
        direction = position['direction']
        entry_price = position['entry_price']
        stop_loss = position['stop_loss']
        take_profit = position['take_profit']
        lots = position['lots']
        user_id = position['user_id']
        position_id = position['id']
        
        triggered = False
        exit_reason = None
        exit_price = current_price
        is_correct = None
        
        if direction == 'BUY':
            # Check TP hit
            if current_price >= take_profit:
                triggered = True
                exit_reason = 'TP_HIT'
                exit_price = take_profit
                is_correct = 1  # Correct direction
            # Check SL hit
            elif current_price <= stop_loss:
                triggered = True
                exit_reason = 'SL_HIT'
                exit_price = stop_loss
                is_correct = 0  # Wrong direction
        
        elif direction == 'SELL':
            # Check TP hit
            if current_price <= take_profit:
                triggered = True
                exit_reason = 'TP_HIT'
                exit_price = take_profit
                is_correct = 1  # Correct direction
            # Check SL hit
            elif current_price >= stop_loss:
                triggered = True
                exit_reason = 'SL_HIT'
                exit_price = stop_loss
                is_correct = 0  # Wrong direction
        
        if triggered:
            close_position(position_id, user_id, exit_price, exit_reason, is_correct, direction, entry_price, lots, pair)
        else:
            # Update current price
            conn = get_db()
            conn.execute('''
                UPDATE auto_executions SET current_price = ? WHERE id = ?
            ''', (current_price, position_id))
            conn.commit()
            conn.close()


def close_position(position_id, user_id, exit_price, exit_reason, is_correct, direction, entry_price, lots, pair):
    """Close a position and update balance"""
    # Calculate P&L
    if direction == 'BUY':
        pnl_pips = (exit_price - entry_price) / entry_price * 10000
    else:
        pnl_pips = (entry_price - exit_price) / entry_price * 10000
    
    # Calculate monetary P&L (simplified)
    lot_value = lots * 100000
    pnl = pnl_pips * lot_value / 10000
    pnl = round(pnl, 2)
    
    conn = get_db()
    
    # Update position
    conn.execute('''
        UPDATE auto_executions 
        SET status = 'closed', exit_price = ?, exit_reason = ?, pnl = ?, 
            is_correct = ?, closed_at = ?
        WHERE id = ?
    ''', (exit_price, exit_reason, pnl, is_correct, datetime.now(), position_id))
    
    # Update account balance
    conn.execute('''
        UPDATE account SET current_balance = current_balance + ? WHERE user_id = ?
    ''', (pnl, user_id))
    
    conn.commit()
    
    # Get updated balance
    account = conn.execute('SELECT current_balance FROM account WHERE user_id = ?', (user_id,)).fetchone()
    new_balance = account['current_balance'] if account else 0
    
    # Check if user wants telegram alerts
    settings = conn.execute('SELECT telegram_alerts FROM auto_settings WHERE user_id = ?', (user_id,)).fetchone()
    
    conn.close()
    
    # Log the closure
    log_action(user_id, f'POSITION_CLOSED_{exit_reason}', pair,
              f"Exit: {exit_price}, P&L: ${pnl}, Correct: {'Yes' if is_correct else 'No'}")
    
    # Send Telegram notification
    if settings and settings['telegram_alerts']:
        emoji = '✅' if is_correct else '❌'
        pnl_emoji = '💰' if pnl > 0 else '📉'
        
        message = f"""
{emoji} *POSITION CLOSED - {exit_reason.replace('_', ' ')}*
━━━━━━━━━━━━━━━━━━

📊 *Pair:* `{pair}`
📈 *Direction:* `{direction}`
{'🎯' if exit_reason == 'TP_HIT' else '🛑'} *Exit Reason:* `{exit_reason.replace('_', ' ')}`

💵 *Entry:* `{entry_price}`
💵 *Exit:* `{exit_price}`
{pnl_emoji} *P&L:* `{'+'if pnl > 0 else ''}${pnl}`

{'✅ *Direction Correct*' if is_correct else '❌ *Direction Wrong*'}

💼 *New Balance:* `${new_balance:,.2f}`

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        send_telegram_notification(user_id, message)


def monitor_positions():
    """Background thread to monitor positions"""
    global stop_monitor
    
    while not stop_monitor:
        try:
            check_tp_sl_triggers()
        except Exception as e:
            print(f"Monitor error: {e}")
        
        time.sleep(60)  # Check every minute


def scheduled_scan():
    """Scheduled job to scan markets for all enabled users"""
    conn = get_db()
    
    enabled_users = conn.execute('''
        SELECT user_id FROM auto_settings WHERE enabled = 1
    ''').fetchall()
    
    conn.close()
    
    for user in enabled_users:
        try:
            scan_markets_for_user(user['user_id'])
        except Exception as e:
            print(f"Scan error for user {user['user_id']}: {e}")


def start_scheduler(app):
    """Start the background scheduler"""
    global scheduler, monitor_thread, stop_monitor
    
    init_auto_tables()
    
    if scheduler is None:
        scheduler = BackgroundScheduler()
        
        # Add job to scan markets every 30 minutes
        scheduler.add_job(
            scheduled_scan, 
            'interval', 
            minutes=30, 
            id='market_scan',
            replace_existing=True
        )
        
        scheduler.start()
        print("Scheduler started - scanning every 30 minutes")
    
    # Start position monitor thread
    if monitor_thread is None or not monitor_thread.is_alive():
        stop_monitor = False
        monitor_thread = threading.Thread(target=monitor_positions, daemon=True)
        monitor_thread.start()
        print("Position monitor started")


def stop_scheduler():
    """Stop the scheduler"""
    global scheduler, stop_monitor
    
    stop_monitor = True
    
    if scheduler:
        scheduler.shutdown()
        scheduler = None
        print("Scheduler stopped")


def get_user_stats(user_id):
    """Get execution statistics for a user"""
    conn = get_db()
    
    # Total trades
    total = conn.execute('''
        SELECT COUNT(*) FROM auto_executions WHERE user_id = ?
    ''', (user_id,)).fetchone()[0]
    
    # Closed trades
    closed = conn.execute('''
        SELECT COUNT(*) FROM auto_executions WHERE user_id = ? AND status = 'closed'
    ''', (user_id,)).fetchone()[0]
    
    # Open trades
    open_count = conn.execute('''
        SELECT COUNT(*) FROM auto_executions WHERE user_id = ? AND status = 'open'
    ''', (user_id,)).fetchone()[0]
    
    # Today's trades
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_trades = conn.execute('''
        SELECT COUNT(*) FROM auto_executions WHERE user_id = ? AND created_at >= ?
    ''', (user_id, today_start)).fetchone()[0]
    
    # Correct predictions
    correct = conn.execute('''
        SELECT COUNT(*) FROM auto_executions WHERE user_id = ? AND is_correct = 1
    ''', (user_id,)).fetchone()[0]
    
    # Wrong predictions
    wrong = conn.execute('''
        SELECT COUNT(*) FROM auto_executions WHERE user_id = ? AND is_correct = 0
    ''', (user_id,)).fetchone()[0]
    
    # Total P&L
    total_pnl = conn.execute('''
        SELECT COALESCE(SUM(pnl), 0) FROM auto_executions WHERE user_id = ? AND status = 'closed'
    ''', (user_id,)).fetchone()[0]
    
    # TP hits
    tp_hits = conn.execute('''
        SELECT COUNT(*) FROM auto_executions WHERE user_id = ? AND exit_reason = 'TP_HIT'
    ''', (user_id,)).fetchone()[0]
    
    # SL hits
    sl_hits = conn.execute('''
        SELECT COUNT(*) FROM auto_executions WHERE user_id = ? AND exit_reason = 'SL_HIT'
    ''', (user_id,)).fetchone()[0]
    
    # Accuracy rate
    accuracy = (correct / closed * 100) if closed > 0 else 0
    
    # Win rate (profitable trades)
    profitable = conn.execute('''
        SELECT COUNT(*) FROM auto_executions WHERE user_id = ? AND pnl > 0
    ''', (user_id,)).fetchone()[0]
    
    win_rate = (profitable / closed * 100) if closed > 0 else 0
    
    conn.close()
    
    return {
        'total_trades': total,
        'closed_trades': closed,
        'open_trades': open_count,
        'today_trades': today_trades,
        'correct_predictions': correct,
        'wrong_predictions': wrong,
        'accuracy_rate': round(accuracy, 1),
        'win_rate': round(win_rate, 1),
        'total_pnl': round(total_pnl, 2),
        'tp_hits': tp_hits,
        'sl_hits': sl_hits
    }


def get_user_executions(user_id, limit=50):
    """Get recent executions for a user"""
    conn = get_db()
    
    executions = conn.execute('''
        SELECT * FROM auto_executions 
        WHERE user_id = ? 
        ORDER BY created_at DESC 
        LIMIT ?
    ''', (user_id, limit)).fetchall()
    
    conn.close()
    
    return [dict(e) for e in executions]


def get_user_logs(user_id, limit=100):
    """Get recent logs for a user"""
    conn = get_db()
    
    logs = conn.execute('''
        SELECT * FROM execution_logs 
        WHERE user_id = ? 
        ORDER BY created_at DESC 
        LIMIT ?
    ''', (user_id, limit)).fetchall()
    
    conn.close()
    
    return [dict(l) for l in logs]


def get_user_settings(user_id):
    """Get auto settings for a user"""
    conn = get_db()
    
    settings = conn.execute('''
        SELECT * FROM auto_settings WHERE user_id = ?
    ''', (user_id,)).fetchone()
    
    conn.close()
    
    if settings:
        result = dict(settings)
        # Ensure trading_method has a default
        if 'trading_method' not in result or not result['trading_method']:
            result['trading_method'] = 'ML'
        return result
    
    return {
        'enabled': 0,
        'scan_interval': 30,
        'probability_threshold': 65.0,
        'max_open_positions': 3,
        'auto_execute': 0,
        'telegram_alerts': 1,
        'trading_method': 'ML',
        'pairs': 'EUR/USD,GBP/USD,XAU/USD'
    }


def save_user_settings(user_id, settings):
    """Save auto settings for a user"""
    conn = get_db()
    
    existing = conn.execute('SELECT id FROM auto_settings WHERE user_id = ?', (user_id,)).fetchone()
    
    if existing:
        conn.execute('''
            UPDATE auto_settings SET
                enabled = ?, scan_interval = ?, probability_threshold = ?,
                max_open_positions = ?, auto_execute = ?, telegram_alerts = ?,
                trading_method = ?, pairs = ?, updated_at = ?
            WHERE user_id = ?
        ''', (
            settings.get('enabled', 0),
            settings.get('scan_interval', 30),
            settings.get('probability_threshold', 65.0),
            settings.get('max_open_positions', 3),
            settings.get('auto_execute', 0),
            settings.get('telegram_alerts', 1),
            settings.get('trading_method', 'ML'),
            settings.get('pairs', 'EUR/USD,GBP/USD,XAU/USD'),
            datetime.now(),
            user_id
        ))
    else:
        conn.execute('''
            INSERT INTO auto_settings 
            (user_id, enabled, scan_interval, probability_threshold, max_open_positions, auto_execute, telegram_alerts, trading_method, pairs)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            settings.get('enabled', 0),
            settings.get('scan_interval', 30),
            settings.get('probability_threshold', 65.0),
            settings.get('max_open_positions', 3),
            settings.get('auto_execute', 0),
            settings.get('telegram_alerts', 1),
            settings.get('trading_method', 'ML'),
            settings.get('pairs', 'EUR/USD,GBP/USD,XAU/USD')
        ))
    
    conn.commit()
    conn.close()
    
    log_action(user_id, 'SETTINGS_UPDATED', details=f"Method: {settings.get('trading_method', 'ML')}, Auto-execute: {settings.get('auto_execute', 0)}")
