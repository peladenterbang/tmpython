"""
ML-based Forex Entry, Take Profit, and Stop Loss Predictor
Uses technical indicators and price patterns to generate predictions
"""

import numpy as np
import pandas as pd
from indicators import calculate_sma, calculate_ema, calculate_rsi, calculate_macd, calculate_bollinger_bands


class ForexMLPredictor:
    """
    ML Predictor for Forex Entry, TP, and SL
    Uses a combination of technical analysis and statistical methods
    """
    
    def __init__(self):
        self.atr_period = 14
        self.lookback = 50
        
    def calculate_atr(self, highs, lows, closes, period=14):
        """Calculate Average True Range for volatility-based SL/TP"""
        if len(closes) < period + 1:
            return None
        
        true_ranges = []
        for i in range(1, len(closes)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i-1])
            low_close = abs(lows[i] - closes[i-1])
            true_ranges.append(max(high_low, high_close, low_close))
        
        if len(true_ranges) < period:
            return None
        
        atr = sum(true_ranges[-period:]) / period
        return atr
    
    def calculate_support_resistance(self, highs, lows, closes, lookback=20):
        """Find key support and resistance levels using pivot points"""
        if len(closes) < lookback:
            return None, None
        
        recent_highs = highs[-lookback:]
        recent_lows = lows[-lookback:]
        
        resistance_candidates = []
        support_candidates = []
        
        for i in range(2, len(recent_highs) - 2):
            if recent_highs[i] > recent_highs[i-1] and recent_highs[i] > recent_highs[i-2] and \
               recent_highs[i] > recent_highs[i+1] and recent_highs[i] > recent_highs[i+2]:
                resistance_candidates.append(recent_highs[i])
            
            if recent_lows[i] < recent_lows[i-1] and recent_lows[i] < recent_lows[i-2] and \
               recent_lows[i] < recent_lows[i+1] and recent_lows[i] < recent_lows[i+2]:
                support_candidates.append(recent_lows[i])
        
        resistance = max(resistance_candidates) if resistance_candidates else max(recent_highs)
        support = min(support_candidates) if support_candidates else min(recent_lows)
        
        return support, resistance
    
    def extract_features(self, opens, highs, lows, closes):
        """Extract features for ML prediction"""
        if len(closes) < 50:
            return None
        
        features = {}
        
        features['current_price'] = closes[-1]
        features['price_change_1'] = (closes[-1] - closes[-2]) / closes[-2] * 100
        features['price_change_5'] = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) > 5 else 0
        features['price_change_10'] = (closes[-1] - closes[-11]) / closes[-11] * 100 if len(closes) > 10 else 0
        
        features['sma_20'] = calculate_sma(closes, 20)
        features['sma_50'] = calculate_sma(closes, 50) if len(closes) >= 50 else calculate_sma(closes, len(closes))
        features['ema_12'] = calculate_ema(closes, 12)
        features['ema_26'] = calculate_ema(closes, 26) if len(closes) >= 26 else calculate_ema(closes, len(closes))
        
        features['rsi'] = calculate_rsi(closes, 14)
        
        macd, signal, histogram = calculate_macd(closes)
        features['macd'] = macd
        features['macd_signal'] = signal
        features['macd_histogram'] = histogram
        
        upper_bb, middle_bb, lower_bb = calculate_bollinger_bands(closes)
        features['bb_upper'] = upper_bb
        features['bb_middle'] = middle_bb
        features['bb_lower'] = lower_bb
        
        if upper_bb and lower_bb:
            bb_width = upper_bb - lower_bb
            features['bb_position'] = (closes[-1] - lower_bb) / bb_width if bb_width > 0 else 0.5
        else:
            features['bb_position'] = 0.5
        
        features['atr'] = self.calculate_atr(highs, lows, closes)
        
        support, resistance = self.calculate_support_resistance(highs, lows, closes)
        features['support'] = support
        features['resistance'] = resistance
        
        features['volatility'] = np.std(closes[-20:]) / np.mean(closes[-20:]) * 100
        
        features['high_low_range'] = max(highs[-20:]) - min(lows[-20:])
        
        features['body_momentum'] = sum(1 if closes[i] > opens[i] else -1 for i in range(-10, 0))
        
        return features
    
    def calculate_trend_strength(self, features):
        """Calculate trend strength score (-100 to 100)"""
        score = 0
        
        if features['current_price'] > features['sma_20']:
            score += 15
        else:
            score -= 15
        
        if features['sma_20'] and features['sma_50'] and features['sma_20'] > features['sma_50']:
            score += 15
        elif features['sma_20'] and features['sma_50']:
            score -= 15
        
        if features['ema_12'] and features['ema_26'] and features['ema_12'] > features['ema_26']:
            score += 10
        elif features['ema_12'] and features['ema_26']:
            score -= 10
        
        if features['rsi']:
            if features['rsi'] > 70:
                score -= 15
            elif features['rsi'] < 30:
                score += 15
            elif features['rsi'] > 50:
                score += 5
            else:
                score -= 5
        
        if features['macd'] and features['macd_signal']:
            if features['macd'] > features['macd_signal']:
                score += 15
            else:
                score -= 15
        
        if features['bb_position']:
            if features['bb_position'] < 0.2:
                score += 10
            elif features['bb_position'] > 0.8:
                score -= 10
        
        if features['body_momentum'] > 5:
            score += 10
        elif features['body_momentum'] < -5:
            score -= 10
        
        if features['price_change_5'] > 0:
            score += 5
        else:
            score -= 5
        
        return max(-100, min(100, score))
    
    def predict_entry_tp_sl(self, opens, highs, lows, closes, balance=10000, risk_percent=1.0):
        """
        Main prediction method
        Returns entry price, take profit, stop loss, and trade direction
        """
        features = self.extract_features(opens, highs, lows, closes)
        if not features:
            return {'error': 'Not enough data for prediction (need at least 50 candles)'}
        
        trend_score = self.calculate_trend_strength(features)
        
        current_price = features['current_price']
        atr = features['atr'] if features['atr'] else current_price * 0.001
        
        predictions = []
        
        if trend_score >= 30:
            direction = 'BUY'
            confidence = min(95, 50 + abs(trend_score) / 2)
            
            entry = current_price
            
            if features['support']:
                sl_distance = max(atr * 1.5, current_price - features['support'])
            else:
                sl_distance = atr * 2
            stop_loss = current_price - sl_distance
            
            if features['resistance']:
                tp_distance = features['resistance'] - current_price
                if tp_distance < atr * 2:
                    tp_distance = atr * 3
            else:
                tp_distance = atr * 3
            take_profit = current_price + tp_distance
            
            risk_reward = tp_distance / sl_distance if sl_distance > 0 else 0
            
            risk_amount = balance * (risk_percent / 100)
            pip_value = sl_distance * 10000
            lots = risk_amount / (pip_value * 10) if pip_value > 0 else 0.01
            
            predictions.append({
                'direction': direction,
                'entry': round(entry, 5),
                'stop_loss': round(stop_loss, 5),
                'take_profit': round(take_profit, 5),
                'risk_reward': round(risk_reward, 2),
                'confidence': round(confidence, 1),
                'lots': round(lots, 2),
                'risk_amount': round(risk_amount, 2),
                'trend_score': trend_score,
                'reason': self._generate_reason(features, 'BUY')
            })
            
            tp2 = current_price + (tp_distance * 1.5)
            predictions.append({
                'direction': 'BUY',
                'entry': round(entry, 5),
                'stop_loss': round(stop_loss, 5),
                'take_profit': round(tp2, 5),
                'risk_reward': round((tp2 - current_price) / sl_distance, 2),
                'confidence': round(confidence * 0.85, 1),
                'lots': round(lots * 0.7, 2),
                'risk_amount': round(risk_amount * 0.7, 2),
                'trend_score': trend_score,
                'reason': 'Extended target - higher R:R'
            })
        
        elif trend_score <= -30:
            direction = 'SELL'
            confidence = min(95, 50 + abs(trend_score) / 2)
            
            entry = current_price
            
            if features['resistance']:
                sl_distance = max(atr * 1.5, features['resistance'] - current_price)
            else:
                sl_distance = atr * 2
            stop_loss = current_price + sl_distance
            
            if features['support']:
                tp_distance = current_price - features['support']
                if tp_distance < atr * 2:
                    tp_distance = atr * 3
            else:
                tp_distance = atr * 3
            take_profit = current_price - tp_distance
            
            risk_reward = tp_distance / sl_distance if sl_distance > 0 else 0
            
            risk_amount = balance * (risk_percent / 100)
            pip_value = sl_distance * 10000
            lots = risk_amount / (pip_value * 10) if pip_value > 0 else 0.01
            
            predictions.append({
                'direction': direction,
                'entry': round(entry, 5),
                'stop_loss': round(stop_loss, 5),
                'take_profit': round(take_profit, 5),
                'risk_reward': round(risk_reward, 2),
                'confidence': round(confidence, 1),
                'lots': round(lots, 2),
                'risk_amount': round(risk_amount, 2),
                'trend_score': trend_score,
                'reason': self._generate_reason(features, 'SELL')
            })
            
            tp2 = current_price - (tp_distance * 1.5)
            predictions.append({
                'direction': 'SELL',
                'entry': round(entry, 5),
                'stop_loss': round(stop_loss, 5),
                'take_profit': round(tp2, 5),
                'risk_reward': round((current_price - tp2) / sl_distance, 2),
                'confidence': round(confidence * 0.85, 1),
                'lots': round(lots * 0.7, 2),
                'risk_amount': round(risk_amount * 0.7, 2),
                'trend_score': trend_score,
                'reason': 'Extended target - higher R:R'
            })
        
        else:
            predictions.append({
                'direction': 'WAIT',
                'entry': None,
                'stop_loss': None,
                'take_profit': None,
                'risk_reward': 0,
                'confidence': 0,
                'lots': 0,
                'risk_amount': 0,
                'trend_score': trend_score,
                'reason': 'No clear trend - wait for better setup'
            })
        
        return {
            'predictions': predictions,
            'features': {
                'current_price': features['current_price'],
                'trend_score': trend_score,
                'rsi': features['rsi'],
                'macd': features['macd'],
                'macd_signal': features['macd_signal'],
                'sma_20': features['sma_20'],
                'sma_50': features['sma_50'],
                'bb_position': round(features['bb_position'] * 100, 1),
                'atr': round(atr, 5),
                'support': features['support'],
                'resistance': features['resistance'],
                'volatility': round(features['volatility'], 2),
                'body_momentum': features['body_momentum']
            },
            'analysis': self._generate_analysis(features, trend_score)
        }
    
    def _generate_reason(self, features, direction):
        """Generate human-readable reason for the trade"""
        reasons = []
        
        if direction == 'BUY':
            if features['rsi'] and features['rsi'] < 40:
                reasons.append(f"RSI oversold ({features['rsi']:.1f})")
            if features['macd'] and features['macd_signal'] and features['macd'] > features['macd_signal']:
                reasons.append("MACD bullish crossover")
            if features['current_price'] > features['sma_20']:
                reasons.append("Price above SMA20")
            if features['bb_position'] < 0.3:
                reasons.append("Near lower Bollinger Band")
            if features['body_momentum'] > 0:
                reasons.append("Bullish momentum")
        else:
            if features['rsi'] and features['rsi'] > 60:
                reasons.append(f"RSI overbought ({features['rsi']:.1f})")
            if features['macd'] and features['macd_signal'] and features['macd'] < features['macd_signal']:
                reasons.append("MACD bearish crossover")
            if features['current_price'] < features['sma_20']:
                reasons.append("Price below SMA20")
            if features['bb_position'] > 0.7:
                reasons.append("Near upper Bollinger Band")
            if features['body_momentum'] < 0:
                reasons.append("Bearish momentum")
        
        return " | ".join(reasons[:3]) if reasons else "Multiple indicator confluence"
    
    def _generate_analysis(self, features, trend_score):
        """Generate detailed analysis"""
        analysis = []
        
        if trend_score > 50:
            analysis.append("Strong bullish trend detected")
        elif trend_score > 30:
            analysis.append("Moderate bullish trend detected")
        elif trend_score < -50:
            analysis.append("Strong bearish trend detected")
        elif trend_score < -30:
            analysis.append("Moderate bearish trend detected")
        else:
            analysis.append("No clear trend - consolidation phase")
        
        if features['rsi']:
            if features['rsi'] > 70:
                analysis.append(f"RSI ({features['rsi']:.1f}) indicates overbought conditions")
            elif features['rsi'] < 30:
                analysis.append(f"RSI ({features['rsi']:.1f}) indicates oversold conditions")
        
        if features['macd'] and features['macd_signal']:
            if features['macd'] > features['macd_signal']:
                analysis.append("MACD shows bullish momentum")
            else:
                analysis.append("MACD shows bearish momentum")
        
        if features['bb_position'] < 0.2:
            analysis.append("Price near lower Bollinger Band - potential bounce zone")
        elif features['bb_position'] > 0.8:
            analysis.append("Price near upper Bollinger Band - potential reversal zone")
        
        if features['volatility'] > 2:
            analysis.append(f"High volatility ({features['volatility']:.1f}%) - use wider stops")
        elif features['volatility'] < 0.5:
            analysis.append(f"Low volatility ({features['volatility']:.1f}%) - expect range-bound action")
        
        return analysis


def predict_forex(opens, highs, lows, closes, balance=10000, risk_percent=1.0):
    """Convenience function for prediction"""
    predictor = ForexMLPredictor()
    return predictor.predict_entry_tp_sl(opens, highs, lows, closes, balance, risk_percent)
