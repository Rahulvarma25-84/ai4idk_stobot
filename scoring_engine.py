"""
BuzzFlow - Scoring Engine
Entry Score, Exit Score, Market Regime, Tier 1/2/3 Filters.
Production-grade with earnings blackout, volume confirmation, trend filter.
"""

import logging
from typing import Tuple, Optional
from datetime import datetime, date

import yfinance as yf
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Earnings blackout: avoid entries in results months
EARNINGS_MONTHS = {
    1:  ["TCS.NS","INFY.NS","HCLTECH.NS","WIPRO.NS","TECHM.NS"],
    2:  ["HDFCBANK.NS","ICICIBANK.NS","SBIN.NS","KOTAKBANK.NS"],
    4:  ["TCS.NS","INFY.NS","HCLTECH.NS","WIPRO.NS","TECHM.NS"],
    5:  ["HDFCBANK.NS","ICICIBANK.NS","SBIN.NS","RELIANCE.NS"],
    7:  ["TCS.NS","INFY.NS","HCLTECH.NS","WIPRO.NS","TECHM.NS"],
    8:  ["HDFCBANK.NS","ICICIBANK.NS","SBIN.NS","KOTAKBANK.NS"],
    10: ["TCS.NS","INFY.NS","HCLTECH.NS","WIPRO.NS","TECHM.NS"],
    11: ["HDFCBANK.NS","ICICIBANK.NS","SBIN.NS","RELIANCE.NS"],
}


