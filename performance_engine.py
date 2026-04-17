"""
BuzzFlow - Performance Engine
Tracks win rate, avg PnL, drawdown, holding time, score vs performance.
"""

import logging
from typing import Dict, List
from datetime import datetime

from database import get_trade_history, get_watchlist

logger = logging.getLogger(__name__)


def compute_performance() -> Dict:
    trades = get_trade_history()
    closed = [t for t in trades if t.get("pnl_percent") is not None]

    if not closed:
        return {
            "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
            "win_rate": 0, "avg_pnl": 0, "total_pnl": 0,
            "avg_holding_days": 0, "max_drawdown": 0,
            "profit_factor": 0, "best_trade": None, "worst_trade": None,
            "score_vs_pnl": [], "trades": []
        }

    wins   = [t for t in closed if t["pnl_percent"] > 0]
    losses = [t for t in closed if t["pnl_percent"] <= 0]
    pnls   = [t["pnl_percent"] for t in closed]

    # Profit factor
    gross_profit = sum(t["pnl_percent"] for t in wins) if wins else 0
    gross_loss   = abs(sum(t["pnl_percent"] for t in losses)) if losses else 0.001
    profit_factor = round(gross_profit / gross_loss, 2)

    # Max drawdown (peak-to-trough on cumulative PnL)
    cum = 0
    peak = 0
    max_dd = 0
    for p in pnls:
        cum += p
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    # Avg holding days
    holding_days = [t.get("holding_days", 0) or 0 for t in closed]
    avg_holding  = round(sum(holding_days) / max(len(holding_days), 1), 1)

    # Score vs PnL correlation data
    score_vs_pnl = [
        {"entry_score": t.get("entry_score"), "pnl": t["pnl_percent"], "symbol": t["symbol"]}
        for t in closed if t.get("entry_score")
    ]

    # Open PnL from active watchlist
    active = [w for w in get_watchlist() if w["status"] not in ("CLOSED","EXIT")]

    return {
        "total_trades":    len(closed),
        "winning_trades":  len(wins),
        "losing_trades":   len(losses),
        "win_rate":        round(len(wins) / len(closed) * 100, 1),
        "avg_pnl":         round(sum(pnls) / len(pnls), 2),
        "total_pnl":       round(sum(pnls), 2),
        "avg_holding_days": avg_holding,
        "max_drawdown":    round(max_dd, 2),
        "profit_factor":   profit_factor,
        "best_trade":      max(closed, key=lambda t: t["pnl_percent"]),
        "worst_trade":     min(closed, key=lambda t: t["pnl_percent"]),
        "score_vs_pnl":    score_vs_pnl,
        "active_positions": len(active),
        "trades":          closed,
    }
