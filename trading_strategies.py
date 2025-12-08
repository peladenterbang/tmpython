"""
Jim Simons Inspired Trading Strategies
Quantitative strategies based on Renaissance Technologies principles:
1. Mean Reversion - Price tends to return to average
2. Momentum/Trend Following - Winners keep winning
3. Pairs Trading (Statistical Arbitrage) - Correlated assets divergence
4. Breakout Strategy - Price breaks key levels
5. Volatility Breakout - Trade when volatility expands
6. Multi-Factor Ensemble - Combine multiple signals
"""

import numpy as np
from datetime import datetime


class QuantStrategy:
    """Base class for quantitative trading strategies"""
    
    def __init__(self):
        self.name = "Base Strategy"
    
    def calculate_atr(self, highs, lows, closes, period=14):
        """Average True Range for volatility-based stops"""
        if len(closes) < period + 1:
            return closes[-1] * 0.001
        
        true_ranges = []
        for i in range(1, len(closes)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i-1])
            low_close = abs(lows[i] - closes[i-1])
            true_ranges.append(max(high_low, high_close, low_close))
        
        return sum(true_ranges[-period:]) / period
    
    def calculate_position_size(self, balance, risk_percent, entry, stop_loss):
        """Calculate position size based on risk"""
        risk_amount = balance * (risk_percent / 100)
        risk_pips = abs(entry - stop_loss)
        if risk_pips == 0:
            return 0.01
        lots = risk_amount / (risk_pips * 10000 * 10)
        return round(max(0.01, lots), 2)


class MeanReversionStrategy(QuantStrategy):
    """
    Mean Reversion Strategy
    - When price deviates significantly from moving average, bet on return
    - Uses Bollinger Bands and RSI for overbought/oversold
    """
    
    def __init__(self):
        super().__init__()
        self.name = "Mean Reversion"
    
    def calculate_bollinger(self, prices, period=20, std_dev=2):
        """Calculate Bollinger Bands"""
        if len(prices) < period:
            return None, None, None
        
        sma = sum(prices[-period:]) / period
        variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
        std = variance ** 0.5
        
        upper = sma + (std_dev * std)
        lower = sma - (std_dev * std)
        
        return round(upper, 5), round(sma, 5), round(lower, 5)
    
    def calculate_rsi(self, prices, period=14):
        """Calculate RSI"""
        if len(prices) < period + 1:
            return 50
        
        gains, losses = [], []
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            gains.append(max(0, change))
            losses.append(max(0, -change))
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 2)
    
    def analyze(self, opens, highs, lows, closes, balance=10000, risk_percent=1.0):
        """Generate mean reversion signals"""
        if len(closes) < 30:
            return {'error': 'Need at least 30 candles'}
        
        current_price = closes[-1]
        upper_bb, middle_bb, lower_bb = self.calculate_bollinger(closes)
        rsi = self.calculate_rsi(closes)
        atr = self.calculate_atr(highs, lows, closes)
        
        signals = []
        
        # Oversold condition - BUY signal
        if current_price < lower_bb and rsi < 30:
            entry = current_price
            stop_loss = entry - (atr * 2)
            take_profit = middle_bb  # Target: return to mean
            
            risk = entry - stop_loss
            reward = take_profit - entry
            rr = reward / risk if risk > 0 else 0
            
            signals.append({
                'direction': 'BUY',
                'entry': round(entry, 5),
                'stop_loss': round(stop_loss, 5),
                'take_profit': round(take_profit, 5),
                'risk_reward': round(rr, 2),
                'confidence': min(90, 50 + (30 - rsi)),
                'lots': self.calculate_position_size(balance, risk_percent, entry, stop_loss),
                'reason': f'Oversold: RSI={rsi}, Price below lower BB'
            })
        
        # Overbought condition - SELL signal
        elif current_price > upper_bb and rsi > 70:
            entry = current_price
            stop_loss = entry + (atr * 2)
            take_profit = middle_bb  # Target: return to mean
            
            risk = stop_loss - entry
            reward = entry - take_profit
            rr = reward / risk if risk > 0 else 0
            
            signals.append({
                'direction': 'SELL',
                'entry': round(entry, 5),
                'stop_loss': round(stop_loss, 5),
                'take_profit': round(take_profit, 5),
                'risk_reward': round(rr, 2),
                'confidence': min(90, 50 + (rsi - 70)),
                'lots': self.calculate_position_size(balance, risk_percent, entry, stop_loss),
                'reason': f'Overbought: RSI={rsi}, Price above upper BB'
            })
        
        return {
            'strategy': self.name,
            'current_price': round(current_price, 5),
            'signals': signals,
            'indicators': {
                'rsi': rsi,
                'upper_bb': upper_bb,
                'middle_bb': middle_bb,
                'lower_bb': lower_bb,
                'atr': round(atr, 5)
            },
            'status': 'SIGNAL' if signals else 'NO_SIGNAL',
            'explanation': 'Mean reversion expects price to return to average after extreme moves'
        }


