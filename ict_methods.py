"""
ICT Simple Weekly Bias Method
1. Get Previous Week High/Low
2. Determine Weekly Bias (which level will be taken)
3. Look for reversal on Tuesday-Thursday
4. Find entry at Order Block or FVG
"""

from datetime import datetime

def get_weekly_levels(highs, lows, closes, dates, interval='1h'):
    """
    Get Previous Week High/Low and Current Week levels
    """
    # Estimate candles per day based on interval
    candles_per_day = {'5m': 288, '15m': 96, '30m': 48, '1h': 24, '4h': 6, '1d': 1}.get(interval, 24)
    candles_per_week = candles_per_day * 5
    
    n = len(closes)
    
    levels = {
        'current_price': closes[-1] if closes else 0,
        'previous_week_high': None,
        'previous_week_low': None,
        'current_week_high': None,
        'current_week_low': None,
    }
    
    # Previous week (5-10 days ago)
    if n >= candles_per_week * 2:
        pw_start = n - candles_per_week * 2
        pw_end = n - candles_per_week
        levels['previous_week_high'] = round(max(highs[pw_start:pw_end]), 5)
        levels['previous_week_low'] = round(min(lows[pw_start:pw_end]), 5)
    elif n >= candles_per_week:
        # Use first half as previous week
        mid = n // 2
        levels['previous_week_high'] = round(max(highs[:mid]), 5)
        levels['previous_week_low'] = round(min(lows[:mid]), 5)
    
    # Current week
    if n >= candles_per_week:
        levels['current_week_high'] = round(max(highs[-candles_per_week:]), 5)
        levels['current_week_low'] = round(min(lows[-candles_per_week:]), 5)
    else:
        levels['current_week_high'] = round(max(highs), 5)
        levels['current_week_low'] = round(min(lows), 5)
    
    return levels


def determine_weekly_bias(levels, current_price):
    """
    Determine Weekly Bias based on previous week levels
    
    - If price is near Previous Week Low → Expect BULLISH (buy the low)
    - If price is near Previous Week High → Expect BEARISH (sell the high)
    - Look for reversal Tuesday-Thursday
    """
    pwh = levels.get('previous_week_high')
    pwl = levels.get('previous_week_low')
    
    if not pwh or not pwl:
        return 'NEUTRAL', "Not enough data for weekly bias"
    
    weekly_range = pwh - pwl
    mid_point = pwl + (weekly_range * 0.5)
    
    # Premium zone: above 50%
    # Discount zone: below 50%
    
    if current_price < mid_point:
        # Price in discount - look for buys
        distance_to_pwl = abs(current_price - pwl)
        distance_percent = (distance_to_pwl / weekly_range) * 100
        
        if distance_percent < 30:
            bias = 'BULLISH'
            reason = f"Price near Previous Week Low ({pwl:.5f}) - Look for BUY"
        else:
            bias = 'BULLISH'
            reason = f"Price in discount zone - Look for BUY on pullback to PWL"
    else:
        # Price in premium - look for sells
        distance_to_pwh = abs(current_price - pwh)
        distance_percent = (distance_to_pwh / weekly_range) * 100
        
        if distance_percent < 30:
            bias = 'BEARISH'
            reason = f"Price near Previous Week High ({pwh:.5f}) - Look for SELL"
        else:
            bias = 'BEARISH'
            reason = f"Price in premium zone - Look for SELL on rally to PWH"
    
    return bias, reason


