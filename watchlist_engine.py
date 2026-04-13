"""
BuzzFlow - Watchlist Engine
Manages the user's tracked stocks with entry, SL, target, and status.
"""

import logging
from typing import List, Dict
from datetime import datetime

from database import (
    init_db, add_to_watchlist, get_watchlist,
    update_watchlist_status, remove_from_watchlist,
    log_trade
)

logger = logging.getLogger(__name__)


class WatchlistEngine:
    """
    Manages the watchlist: add, update, remove, display.
    All data persisted in SQLite via database.py.
    """

    def __init__(self):
        init_db()

    def add(self, symbol: str, entry_price: float, stop_loss: float,
            target: float, entry_score: float = None,
            confidence: str = None, company_name: str = "",
            notes: str = "") -> int:
        """Add a stock to the watchlist."""
        rr = round((target - entry_price) / max(entry_price - stop_loss, 0.01), 2)
        full_notes = f"R:R={rr} | {notes}".strip(" |")
        row_id = add_to_watchlist(
            symbol=symbol,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            entry_score=entry_score,
            confidence=confidence,
            company_name=company_name,
            notes=full_notes
        )
        return row_id

    def get_active(self) -> List[Dict]:
        """Return all WATCH / BUY / CAUTION stocks."""
        all_items = get_watchlist()
        return [w for w in all_items if w["status"] not in ("CLOSED", "EXIT")]

    def get_all(self) -> List[Dict]:
        return get_watchlist()

    def update_status(self, symbol: str, status: str, notes: str = ""):
        """Update status: WATCH | BUY | CAUTION | EXIT | CLOSED"""
        update_watchlist_status(symbol, status, notes)

    def close_position(self, symbol: str, exit_price: float,
                       exit_score: float = None, exit_reason: str = "",
                       entry_price: float = None):
        """Mark position as closed and log the trade."""
        pnl = None
        if entry_price and entry_price > 0:
            pnl = round(((exit_price - entry_price) / entry_price) * 100, 2)

        log_trade(
            symbol=symbol,
            action="EXIT",
            price=exit_price,
            exit_score=exit_score,
            exit_reason=exit_reason,
            pnl_percent=pnl,
            notes=f"PnL: {pnl}%" if pnl is not None else ""
        )
        remove_from_watchlist(symbol)
        logger.info(f"Closed {symbol} @ {exit_price} | PnL: {pnl}%")

    def print_watchlist(self):
        """Pretty-print the active watchlist."""
        items = self.get_active()
        if not items:
            print("\n📋 Watchlist is empty.\n")
            return

        print("\n" + "=" * 75)
        print(f"{'📋 WATCHLIST':^75}")
        print("=" * 75)
        print(f"{'Symbol':<12} {'Entry':>8} {'SL':>8} {'Target':>8} {'Score':>7} {'Status':<10} {'Added'}")
        print("-" * 75)
        for w in items:
            added = w["added_at"][:10] if w["added_at"] else "-"
            score = f"{w['entry_score']:.1f}" if w["entry_score"] else "-"
            print(f"{w['symbol']:<12} {w['entry_price']:>8.2f} {w['stop_loss']:>8.2f} "
                  f"{w['target']:>8.2f} {score:>7} {w['status']:<10} {added}")
        print("=" * 75 + "\n")