class MomentumStrategy(QuantStrategy):
    """
    Momentum/Trend Following Strategy
    - Assets that performed well recently tend to continue
    - Uses EMA crossovers and momentum indicators
    """
    
    def __init__(self):
        super().__init__()
        self.name = "Momentum"
    
    def calculate_ema(self, prices, period):
        """Calculate EMA"""
        if len(prices) < period:
            return prices[-1]
        
        multiplier = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        return round(ema, 5)
    
    def calculate_momentum(self, prices, period=10):
        """Calculate Rate of Change momentum"""
        if len(prices) <= period:
            return 0
        return round((prices[-1] / prices[-period - 1] - 1) * 100, 2)
    
    def analyze(self, opens, highs, lows, closes, balance=10000, risk_percent=1.0):
        """Generate momentum signals"""
        if len(closes) < 50:
            return {'error': 'Need at least 50 candles'}
        
        current_price = closes[-1]
        ema_fast = self.calculate_ema(closes, 12)
        ema_slow = self.calculate_ema(closes, 26)
        ema_trend = self.calculate_ema(closes, 50)
        momentum = self.calculate_momentum(closes, 10)
        atr = self.calculate_atr(highs, lows, closes)
        
        # Trend strength
        trend_score = 0
        if current_price > ema_trend:
            trend_score += 30
        if ema_fast > ema_slow:
            trend_score += 30
        if momentum > 0:
            trend_score += 20
        if momentum > 1:
            trend_score += 20
        
        signals = []
        
        # Bullish momentum
        if ema_fast > ema_slow and current_price > ema_trend and momentum > 0.5:
            entry = current_price
            stop_loss = min(ema_slow, entry - atr * 2)
            take_profit = entry + (atr * 3)
            
            risk = entry - stop_loss
            reward = take_profit - entry
            rr = reward / risk if risk > 0 else 0
            
            signals.append({
                'direction': 'BUY',
                'entry': round(entry, 5),
                'stop_loss': round(stop_loss, 5),
                'take_profit': round(take_profit, 5),
                'risk_reward': round(rr, 2),
                'confidence': min(95, trend_score),
                'lots': self.calculate_position_size(balance, risk_percent, entry, stop_loss),
                'reason': f'Bullish momentum: EMA cross up, Momentum={momentum}%'
            })
        
        # Bearish momentum
        elif ema_fast < ema_slow and current_price < ema_trend and momentum < -0.5:
            entry = current_price
            stop_loss = max(ema_slow, entry + atr * 2)
            take_profit = entry - (atr * 3)
            
            risk = stop_loss - entry
            reward = entry - take_profit
            rr = reward / risk if risk > 0 else 0
            
            signals.append({
                'direction': 'SELL',
                'entry': round(entry, 5),
                'stop_loss': round(stop_loss, 5),
                'take_profit': round(take_profit, 5),
                'risk_reward': round(rr, 2),
                'confidence': min(95, abs(trend_score)),
                'lots': self.calculate_position_size(balance, risk_percent, entry, stop_loss),
                'reason': f'Bearish momentum: EMA cross down, Momentum={momentum}%'
            })
        
        return {
            'strategy': self.name,
            'current_price': round(current_price, 5),
            'signals': signals,
            'indicators': {
                'ema_12': ema_fast,
                'ema_26': ema_slow,
                'ema_50': ema_trend,
                'momentum': momentum,
                'trend_score': trend_score,
                'atr': round(atr, 5)
            },
            'status': 'SIGNAL' if signals else 'NO_SIGNAL',
            'explanation': 'Momentum strategy follows the trend - winners keep winning'
        }


