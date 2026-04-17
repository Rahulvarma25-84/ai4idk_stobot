"""
BuzzFlow - Trade State Classification
Classifies each active position as STRONG / NEUTRAL / WEAK.
Drives the replacement engine and alert decisions.
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass
class TradeStateResult:
    state: str          # STRONG / NEUTRAL / WEAK
    exit_score: float   # 0-100
    opportunity_score: float  # 0-100
    suggested_action: str
    reason: str


def classify_trade_state(
    exit_score: float,
    opportunity_score: float,
    current_price: float,
    entry_price: float,
    stop_loss: float,
    pnl_pct: float,
) -> TradeStateResult:
    """
    Classify a trade into STRONG / NEUTRAL / WEAK.

    STRONG:  Exit score < 30, price above entry, trend intact
    NEUTRAL: Exit score 30-50
    WEAK:    Exit score > 50 OR price nearing stop loss (within 2%)

    Returns TradeStateResult with state, action, and reason.
    """
    sl_proximity = (current_price - stop_loss) / max(stop_loss, 0.01) * 100
    near_sl = sl_proximity < 2.0  # within 2% of stop loss

    if exit_score < 30 and current_price > entry_price and not near_sl:
        state = "STRONG"
        action = "HOLD"
        reason = "Trend intact. No action needed."

    elif exit_score > 50 or near_sl:
        state = "WEAK"
        if near_sl:
            action = "EXIT"
            reason = f"Price within 2% of stop loss (₹{stop_loss:.2f}). Exit to protect capital."
        elif exit_score > 70:
            action = "EXIT"
            reason = f"Exit score {exit_score:.0f}/100. Momentum fading significantly."
        else:
            action = "CAUTION"
            reason = f"Exit score {exit_score:.0f}/100. Monitor closely, consider tightening SL."

    else:
        state = "NEUTRAL"
        action = "MONITOR"
        reason = f"Exit score {exit_score:.0f}/100. No immediate action required."

    return TradeStateResult(
        state=state,
        exit_score=exit_score,
        opportunity_score=opportunity_score,
        suggested_action=action,
        reason=reason,
    )


def compute_opportunity_score(
    entry_score: float,
    exit_score: float,
    momentum_score: float,
) -> float:
    """
    opportunity_score = 0.5 × entry_score + 0.3 × (100 - exit_score) + 0.2 × momentum_score
    Higher = better opportunity to be in this trade.
    """
    score = (
        0.5 * entry_score +
        0.3 * (100 - exit_score) +
        0.2 * momentum_score
    )
    return round(max(0.0, min(100.0, score)), 2)


def compute_trailing_stop(
    entry_price: float,
    current_price: float,
    original_sl: float,
    recent_low: float,
) -> float:
    """
    Trailing stop logic:
    - After +3% gain → move SL to entry (breakeven)
    - After +5% gain → trail below recent low (with 1% buffer)
    - Otherwise → keep original SL
    """
    pnl_pct = (current_price - entry_price) / entry_price * 100

    if pnl_pct >= 5.0:
        # Trail below recent low with 1% buffer
        trailing = recent_low * 0.99
        return max(trailing, original_sl)  # never go below original SL
    elif pnl_pct >= 3.0:
        # Move to breakeven
        return max(entry_price, original_sl)
    else:
        return original_sl
