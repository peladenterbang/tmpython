"""
ARIMA (Autoregressive Integrated Moving Average) Predictor
For Forex Time Series Forecasting - Enhanced Version
"""

import numpy as np
from datetime import datetime, timedelta


def calculate_ema(prices, period):
    """Calculate Exponential Moving Average"""
    prices = np.array(prices, dtype=float)
    ema = np.zeros_like(prices)
    multiplier = 2 / (period + 1)
    ema[0] = prices[0]
    for i in range(1, len(prices)):
        ema[i] = (prices[i] * multiplier) + (ema[i-1] * (1 - multiplier))
    return ema


def calculate_rsi(prices, period=14):
    """Calculate RSI"""
    prices = np.array(prices, dtype=float)
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi)


def calculate_momentum(prices, period=10):
    """Calculate momentum indicator"""
    prices = np.array(prices, dtype=float)
    if len(prices) < period:
        return 0.0
    return float((prices[-1] / prices[-period] - 1) * 100)


def detect_trend(prices):
    """Detect trend using multiple methods"""
    prices = np.array(prices, dtype=float)
    
    # Method 1: EMA crossover
    if len(prices) >= 20:
        ema_fast = calculate_ema(prices, 8)
        ema_slow = calculate_ema(prices, 21)
        ema_signal = 1 if ema_fast[-1] > ema_slow[-1] else -1
    else:
        ema_signal = 0
    
    # Method 2: Linear regression slope
    x = np.arange(min(20, len(prices)))
    y = prices[-len(x):]
    slope = np.polyfit(x, y, 1)[0]
    slope_signal = 1 if slope > 0 else -1
    
    # Method 3: Higher highs / Lower lows
    recent = prices[-10:] if len(prices) >= 10 else prices
    mid = len(recent) // 2
    first_half_high = np.max(recent[:mid])
    second_half_high = np.max(recent[mid:])
    first_half_low = np.min(recent[:mid])
    second_half_low = np.min(recent[mid:])
    
    if second_half_high > first_half_high and second_half_low > first_half_low:
        hh_ll_signal = 1  # Uptrend
    elif second_half_high < first_half_high and second_half_low < first_half_low:
        hh_ll_signal = -1  # Downtrend
    else:
        hh_ll_signal = 0
    
    # Method 4: Price vs SMA
    sma_20 = np.mean(prices[-20:]) if len(prices) >= 20 else np.mean(prices)
    price_vs_sma = 1 if prices[-1] > sma_20 else -1
    
    # Combine signals with weights
    trend_score = (ema_signal * 0.3 + slope_signal * 0.25 + 
                   hh_ll_signal * 0.25 + price_vs_sma * 0.2)
    
    return float(trend_score)


def calculate_support_resistance(prices):
    """Find key support and resistance levels"""
    prices = np.array(prices, dtype=float)
    
    # Find local highs and lows
    highs = []
    lows = []
    
    for i in range(2, len(prices) - 2):
        if prices[i] > prices[i-1] and prices[i] > prices[i+1] and \
           prices[i] > prices[i-2] and prices[i] > prices[i+2]:
            highs.append(prices[i])
        if prices[i] < prices[i-1] and prices[i] < prices[i+1] and \
           prices[i] < prices[i-2] and prices[i] < prices[i+2]:
            lows.append(prices[i])
    
    resistance = np.mean(highs[-3:]) if highs else prices[-1] * 1.01
    support = np.mean(lows[-3:]) if lows else prices[-1] * 0.99
    
    return float(support), float(resistance)