class BreakoutStrategy(QuantStrategy):
    """
    Breakout Strategy
    - Trade when price breaks key support/resistance levels
    - Volume confirmation preferred
    """
    
    def __init__(self):
        super().__init__()
        self.name = "Breakout"
    
    def find_levels(self, highs, lows, closes, lookback=20):
        """Find key support and resistance levels"""
        recent_highs = highs[-lookback:]
        recent_lows = lows[-lookback:]
        
        # Find pivot highs and lows
        resistances = []
        supports = []
        
        for i in range(2, len(recent_highs) - 2):
            if recent_highs[i] > recent_highs[i-1] and recent_highs[i] > recent_highs[i+1]:
                resistances.append(recent_highs[i])
            if recent_lows[i] < recent_lows[i-1] and recent_lows[i] < recent_lows[i+1]:
                supports.append(recent_lows[i])
        
        # Get strongest levels
        resistance = max(resistances[-3:]) if resistances else max(recent_highs)
        support = min(supports[-3:]) if supports else min(recent_lows)
        
        return round(support, 5), round(resistance, 5)
    
    def detect_breakout(self, closes, highs, lows, resistance, support):
        """Detect if breakout occurred"""
        current = closes[-1]
        prev_high = max(highs[-5:-1])
        prev_low = min(lows[-5:-1])
        
        # Bullish breakout
        if current > resistance and prev_high < resistance:
            return 'BULLISH', resistance
        
        # Bearish breakout
        if current < support and prev_low > support:
            return 'BEARISH', support
        
        return None, None
    
    def analyze(self, opens, highs, lows, closes, balance=10000, risk_percent=1.0):
        """Generate breakout signals"""
        if len(closes) < 30:
            return {'error': 'Need at least 30 candles'}
        
        current_price = closes[-1]
        support, resistance = self.find_levels(highs, lows, closes)
        breakout_type, breakout_level = self.detect_breakout(closes, highs, lows, resistance, support)
        atr = self.calculate_atr(highs, lows, closes)
        
        signals = []
        
        if breakout_type == 'BULLISH':
            entry = current_price
            stop_loss = breakout_level - (atr * 1.5)  # Below breakout level
            take_profit = entry + (atr * 3)
            
            risk = entry - stop_loss
            reward = take_profit - entry
            rr = reward / risk if risk > 0 else 0
            
            signals.append({
                'direction': 'BUY',
                'entry': round(entry, 5),
                'stop_loss': round(stop_loss, 5),
                'take_profit': round(take_profit, 5),
                'risk_reward': round(rr, 2),
                'confidence': 75,
                'lots': self.calculate_position_size(balance, risk_percent, entry, stop_loss),
                'reason': f'Bullish breakout above {breakout_level}'
            })
        
        elif breakout_type == 'BEARISH':
            entry = current_price
            stop_loss = breakout_level + (atr * 1.5)  # Above breakout level
            take_profit = entry - (atr * 3)
            
            risk = stop_loss - entry
            reward = entry - take_profit
            rr = reward / risk if risk > 0 else 0
            
            signals.append({
                'direction': 'SELL',
                'entry': round(entry, 5),
                'stop_loss': round(stop_loss, 5),
                'take_profit': round(take_profit, 5),
                'risk_reward': round(rr, 2),
                'confidence': 75,
                'lots': self.calculate_position_size(balance, risk_percent, entry, stop_loss),
                'reason': f'Bearish breakout below {breakout_level}'
            })
        
        return {
            'strategy': self.name,
            'current_price': round(current_price, 5),
            'signals': signals,
            'indicators': {
                'resistance': resistance,
                'support': support,
                'breakout_type': breakout_type,
                'breakout_level': breakout_level,
                'atr': round(atr, 5)
            },
            'status': 'SIGNAL' if signals else 'NO_SIGNAL',
            'explanation': 'Breakout strategy trades when price breaks key levels'
        }


