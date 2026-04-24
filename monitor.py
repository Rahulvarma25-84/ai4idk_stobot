#!/usr/bin/env python3
"""
BuzzFlow - Monitor Runner
Runs 2-3x/day: 12:30 PM and 2:30 PM IST.
Also runs replacement scan at 2:00 PM.
Also runs market sentiment check (--sentiment).
"""

import os
import logging
import argparse
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("buzzflow.log"), logging.StreamHandler()]
)

from monitoring_engine import MonitoringEngine
from replacement_engine import ReplacementEngine
from watchlist_engine import WatchlistEngine
from market_regime_engine import get_market_sentiment, format_sentiment_alert
from alert_engine import AlertEngine


def main():
    parser = argparse.ArgumentParser(description="BuzzFlow Monitor")
    parser.add_argument("--watchlist",   action="store_true", help="Print watchlist and exit")
    parser.add_argument("--replacement", action="store_true", help="Run replacement scan only")
    parser.add_argument("--sentiment",   action="store_true", help="Run market sentiment analysis and alert")
    args = parser.parse_args()

    token   = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if args.watchlist:
        WatchlistEngine().print_watchlist()
        return

    if args.sentiment:
        print("\n  Computing market sentiment (breadth scan ~30s)...\n")
        s = get_market_sentiment(force=True)
        msg = format_sentiment_alert(s)
        print(msg)
        alert = AlertEngine(token=token, chat_id=chat_id)
        alert.send(msg)
        return

    if args.replacement:
        engine = ReplacementEngine(telegram_token=token, telegram_chat_id=chat_id)
        suggestions = engine.run()
        engine.print_report(suggestions)
        return

    # Full monitoring run — prepend sentiment check
    s = get_market_sentiment()
    if s["bearish_warning"]:
        alert = AlertEngine(token=token, chat_id=chat_id)
        alert.send(format_sentiment_alert(s))
        logging.warning(f"BEARISH WARNING sent: regime={s['regime']} score={s['composite_score']}")

    engine = MonitoringEngine(telegram_token=token, telegram_chat_id=chat_id)
    print("\n  Running position monitoring...\n")
    results = engine.run()
    engine.print_report(results)

    # Also check replacements after monitoring
    rep_engine = ReplacementEngine(telegram_token=token, telegram_chat_id=chat_id)
    suggestions = rep_engine.run()
    if suggestions:
        rep_engine.print_report(suggestions)


if __name__ == "__main__":
    main()
