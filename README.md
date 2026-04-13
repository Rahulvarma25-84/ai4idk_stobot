# BuzzFlow — Automated Swing Trading System for Indian Markets

A fully automated, zero-cost swing trading system for NSE stocks.
Scans Nifty 50 / Bank Nifty / IT stocks every morning, monitors open positions
during the day, and sends Telegram alerts — all running free on GitHub Actions.

---

## How It Works

```
Every Trading Day (Mon–Fri)
─────────────────────────────────────────────────────────────────────

8:30 AM IST   →  scanner_v2.py   →  Scans stocks, scores them, adds top picks to watchlist
12:30 PM IST  →  monitor.py      →  Checks open positions, fires EXIT/CAUTION alerts
2:30 PM IST   →  monitor.py      →  Final check before market close

All alerts → Telegram Bot (your phone)
All data   → buzzflow.db (SQLite, stored locally or as GitHub artifact)
```

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  GitHub Actions (Cron)                      │
│         8:30 AM → Scan    |    12:30 PM / 2:30 PM → Monitor │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │    DATA INGESTION       │
              │  Yahoo Finance (OHLCV)  │
              │  Google News RSS (free) │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │    FEATURE ENGINE       │
              │  Price + Volume + News  │
              │  RSI, MACD, ATR, MA20   │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │    SCORING ENGINE       │
              │  Entry Score (0–100)    │
              │  Trap Filter (gap/RSI)  │
              │  Exit Score (0–100)     │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │    WATCHLIST ENGINE     │
              │  SQLite persistence     │
              │  Entry / SL / Target    │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │    MONITORING ENGINE    │
              │  Exit scoring 3x/day    │
              │  Stop loss / target hit │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │    ALERT ENGINE         │
              │  Telegram Bot           │
              └─────────────────────────┘
```

---

## Scoring Formulas

### Entry Score (0–100)

```
Entry Score = (0.30 × accumulation)
            + (0.20 × compression)
            + (0.15 × relative_strength_vs_nifty)
            + (0.10 × position_near_support)
            + (0.10 × news_sentiment)
            + (0.10 × fundamentals)
            + (0.05 × chart_pattern)

Trap Penalty:
  − 20 pts  if gap > 5%
  − 20 pts  if RSI > 80 (overextended)
```

| Score | Signal      |
|-------|-------------|
| ≥ 70  | STRONG_BUY  |
| ≥ 55  | BUY         |
| ≥ 40  | WATCH       |
| < 40  | SKIP        |

### Exit Score (0–100)

```
Exit Score = (0.35 × momentum_loss)
           + (0.20 × volume_drop)
           + (0.20 × trend_break)
           + (0.15 × market_weakness)
           + (0.10 × profit_exhaustion)
```

| Score | Decision |
|-------|----------|
| > 70  | EXIT     |
| > 40  | CAUTION  |
| ≤ 40  | HOLD     |

---

## File Structure

```
buzzflow/
│
├── scanner_v2.py          ← Main scanner (run this every morning)
├── monitor.py             ← Position monitor (run 2–3x per day)
│
├── news_engine.py         ← Google News RSS fetcher + sentiment scorer
├── scoring_engine.py      ← Entry score + exit score formulas
├── watchlist_engine.py    ← Add/track/close positions
├── monitoring_engine.py   ← Exit scoring logic + alert triggers
├── alert_engine.py        ← Telegram Bot alerts
├── database.py            ← SQLite: watchlist, trades_log, scan_results
│
├── calculate_indicators.py  ← Technical indicators (RSI, MACD, BB, etc.)
├── buzz_enhancer.py         ← Volume analysis + pattern detection
├── risk_management.py       ← Position sizing + portfolio risk
├── recommendation_engine.py ← Legacy recommendation engine
├── buzz_engine.py           ← Legacy Reddit/NewsAPI engine (optional)
├── sentiment_engine.py      ← Legacy VADER sentiment (optional)
├── backtesting_engine.py    ← Historical backtesting
├── stock_scanner.py         ← Legacy scanner (still works)
├── main.py                  ← Legacy single-stock analysis CLI
│
├── .github/
│   └── workflows/
│       └── buzzflow.yml   ← GitHub Actions automation
│
├── .env                   ← Your secrets (never commit this)
├── .env.example           ← Template for .env
├── requirements.txt       ← Python dependencies
└── buzzflow.db            ← SQLite database (auto-created)
```

---

## Setup

### Step 1 — Clone and install dependencies

```bash
git clone https://github.com/YOUR_USERNAME/buzzflow.git
cd buzzflow
pip install -r requirements.txt
```

### Step 2 — Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in your Telegram credentials:

```env
TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID=987654321
```

**How to get these:**
1. Open Telegram → search `@BotFather` → send `/newbot` → copy the token
2. Message `@userinfobot` on Telegram → it replies with your chat ID

> Telegram is optional. The system works without it — alerts just go to the log file.

### Step 3 — Test your setup

```bash
# Test Telegram alert
python -c "from alert_engine import AlertEngine; AlertEngine().test()"

# Quick scan of 3 stocks to verify everything works
python scanner_v2.py --index nifty_it --min-score 40 --max-results 5
```

---

## Daily Usage

### Morning Scan (8:30 AM)

Scans all Nifty 50 stocks, scores them, prints top picks:

```bash
python scanner_v2.py
```

With options:

```bash
# Scan a specific index
python scanner_v2.py --index nifty_50
python scanner_v2.py --index bank_nifty
python scanner_v2.py --index nifty_it
python scanner_v2.py --index all          # scan all three

# Adjust score threshold (default: 55)
python scanner_v2.py --min-score 60

# Limit results (default: 10)
python scanner_v2.py --max-results 5