class MarketRegime:
    """
    Nifty 50 trend check. Cached 1 hour.
    Bullish = price above 20-day MA → allow BUY signals.
    Bearish = price below 20-day MA → block/reduce signals.
    """
    _cache: Optional[dict] = None
    _cache_time: Optional[datetime] = None
    CACHE_MINUTES = 60

    @classmethod
    def get(cls) -> dict:
        now = datetime.now()
        if (cls._cache and cls._cache_time and
                (now - cls._cache_time).seconds < cls.CACHE_MINUTES * 60):
            return cls._cache
        try:
            hist = yf.Ticker("^NSEI").history(period="60d", interval="1d")
            if hist.empty or len(hist) < 20:
                raise ValueError("Insufficient Nifty data")
            close = hist["Close"].astype(float)
            price = float(close.iloc[-1])
            ma20  = float(close.rolling(20).mean().iloc[-1])
            ma50  = float(close.rolling(50, min_periods=20).mean().iloc[-1])
            ret5  = float((close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100) if len(close) >= 5 else 0.0
            cls._cache = {
                "bullish":      price > ma20,
                "nifty_price":  round(price, 2),
                "ma20":         round(ma20, 2),
                "ma50":         round(ma50, 2),
                "pct_above_ma": round((price - ma20) / ma20 * 100, 2),
                "ret5d":        round(ret5, 2),
            }
        except Exception as e:
            logger.warning(f"MarketRegime fetch failed: {e}")
            cls._cache = {"bullish": True, "nifty_price": 0, "ma20": 0, "ma50": 0, "pct_above_ma": 0, "ret5d": 0}
        cls._cache_time = now
        return cls._cache


class ScoringEngine:
    """
    Entry scoring, exit scoring, and all signal filters.

    Entry Score weights:
        accumulation      30%  (volume trend)
        compression       20%  (ATR tightening = coiling)
        relative_strength 15%  (stock vs Nifty)
        position          10%  (near support)
        sentiment         10%  (news)
        fundamentals      10%  (proxy)
        pattern            5%  (chart)

    Exit Score weights:
        momentum_loss     35%
        volume_drop       20%
        trend_break       20%
        market_weakness   15%
        profit_exhaustion 10%
    """

    def __init__(self):
        self._alerted_today: set = set()
        self._alert_date: Optional[date] = None

    def _reset_daily(self):
        today = date.today()
        if self._alert_date != today:
            self._alerted_today.clear()
            self._alert_date = today

    # ── Filters ────────────────────────────────────────────────────────────

    def already_alerted(self, symbol: str) -> bool:
        self._reset_daily()
        return symbol in self._alerted_today

    def mark_alerted(self, symbol: str):
        self._reset_daily()
        self._alerted_today.add(symbol)

    def apply_filters(self, symbol: str, signal: str, tech: dict,
                      cap_tier: str = "large", skip_dedup: bool = False) -> Tuple[str, list]:
        """
        Apply Tier 1/2/3 filters with cap-tier aware thresholds.
        cap_tier: "large" | "mid" | "small" | "micro"
        Returns (final_signal, [reasons]) — if filtered, signal = 'FILTERED'.
        """
        if signal in ("SKIP", "WATCH"):
            return signal, []

        reasons = []
        tier = cap_tier.lower() if cap_tier else "large"

        # ── Cap-tier thresholds ────────────────────────────────────────
        # Small/micro caps need stricter filters — more volatile, less liquid,
        # more prone to manipulation and sharp reversals.
        if tier in ("small", "micro"):
            vol_min       = 1.5    # needs stronger volume confirmation
            rsi_max       = 70     # overbought threshold lower (spikes reverse fast)
            ma50_floor    = 0.97   # must be closer to MA50
            regime_strict = True   # block ALL small/micro in bearish market
        elif tier == "mid":
            vol_min       = 1.3
            rsi_max       = 73
            ma50_floor    = 0.98
            regime_strict = False
        else:  # large
            vol_min       = 1.2
            rsi_max       = 75
            ma50_floor    = 0.98
            regime_strict = False

        # Tier 1a: Market regime
        regime = MarketRegime.get()
        if not regime["bullish"]:
            if regime_strict:
                # Small/micro: hard block in any bearish condition
                reasons.append(f"Market bearish — small/micro cap blocked ({regime['pct_above_ma']:.1f}% vs MA20)")
            else:
                reasons.append(f"Market bearish ({regime['pct_above_ma']:.1f}% below MA20)")

        # Tier 1b: Volume confirmation
        if tech.get("volume_ratio", 0) < vol_min:
            reasons.append(f"Low volume ({tech.get('volume_ratio',0):.2f}× avg, need {vol_min}×)")

        # Tier 1c: Price above MA50
        price, ma50 = tech.get("current_price", 0), tech.get("ma50", 0)
        if ma50 > 0 and price < ma50 * ma50_floor:
            reasons.append(f"Price below MA50 (₹{price:.0f} < ₹{ma50:.0f})")

        # Tier 1d: RSI not overbought
        rsi = tech.get("rsi", 50)
        if rsi > rsi_max:
            reasons.append(f"RSI overbought ({rsi:.0f} > {rsi_max})")

        # Tier 1e: Small/micro — additional liquidity check (ATR not exploding)
        if tier in ("small", "micro"):
            atr_ratio = tech.get("atr_ratio", 1.0)
            if atr_ratio > 1.8:
                reasons.append(f"ATR spike ({atr_ratio:.2f}×) — erratic price action")

        # Tier 2: Earnings blackout
        if symbol in EARNINGS_MONTHS.get(date.today().month, []):
            reasons.append("Earnings blackout period")

        # Tier 3: Duplicate suppression
        if not skip_dedup and self.already_alerted(symbol):
            reasons.append("Already alerted today")

        if reasons:
            return "FILTERED", reasons
        return signal, []

    # ── Cap-tier risk params ───────────────────────────────────────────────

    @staticmethod
    def cap_tier_params(cap_tier: str) -> dict:
        """
        Returns adjusted risk parameters per cap tier.
        Small/micro caps need wider stops, better R:R, higher delivery threshold.
        """
        tier = (cap_tier or "large").lower()
        if tier == "micro":
            return {
                "atr_sl_mult":      2.5,   # wider stop (more volatile)
                "atr_target_mult":  4.0,   # bigger target needed to justify risk
                "min_rr":           1.8,   # higher R:R requirement
                "max_sl_pct":       0.88,  # max 12% loss floor
                "min_target_pct":   1.08,  # min 8% upside
                "delivery_min":     55,    # higher delivery threshold (manipulation risk)
                "sentiment_weight": 0.15,  # news matters more for small/micro
                "risk_cap_pct":     0.5,   # max 0.5% capital risk regardless of score
            }
        elif tier == "small":
            return {
                "atr_sl_mult":      2.0,
                "atr_target_mult":  3.5,
                "min_rr":           1.5,
                "max_sl_pct":       0.90,  # max 10% loss floor
                "min_target_pct":   1.07,
                "delivery_min":     50,
                "sentiment_weight": 0.12,
                "risk_cap_pct":     0.75,
            }
        elif tier == "mid":
            return {
                "atr_sl_mult":      1.7,
                "atr_target_mult":  3.0,
                "min_rr":           1.3,
                "max_sl_pct":       0.91,
                "min_target_pct":   1.06,
                "delivery_min":     45,
                "sentiment_weight": 0.10,
                "risk_cap_pct":     1.0,
            }
        else:  # large
            return {
                "atr_sl_mult":      1.5,
                "atr_target_mult":  2.5,
                "min_rr":           1.2,
                "max_sl_pct":       0.92,
                "min_target_pct":   1.05,
                "delivery_min":     40,
                "sentiment_weight": 0.10,
                "risk_cap_pct":     1.5,
            }

    # ── Entry Score ────────────────────────────────────────────────────────

    def compute_entry_score(
        self,
        accumulation: float,
        compression: float,
        relative_strength: float,
        position: float,
        sentiment: float,
        fundamentals: float = 50,
        pattern: float = 50,
        gap_percent: float = 0,
        overextended: bool = False,
    ) -> Tuple[float, str]:
        """Returns (score 0-100, signal)."""
        raw = (
            0.30 * accumulation +
            0.20 * compression +
            0.15 * relative_strength +
            0.10 * position +
            0.10 * sentiment +
            0.10 * fundamentals +
            0.05 * pattern
        )
        penalty = 0
        if abs(gap_percent) > 5:
            penalty += 20
        if overextended:
            penalty += 20

        score = round(max(0.0, min(100.0, raw - penalty)), 2)

        if score >= 70:   signal = "STRONG_BUY"
        elif score >= 65: signal = "BUY"
        elif score >= 55: signal = "WATCH"
        else:             signal = "SKIP"

        return score, signal

    # ── Exit Score ─────────────────────────────────────────────────────────

    def compute_exit_score(
        self,
        momentum_loss: float,
        volume_drop: float,
        trend_break: float,
        market_weakness: float,
        profit_exhaustion: float,
    ) -> Tuple[float, str]:
        """Returns (score 0-100, decision)."""
        score = round(max(0.0, min(100.0,
            0.35 * momentum_loss +
            0.20 * volume_drop +
            0.20 * trend_break +
            0.15 * market_weakness +
            0.10 * profit_exhaustion
        )), 2)

        if score > 70:   decision = "EXIT"
        elif score > 40: decision = "CAUTION"
        else:            decision = "HOLD"

        return score, decision

    # ── Component builders ─────────────────────────────────────────────────

    def technical_to_entry_components(self, tech: dict, sentiment: float,
                                       nifty_return: float = 0.0) -> dict:
        rsi           = tech.get("rsi", 50)
        vol_ratio     = tech.get("volume_ratio", 1.0)
        atr_ratio     = tech.get("atr_ratio", 1.0)
        price_vs_res  = tech.get("price_vs_resistance", 0.5)
        stock_ret     = tech.get("stock_return_5d", 0.0)
        pattern       = tech.get("pattern_score", 50)

        accumulation      = min(100, vol_ratio * 50)
        compression       = max(0, 100 - atr_ratio * 50)
        rs_diff           = stock_ret - nifty_return
        relative_strength = min(100, max(0, 50 + rs_diff * 5))
        position          = max(0, min(100, (1 - price_vs_res) * 100))

        return {
            "accumulation":      accumulation,
            "compression":       compression,
            "relative_strength": relative_strength,
            "position":          position,
            "sentiment":         sentiment,
            "pattern":           pattern,
            "gap_percent":       tech.get("gap_percent", 0.0),
            "overextended":      rsi > 80,
        }

    def technical_to_exit_components(self, tech: dict, entry_price: float,
                                      current_price: float, target: float,
                                      nifty_weakness: float = 0.0) -> dict:
        rsi      = tech.get("rsi", 50)
        vol_r    = tech.get("volume_ratio", 1.0)
        pvm      = tech.get("price_vs_ma20", 1.0)
        macd_h   = tech.get("macd_histogram", 0.0)

        momentum_loss = 0
        if rsi < 50:
            momentum_loss += (50 - rsi) * 2
        if macd_h < 0:
            momentum_loss += min(40, abs(macd_h) * 100)
        momentum_loss = min(100, momentum_loss)

        volume_drop  = max(0, min(100, (1 - vol_r) * 100)) if vol_r < 1 else 0
        trend_break  = max(0, min(100, (1 - pvm) * 200)) if pvm < 1 else 0
        mkt_weakness = min(100, max(0, nifty_weakness * 10))

        if target > entry_price and current_price > entry_price:
            progress = (current_price - entry_price) / (target - entry_price)
            profit_exhaustion = min(100, progress * 100)
        else:
            profit_exhaustion = 0

        return {
            "momentum_loss":    momentum_loss,
            "volume_drop":      volume_drop,
            "trend_break":      trend_break,
            "market_weakness":  mkt_weakness,
            "profit_exhaustion": profit_exhaustion,
        }

    def compute_momentum_score(self, tech: dict) -> float:
        """0-100 momentum score for opportunity_score calculation."""
        rsi      = tech.get("rsi", 50)
        vol_r    = tech.get("volume_ratio", 1.0)
        macd_h   = tech.get("macd_histogram", 0.0)
        pvm      = tech.get("price_vs_ma20", 1.0)

        rsi_score  = max(0, min(100, (rsi - 40) / 30 * 100)) if rsi < 70 else max(0, (100 - rsi) * 5)
        vol_score  = min(100, vol_r * 50)
        macd_score = 70 if macd_h > 0 else 30
        trend_score = 80 if pvm > 1 else 30

        return round(rsi_score * 0.3 + vol_score * 0.3 + macd_score * 0.2 + trend_score * 0.2, 2)