def find_order_blocks(opens, highs, lows, closes):
    """
    Find Order Blocks - Simple version
    Bullish OB: Last red candle before big green move
    Bearish OB: Last green candle before big red move
    """
    order_blocks = []
    
    if len(closes) < 10:
        return order_blocks
    
    # Calculate average candle size
    avg_body = sum(abs(closes[i] - opens[i]) for i in range(len(closes))) / len(closes)
    
    for i in range(2, len(closes) - 2):
        current_body = abs(closes[i+1] - opens[i+1])
        
        # Bullish OB: Red candle followed by big green candle
        if closes[i] < opens[i]:  # Red candle
            if closes[i+1] > opens[i+1] and current_body > avg_body * 1.5:  # Big green after
                order_blocks.append({
                    'type': 'bullish',
                    'index': i,
                    'high': highs[i],
                    'low': lows[i],
                    'entry': (highs[i] + lows[i]) / 2,
                    'stop_loss': lows[i],
                })
        
        # Bearish OB: Green candle followed by big red candle
        if closes[i] > opens[i]:  # Green candle
            if closes[i+1] < opens[i+1] and current_body > avg_body * 1.5:  # Big red after
                order_blocks.append({
                    'type': 'bearish',
                    'index': i,
                    'high': highs[i],
                    'low': lows[i],
                    'entry': (highs[i] + lows[i]) / 2,
                    'stop_loss': highs[i],
                })
    
    return order_blocks[-5:]  # Return last 5


def find_fvg(highs, lows):
    """
    Find Fair Value Gaps - Simple version
    Bullish FVG: Gap up (candle 3 low > candle 1 high)
    Bearish FVG: Gap down (candle 3 high < candle 1 low)
    """
    fvg_list = []
    
    for i in range(2, len(highs)):
        # Bullish FVG
        if lows[i] > highs[i-2]:
            fvg_list.append({
                'type': 'bullish',
                'index': i,
                'high': lows[i],
                'low': highs[i-2],
                'entry': (lows[i] + highs[i-2]) / 2,
            })
        
        # Bearish FVG
        if highs[i] < lows[i-2]:
            fvg_list.append({
                'type': 'bearish',
                'index': i,
                'high': lows[i-2],
                'low': highs[i],
                'entry': (lows[i-2] + highs[i]) / 2,
            })
    
    return fvg_list[-5:]  # Return last 5


