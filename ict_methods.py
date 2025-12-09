"""
ICT (Inner Circle Trader) Methods
Based on Michael J. Huddleston's concepts:

1. Kill Zones (Session Times)
2. Liquidity Zones (Buy-side/Sell-side)
3. Fair Value Gaps (FVG)
4. Order Blocks (OB)
5. Break of Structure (BOS) / Change of Character (ChoCH)
6. Premium/Discount Zones
7. Previous Day/Week/Month Levels
8. Breaker Blocks
9. Displacement Detection
10. Power of 3 (Accumulation, Manipulation, Distribution)
"""

from datetime import datetime, timezone
import pytz


# ============== KILL ZONES ==============
def get_kill_zones():
    """
    ICT Kill Zones - High probability trading times
    All times in EST (New York time)
    """
    return {
        'asian': {'start': 20, 'end': 0, 'name': 'Asian Session', 'description': 'Low volatility, accumulation'},
        'london_open': {'start': 2, 'end': 5, 'name': 'London Open Kill Zone', 'description': 'High volatility, trend starts'},
        'ny_open': {'start': 7, 'end': 10, 'name': 'New York Open Kill Zone', 'description': 'Highest volatility, reversals'},
        'london_close': {'start': 10, 'end': 12, 'name': 'London Close Kill Zone', 'description': 'Profit taking, reversals'},
        'ny_pm': {'start': 13, 'end': 16, 'name': 'NY Afternoon', 'description': 'Lower volatility, consolidation'},
    }


def get_current_session():
    """
    Get current trading session based on EST time
    """
    try:
        est = pytz.timezone('America/New_York')
        now = datetime.now(est)
        hour = now.hour
        
        kill_zones = get_kill_zones()
        
        for zone_key, zone in kill_zones.items():
            start = zone['start']
            end = zone['end']
            
            # Handle overnight sessions
            if start > end:
                if hour >= start or hour < end:
                    return {
                        'zone': zone_key,
                        'name': zone['name'],
                        'description': zone['description'],
                        'is_kill_zone': zone_key in ['london_open', 'ny_open', 'london_close'],
                        'hour': hour
                    }
            else:
                if start <= hour < end:
                    return {
                        'zone': zone_key,
                        'name': zone['name'],
                        'description': zone['description'],
                        'is_kill_zone': zone_key in ['london_open', 'ny_open', 'london_close'],
                        'hour': hour
                    }
        
        return {
            'zone': 'off_hours',
            'name': 'Off Hours',
            'description': 'Low liquidity period',
            'is_kill_zone': False,
            'hour': hour
        }
    except:
        return {
            'zone': 'unknown',
            'name': 'Unknown',
            'description': 'Could not determine session',
            'is_kill_zone': False,
            'hour': 0
        }


