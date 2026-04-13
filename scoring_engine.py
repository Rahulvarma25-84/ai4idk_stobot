"""
BuzzFlow - Scoring Engine
Entry Score + Trap Filter + Exit Score as per the architecture spec.
"""

import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


class ScoringEngine:
    """
    Computes entry and exit scores using weighted formulas.

    Entry Score weights:
        accumulation    30%
        compression     20%
        relative_strength 15%
        position        10%
        sentiment       10%
        fundamentals    10%
        pattern          5%

    Exit Score weights:
        momentum_loss   35%
        volume_drop     20%
        trend_break     20%
        market_weakness 15%
        profit_exhaustion 10%
    """

    # ── Entry ──────────────────────────────────────────────────────────────

    def compute_entry_score(
        self,
        accumulation: float,      # 0-100: delivery volume / volume trend
        compression: float,       # 0-100: ATR compression / tight range
        relative_strength: float, # 0-100: stock vs Nifty 50
        position: float,          # 0-100: proximity to support vs resistance
        sentiment: float,         # 0-100: news sentiment score
        fundamentals: float = 50, # 0-100: basic fundamental proxy
        pattern: float = 50,      # 0-100: chart pattern score
        gap_percent: float = 0,   # % gap up/down (for trap filter)
        overextended: bool = False
    ) -> Tuple[float, str]:
        """
        Returns (entry_score 0-100, signal string).
        """
        raw = (
            0.30 * accumulation +
            0.20 * compression +
            0.15 * relative_strength +
            0.10 * position +
            0.10 * sentiment +
            0.10 * fundamentals +
            0.05 * pattern
        )

        # Trap penalty
        penalty = 0
        if abs(gap_percent) > 5:
            penalty += 20
            logger.debug(f"Trap penalty: gap={gap_percent:.1f}%")
        if overextended:
            penalty += 20
            logger.debug("Trap penalty: overextended")

        score = max(0.0, min(100.0, raw - penalty))

        if score >= 70:
            signal = "STRONG_BUY"
        elif score >= 55:
            signal = "BUY"
        elif score >= 40:
            signal = "WATCH"
        else:
            signal = "SKIP"

        return round(score, 2), signal

    # ── Exit ───────────────────────────────────────────────────────────────

    def compute_exit_score(
        self,
        momentum_loss: float,     # 0-100: RSI falling, MACD weakening
        volume_drop: float,       # 0-100: volume declining vs average
        trend_break: float,       # 0-100: price below key MAs
        market_weakness: float,   # 0-100: Nifty weakness
        profit_exhaustion: float  # 0-100: near target, candle exhaustion
    ) -> Tuple[float, str]:
        """
        Returns (exit_score 0-100, decision string).
        """
        score = (
            0.35 * momentum_loss +
            0.20 * volume_drop +
            0.20 * trend_break +
            0.15 * market_weakness +
            0.10 * profit_exhaustion
        )
        score = round(max(0.0, min(100.0, score)), 2)

        if score > 70:
            decision = "EXIT"
        elif score > 40:
            decision = "CAUTION"
        else:
            decision = "HOLD"

        return score, decision

    # ── Helpers ────────────────────────────────────────────────────────────

    def technical_to_entry_components(self, tech_data: dict, sentiment_score: float,
                                      nifty_return: float = 0.0) -> dict:
        """
        Convert raw technical indicator data into entry score components (0-100 each).
        """
        rsi = tech_data.get("rsi", 50)
        volume_ratio = tech_data.get("volume_ratio", 1.0)
        atr_ratio = tech_data.get("atr_ratio", 1.0)   # current ATR / avg ATR
        price_vs_resistance = tech_data.get("price_vs_resistance", 0.5)  # 0=at support, 1=at resistance
        stock_return = tech_data.get("stock_return_5d", 0.0)
        pattern_score = tech_data.get("pattern_score", 50)

        # Accumulation: high volume + delivery proxy
        accumulation = min(100, volume_ratio * 50)

        # Compression: low ATR = tight range = coiling
        compression = max(0, 100 - (atr_ratio * 50))

        # Relative strength vs Nifty
        rs_diff = stock_return - nifty_return
        relative_strength = min(100, max(0, 50 + rs_diff * 5))

        # Position: closer to support = higher score
        position = max(0, min(100, (1 - price_vs_resistance) * 100))

        # Gap detection
        gap_percent = tech_data.get("gap_percent", 0.0)
        overextended = rsi > 80

        return {
            "accumulation": accumulation,
            "compression": compression,
            "relative_strength": relative_strength,
            "position": position,
            "sentiment": sentiment_score,
            "pattern": pattern_score,
            "gap_percent": gap_percent,
            "overextended": overextended
        }

    def technical_to_exit_components(self, tech_data: dict, entry_price: float,
                                     current_price: float, target: float,
                                     nifty_weakness: float = 0.0) -> dict:
        """
        Convert technical data into exit score components (0-100 each).
        """
        rsi = tech_data.get("rsi", 50)
        volume_ratio = tech_data.get("volume_ratio", 1.0)
        price_vs_ma = tech_data.get("price_vs_ma20", 1.0)  # ratio: price/MA20
        macd_hist = tech_data.get("macd_histogram", 0.0)

        # Momentum loss: RSI falling below 50, MACD histogram negative
        momentum_loss = 0
        if rsi < 50:
            momentum_loss += (50 - rsi) * 2
        if macd_hist < 0:
            momentum_loss += min(40, abs(macd_hist) * 100)
        momentum_loss = min(100, momentum_loss)

        # Volume drop
        volume_drop = max(0, min(100, (1 - volume_ratio) * 100)) if volume_ratio < 1 else 0

        # Trend break: price below MA20
        trend_break = max(0, min(100, (1 - price_vs_ma) * 200)) if price_vs_ma < 1 else 0

        # Market weakness
        market_weakness = min(100, max(0, nifty_weakness * 10))

        # Profit exhaustion: near target
        if target > entry_price and current_price > entry_price:
            progress = (current_price - entry_price) / (target - entry_price)
            profit_exhaustion = min(100, progress * 100)
        else:
            profit_exhaustion = 0

        return {
            "momentum_loss": momentum_loss,
            "volume_drop": volume_drop,
            "trend_break": trend_break,
            "market_weakness": market_weakness,
            "profit_exhaustion": profit_exhaustion
        }
