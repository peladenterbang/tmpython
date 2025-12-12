# Forex Risk Manager - Features

A comprehensive forex trading risk management platform with AI-powered analysis, ICT concepts, and automated trading features.

---

## Table of Contents

1. [User Authentication & Management](#1-user-authentication--management)
2. [Dashboard & Trade Journal](#2-dashboard--trade-journal)
3. [Position Size Calculator](#3-position-size-calculator)
4. [Technical Analysis](#4-technical-analysis-prediction)
5. [ICT Analysis](#5-ict-analysis-smart-money-concepts)
6. [ML Predict](#6-ml-predict-machine-learning)
7. [ARIMA Forecasting](#7-arima-forecasting)
8. [Quant Strategies](#8-quant-strategies)
9. [Auto Execution Portfolio](#9-auto-execution-portfolio)
10. [Telegram Alerts](#10-telegram-alerts)
11. [Payment System](#11-payment-system-midtrans)
12. [Admin Panel](#12-admin-panel)
13. [Email System](#13-email-system)

---

## 1. User Authentication & Management

### Features
- **User Registration/Login** - Secure authentication with password hashing (PBKDF2-SHA256)
- **Forgot Password** - Email-based password reset with secure tokens (1-hour expiry)
- **Change Email/Password** - Account management with verification
- **Subscription Plans** - Free, Basic ($9.99/mo), Pro ($19.99/mo) tiers
- **Role-based Access** - Admin and user roles with different permissions

### Subscription Tiers

| Feature | Free | Basic | Pro |
|---------|------|-------|-----|
| Dashboard | ✓ | ✓ | ✓ |
| Trade Journal | 10 trades | Unlimited | Unlimited |
| Technical Analysis | 5/day | 50/day | Unlimited |
| ICT Analysis | ✗ | ✓ | ✓ |
| ML Predict | ✗ | 20/day | Unlimited |
| ARIMA Forecast | ✗ | 10/day | Unlimited |
| Quant Strategies | ✗ | ✗ | ✓ |
| Auto Execution | ✗ | ✗ | ✓ |
| Telegram Alerts | ✗ | ✓ | ✓ |
| PDF Reports | ✗ | ✗ | ✓ |

---

## 2. Dashboard & Trade Journal

### Features
- **Account Balance Tracking** - Monitor initial and current balance
- **Trade Journal** - Log all trades with entry/exit prices, SL/TP, P&L
- **Performance Metrics** - Win rate, total profit/loss, trade history
- **Balance Sync** - Automatic balance updates based on closed trades

### Trade Entry Fields
- Trading pair (67+ pairs supported)
- Trade type (Buy/Sell)
- Lot size
- Entry price
- Stop loss / Take profit
- Risk percentage
- Status (Open/Closed)
- Profit/Loss calculation

---

## 3. Position Size Calculator

### Features
- **Risk-based Calculation** - Calculate lot size based on risk percentage
- **Multiple Pair Support** - Different pip values for various instruments
- **Stop Loss Integration** - Factor in SL distance for accurate sizing
- **ATR-based Risk** - Dynamic position sizing based on volatility

### Formula
```
Lot Size = (Account Balance × Risk%) / (SL Pips × Pip Value)
```

### Supported Instruments
- **Forex Majors**: EUR/USD, GBP/USD, USD/JPY, etc.
- **Forex Crosses**: EUR/GBP, GBP/JPY, AUD/NZD, etc.
- **Commodities**: XAU/USD (Gold), XAG/USD (Silver), Oil
- **Crypto**: BTC/USD, ETH/USD, etc.
- **Indices**: US30, NAS100, SPX500, etc.

---

## 4. Technical Analysis (Prediction)

### Features
- **Live Data** - Real-time prices from Yahoo Finance
- **Multi-timeframe Analysis** - 5m, 15m, 30m, 1H, 4H, Daily
- **Signal Generation** - Buy/Sell/Hold recommendations
- **Confidence Scoring** - Signal strength indicator

### Technical Indicators

| Indicator | Description |
|-----------|-------------|
| SMA | Simple Moving Average (20, 50, 200 periods) |
| EMA | Exponential Moving Average (12, 26 periods) |
| RSI | Relative Strength Index (14 periods) |
| MACD | Moving Average Convergence Divergence |
| Bollinger Bands | Volatility bands (20 periods, 2 std) |
| ATR | Average True Range (14 periods) |

### Signal Logic
- **Buy**: RSI < 30, Price below lower BB, MACD bullish crossover
- **Sell**: RSI > 70, Price above upper BB, MACD bearish crossover
- **Hold**: Neutral conditions

---

## 5. ICT Analysis (Smart Money Concepts)

### Features
- **Kill Zones** - London, New York, Asian session identification
- **Liquidity Zones** - Buy-side and sell-side liquidity detection
- **Market Structure** - Break of Structure (BOS), Change of Character (ChoCH)
- **Order Blocks** - Bullish and bearish order block identification
- **Fair Value Gaps (FVG)** - Imbalance zone detection
- **Premium/Discount Zones** - Optimal entry areas
- **Power of 3** - Accumulation, Manipulation, Distribution phases
- **Weekly Bias** - Directional bias based on previous week
- **Confidence Scoring** - 0-100% confidence in analysis

### ICT Concepts Implemented

| Concept | Description |
|---------|-------------|
| Kill Zones | High-probability trading times |
| Liquidity Pools | Areas where stop losses cluster |
| BOS/ChoCH | Market structure shifts |
| Order Blocks | Institutional entry zones |
| FVG | Price imbalances to fill |
| Breaker Blocks | Failed order blocks |
| Inducement | Fake breakouts to trap traders |
| HTF Levels | Higher timeframe S/R levels |

---

## 6. ML Predict (Machine Learning)

### Features
- **AI-powered Signals** - Buy/Sell/Hold recommendations
- **Entry/TP/SL Prediction** - Suggested trade levels
- **Trend Score** - Bullish/bearish strength indicator (-100 to +100)
- **Technical Features** - RSI, MACD, Bollinger position analysis
- **Signal Caching** - Database storage for signal comparison
- **Previous Signal Comparison** - Track signal changes over time

### ML Features Used
- Price momentum
- RSI values
- MACD histogram
- Bollinger Band position
- Volume analysis
- Trend strength

### Output
```json
{
  "signal": "BUY",
  "confidence": 78.5,
  "entry": 1.0850,
  "stop_loss": 1.0820,
  "take_profit": 1.0910,
  "trend_score": 65.2
}
```

---

## 7. ARIMA Forecasting

### Features
- **Time Series Analysis** - ARIMA(p,d,q) model implementation
- **Price Forecasting** - 3-10 period ahead predictions
- **Confidence Intervals** - 80% and 95% prediction bands
- **Backtest Results** - Direction accuracy, RMSE, MAPE, MAE
- **ACF/PACF Charts** - Autocorrelation analysis
- **Model Diagnostics** - Stationarity tests, suggested parameters
- **PDF Report Generation** - Macro analysis with charts

### Model Parameters
- **p**: Autoregressive order (0-5)
- **d**: Differencing order (0-2)
- **q**: Moving average order (0-5)

### Backtest Metrics
| Metric | Description |
|--------|-------------|
| Direction Accuracy | % of correct up/down predictions |
| RMSE | Root Mean Square Error |
| MAPE | Mean Absolute Percentage Error |
| MAE | Mean Absolute Error |

### PDF Report Contents
- ARIMA forecast results
- Technical indicator summary
- Macro context (DXY, Gold, Oil, S&P500, VIX)
- Chart screenshots
- Trading recommendations

---

## 8. Quant Strategies (Jim Simons Inspired)

### Features
- **Ensemble Strategy** - Multi-factor combined signals
- **Mean Reversion** - Oversold/overbought opportunities
- **Momentum/Trend** - Trend-following signals
- **Breakout Strategy** - Support/resistance breakout detection
- **Volatility Breakout** - ATR-based breakout signals
- **Risk-adjusted Sizing** - Kelly criterion position sizing

### Strategies

| Strategy | Description |
|----------|-------------|
| Ensemble | Combines all strategies with weighted voting |
| Mean Reversion | Trades against extreme moves |
| Momentum | Follows strong trends |
| Breakout | Trades S/R breaks |
| Volatility | Trades volatility expansion |

---

## 9. Auto Execution Portfolio

### Features
- **67 Trading Pairs** - Comprehensive instrument coverage
- **Trading Methods** - ML, ICT, or Hybrid approach
- **ATR-based Risk Management** - Dynamic SL/TP calculation
- **Proper Lot Sizing** - Risk-adjusted position sizes
- **Position Monitoring** - Track open positions, TP/SL triggers
- **Trade Statistics** - Win rate, accuracy, total P&L

### Supported Pairs

| Category | Count | Examples |
|----------|-------|----------|
| Forex Majors | 7 | EUR/USD, GBP/USD, USD/JPY |
| Forex Crosses | 21 | EUR/GBP, GBP/JPY, AUD/NZD |
| Exotics | 11 | USD/ZAR, EUR/TRY, USD/MXN |
| Commodities | 7 | XAU/USD, XAG/USD, Oil |
| Crypto | 12 | BTC/USD, ETH/USD, XRP/USD |
| Indices | 9 | US30, NAS100, SPX500 |

### Trading Methods

| Method | Description |
|--------|-------------|
| ML | Machine learning signals only |
| ICT | ICT/Smart Money concepts only |
| HYBRID | Combined ML + ICT signals |

### Risk Management
- Maximum SL: 100 pips (forex), 500 pips (gold/indices), 5000 pips (crypto)
- ATR multiplier for SL/TP
- Risk per trade: 0.5% - 3% configurable
- Maximum trades per day: 1-20 configurable

---

## 10. Telegram Alerts

### Features
- **Bot Integration** - Connect personal Telegram bot
- **Chart Screenshots** - Send analysis with chart images
- **Signal Notifications** - Receive trade signals on Telegram
- **Test Messages** - Verify bot configuration

### Setup
1. Create bot via @BotFather
2. Get bot token
3. Get chat ID from @userinfobot
4. Configure in Settings page

### Alert Types
- New trade signals
- Position opened
- TP/SL hit
- Daily summary

---

## 11. Payment System (Midtrans)

### Features
- **Multiple Payment Methods** - Credit card, bank transfer, e-wallet, retail
- **USD to IDR Conversion** - Live or manual exchange rates
- **Subscription Management** - Auto-upgrade on successful payment
- **Invoice Emails** - Automatic and manual invoice sending
- **Webhook Integration** - Real-time payment status updates
- **Sandbox/Production** - Test mode for development

### Payment Methods (Indonesia)
- Credit/Debit Cards (Visa, Mastercard)
- Bank Transfer (BCA, Mandiri, BNI, BRI, Permata)
- E-Wallets (GoPay, ShopeePay, DANA, OVO)
- Retail (Alfamart, Indomaret)
- QRIS

### Payment Flow
```
1. User selects plan → 2. Snap popup opens → 3. User pays
4. Webhook received → 5. Subscription upgraded → 6. Invoice sent
```

---

## 12. Admin Panel

### Features
- **Dashboard** - Overview of users, payments, subscriptions
- **User Management** - View, edit, delete users
- **Payment Management** - Track all payments, sync with Midtrans
- **Subscription Control** - Manually upgrade/downgrade users
- **Settings Management**:
  - Site URL configuration
  - Midtrans API keys
  - Email SMTP settings
  - Exchange rate settings
- **Resend Invoices** - Manual invoice email sending

### Admin Routes
| Route | Description |
|-------|-------------|
| /admin | Dashboard |
| /admin/users | User management |
| /admin/payments | Payment management |
| /admin/settings | App settings |

---

## 13. Email System

### Features
- **Password Reset Emails** - Secure reset links
- **Email Change Notifications** - Security alerts
- **Payment Invoices** - Professional HTML invoices
- **Test Email** - Verify SMTP configuration

### Supported Providers
- Zoho Mail (recommended)
- Gmail (with App Password)
- Any SMTP provider

### Email Templates
- Password Reset
- Email Change Notification
- Payment Invoice
- Welcome Email

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Python Flask |
| Database | SQLite (MySQL supported) |
| Frontend | Bootstrap 5, Vanilla JS |
| Charts | Lightweight Charts (TradingView) |
| Market Data | Yahoo Finance API |
| Payments | Midtrans Payment Gateway |
| Email | SMTP (Zoho Mail) |
| PDF Generation | ReportLab |

---

## Security Features

- Password hashing (PBKDF2-SHA256)
- Secure session management
- CSRF protection
- Input validation & sanitization
- SQL injection prevention
- Rate limiting (subscription-based)
- Secure password reset tokens

---

*Last updated: December 2024*