class VolatilityBreakoutStrategy(QuantStrategy):
    """
    Volatility Breakout Strategy (Jim Simons favorite)
    - Measure overnight/session volatility
    - Enter when price breaks beyond expected range
    - Quick profit-taking (scalping style)
    """
    
    def __init__(self):
        super().__init__()
        self.name = "Volatility Breakout"
    
    def calculate_volatility_range(self, highs, lows, closes, period=10):
        """Calculate expected volatility range"""
        if len(closes) < period:
            return closes[-1] * 0.001
        
        ranges = []
        for i in range(-period, 0):
            ranges.append(highs[i] - lows[i])
        
        avg_range = sum(ranges) / len(ranges)
        return avg_range
    
    def analyze(self, opens, highs, lows, closes, balance=10000, risk_percent=1.0):
        """Generate volatility breakout signals"""
        if len(closes) < 20:
            return {'error': 'Need at least 20 candles'}
        
        current_price = closes[-1]
        current_open = opens[-1]
        avg_range = self.calculate_volatility_range(highs, lows, closes)
        atr = self.calculate_atr(highs, lows, closes)
        
        # Volatility expansion factor
        current_range = highs[-1] - lows[-1]
        volatility_expansion = current_range / avg_range if avg_range > 0 else 1
        
        # Expected breakout levels from session open
        upper_breakout = current_open + (avg_range * 0.7)
        lower_breakout = current_open - (avg_range * 0.7)
        
        signals = []
        
        # Bullish volatility breakout
        if current_price > upper_breakout and volatility_expansion > 1.2:
            entry = current_price
            stop_loss = current_open  # Stop at session open
            take_profit = entry + (atr * 1.5)  # Quick profit
            
            risk = entry - stop_loss
            reward = take_profit - entry
            rr = reward / risk if risk > 0 else 0
            
            signals.append({
                'direction': 'BUY',
                'entry': round(entry, 5),
                'stop_loss': round(stop_loss, 5),
                'take_profit': round(take_profit, 5),
                'risk_reward': round(rr, 2),
                'confidence': min(85, 60 + (volatility_expansion - 1) * 20),
                'lots': self.calculate_position_size(balance, risk_percent, entry, stop_loss),
                'reason': f'Volatility expansion {volatility_expansion:.1f}x, bullish breakout'
            })
        
        # Bearish volatility breakout
        elif current_price < lower_breakout and volatility_expansion > 1.2:
            entry = current_price
            stop_loss = current_open  # Stop at session open
            take_profit = entry - (atr * 1.5)  # Quick profit
            
            risk = stop_loss - entry
            reward = entry - take_profit
            rr = reward / risk if risk > 0 else 0
            
            signals.append({
                'direction': 'SELL',
                'entry': round(entry, 5),
                'stop_loss': round(stop_loss, 5),
                'take_profit': round(take_profit, 5),
                'risk_reward': round(rr, 2),
                'confidence': min(85, 60 + (volatility_expansion - 1) * 20),
                'lots': self.calculate_position_size(balance, risk_percent, entry, stop_loss),
                'reason': f'Volatility expansion {volatility_expansion:.1f}x, bearish breakout'
            })
        
        return {
            'strategy': self.name,
            'current_price': round(current_price, 5),
            'signals': signals,
            'indicators': {
                'session_open': round(current_open, 5),
                'avg_range': round(avg_range, 5),
                'current_range': round(current_range, 5),
                'volatility_expansion': round(volatility_expansion, 2),
                'upper_breakout': round(upper_breakout, 5),
                'lower_breakout': round(lower_breakout, 5),
                'atr': round(atr, 5)
            },
            'status': 'SIGNAL' if signals else 'NO_SIGNAL',
            'explanation': 'Trade when volatility expands beyond normal range - quick scalping style'
        }