# ============== LIQUIDITY ZONES ==============
def find_liquidity_zones(highs, lows, closes, lookback=20):
    """
    Find Buy-side and Sell-side liquidity zones
    - Buy-side liquidity: Above recent highs (stop losses of shorts)
    - Sell-side liquidity: Below recent lows (stop losses of longs)
    """
    if len(highs) < lookback:
        return {'buy_side': [], 'sell_side': []}
    
    buy_side_liquidity = []
    sell_side_liquidity = []
    
    # Find swing highs (potential buy-side liquidity)
    for i in range(2, len(highs) - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and \
           highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            buy_side_liquidity.append({
                'level': round(highs[i], 5),
                'index': i,
                'type': 'swing_high',
                'taken': closes[-1] > highs[i] if closes else False
            })
    
    # Find swing lows (potential sell-side liquidity)
    for i in range(2, len(lows) - 2):
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and \
           lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            sell_side_liquidity.append({
                'level': round(lows[i], 5),
                'index': i,
                'type': 'swing_low',
                'taken': closes[-1] < lows[i] if closes else False
            })
    
    # Get nearest untaken levels
    current_price = closes[-1] if closes else 0
    
    nearest_buy_side = None
    nearest_sell_side = None
    
    for level in sorted(buy_side_liquidity, key=lambda x: x['level']):
        if level['level'] > current_price and not level['taken']:
            nearest_buy_side = level
            break
    
    for level in sorted(sell_side_liquidity, key=lambda x: x['level'], reverse=True):
        if level['level'] < current_price and not level['taken']:
            nearest_sell_side = level
            break
    
    return {
        'buy_side': buy_side_liquidity[-5:],
        'sell_side': sell_side_liquidity[-5:],
        'nearest_buy_side': nearest_buy_side,
        'nearest_sell_side': nearest_sell_side
    }


# ============== BREAK OF STRUCTURE / CHANGE OF CHARACTER ==============
def detect_market_structure(highs, lows, closes, lookback=20):
    """
    Detect Break of Structure (BOS) and Change of Character (ChoCH)
    - BOS: Continuation of trend (HH/HL in uptrend, LH/LL in downtrend)
    - ChoCH: First sign of reversal
    """
    if len(closes) < lookback:
        return {'trend': 'NEUTRAL', 'structures': []}
    
    structures = []
    swing_highs = []
    swing_lows = []
    
    # Find swing points
    for i in range(2, len(highs) - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
            swing_highs.append({'price': highs[i], 'index': i})
        if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
            swing_lows.append({'price': lows[i], 'index': i})
    
    # Analyze structure
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        last_high = swing_highs[-1]['price']
        prev_high = swing_highs[-2]['price']
        last_low = swing_lows[-1]['price']
        prev_low = swing_lows[-2]['price']
        
        current_price = closes[-1]
        
        # Uptrend: Higher Highs and Higher Lows
        if last_high > prev_high and last_low > prev_low:
            trend = 'BULLISH'
            
            # Check for BOS (break above last high)
            if current_price > last_high:
                structures.append({
                    'type': 'BOS',
                    'direction': 'BULLISH',
                    'level': round(last_high, 5),
                    'description': 'Break of Structure - Bullish continuation'
                })
            
            # Check for ChoCH (break below last low in uptrend)
            if current_price < last_low:
                structures.append({
                    'type': 'ChoCH',
                    'direction': 'BEARISH',
                    'level': round(last_low, 5),
                    'description': 'Change of Character - Potential reversal to bearish'
                })
        
        # Downtrend: Lower Highs and Lower Lows
        elif last_high < prev_high and last_low < prev_low:
            trend = 'BEARISH'
            
            # Check for BOS (break below last low)
            if current_price < last_low:
                structures.append({
                    'type': 'BOS',
                    'direction': 'BEARISH',
                    'level': round(last_low, 5),
                    'description': 'Break of Structure - Bearish continuation'
                })
            
            # Check for ChoCH (break above last high in downtrend)
            if current_price > last_high:
                structures.append({
                    'type': 'ChoCH',
                    'direction': 'BULLISH',
                    'level': round(last_high, 5),
                    'description': 'Change of Character - Potential reversal to bullish'
                })
        else:
            trend = 'RANGING'
    else:
        trend = 'NEUTRAL'
    
    return {
        'trend': trend,
        'structures': structures,
        'swing_highs': swing_highs[-3:],
        'swing_lows': swing_lows[-3:]
    }


# ============== DISPLACEMENT ==============
def detect_displacement(opens, highs, lows, closes, threshold=1.5):
    """
    Detect Displacement - Strong impulsive moves
    Displacement = Large candle body (> 1.5x average)
    """
    if len(closes) < 20:
        return []
    
    displacements = []
    
    # Calculate average body size
    bodies = [abs(closes[i] - opens[i]) for i in range(len(closes))]
    avg_body = sum(bodies) / len(bodies)
    
    for i in range(len(closes) - 10, len(closes)):
        if i < 0:
            continue
            
        body = abs(closes[i] - opens[i])
        
        if body > avg_body * threshold:
            direction = 'BULLISH' if closes[i] > opens[i] else 'BEARISH'
            displacements.append({
                'index': i,
                'direction': direction,
                'size': round(body / avg_body, 2),
                'open': round(opens[i], 5),
                'close': round(closes[i], 5),
                'description': f'{direction} displacement ({round(body/avg_body, 1)}x average)'
            })
    
    return displacements


# ============== INDUCEMENT ==============
def find_inducement(highs, lows, closes, lookback=20):
    """
    Find Inducement levels - Minor swing points used to trap traders
    """
    if len(closes) < lookback:
        return []
    
    inducements = []
    
    # Find minor swing points (using 1 candle lookback instead of 2)
    for i in range(1, len(highs) - 1):
        # Minor high
        if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
            inducements.append({
                'type': 'minor_high',
                'level': round(highs[i], 5),
                'index': i,
                'description': 'Potential inducement high (stop hunt target)'
            })
        
        # Minor low
        if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
            inducements.append({
                'type': 'minor_low',
                'level': round(lows[i], 5),
                'index': i,
                'description': 'Potential inducement low (stop hunt target)'
            })
    
    return inducements[-10:]


# ============== BREAKER BLOCKS ==============
def find_breaker_blocks(opens, highs, lows, closes):
    """
    Find Breaker Blocks - Failed Order Blocks that become support/resistance
    When an Order Block fails, it becomes a Breaker Block
    """
    if len(closes) < 20:
        return []
    
    breakers = []
    order_blocks = find_order_blocks(opens, highs, lows, closes)
    
    current_price = closes[-1]
    
    for ob in order_blocks:
        # Bullish OB that gets broken becomes bearish breaker
        if ob['type'] == 'bullish':
            # Check if price broke below the OB low after it formed
            broken = False
            for i in range(ob['index'] + 3, len(lows)):
                if lows[i] < ob['low']:
                    broken = True
                    break
            
            if broken and current_price > ob['low']:
                breakers.append({
                    'type': 'bearish_breaker',
                    'high': ob['high'],
                    'low': ob['low'],
                    'index': ob['index'],
                    'description': 'Failed bullish OB - Now resistance'
                })
        
        # Bearish OB that gets broken becomes bullish breaker
        elif ob['type'] == 'bearish':
            broken = False
            for i in range(ob['index'] + 3, len(highs)):
                if highs[i] > ob['high']:
                    broken = True
                    break
            
            if broken and current_price < ob['high']:
                breakers.append({
                    'type': 'bullish_breaker',
                    'high': ob['high'],
                    'low': ob['low'],
                    'index': ob['index'],
                    'description': 'Failed bearish OB - Now support'
                })
    
    return breakers[-5:]


# ============== POWER OF 3 (AMD) ==============
def detect_power_of_3(opens, highs, lows, closes, dates=None):
    """
    Detect Power of 3 (AMD) pattern:
    - Accumulation: Consolidation/range (Asian session)
    - Manipulation: Fake move to grab liquidity
    - Distribution: True move in opposite direction
    """
    if len(closes) < 30:
        return {'phase': 'UNKNOWN', 'description': 'Not enough data'}
    
    # Get last 30 candles
    recent_highs = highs[-30:]
    recent_lows = lows[-30:]
    recent_closes = closes[-30:]
    
    # Calculate ranges
    full_range = max(recent_highs) - min(recent_lows)
    
    # First third (Accumulation)
    acc_range = max(recent_highs[:10]) - min(recent_lows[:10])
    
    # Second third (Manipulation)
    manip_range = max(recent_highs[10:20]) - min(recent_lows[10:20])
    
    # Third third (Distribution)
    dist_range = max(recent_highs[20:]) - min(recent_lows[20:])
    
    # Determine current phase
    if dist_range > manip_range and dist_range > acc_range:
        phase = 'DISTRIBUTION'
        description = 'True move underway - Trade with the trend'
    elif manip_range > acc_range * 1.5:
        phase = 'MANIPULATION'
        description = 'Stop hunt in progress - Wait for reversal'
    else:
        phase = 'ACCUMULATION'
        description = 'Range building - Wait for breakout'
    
    # Determine likely direction
    close_start = recent_closes[0]
    close_end = recent_closes[-1]
    direction = 'BULLISH' if close_end > close_start else 'BEARISH'
    
    return {
        'phase': phase,
        'description': description,
        'direction': direction,
        'accumulation_range': round(acc_range, 5),
        'manipulation_range': round(manip_range, 5),
        'distribution_range': round(dist_range, 5)
    }


# ============== PREMIUM/DISCOUNT ZONES ==============
def get_premium_discount(highs, lows, closes, lookback=50):
    """
    Calculate Premium and Discount zones
    - Premium: Upper 50% of range (look to sell)
    - Discount: Lower 50% of range (look to buy)
    - Equilibrium: 50% level
    """
    if len(closes) < lookback:
        lookback = len(closes)
    
    range_high = max(highs[-lookback:])
    range_low = min(lows[-lookback:])
    current_price = closes[-1]
    
    range_size = range_high - range_low
    equilibrium = range_low + (range_size * 0.5)
    
    # Premium/Discount thresholds
    premium_start = range_low + (range_size * 0.5)
    deep_premium = range_low + (range_size * 0.75)
    discount_end = range_low + (range_size * 0.5)
    deep_discount = range_low + (range_size * 0.25)
    
    # Determine zone
    if current_price >= deep_premium:
        zone = 'DEEP_PREMIUM'
        bias = 'BEARISH'
        description = 'Price in deep premium - Strong sell zone'
    elif current_price >= premium_start:
        zone = 'PREMIUM'
        bias = 'BEARISH'
        description = 'Price in premium - Look for sells'
    elif current_price <= deep_discount:
        zone = 'DEEP_DISCOUNT'
        bias = 'BULLISH'
        description = 'Price in deep discount - Strong buy zone'
    elif current_price <= discount_end:
        zone = 'DISCOUNT'
        bias = 'BULLISH'
        description = 'Price in discount - Look for buys'
    else:
        zone = 'EQUILIBRIUM'
        bias = 'NEUTRAL'
        description = 'Price at equilibrium - Wait for better entry'
    
    return {
        'zone': zone,
        'bias': bias,
        'description': description,
        'current_price': round(current_price, 5),
        'equilibrium': round(equilibrium, 5),
        'range_high': round(range_high, 5),
        'range_low': round(range_low, 5),
        'premium_start': round(premium_start, 5),
        'discount_end': round(discount_end, 5),
        'deep_premium': round(deep_premium, 5),
        'deep_discount': round(deep_discount, 5)
    }


# ============== PREVIOUS DAY/WEEK/MONTH LEVELS ==============
def get_htf_levels(highs, lows, closes, interval='1h'):
    """
    Get Previous Day, Week, Month High/Low levels
    These are key liquidity targets
    """
    candles_per_day = {'5m': 288, '15m': 96, '30m': 48, '1h': 24, '4h': 6, '1d': 1}.get(interval, 24)
    candles_per_week = candles_per_day * 5
    candles_per_month = candles_per_day * 20
    
    n = len(closes)
    levels = {}
    
    # Previous Day
    if n >= candles_per_day * 2:
        pd_start = n - candles_per_day * 2
        pd_end = n - candles_per_day
        levels['pdh'] = round(max(highs[pd_start:pd_end]), 5)  # Previous Day High
        levels['pdl'] = round(min(lows[pd_start:pd_end]), 5)   # Previous Day Low
    
    # Current Day
    if n >= candles_per_day:
        levels['cdh'] = round(max(highs[-candles_per_day:]), 5)  # Current Day High
        levels['cdl'] = round(min(lows[-candles_per_day:]), 5)   # Current Day Low
    
    # Previous Week
    if n >= candles_per_week * 2:
        pw_start = n - candles_per_week * 2
        pw_end = n - candles_per_week
        levels['pwh'] = round(max(highs[pw_start:pw_end]), 5)  # Previous Week High
        levels['pwl'] = round(min(lows[pw_start:pw_end]), 5)   # Previous Week Low
    
    # Previous Month
    if n >= candles_per_month * 2:
        pm_start = n - candles_per_month * 2
        pm_end = n - candles_per_month
        levels['pmh'] = round(max(highs[pm_start:pm_end]), 5)  # Previous Month High
        levels['pml'] = round(min(lows[pm_start:pm_end]), 5)   # Previous Month Low
    
    return levels


# ============== ORIGINAL FUNCTIONS (ENHANCED) ==============
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
    Complete ICT Analysis
    
    Includes:
    1. Kill Zones (Session Times)
    2. Previous Week High/Low
    3. Weekly Bias
    4. Order Blocks & FVG
    5. Market Structure (BOS/ChoCH)
    6. Liquidity Zones
    7. Premium/Discount
    8. Power of 3 (AMD)
    9. Displacement
    10. Breaker Blocks
    11. HTF Levels (PDH/PDL, PWH/PWL, PMH/PML)
    """
    if len(closes) < 20:
        return {'error': 'Need at least 20 candles'}
    
    current_price = closes[-1]
    
    # 1. Current Session / Kill Zone
    session = get_current_session()
    
    # 2. Get weekly levels
    levels = get_weekly_levels(highs, lows, closes, [], interval)
    
    # 3. Determine weekly bias
    bias, bias_reason = determine_weekly_bias(levels, current_price)
    
    # 4. Find OB and FVG
    order_blocks = find_order_blocks(opens, highs, lows, closes)
    fvg_list = find_fvg(highs, lows)
    
    # 5. Market Structure (BOS/ChoCH)
    market_structure = detect_market_structure(highs, lows, closes)
    
    # 6. Liquidity Zones
    liquidity = find_liquidity_zones(highs, lows, closes)
    
    # 7. Premium/Discount
    premium_discount = get_premium_discount(highs, lows, closes)
    
    # 8. Power of 3 (AMD)
    power_of_3 = detect_power_of_3(opens, highs, lows, closes)
    
    # 9. Displacement
    displacements = detect_displacement(opens, highs, lows, closes)
    
    # 10. Breaker Blocks
    breaker_blocks = find_breaker_blocks(opens, highs, lows, closes)
    
    # 11. HTF Levels
    htf_levels = get_htf_levels(highs, lows, closes, interval)
    
    # 12. Inducement
    inducements = find_inducement(highs, lows, closes)
    
    # Generate setups
    trade_setups = generate_trade_setup(bias, levels, order_blocks, fvg_list, current_price, balance, risk_percent)
    
    # Check trading day
    trading_day = get_trading_day()
    
    # Calculate overall confidence
    confidence_factors = []
    
    # Kill zone bonus
    if session.get('is_kill_zone'):
        confidence_factors.append(('Kill Zone Active', 15))
    
    # Structure alignment
    if market_structure['trend'] == 'BULLISH' and bias == 'BULLISH':
        confidence_factors.append(('Structure + Bias Aligned (Bullish)', 20))
    elif market_structure['trend'] == 'BEARISH' and bias == 'BEARISH':
        confidence_factors.append(('Structure + Bias Aligned (Bearish)', 20))
    
    # Premium/Discount alignment
    if premium_discount['bias'] == bias:
        confidence_factors.append(('Premium/Discount Aligned', 15))
    
    # Recent displacement
    if displacements:
        last_disp = displacements[-1]
        if (last_disp['direction'] == 'BULLISH' and bias == 'BULLISH') or \
           (last_disp['direction'] == 'BEARISH' and bias == 'BEARISH'):
            confidence_factors.append(('Displacement Confirms Bias', 10))
    
    # Power of 3 phase
    if power_of_3['phase'] == 'DISTRIBUTION':
        confidence_factors.append(('Distribution Phase (Trade Now)', 10))
    elif power_of_3['phase'] == 'MANIPULATION':
        confidence_factors.append(('Manipulation Phase (Wait)', -10))
    
    total_confidence = sum(f[1] for f in confidence_factors)
    base_confidence = 50
    final_confidence = min(95, max(20, base_confidence + total_confidence))
    
    return {
        'current_price': round(current_price, 5),
        'weekly_bias': bias,
        'bias_reason': bias_reason,
        'levels': levels,
        'htf_levels': htf_levels,
        'order_blocks': order_blocks,
        'fvg': fvg_list,
        'breaker_blocks': breaker_blocks,
        'trade_setups': trade_setups,
        'trading_day': trading_day,
        'session': session,
        'market_structure': market_structure,
        'liquidity': liquidity,
        'premium_discount': premium_discount,
        'power_of_3': power_of_3,
        'displacements': displacements,
        'inducements': inducements[-5:],
        'confidence': final_confidence,
        'confidence_factors': confidence_factors,
    }
