#!/usr/bin/env python3
"""
BuzzFlow - Monitor Runner
Runs 2-3x/day: 12:30 PM and 2:30 PM IST.
Also runs replacement scan at 2:00 PM.
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


def main():
    parser = argparse.ArgumentParser(description="BuzzFlow Monitor")
    parser.add_argument("--watchlist",    action="store_true", help="Print watchlist and exit")
    parser.add_argument("--replacement",  action="store_true", help="Run replacement scan only")
    args = parser.parse_args()

    if args.watchlist:
        WatchlistEngine().print_watchlist()
        return

    token   = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if args.replacement:
        engine = ReplacementEngine(telegram_token=token, telegram_chat_id=chat_id)
        suggestions = engine.run()
        engine.print_report(suggestions)
        return

    # Full monitoring run
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