class StatisticalArbitrageStrategy(QuantStrategy):
    """
    Statistical Arbitrage / Pairs Trading
    - Find correlated assets and trade divergence
    - When spread widens, short outperformer and long underperformer
    """
    
    def __init__(self):
        super().__init__()
        self.name = "Statistical Arbitrage"
    
    def calculate_zscore(self, prices1, prices2, period=20):
        """Calculate z-score of price ratio"""
        if len(prices1) < period or len(prices2) < period:
            return 0, 1, []
        
        ratios = [p1 / p2 for p1, p2 in zip(prices1, prices2)]
        recent_ratios = ratios[-period:]
        
        mean_ratio = sum(recent_ratios) / len(recent_ratios)
        variance = sum((r - mean_ratio) ** 2 for r in recent_ratios) / len(recent_ratios)
        std_ratio = variance ** 0.5 if variance > 0 else 0.0001
        
        current_ratio = ratios[-1]
        zscore = (current_ratio - mean_ratio) / std_ratio
        
        return round(zscore, 2), round(mean_ratio, 5), ratios[-10:]
    
    def calculate_correlation(self, prices1, prices2, period=20):
        """Calculate correlation between two price series"""
        if len(prices1) < period or len(prices2) < period:
            return 0
        
        p1 = prices1[-period:]
        p2 = prices2[-period:]
        
        mean1 = sum(p1) / len(p1)
        mean2 = sum(p2) / len(p2)
        
        numerator = sum((a - mean1) * (b - mean2) for a, b in zip(p1, p2))
        var1 = sum((a - mean1) ** 2 for a in p1) ** 0.5
        var2 = sum((b - mean2) ** 2 for b in p2) ** 0.5
        
        if var1 * var2 == 0:
            return 0
        
        return round(numerator / (var1 * var2), 3)
    
    def analyze_pair(self, prices1, prices2, pair1_name="Asset1", pair2_name="Asset2"):
        """Analyze a pair for statistical arbitrage opportunity"""
        if len(prices1) < 30 or len(prices2) < 30:
            return {'error': 'Need at least 30 candles for both assets'}
        
        zscore, mean_ratio, recent_ratios = self.calculate_zscore(prices1, prices2)
        correlation = self.calculate_correlation(prices1, prices2)
        
        signals = []
        
        # High correlation required for pairs trading
        if abs(correlation) < 0.7:
            return {
                'strategy': self.name,
                'pair1': pair1_name,
                'pair2': pair2_name,
                'signals': [],
                'indicators': {
                    'zscore': zscore,
                    'mean_ratio': mean_ratio,
                    'correlation': correlation
                },
                'status': 'NO_SIGNAL',
                'explanation': f'Correlation {correlation} too low for pairs trading (need > 0.7)'
            }
        
        # Z-score > 2: Asset1 overvalued relative to Asset2
        if zscore > 2:
            signals.append({
                'direction': 'PAIRS_TRADE',
                'action': f'SELL {pair1_name}, BUY {pair2_name}',
                'zscore': zscore,
                'confidence': min(90, 60 + abs(zscore) * 10),
                'reason': f'Z-score={zscore}: {pair1_name} overvalued vs {pair2_name}'
            })
        
        # Z-score < -2: Asset1 undervalued relative to Asset2
        elif zscore < -2:
            signals.append({
                'direction': 'PAIRS_TRADE',
                'action': f'BUY {pair1_name}, SELL {pair2_name}',
                'zscore': zscore,
                'confidence': min(90, 60 + abs(zscore) * 10),
                'reason': f'Z-score={zscore}: {pair1_name} undervalued vs {pair2_name}'
            })
        
        return {
            'strategy': self.name,
            'pair1': pair1_name,
            'pair2': pair2_name,
            'signals': signals,
            'indicators': {
                'zscore': zscore,
                'mean_ratio': mean_ratio,
                'correlation': correlation,
                'recent_ratios': recent_ratios
            },
            'status': 'SIGNAL' if signals else 'NO_SIGNAL',
            'explanation': 'Pairs trading profits from mean reversion of correlated asset spreads'
        }


