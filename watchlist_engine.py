"""
BuzzFlow - Watchlist Engine
Full trade lifecycle: add, monitor, trail, close, log.
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime

from database import (
    init_db, add_to_watchlist, get_watchlist,
    update_watchlist_status, update_watchlist_scores,
    remove_from_watchlist, log_trade
)

logger = logging.getLogger(__name__)


class WatchlistEngine:

    def __init__(self):
        init_db()

    def add(self, symbol: str, entry_price: float, stop_loss: float,
            target: float, entry_score: float = 0, confidence: str = "medium",
            company_name: str = "", entry_zone_low: float = None,
            entry_zone_high: float = None, breakout_level: float = None,
            pullback_level: float = None, risk_capital_pct: float = 1.0,
            qty: int = 0, notes: str = "") -> int:
        rr = round((target - entry_price) / max(entry_price - stop_loss, 0.01), 2)
        return add_to_watchlist(
            symbol=symbol, entry_price=entry_price, stop_loss=stop_loss,
            target=target, entry_score=entry_score, confidence=confidence,
            company_name=company_name, entry_zone_low=entry_zone_low,
            entry_zone_high=entry_zone_high, breakout_level=breakout_level,
            pullback_level=pullback_level, risk_capital_pct=risk_capital_pct,
            qty=qty, notes=f"R:R={rr} | {notes}".strip(" |")
        )

    def get_active(self) -> List[Dict]:
        return [w for w in get_watchlist() if w["status"] not in ("CLOSED", "EXIT")]

    def get_all(self) -> List[Dict]:
        return get_watchlist()

    def update_scores(self, symbol: str, exit_score: float,
                      opportunity_score: float, trade_state: str,
                      suggested_action: str, trailing_sl: float = None,
                      notes: str = ""):
        update_watchlist_scores(symbol, exit_score, opportunity_score,
                                trade_state, suggested_action, trailing_sl, notes)

    def update_status(self, symbol: str, status: str, notes: str = ""):
        update_watchlist_status(symbol, status, notes)

    def close_position(self, symbol: str, exit_price: float,
                       exit_score: float = None, exit_reason: str = "",
                       entry_price: float = None, qty: int = 0,
                       entry_score: float = None):
        pnl_pct = None
        pnl_abs = None
        holding_days = 0

        items = get_watchlist()
        match = next((w for w in items if w["symbol"] == symbol.upper()), None)
        if match:
            if entry_price is None:
                entry_price = match["entry_price"]
            if qty == 0:
                qty = match.get("qty", 0)
            if entry_score is None:
                entry_score = match.get("entry_score")
            if match.get("added_at"):
                try:
                    added = datetime.fromisoformat(match["added_at"])
                    holding_days = (datetime.now() - added).days
                except Exception:
                    pass

        if entry_price and entry_price > 0:
            pnl_pct = round(((exit_price - entry_price) / entry_price) * 100, 2)
            pnl_abs = round((exit_price - entry_price) * max(qty, 1), 2)

        log_trade(
            symbol=symbol, action="EXIT", price=exit_price, qty=qty,
            exit_score=exit_score, exit_reason=exit_reason,
            pnl_percent=pnl_pct, pnl_abs=pnl_abs,
            holding_days=holding_days, entry_score=entry_score
        )
        remove_from_watchlist(symbol)
        logger.info(f"Closed {symbol} @ ₹{exit_price} | PnL: {pnl_pct}% | Reason: {exit_reason}")

    def print_watchlist(self):
        items = self.get_active()
        if not items:
            print("\n  Watchlist is empty.\n")
            return
        print(f"\n{'='*100}")
        print(f"  {'WATCHLIST':^98}")
        print(f"{'='*100}")
        print(f"  {'Symbol':<14} {'Entry':>8} {'SL':>8} {'Target':>8} {'Score':>6} {'Exit':>6} {'Opp':>6} {'State':<10} {'Action':<12} {'Status'}")
        print(f"  {'-'*96}")
        for w in items:
            es = f"{w['entry_score']:.0f}" if w.get('entry_score') else "-"
            xs = f"{w['exit_score']:.0f}" if w.get('exit_score') else "-"
            os_ = f"{w['opportunity_score']:.0f}" if w.get('opportunity_score') else "-"
            print(f"  {w['symbol']:<14} {w['entry_price']:>8.2f} {w['stop_loss']:>8.2f} "
                  f"{w['target']:>8.2f} {es:>6} {xs:>6} {os_:>6} "
                  f"{w.get('trade_state','?'):<10} {w.get('suggested_action','?'):<12} {w['status']}")
        print(f"{'='*100}\n")
