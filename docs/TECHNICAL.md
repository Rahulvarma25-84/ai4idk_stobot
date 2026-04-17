# BuzzFlow — Technical Reference

Semi-automated swing trading assistant for NSE. Scans stocks, scores them, monitors positions, and sends Telegram alerts. You execute trades manually.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Market Data | yfinance (OHLCV, free) |
| News / Sentiment | Google News RSS via feedparser (free, no limits) |
| Stock Universe | NSE archives CSV (Nifty 500, auto-updated monthly) |
| Database | SQLite with WAL mode |
| Dashboard API | Flask + Flask-CORS |
| Dashboard UI | React 18 + Vite + Recharts |
| Alerts | Telegram Bot API |
| Automation | GitHub Actions (cron) |

---

## System Flow

```
08:30 AM  scanner_v2.py
          Phase 1: technical pre-filter on 499 stocks (20 workers, ~3s)
          Phase 2: full analysis + news on top 50 candidates (5 workers, ~40s)
          → saves to scan_results table
          → adds BUY signals to watchlist
          → sends Telegram morning alert

12:30 PM  monitor.py
02:30 PM  monitor.py
          → fetches live prices for each watchlist position
          → computes exit score + trade state
          → updates trailing stop
          → sends alert only if WEAK / EXIT / SL hit / target hit

02:00 PM  monitor.py --replacement
          → checks if any WEAK position has a better replacement candidate
          → sends replacement suggestion if score diff >= 20
```

---

## Scoring Formulas

### Entry Score (0–100)

```
Entry Score = 0.30 × accumulation        (CMF-based delivery proxy)
            + 0.20 × compression         (ATR tightening = coiling setup)
            + 0.15 × relative_strength   (stock 5d return vs Nifty 5d return)
            + 0.10 × position            (proximity to 20-day support)
            + 0.10 × sentiment           (Google News keyword score)
            + 0.10 × fundamentals        (neutral proxy = 50)
            + 0.05 × pattern             (neutral proxy = 50)

Trap penalties (applied after):
  gap > 5%   → -20 pts
  RSI > 80   → -20 pts (overextended)
```

| Score | Signal |
|---|---|
| >= 70 | STRONG_BUY |
| >= 65 | BUY |
| >= 55 | WATCH |
| < 55 | SKIP |

### Exit Score (0–100)

```
Exit Score = 0.35 × momentum_loss      (RSI < 50 + MACD histogram negative)
           + 0.20 × volume_drop        (current vol < 20-day avg)
           + 0.20 × trend_break        (price below MA20)
           + 0.15 × market_weakness    (Nifty daily return negative)
           + 0.10 × profit_exhaustion  (% progress toward target)
```

| Score | Decision |
|---|---|
| > 70 | EXIT |
| > 40 | CAUTION |
| <= 40 | HOLD |

### Opportunity Score (0–100)

Used to compare positions and trigger replacements.

```
Opportunity Score = 0.5 × entry_score
                  + 0.3 × (100 - exit_score)
                  + 0.2 × momentum_score
```

---

## Delivery Volume Proxy

NSE bhavcopy requires browser cookies so we compute a proxy from OHLCV:

```
MFR  = (Close - Low) / (High - Low)          5-day avg, 0-1
CMF  = sum(MFV) / sum(Volume) over 20 days   Chaikin Money Flow
       MFV = ((Close-Low) - (High-Close)) / (High-Low) * Volume

Delivery Score = 0.35 × MFR_score
               + 0.45 × CMF_score
               + 0.20 × vol_trend_score

>= 65 + CMF > 0.05  → ACCUMULATION
< 40  or CMF < -0.05 → DISTRIBUTION
```

Distribution signal adds up to 20 pts to exit score's momentum_loss component.

---

## Signal Filters (applied after entry score)

| Tier | Filter | Condition |
|---|---|---|
| 1a | Market regime | Nifty price > 20-day MA (cached 1hr) |
| 1b | Volume confirmation | volume_ratio >= 1.2x 20-day avg |
| 1c | Trend filter | price >= MA50 * 0.98 |
| 1d | Not overbought | RSI <= 75 |
| 2 | Earnings blackout | skip known results months per symbol |
| 3 | Duplicate suppression | each symbol alerted once per day |

---

## Risk Tiers

```
Entry Score >= 70  → risk 1.5% of capital, confidence = high
Entry Score >= 65  → risk 1.0% of capital, confidence = high
Entry Score >= 60  → risk 0.5% of capital, confidence = medium

Position size = (capital × risk%) / (entry_price - stop_loss)
```

---

## Stop Loss & Target

```
Stop Loss = max(20-day support, entry - 1.5 × ATR14)
            hard floor at entry × 0.92 (max 8% loss)

Target    = min(resistance × 0.98, entry + 2.5 × ATR14)
            floor at entry × 1.05 (min 5% upside)

R:R filter: skip if reward/risk < 1.2
```

### Trailing Stop

```
PnL >= +3%  → move SL to entry (breakeven)
PnL >= +5%  → trail below 5-day recent low × 0.99
```

---

## Trade State Classification

| State | Condition | Action |
|---|---|---|
| STRONG | exit_score < 30, price > entry, not near SL | HOLD |
| NEUTRAL | exit_score 30–50 | MONITOR |
| WEAK | exit_score > 50 OR price within 2% of SL | CAUTION or EXIT |

---

## Replacement Logic

Only fires when:
1. A position is classified WEAK
2. A scan candidate has entry_score >= 70
3. Opportunity score difference >= 20 points

Never suggests replacements for STRONG or NEUTRAL positions.

---

## Stock Universe

Source: `data/universe.csv` — fetched from NSE archives (free).

```bash
python update_universe.py   # refresh from NSE (run monthly)
```

Covers Nifty 500 + Midcap 150 = ~499 unique EQ-series stocks with company, industry, category, cap tier, ISIN.

---

## Database Schema (SQLite)

| Table | Purpose |
|---|---|
| `watchlist` | Active and closed positions with all scores |
| `trades_log` | Every exit with PnL, holding days, entry score |
| `scan_results` | Latest scan signal per symbol |
| `replacement_log` | History of replacement suggestions |

---

## GitHub Actions Schedule

| Cron | IST | Job |
|---|---|---|
| `0 3 * * 1-5` | 8:30 AM | Morning scan |
| `0 7 * * 1-5` | 12:30 PM | Monitor |
| `30 8 * * 1-5` | 2:00 PM | Replacement scan |
| `0 9 * * 1-5` | 2:30 PM | Monitor |
| `0 2 1 * *` | Monthly | Update universe CSV |

DB is persisted between jobs via GitHub Actions cache keyed on branch name.

---

## Dashboard API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/market` | Nifty regime (bullish/bearish) |
| GET | `/api/watchlist` | All positions with live price + PnL |
| POST | `/api/watchlist` | Add position manually |
| PATCH | `/api/watchlist/<symbol>/status` | Update status |
| POST | `/api/watchlist/<symbol>/close` | Close position, log PnL |
| POST | `/api/monitor` | Run monitoring on demand |
| POST | `/api/replacement` | Run replacement check on demand |
| GET | `/api/scans` | Latest scan results |
| POST | `/api/scans/run` | Trigger manual scan from dashboard |
| GET | `/api/performance` | Win rate, drawdown, equity curve data |
| GET | `/api/universe` | Universe stats |
| GET | `/api/health` | System status |
| POST | `/api/telegram/test` | Test Telegram connectivity |
