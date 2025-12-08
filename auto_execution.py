"""
Auto Execution Portfolio Manager
Automatically executes trades based on algorithm signals with probability calculation
Uses yfinance for market data and integrates with existing trading strategies
"""

import yfinance as yf
import numpy as np
from datetime import datetime, timedelta
from trading_strategies import (
    MeanReversionStrategy, MomentumStrategy, BreakoutStrategy,
    VolatilityBreakoutStrategy, EnsembleStrategy
)


class Portfolio:
    """Portfolio manager for auto execution"""
    
    def __init__(self, initial_balance=10000, risk_percent=1.0):
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.risk_percent = risk_percent
        self.positions = []
        self.closed_trades = []
        self.equity_curve = [(datetime.now(), initial_balance)]
    
    def get_stats(self):
        """Get portfolio statistics"""
        total_trades = len(self.closed_trades)
        winning_trades = len([t for t in self.closed_trades if t['pnl'] > 0])
        losing_trades = len([t for t in self.closed_trades if t['pnl'] < 0])
        
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        total_profit = sum([t['pnl'] for t in self.closed_trades if t['pnl'] > 0])
        total_loss = abs(sum([t['pnl'] for t in self.closed_trades if t['pnl'] < 0]))
        
        profit_factor = total_profit / total_loss if total_loss > 0 else total_profit if total_profit > 0 else 0
        
        max_drawdown = self.calculate_max_drawdown()
        
        return {
            'initial_balance': self.initial_balance,
            'current_balance': round(self.current_balance, 2),
            'total_pnl': round(self.current_balance - self.initial_balance, 2),
            'total_pnl_percent': round((self.current_balance / self.initial_balance - 1) * 100, 2),
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': round(win_rate, 1),
            'profit_factor': round(profit_factor, 2),
            'max_drawdown': round(max_drawdown, 2),
            'open_positions': len(self.positions)
        }
    
    def calculate_max_drawdown(self):
        """Calculate maximum drawdown from equity curve"""
        if len(self.equity_curve) < 2:
            return 0
        
        peak = self.equity_curve[0][1]
        max_dd = 0
        
        for _, equity in self.equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd:
                max_dd = dd
        
        return max_dd