# Auto-add BUY signals to your watchlist
python scanner_v2.py --auto-watchlist

# Send top picks to Telegram
python scanner_v2.py --alert

# Full morning routine (recommended)
python scanner_v2.py --index nifty_50 --min-score 60 --auto-watchlist --alert
```

**Sample output:**
```
================================================================================
                   🔍 BUZZFLOW SCAN RESULTS — NIFTY_50
                      Generated: 2026-04-14 08:32
================================================================================
Symbol          Price   Score Signal       SL   Target   R:R
--------------------------------------------------------------------------------
INFY.NS       1292.50    72.1 STRONG_BUY  1227.88  1376.90   1.3
TCS.NS        3801.20    68.4 BUY         3611.14  4033.27   1.4
HCLTECH.NS    1540.00    61.2 BUY         1463.00  1617.00   1.0
================================================================================

📰 Top News Headlines:

  INFY.NS:
    • Infosys Q4 results beat estimates, revenue up 8%
    • Infosys raises FY26 guidance on strong deal wins
```

---

### Midday / Afternoon Monitor (12:30 PM and 2:30 PM)

Checks all open positions and fires alerts if anything needs action:

```bash
python monitor.py
```

**Sample output:**
```
======================================================================
         📊 MONITORING REPORT — 2026-04-14 12:31
======================================================================
Symbol          Price    PnL%  ExitScore Decision
----------------------------------------------------------------------
INFY.NS       1318.50   +2.01%        8.0 HOLD
TCS.NS        3750.00   -1.35%       52.0 CAUTION
======================================================================
```

View your watchlist anytime:

```bash
python monitor.py --watchlist
```

**Sample output:**
```
===========================================================================
                              📋 WATCHLIST
===========================================================================
Symbol          Entry       SL   Target   Score Status     Added
---------------------------------------------------------------------------
INFY.NS       1292.50  1227.88  1376.90    72.1 HOLD       2026-04-14
TCS.NS        3801.20  3611.14  4033.27    68.4 CAUTION    2026-04-14
===========================================================================
```

---

### Manage Watchlist Manually

```python
from watchlist_engine import WatchlistEngine

wl = WatchlistEngine()

# Add a stock manually
wl.add("RELIANCE.NS", entry_price=1400, stop_loss=1330, target=1540, entry_score=71.0)

# View active positions
wl.print_watchlist()

# Close a position (logs PnL automatically)
wl.close_position("RELIANCE.NS", exit_price=1520, entry_price=1400)
```

---

### View Trade History

```python
from database import get_trade_history

trades = get_trade_history()
for t in trades:
    print(t["symbol"], t["action"], t["price"], t["pnl_percent"])
```

---

## GitHub Actions — Full Automation (Zero Cost)

Push your code to GitHub and it runs automatically every trading day.

### Step 1 — Push to GitHub

```bash
git init
git add .
git commit -m "BuzzFlow v2"
git remote add origin https://github.com/YOUR_USERNAME/buzzflow.git
git push -u origin main
```

### Step 2 — Add secrets

Go to your GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these two secrets:

| Secret Name       | Value                          |
|-------------------|--------------------------------|
| `TELEGRAM_TOKEN`  | Your bot token from BotFather  |
| `TELEGRAM_CHAT_ID`| Your chat ID from userinfobot  |

### Step 3 — Done

The workflow runs automatically:

| Time (IST) | Action                                      |
|------------|---------------------------------------------|
| 8:30 AM    | Morning scan → top picks → Telegram alert   |
| 12:30 PM   | Monitor positions → EXIT/CAUTION alerts     |
| 2:30 PM    | Final monitor before market close           |

You can also trigger it manually from the **Actions** tab in your repo.

---

## What Each Alert Looks Like on Telegram

**Morning scan:**
```
📊 BuzzFlow Morning Scan

🔹 INFY.NS | Score: 72.1 | STRONG_BUY
   Entry: ₹1292.50 | SL: ₹1227.88 | Target: ₹1376.90

🔹 TCS.NS | Score: 68.4 | BUY
   Entry: ₹3801.20 | SL: ₹3611.14 | Target: ₹4033.27
```

**Target hit:**
```
🎯 TARGET HIT: INFY.NS
Price: ₹1376.90 | Target: ₹1376.90
Profit: +6.5%
```

**Stop loss hit:**
```
🛑 STOP LOSS HIT: TCS.NS
Price: ₹3611.14 | SL: ₹3611.14
PnL: -5.0%
```

**Caution / Exit signal:**
```
🟡 CAUTION: TCS.NS
Exit Score: 52.0/100
Price: ₹3750.00 | PnL: -1.35%
Consider tightening stop loss.
```

---

## Indices Supported

| Index       | Stocks                                    |
|-------------|-------------------------------------------|
| `nifty_50`  | 50 large-cap NSE stocks                   |
| `bank_nifty`| 13 banking stocks                         |
| `nifty_it`  | 10 IT sector stocks                       |
| `all`       | All three combined                        |

---

## Key Design Decisions

**Why Google News RSS instead of NewsAPI / Reddit?**
- NewsAPI free tier: 100 requests/day, no historical data
- Reddit API: requires OAuth, rate limited, unreliable for Indian stocks
- Google News RSS: unlimited, no key needed, covers Indian financial news well

**Why SQLite instead of CSV?**
- Concurrent-safe reads/writes
- Easy to query trade history
- Single file, zero setup

**Why GitHub Actions instead of a server?**
- Completely free for public repos (2000 min/month for private)
- No server to maintain
- Runs reliably on schedule

---

## Disclaimer

This software is for educational and research purposes only.
It does not constitute financial advice. Always do your own research
before making any investment decisions. Past performance of any
algorithm does not guarantee future results.