def get_arima_prediction(prices, periods=5):
    """
    Enhanced ARIMA prediction with trend following and mean reversion
    """
    if len(prices) < 30:
        return None, "Need at least 30 data points for analysis"
    
    prices = np.array(prices, dtype=float)
    current_price = float(prices[-1])
    
    # Calculate returns
    returns = np.diff(prices) / prices[:-1] * 100
    
    # === TREND DETECTION ===
    trend_score = detect_trend(prices)
    trend_direction = 1 if trend_score > 0.1 else (-1 if trend_score < -0.1 else 0)
    
    # === MOMENTUM ===
    momentum = calculate_momentum(prices, 10)
    rsi = calculate_rsi(prices, 14)
    
    # RSI extremes suggest reversal
    rsi_signal = 0
    if rsi > 70:
        rsi_signal = -0.5  # Overbought - potential reversal down
    elif rsi < 30:
        rsi_signal = 0.5   # Oversold - potential reversal up
    
    # === VOLATILITY (ATR-like) ===
    high_low_range = []
    for i in range(1, min(14, len(prices))):
        high_low_range.append(abs(prices[-i] - prices[-i-1]))
    avg_range = np.mean(high_low_range) if high_low_range else current_price * 0.001
    volatility_pct = float(avg_range / current_price * 100)
    
    # === SUPPORT/RESISTANCE ===
    support, resistance = calculate_support_resistance(prices)
    
    # Distance to S/R levels
    dist_to_resistance = (resistance - current_price) / current_price * 100
    dist_to_support = (current_price - support) / current_price * 100
    
    # === AR COMPONENT ===
    ar_order = 5
    ar_coeffs = []
    for lag in range(1, ar_order + 1):
        if len(returns) > lag:
            corr = np.corrcoef(returns[:-lag], returns[lag:])[0, 1]
            if not np.isnan(corr):
                ar_coeffs.append(float(corr * 0.3))
            else:
                ar_coeffs.append(0.0)
        else:
            ar_coeffs.append(0.0)
    
    # === GENERATE PREDICTIONS ===
    predictions = []
    last_price = current_price
    last_returns = [float(r) for r in returns[-ar_order:]]
    
    for i in range(periods):
        # AR component
        ar_pred = sum(c * r for c, r in zip(ar_coeffs, reversed(last_returns[-ar_order:])))
        
        # Trend component (stronger influence)
        trend_pred = trend_direction * volatility_pct * 0.3
        
        # Momentum component
        momentum_pred = momentum * 0.05
        
        # Mean reversion near S/R
        sr_adjustment = 0
        if dist_to_resistance < 0.5 and trend_direction > 0:
            sr_adjustment = -volatility_pct * 0.2  # Slow down near resistance
        elif dist_to_support < 0.5 and trend_direction < 0:
            sr_adjustment = volatility_pct * 0.2   # Slow down near support
        
        # RSI reversal component
        rsi_pred = rsi_signal * volatility_pct * 0.2
        
        # Combine all components
        predicted_return = (
            ar_pred * 0.2 +           # AR: 20%
            trend_pred * 0.4 +        # Trend: 40%
            momentum_pred * 0.15 +    # Momentum: 15%
            sr_adjustment * 0.15 +    # S/R: 15%
            rsi_pred * 0.1            # RSI: 10%
        )
        
        # Decay factor for further predictions
        decay = 0.9 ** i
        predicted_return *= decay
        
        # Limit extreme predictions
        max_move = volatility_pct * 1.5
        predicted_return = float(np.clip(predicted_return, -max_move, max_move))
        
        # Calculate price
        pred_price = last_price * (1 + predicted_return / 100)
        predictions.append(float(pred_price))
        
        # Update for next iteration
        last_returns.append(predicted_return)
        last_price = pred_price
        
        # Update S/R distances
        dist_to_resistance = (resistance - pred_price) / pred_price * 100
        dist_to_support = (pred_price - support) / pred_price * 100
    
    return predictions, None