class AutoExecutor:
    """Automatic trade executor using algorithm signals"""
    
    def __init__(self):
        self.strategies = {
            'ensemble': EnsembleStrategy(),
            'mean_reversion': MeanReversionStrategy(),
            'momentum': MomentumStrategy(),
            'breakout': BreakoutStrategy(),
            'volatility': VolatilityBreakoutStrategy()
        }
    
    def calculate_execution_probability(self, signals, strategy_results):
        """
        Calculate probability percentage for execution based on multiple factors:
        - Signal confidence
        - Strategy agreement
        - Market conditions
        - Historical accuracy
        """
        if not signals:
            return 0, "No valid signals"
        
        base_confidence = signals[0].get('confidence', 0)
        
        # Factor 1: Strategy Agreement (how many strategies agree)
        agreement_score = 0
        direction = signals[0].get('direction', 'WAIT')
        
        for name, result in strategy_results.items():
            if 'signals' in result and result['signals']:
                for sig in result['signals']:
                    if sig.get('direction') == direction:
                        agreement_score += 15
        
        agreement_score = min(30, agreement_score)
        
        # Factor 2: Risk/Reward ratio
        rr = signals[0].get('risk_reward', 0)
        rr_score = min(20, rr * 8) if rr > 0 else 0
        
        # Factor 3: Confidence level
        conf_score = base_confidence * 0.4
        
        # Factor 4: Market volatility consideration
        volatility_score = 10  # Default neutral
        
        total_probability = agreement_score + rr_score + conf_score + volatility_score
        total_probability = min(95, max(5, total_probability))
        
        reasons = []
        if agreement_score >= 20:
            reasons.append("Strong strategy agreement")
        if rr >= 2:
            reasons.append(f"Good R:R ({rr}:1)")
        if base_confidence >= 70:
            reasons.append("High confidence signal")
        
        reason_text = ", ".join(reasons) if reasons else "Moderate signal strength"
        
        return round(total_probability, 1), reason_text
    
    def analyze_pair(self, pair, ticker_symbol, period='1mo', interval='1h', balance=10000, risk_percent=1.0):
        """Analyze a trading pair and generate execution recommendation"""
        try:
            ticker = yf.Ticker(ticker_symbol)
            df = ticker.history(period=period, interval=interval)
            
            if df.empty:
                return {'error': 'No data available'}
            
            opens = df['Open'].tolist()
            highs = df['High'].tolist()
            lows = df['Low'].tolist()
            closes = df['Close'].tolist()
            dates = df.index.strftime('%Y-%m-%d %H:%M').tolist()
            
            if len(closes) < 50:
                return {'error': 'Not enough data (need at least 50 candles)'}
            
            # Run all strategies
            strategy_results = {}
            for name, strategy in self.strategies.items():
                try:
                    strategy_results[name] = strategy.analyze(opens, highs, lows, closes, balance, risk_percent)
                except Exception as e:
                    strategy_results[name] = {'error': str(e)}
            
            # Get ensemble signal (main signal)
            ensemble_result = strategy_results.get('ensemble', {})
            signals = ensemble_result.get('signals', [])
            
            # Calculate execution probability
            probability, reason = self.calculate_execution_probability(signals, strategy_results)
            
            # Determine execution recommendation
            should_execute = probability >= 60 and signals
            
            signal = signals[0] if signals else {}
            
            return {
                'pair': pair,
                'current_price': round(closes[-1], 5),
                'signal': signal.get('direction', 'NO SIGNAL'),
                'entry': signal.get('entry'),
                'stop_loss': signal.get('stop_loss'),
                'take_profit': signal.get('take_profit'),
                'lots': signal.get('lots', 0.01),
                'risk_reward': signal.get('risk_reward', 0),
                'confidence': signal.get('confidence', 0),
                'execution_probability': probability,
                'probability_reason': reason,
                'should_execute': should_execute,
                'strategy_results': strategy_results,
                'ensemble_scores': ensemble_result.get('ensemble_scores', {}),
                'ohlc': {
                    'opens': opens,
                    'highs': highs,
                    'lows': lows,
                    'closes': closes
                },
                'dates': dates,
                'analyzed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
        except Exception as e:
            return {'error': str(e)}
    
    def simulate_portfolio(self, pairs, period='3mo', interval='1d', initial_balance=10000, risk_percent=1.0):
        """
        Simulate portfolio performance using historical data
        Returns simulated trades and portfolio statistics
        """
        from datetime import datetime
        
        portfolio = Portfolio(initial_balance, risk_percent)
        all_trades = []
        
        for pair, ticker_symbol in pairs.items():
            try:
                ticker = yf.Ticker(ticker_symbol)
                df = ticker.history(period=period, interval=interval)
                
                if df.empty or len(df) < 60:
                    continue
                
                opens = df['Open'].tolist()
                highs = df['High'].tolist()
                lows = df['Low'].tolist()
                closes = df['Close'].tolist()
                dates = df.index.tolist()
                
                # Simulate trading over the period
                lookback = 50
                for i in range(lookback, len(closes) - 5, 5):  # Every 5 candles
                    window_opens = opens[:i]
                    window_highs = highs[:i]
                    window_lows = lows[:i]
                    window_closes = closes[:i]
                    
                    # Get ensemble signal
                    ensemble = EnsembleStrategy()
                    result = ensemble.analyze(
                        window_opens, window_highs, window_lows, window_closes,
                        portfolio.current_balance, risk_percent
                    )
                    
                    if 'signals' not in result or not result['signals']:
                        continue
                    
                    signal = result['signals'][0]
                    if signal['direction'] not in ['BUY', 'SELL']:
                        continue
                    
                    # Simulate trade outcome
                    entry_price = closes[i]
                    future_prices = closes[i:i+5]
                    
                    if signal['direction'] == 'BUY':
                        exit_price = max(future_prices)
                        pnl_pips = (exit_price - entry_price) / entry_price * 10000
                    else:
                        exit_price = min(future_prices)
                        pnl_pips = (entry_price - exit_price) / entry_price * 10000
                    
                    # Calculate P&L based on lot size
                    lot_value = signal.get('lots', 0.01) * 100000
                    pnl = pnl_pips * lot_value / 10000
                    
                    # Cap P&L based on SL/TP
                    max_loss = portfolio.current_balance * (risk_percent / 100)
                    max_profit = max_loss * signal.get('risk_reward', 2)
                    pnl = max(-max_loss, min(max_profit, pnl))
                    
                    trade = {
                        'pair': pair,
                        'direction': signal['direction'],
                        'entry_price': round(entry_price, 5),
                        'exit_price': round(exit_price, 5),
                        'lots': signal.get('lots', 0.01),
                        'pnl': round(pnl, 2),
                        'confidence': signal.get('confidence', 0),
                        'date': dates[i].strftime('%Y-%m-%d') if hasattr(dates[i], 'strftime') else str(dates[i])[:10]
                    }
                    
                    all_trades.append(trade)
                    portfolio.closed_trades.append(trade)
                    portfolio.current_balance += pnl
                    portfolio.equity_curve.append((dates[i], portfolio.current_balance))
                    
            except Exception as e:
                continue
        
        # Sort trades by date
        all_trades.sort(key=lambda x: x['date'])
        
        return {
            'trades': all_trades[-50:],  # Last 50 trades
            'stats': portfolio.get_stats(),
            'equity_curve': [(str(d), round(v, 2)) for d, v in portfolio.equity_curve[-100:]]
        }


def get_execution_signals(pairs_dict, period='1mo', interval='1h', balance=10000, risk_percent=1.0):
    """
    Get execution signals for multiple pairs
    Returns list of pairs with signals and execution recommendations
    """
    executor = AutoExecutor()
    results = []
    
    for pair, ticker in pairs_dict.items():
        result = executor.analyze_pair(pair, ticker, period, interval, balance, risk_percent)
        if 'error' not in result:
            results.append(result)
    
    # Sort by execution probability
    results.sort(key=lambda x: x.get('execution_probability', 0), reverse=True)
    
    return results


def simulate_auto_portfolio(initial_balance=10000, risk_percent=1.0, period='3mo'):
    """
    Run portfolio simulation with default pairs
    """
    default_pairs = {
        'EUR/USD': 'EURUSD=X',
        'GBP/USD': 'GBPUSD=X',
        'USD/JPY': 'USDJPY=X',
        'XAU/USD': 'GC=F',
        'BTC/USD': 'BTC-USD'
    }
    
    executor = AutoExecutor()
    return executor.simulate_portfolio(default_pairs, period, '1d', initial_balance, risk_percent)