class EnsembleStrategy(QuantStrategy):
    """
    Multi-Factor Ensemble Strategy (Jim Simons' Core Approach)
    - Combine multiple weak signals into stronger prediction
    - Weight signals by historical accuracy
    - Diversify across strategies
    """
    
    def __init__(self):
        super().__init__()
        self.name = "Ensemble (Multi-Factor)"
        self.mean_reversion = MeanReversionStrategy()
        self.momentum = MomentumStrategy()
        self.breakout = BreakoutStrategy()
        self.volatility = VolatilityBreakoutStrategy()
    
    def analyze(self, opens, highs, lows, closes, balance=10000, risk_percent=1.0):
        """Combine all strategies into ensemble signal"""
        if len(closes) < 50:
            return {'error': 'Need at least 50 candles'}
        
        # Run all strategies
        results = {
            'mean_reversion': self.mean_reversion.analyze(opens, highs, lows, closes, balance, risk_percent),
            'momentum': self.momentum.analyze(opens, highs, lows, closes, balance, risk_percent),
            'breakout': self.breakout.analyze(opens, highs, lows, closes, balance, risk_percent),
            'volatility': self.volatility.analyze(opens, highs, lows, closes, balance, risk_percent)
        }
        
        # Collect signals with weights
        weights = {
            'mean_reversion': 0.25,
            'momentum': 0.30,
            'breakout': 0.25,
            'volatility': 0.20
        }
        
        buy_score = 0
        sell_score = 0
        signals_detail = []
        
        for strategy_name, result in results.items():
            if 'error' in result:
                continue
            
            weight = weights.get(strategy_name, 0.25)
            
            for signal in result.get('signals', []):
                confidence = signal.get('confidence', 50)
                
                if signal['direction'] == 'BUY':
                    buy_score += weight * confidence
                    signals_detail.append({
                        'strategy': strategy_name,
                        'direction': 'BUY',
                        'confidence': confidence,
                        'weighted_score': round(weight * confidence, 2)
                    })
                elif signal['direction'] == 'SELL':
                    sell_score += weight * confidence
                    signals_detail.append({
                        'strategy': strategy_name,
                        'direction': 'SELL',
                        'confidence': confidence,
                        'weighted_score': round(weight * confidence, 2)
                    })
        
        # Generate ensemble signal
        current_price = closes[-1]
        atr = self.calculate_atr(highs, lows, closes)
        final_signals = []
        
        # Need significant difference between scores
        if buy_score > sell_score + 20 and buy_score >= 40:
            entry = current_price
            stop_loss = entry - (atr * 2)
            take_profit = entry + (atr * 3)
            
            risk = entry - stop_loss
            reward = take_profit - entry
            rr = reward / risk if risk > 0 else 0
            
            final_signals.append({
                'direction': 'BUY',
                'entry': round(entry, 5),
                'stop_loss': round(stop_loss, 5),
                'take_profit': round(take_profit, 5),
                'risk_reward': round(rr, 2),
                'confidence': round(min(95, buy_score), 1),
                'lots': self.calculate_position_size(balance, risk_percent, entry, stop_loss),
                'reason': f'Ensemble BUY: score {buy_score:.0f} vs SELL {sell_score:.0f}'
            })
        
        elif sell_score > buy_score + 20 and sell_score >= 40:
            entry = current_price
            stop_loss = entry + (atr * 2)
            take_profit = entry - (atr * 3)
            
            risk = stop_loss - entry
            reward = entry - take_profit
            rr = reward / risk if risk > 0 else 0
            
            final_signals.append({
                'direction': 'SELL',
                'entry': round(entry, 5),
                'stop_loss': round(stop_loss, 5),
                'take_profit': round(take_profit, 5),
                'risk_reward': round(rr, 2),
                'confidence': round(min(95, sell_score), 1),
                'lots': self.calculate_position_size(balance, risk_percent, entry, stop_loss),
                'reason': f'Ensemble SELL: score {sell_score:.0f} vs BUY {buy_score:.0f}'
            })
        
        return {
            'strategy': self.name,
            'current_price': round(current_price, 5),
            'signals': final_signals,
            'ensemble_scores': {
                'buy_score': round(buy_score, 1),
                'sell_score': round(sell_score, 1),
                'net_score': round(buy_score - sell_score, 1)
            },
            'individual_strategies': results,
            'signals_detail': signals_detail,
            'status': 'SIGNAL' if final_signals else 'NO_SIGNAL',
            'explanation': 'Ensemble combines multiple strategy signals weighted by confidence'
        }


def analyze_all_strategies(opens, highs, lows, closes, balance=10000, risk_percent=1.0):
    """
    Run all trading strategies and return comprehensive analysis
    """
    strategies = {
        'mean_reversion': MeanReversionStrategy(),
        'momentum': MomentumStrategy(),
        'breakout': BreakoutStrategy(),
        'volatility_breakout': VolatilityBreakoutStrategy(),
        'ensemble': EnsembleStrategy()
    }
    
    results = {}
    for name, strategy in strategies.items():
        try:
            results[name] = strategy.analyze(opens, highs, lows, closes, balance, risk_percent)
        except Exception as e:
            results[name] = {'error': str(e)}
    
    # Summary
    active_signals = []
    for name, result in results.items():
        if 'signals' in result and result['signals']:
            for sig in result['signals']:
                active_signals.append({
                    'strategy': name,
                    **sig
                })
    
    # Sort by confidence
    active_signals.sort(key=lambda x: x.get('confidence', 0), reverse=True)
    
    return {
        'strategies': results,
        'active_signals': active_signals,
        'total_strategies': len(strategies),
        'strategies_with_signals': sum(1 for r in results.values() if r.get('signals')),
        'analyzed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