def generate_trade_setup(bias, levels, order_blocks, fvg_list, current_price, balance=10000, risk_percent=1):
    """
    Generate simple trade setup based on weekly bias
    """
    pwh = levels.get('previous_week_high', current_price * 1.01)
    pwl = levels.get('previous_week_low', current_price * 0.99)
    
    setups = []
    
    if bias == 'BULLISH':
        # Look for bullish OB or FVG for entry
        for ob in order_blocks:
            if ob['type'] == 'bullish' and ob['entry'] < current_price:
                entry = ob['entry']
                sl = ob['stop_loss'] - (current_price * 0.0005)  # Small buffer
                tp = pwh  # Target previous week high
                
                risk = entry - sl
                reward = tp - entry
                rr = reward / risk if risk > 0 else 0
                
                if rr >= 2:
                    risk_amount = balance * (risk_percent / 100)
                    lots = risk_amount / (risk * 10000 * 10)
                    
                    setups.append({
                        'type': 'BUY',
                        'entry': round(entry, 5),
                        'stop_loss': round(sl, 5),
                        'take_profit': round(tp, 5),
                        'risk_reward': round(rr, 1),
                        'lots': round(lots, 2),
                        'risk_amount': round(risk_amount, 2),
                        'reason': 'Bullish OB - Target PWH'
                    })
        
        for fvg in fvg_list:
            if fvg['type'] == 'bullish' and fvg['entry'] < current_price:
                entry = fvg['entry']
                sl = fvg['low'] - (current_price * 0.0005)
                tp = pwh
                
                risk = entry - sl
                reward = tp - entry
                rr = reward / risk if risk > 0 else 0
                
                if rr >= 2:
                    risk_amount = balance * (risk_percent / 100)
                    lots = risk_amount / (risk * 10000 * 10)
                    
                    setups.append({
                        'type': 'BUY',
                        'entry': round(entry, 5),
                        'stop_loss': round(sl, 5),
                        'take_profit': round(tp, 5),
                        'risk_reward': round(rr, 1),
                        'lots': round(lots, 2),
                        'risk_amount': round(risk_amount, 2),
                        'reason': 'Bullish FVG - Target PWH'
                    })
    
    elif bias == 'BEARISH':
        # Look for bearish OB or FVG for entry
        for ob in order_blocks:
            if ob['type'] == 'bearish' and ob['entry'] > current_price:
                entry = ob['entry']
                sl = ob['stop_loss'] + (current_price * 0.0005)
                tp = pwl  # Target previous week low
                
                risk = sl - entry
                reward = entry - tp
                rr = reward / risk if risk > 0 else 0
                
                if rr >= 2:
                    risk_amount = balance * (risk_percent / 100)
                    lots = risk_amount / (risk * 10000 * 10)
                    
                    setups.append({
                        'type': 'SELL',
                        'entry': round(entry, 5),
                        'stop_loss': round(sl, 5),
                        'take_profit': round(tp, 5),
                        'risk_reward': round(rr, 1),
                        'lots': round(lots, 2),
                        'risk_amount': round(risk_amount, 2),
                        'reason': 'Bearish OB - Target PWL'
                    })
        
        for fvg in fvg_list:
            if fvg['type'] == 'bearish' and fvg['entry'] > current_price:
                entry = fvg['entry']
                sl = fvg['high'] + (current_price * 0.0005)
                tp = pwl
                
                risk = sl - entry
                reward = entry - tp
                rr = reward / risk if risk > 0 else 0
                
                if rr >= 2:
                    risk_amount = balance * (risk_percent / 100)
                    lots = risk_amount / (risk * 10000 * 10)
                    
                    setups.append({
                        'type': 'SELL',
                        'entry': round(entry, 5),
                        'stop_loss': round(sl, 5),
                        'take_profit': round(tp, 5),
                        'risk_reward': round(rr, 1),
                        'lots': round(lots, 2),
                        'risk_amount': round(risk_amount, 2),
                        'reason': 'Bearish FVG - Target PWL'
                    })
    
    # Sort by R:R
    setups.sort(key=lambda x: x['risk_reward'], reverse=True)
    return setups[:3]  # Return top 3


def get_trading_day():
    """
    Check if today is a good trading day (Tuesday-Thursday)
    """
    day = datetime.now().weekday()
    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    
    is_optimal = day in [1, 2, 3]  # Tuesday, Wednesday, Thursday
    
    return {
        'day': day_names[day],
        'is_optimal': is_optimal,
        'message': 'Good day for reversals (Tue-Thu)' if is_optimal else 'Wait for Tuesday-Thursday for best setups'
    }


def analyze_ict(opens, highs, lows, closes, balance=10000, risk_percent=1.0, interval='1h'):
    """
    Simple ICT Weekly Bias Analysis
    
    1. Get Previous Week High/Low
    2. Determine bias
    3. Find OB/FVG for entry
    4. Generate trade setup
    """
    if len(closes) < 20:
        return {'error': 'Need at least 20 candles'}
    
    current_price = closes[-1]
    
    # Get weekly levels
    levels = get_weekly_levels(highs, lows, closes, [], interval)
    
    # Determine bias
    bias, bias_reason = determine_weekly_bias(levels, current_price)
    
    # Find OB and FVG
    order_blocks = find_order_blocks(opens, highs, lows, closes)
    fvg_list = find_fvg(highs, lows)
    
    # Generate setups
    trade_setups = generate_trade_setup(bias, levels, order_blocks, fvg_list, current_price, balance, risk_percent)
    
    # Check trading day
    trading_day = get_trading_day()
    
    return {
        'current_price': round(current_price, 5),
        'weekly_bias': bias,
        'bias_reason': bias_reason,
        'levels': levels,
        'order_blocks': order_blocks,
        'fvg': fvg_list,
        'trade_setups': trade_setups,
        'trading_day': trading_day,
    }
