"""
Technical Indicators Module for Forex Risk Management
Includes: SMA, EMA, RSI, MACD
"""

def calculate_sma(prices, period):
    """Calculate Simple Moving Average"""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def calculate_ema(prices, period):
    """Calculate Exponential Moving Average"""
    if len(prices) < period:
        return None
    
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period  # Start with SMA
    
    for price in prices[period:]:
        ema = (price * multiplier) + (ema * (1 - multiplier))
    
    return ema

def calculate_rsi(prices, period=14):
    """
    Calculate Relative Strength Index
    RSI > 70 = Overbought (potential SELL)
    RSI < 30 = Oversold (potential BUY)
    """
    if len(prices) < period + 1:
        return None
    
    gains = []
    losses = []
    
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    if len(gains) < period:
        return None
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return round(rsi, 2)

def calculate_macd(prices, fast_period=12, slow_period=26, signal_period=9):
    """
    Calculate MACD (Moving Average Convergence Divergence)
    Returns: (macd_line, signal_line, histogram)
    
    MACD > Signal = Bullish (BUY signal)
    MACD < Signal = Bearish (SELL signal)
    """
    if len(prices) < slow_period + signal_period:
        return None, None, None
    
    # Calculate EMAs
    fast_ema = calculate_ema(prices, fast_period)
    slow_ema = calculate_ema(prices, slow_period)
    
    if fast_ema is None or slow_ema is None:
        return None, None, None
    
    macd_line = fast_ema - slow_ema
    
    # For signal line, we need MACD history
    macd_history = []
    for i in range(slow_period, len(prices) + 1):
        subset = prices[:i]
        fast = calculate_ema(subset, fast_period)
        slow = calculate_ema(subset, slow_period)
        if fast and slow:
            macd_history.append(fast - slow)
    
    if len(macd_history) < signal_period:
        return macd_line, None, None
    
    signal_line = calculate_ema(macd_history, signal_period)
    histogram = macd_line - signal_line if signal_line else None
    
    return round(macd_line, 5), round(signal_line, 5) if signal_line else None, round(histogram, 5) if histogram else None

def calculate_bollinger_bands(prices, period=20, std_dev=2):
    """
    Calculate Bollinger Bands
    Returns: (upper_band, middle_band, lower_band)
    
    Price near upper band = Overbought
    Price near lower band = Oversold
    """
    if len(prices) < period:
        return None, None, None
    
    middle_band = calculate_sma(prices, period)
    
    # Calculate standard deviation
    squared_diff = [(p - middle_band) ** 2 for p in prices[-period:]]
    std = (sum(squared_diff) / period) ** 0.5
    
    upper_band = middle_band + (std_dev * std)
    lower_band = middle_band - (std_dev * std)
    
    return round(upper_band, 5), round(middle_band, 5), round(lower_band, 5)

def get_signal(prices):
    """
    Generate trading signal based on all indicators
    Returns: dict with signal and analysis
    """
    if len(prices) < 30:
        return {
            'signal': 'NEUTRAL',
            'strength': 0,
            'message': 'Not enough data (need at least 30 price points)',
            'indicators': {}
        }
    
    current_price = prices[-1]
    
    # Calculate all indicators
    sma_20 = calculate_sma(prices, 20)
    ema_12 = calculate_ema(prices, 12)
    rsi = calculate_rsi(prices, 14)
    macd_line, signal_line, histogram = calculate_macd(prices)
    upper_bb, middle_bb, lower_bb = calculate_bollinger_bands(prices)
    
    # Scoring system
    buy_signals = 0
    sell_signals = 0
    total_signals = 0
    
    analysis = []
    
    # SMA Analysis
    if sma_20:
        total_signals += 1
        if current_price > sma_20:
            buy_signals += 1
            analysis.append("Price above SMA(20) - Bullish")
        else:
            sell_signals += 1
            analysis.append("Price below SMA(20) - Bearish")
    
    # EMA Analysis
    if ema_12 and sma_20:
        total_signals += 1
        if ema_12 > sma_20:
            buy_signals += 1
            analysis.append("EMA(12) above SMA(20) - Bullish crossover")
        else:
            sell_signals += 1
            analysis.append("EMA(12) below SMA(20) - Bearish crossover")
    
    # RSI Analysis
    if rsi:
        total_signals += 1
        if rsi < 30:
            buy_signals += 1
            analysis.append(f"RSI({rsi}) Oversold - Buy signal")
        elif rsi > 70:
            sell_signals += 1
            analysis.append(f"RSI({rsi}) Overbought - Sell signal")
        else:
            analysis.append(f"RSI({rsi}) Neutral zone")
    
    # MACD Analysis
    if macd_line and signal_line:
        total_signals += 1
        if macd_line > signal_line:
            buy_signals += 1
            analysis.append("MACD above Signal - Bullish momentum")
        else:
            sell_signals += 1
            analysis.append("MACD below Signal - Bearish momentum")
    
    # Bollinger Bands Analysis
    if upper_bb and lower_bb:
        total_signals += 1
        if current_price <= lower_bb:
            buy_signals += 1
            analysis.append("Price at lower Bollinger Band - Potential bounce (Buy)")
        elif current_price >= upper_bb:
            sell_signals += 1
            analysis.append("Price at upper Bollinger Band - Potential reversal (Sell)")
        else:
            analysis.append("Price within Bollinger Bands - Normal range")
    
    # Determine overall signal
    if total_signals == 0:
        signal = 'NEUTRAL'
        strength = 0
    else:
        buy_ratio = buy_signals / total_signals
        sell_ratio = sell_signals / total_signals
        
        if buy_ratio >= 0.6:
            signal = 'BUY'
            strength = int(buy_ratio * 100)
        elif sell_ratio >= 0.6:
            signal = 'SELL'
            strength = int(sell_ratio * 100)
        else:
            signal = 'NEUTRAL'
            strength = 50
    
    return {
        'signal': signal,
        'strength': strength,
        'message': f"{signal} signal with {strength}% confidence",
        'analysis': analysis,
        'indicators': {
            'current_price': current_price,
            'sma_20': sma_20,
            'ema_12': ema_12,
            'rsi': rsi,
            'macd': macd_line,
            'macd_signal': signal_line,
            'macd_histogram': histogram,
            'bollinger_upper': upper_bb,
            'bollinger_middle': middle_bb,
            'bollinger_lower': lower_bb
        }
    }

def generate_sample_prices(base_price=1.1000, num_points=50, volatility=0.001):
    """Generate sample price data for testing"""
    import random
    prices = [base_price]
    for _ in range(num_points - 1):
        change = random.uniform(-volatility, volatility)
        new_price = prices[-1] + change
        prices.append(round(new_price, 5))
    return prices
