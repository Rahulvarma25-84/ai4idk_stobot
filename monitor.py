#!/usr/bin/env python3
"""
BuzzFlow - Monitoring Runner
Run this 2-3x per day to check active watchlist positions.
Designed for GitHub Actions cron scheduling.
"""

import os
import logging
import argparse
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("buzzflow.log"),
        logging.StreamHandler()
    ]
)

from monitoring_engine import MonitoringEngine
from watchlist_engine import WatchlistEngine


def main():
    parser = argparse.ArgumentParser(description="BuzzFlow - Position Monitor")
    parser.add_argument("--watchlist", action="store_true", help="Print watchlist and exit")
    args = parser.parse_args()

    if args.watchlist:
        wl = WatchlistEngine()
        wl.print_watchlist()
        return

    engine = MonitoringEngine(
        telegram_token=os.getenv("TELEGRAM_TOKEN"),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID")
    )

    print("\n🔍 Running position monitoring...\n")
    results = engine.run()
    engine.print_report(results)


if __name__ == "__main__":
    main()