def calculate_arima_metrics(prices):
    """Calculate ARIMA model diagnostics and statistics"""
    prices = np.array(prices, dtype=float)
    returns = np.diff(prices) / prices[:-1] * 100
    
    # Stationarity test (simplified ADF-like)
    mean_return = float(np.mean(returns))
    std_return = float(np.std(returns))
    
    # Check for stationarity
    first_half_mean = np.mean(returns[:len(returns)//2])
    second_half_mean = np.mean(returns[len(returns)//2:])
    is_stationary = bool(abs(first_half_mean - second_half_mean) < std_return)
    
    # Autocorrelation at different lags
    acf_values = []
    for lag in range(1, min(11, len(returns))):
        if len(returns) > lag:
            corr = np.corrcoef(returns[:-lag], returns[lag:])[0, 1]
            acf_values.append(float(round(corr, 4)) if not np.isnan(corr) else 0.0)
    
    # Partial autocorrelation (simplified)
    pacf_values = acf_values[:5] if len(acf_values) >= 5 else acf_values
    
    # Model order suggestion
    significant_ar = sum(1 for a in acf_values[:5] if abs(a) > 0.2)
    significant_ma = sum(1 for a in pacf_values if abs(a) > 0.2)
    
    # Volatility clustering
    squared_returns = returns ** 2
    vol_acf = np.corrcoef(squared_returns[:-1], squared_returns[1:])[0, 1] if len(squared_returns) > 1 else 0
    has_volatility_clustering = bool(vol_acf > 0.1) if not np.isnan(vol_acf) else False
    
    return {
        'mean_return': round(mean_return, 4),
        'std_return': round(std_return, 4),
        'is_stationary': is_stationary,
        'acf': acf_values,
        'pacf': pacf_values,
        'suggested_ar': int(min(significant_ar, 3)),
        'suggested_i': 1,
        'suggested_ma': int(min(significant_ma, 2)),
        'volatility_clustering': has_volatility_clustering,
        'observations': int(len(prices))
    }


def calculate_forecast_confidence(prices, predictions):
    """Calculate confidence intervals for predictions"""
    prices = np.array(prices, dtype=float)
    returns = np.diff(prices) / prices[:-1] * 100
    std_return = float(np.std(returns))
    
    confidence_intervals = []
    last_price = float(prices[-1])
    
    for i, pred in enumerate(predictions):
        pred = float(pred)
        # Confidence interval widens with forecast horizon
        horizon_factor = float(np.sqrt(i + 1))
        ci_width = 1.96 * std_return * horizon_factor / 100 * last_price
        
        confidence_intervals.append({
            'prediction': round(pred, 5),
            'lower_95': round(pred - ci_width, 5),
            'upper_95': round(pred + ci_width, 5),
            'lower_80': round(pred - ci_width * 0.64, 5),
            'upper_80': round(pred + ci_width * 0.64, 5)
        })
    
    return confidence_intervals


def ensemble_predict(prices, periods=1):
    """
    Ensemble prediction combining multiple methods
    Inspired by sklearn ensemble approach
    """
    prices = np.array(prices, dtype=float)
    current_price = float(prices[-1])
    
    predictions = []
    weights = []
    
    # Method 1: Trend-based (weight: 0.3)
    trend_score = detect_trend(prices)
    ema_8 = calculate_ema(prices, 8)
    ema_21 = calculate_ema(prices, 21)
    
    if trend_score > 0.2:
        trend_pred = current_price * 1.001  # Expect 0.1% up
    elif trend_score < -0.2:
        trend_pred = current_price * 0.999  # Expect 0.1% down
    else:
        trend_pred = current_price
    predictions.append(trend_pred)
    weights.append(0.3)
    
    # Method 2: Mean Reversion (weight: 0.2)
    sma_20 = float(np.mean(prices[-20:]))
    distance_from_mean = (current_price - sma_20) / sma_20
    if abs(distance_from_mean) > 0.01:
        # Price tends to revert to mean
        mean_rev_pred = current_price - (distance_from_mean * current_price * 0.3)
    else:
        mean_rev_pred = current_price
    predictions.append(mean_rev_pred)
    weights.append(0.2)
    
    # Method 3: Momentum (weight: 0.25)
    momentum = calculate_momentum(prices, 5)
    momentum_pred = current_price * (1 + momentum / 100 * 0.2)
    predictions.append(momentum_pred)
    weights.append(0.25)
    
    # Method 4: Linear Regression (weight: 0.25)
    x = np.arange(min(10, len(prices)))
    y = prices[-len(x):]
    slope, intercept = np.polyfit(x, y, 1)
    lr_pred = float(slope * (len(x)) + intercept)
    predictions.append(lr_pred)
    weights.append(0.25)
    
    # Weighted average
    final_pred = sum(p * w for p, w in zip(predictions, weights))
    
    return float(final_pred)


def walk_forward_predict(prices):
    """
    Walk-forward prediction like in arima_research
    Uses expanding window for more accurate backtesting
    """
    prices = np.array(prices, dtype=float)
    current_price = float(prices[-1])
    
    # Calculate multiple signals
    signals = []
    
    # 1. EMA Signal
    if len(prices) >= 21:
        ema_8 = calculate_ema(prices, 8)[-1]
        ema_21 = calculate_ema(prices, 21)[-1]
        ema_signal = 1 if ema_8 > ema_21 else -1
        signals.append(ema_signal)
    
    # 2. RSI Signal
    rsi = calculate_rsi(prices, 14)
    if rsi < 35:
        signals.append(1)  # Oversold - buy
    elif rsi > 65:
        signals.append(-1)  # Overbought - sell
    else:
        signals.append(0)
    
    # 3. Momentum Signal
    momentum = calculate_momentum(prices, 5)
    if momentum > 0.3:
        signals.append(1)
    elif momentum < -0.3:
        signals.append(-1)
    else:
        signals.append(0)
    
    # 4. Price vs SMA
    sma_20 = float(np.mean(prices[-20:])) if len(prices) >= 20 else float(np.mean(prices))
    sma_signal = 1 if current_price > sma_20 else -1
    signals.append(sma_signal)
    
    # 5. Recent direction (last 3 candles)
    if len(prices) >= 4:
        recent_change = (prices[-1] - prices[-4]) / prices[-4]
        recent_signal = 1 if recent_change > 0.001 else (-1 if recent_change < -0.001 else 0)
        signals.append(recent_signal)
    
    # Calculate consensus
    avg_signal = float(np.mean(signals)) if signals else 0.0
    
    # Volatility for magnitude
    if len(prices) >= 21:
        recent_prices = prices[-21:]
        returns = np.diff(recent_prices) / recent_prices[:-1]
    else:
        returns = np.diff(prices) / prices[:-1]
    
    volatility = float(np.std(returns)) if len(returns) > 0 else 0.001
    
    # Predicted move
    predicted_move = avg_signal * volatility * current_price * 2
    predicted_price = current_price + predicted_move
    
    return float(predicted_price), float(avg_signal)


def backtest_arima(prices, test_size=20):
    """
    Walk-forward backtest like arima_research()
    Uses expanding window and ensemble methods
    """
    if len(prices) < test_size + 40:
        return None, "Insufficient data for backtesting"
    
    prices = np.array(prices, dtype=float)
    train_size = len(prices) - test_size
    
    correct_direction = 0
    predictions = []
    actuals = []
    history = list(prices[:train_size])
    
    # Walk-forward validation
    for t in range(test_size - 1):
        # Get current test price
        current_idx = train_size + t
        current_price = float(prices[current_idx])
        actual_next = float(prices[current_idx + 1])
        
        # Make prediction using ensemble
        pred_price, signal_strength = walk_forward_predict(np.array(history))
        
        # Also get ARIMA-style prediction
        arima_pred, _ = get_arima_prediction(history, periods=1)
        if arima_pred:
            # Combine ensemble and ARIMA
            combined_pred = float(pred_price * 0.6 + arima_pred[0] * 0.4)
        else:
            combined_pred = pred_price
        
        # Check direction
        predicted_direction = 1 if combined_pred > current_price else -1
        actual_direction = 1 if actual_next > current_price else -1
        
        if predicted_direction == actual_direction:
            correct_direction += 1
        
        predictions.append(combined_pred)
        actuals.append(actual_next)
        
        # Add observation to history (walk-forward)
        history.append(current_price)
    
    if not predictions:
        return None, "Backtesting failed"
    
    # Calculate metrics
    accuracy = float(correct_direction / (test_size - 1) * 100)
    
    # RMSE
    pred_arr = np.array(predictions)
    actual_arr = np.array(actuals)
    rmse = float(np.sqrt(np.mean((pred_arr - actual_arr) ** 2)))
    
    # MAE
    mae = float(np.mean(np.abs(pred_arr - actual_arr)))
    
    # MAPE
    mape = float(np.mean(np.abs((actual_arr - pred_arr) / actual_arr)) * 100)
    
    return {
        'accuracy': round(accuracy, 2),
        'rmse': round(rmse, 6),
        'mae': round(mae, 6),
        'mape': round(mape, 2),
        'test_size': int(test_size - 1),
        'predictions': [float(p) for p in predictions],
        'actuals': [float(a) for a in actuals]
    }, None


def get_trading_signal(prices, predictions):
    """Generate trading signal based on ARIMA predictions and technical analysis"""
    if not predictions or len(predictions) < 2:
        return {'signal': 'WAIT', 'strength': 0, 'reason': 'Insufficient predictions'}
    
    prices = np.array(prices, dtype=float)
    current_price = float(prices[-1])
    pred_1 = float(predictions[0])
    pred_final = float(predictions[-1])
    
    # Calculate expected move
    short_term_change = float((pred_1 - current_price) / current_price * 100)
    long_term_change = float((pred_final - current_price) / current_price * 100)
    
    # Get trend confirmation
    trend_score = detect_trend(prices)
    
    # Get RSI for confirmation
    rsi = calculate_rsi(prices, 14)
    
    # Get momentum
    momentum = calculate_momentum(prices, 10)
    
    # Count prediction direction consistency
    up_count = sum(1 for i in range(1, len(predictions)) if predictions[i] > predictions[i-1])
    down_count = len(predictions) - 1 - up_count
    consistency = max(up_count, down_count) / (len(predictions) - 1) if len(predictions) > 1 else 0
    
    # Build signal score (-100 to +100)
    signal_score = 0
    reasons = []
    
    # Prediction direction (40%)
    if long_term_change > 0.05:
        signal_score += 40 * min(long_term_change / 0.5, 1)
        reasons.append(f"Forecast +{long_term_change:.2f}%")
    elif long_term_change < -0.05:
        signal_score -= 40 * min(abs(long_term_change) / 0.5, 1)
        reasons.append(f"Forecast {long_term_change:.2f}%")
    
    # Trend confirmation (30%)
    if trend_score > 0.2:
        signal_score += 30
        reasons.append("Uptrend confirmed")
    elif trend_score < -0.2:
        signal_score -= 30
        reasons.append("Downtrend confirmed")
    
    # Momentum (15%)
    if momentum > 0.5:
        signal_score += 15
    elif momentum < -0.5:
        signal_score -= 15
    
    # RSI confirmation (15%)
    if rsi < 35 and long_term_change > 0:
        signal_score += 15
        reasons.append("RSI oversold")
    elif rsi > 65 and long_term_change < 0:
        signal_score -= 15
        reasons.append("RSI overbought")
    elif rsi > 70 and long_term_change > 0:
        signal_score -= 10  # Divergence warning
    elif rsi < 30 and long_term_change < 0:
        signal_score += 10  # Divergence warning
    
    # Consistency bonus
    if consistency > 0.8:
        signal_score *= 1.2
    
    # Determine signal
    if signal_score > 25:
        signal = 'BUY'
        strength = min(abs(signal_score), 100)
    elif signal_score < -25:
        signal = 'SELL'
        strength = min(abs(signal_score), 100)
    else:
        signal = 'WAIT'
        strength = 0
        reasons = ["No clear signal - mixed indicators"]
    
    reason = " | ".join(reasons[:3]) if reasons else "Analyzing..."
    
    return {
        'signal': signal,
        'strength': int(round(strength)),
        'reason': reason,
        'short_term_change': round(short_term_change, 4),
        'long_term_change': round(long_term_change, 4),
        'current_price': round(current_price, 5),
        'target_price': round(pred_final, 5),
        'trend_score': round(trend_score, 2),
        'rsi': round(rsi, 1),
        'momentum': round(momentum, 2)
    }
