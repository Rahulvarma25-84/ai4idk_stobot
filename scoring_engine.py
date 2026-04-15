"""
BuzzFlow - Scoring Engine
Entry Score + Trap Filter + Exit Score + Market Regime + Filters
"""

import logging
from typing import Tuple, Optional
import yfinance as yf
import numpy as np
import pandas as pd
from datetime import datetime, date

logger = logging.getLogger(__name__)

# ── Earnings blackout calendar (symbol → list of result months MM) ────────
# Stocks to avoid 5 days before/after results
# Q4 results: April-May | Q1: July-Aug | Q2: Oct-Nov | Q3: Jan-Feb
EARNINGS_MONTHS = {
    1: ["TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS"],   # Jan
    2: ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS"],     # Feb
    4: ["TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS"],   # Apr
    5: ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "RELIANCE.NS"],      # May
    7: ["TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS"],   # Jul
    8: ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS"],     # Aug
    10: ["TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS"],  # Oct
    11: ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "RELIANCE.NS"],     # Nov
}


class MarketRegime:
    """
    Tier 1: Market regime check.
    If Nifty is below its 20-day MA → bearish regime → suppress BUY signals.
    Cached for 1 hour to avoid repeated API calls.
    """
    _cache: Optional[dict] = None
    _cache_time: Optional[datetime] = None
    CACHE_MINUTES = 60

    @classmethod
    def get(cls) -> dict:
        now = datetime.now()
        if (cls._cache is not None and cls._cache_time is not None and
                (now - cls._cache_time).seconds < cls.CACHE_MINUTES * 60):
            return cls._cache

        try:
            hist = yf.Ticker("^NSEI").history(period="60d", interval="1d")
            if hist.empty or len(hist) < 20:
                cls._cache = {"bullish": True, "nifty_price": 0, "ma20": 0, "pct_above_ma": 0}
                cls._cache_time = now
                return cls._cache

            close = hist["Close"].astype(float)
            ma20  = float(close.rolling(20).mean().iloc[-1])
            ma50  = float(close.rolling(50, min_periods=20).mean().iloc[-1])
            price = float(close.iloc[-1])
            ret5  = float((close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100)

            bullish = price > ma20  # Tier 1: price above 20-day MA

            cls._cache = {
                "bullish":       bullish,
                "nifty_price":   round(price, 2),
                "ma20":          round(ma20, 2),
                "ma50":          round(ma50, 2),
                "pct_above_ma":  round((price - ma20) / ma20 * 100, 2),
                "ret5d":         round(ret5, 2),
            }
            cls._cache_time = now
            logger.info(f"Market regime: {'BULLISH' if bullish else 'BEARISH'} | "
                        f"Nifty {price:.0f} vs MA20 {ma20:.0f}")
        except Exception as e:
            logger.warning(f"Market regime check failed: {e}")
            cls._cache = {"bullish": True, "nifty_price": 0, "ma20": 0, "pct_above_ma": 0}
            cls._cache_time = now

        return cls._cache


class ScoringEngine:
    """
    Production-grade scoring with all tiers implemented.

    Tier 1 — Signal quality filters:
      - Volume confirmation  (>1.2× 20-day avg)
      - Trend filter         (price above 50-day MA)
      - Market regime        (Nifty above 20-day MA)

    Tier 2 — Better data:
      - Sector momentum      (sector index trend)
      - Earnings blackout    (avoid 5 days before/after results)

    Tier 3 — Reliability:
      - Duplicate suppression (already alerted today → skip)
      - Performance tracking  (logged in trades_log)

    Entry Score weights:
        accumulation      30%
        compression       20%
        relative_strength 15%
        position          10%
        sentiment         10%
        fundamentals      10%
        pattern            5%

    Exit Score weights:
        momentum_loss     35%
        volume_drop       20%
        trend_break       20%
        market_weakness   15%
        profit_exhaustion 10%
    """

    def __init__(self):
        self._alerted_today: set = set()   # Tier 3: duplicate suppression
        self._alert_date: Optional[date] = None

    def _reset_daily_alerts(self):
        today = date.today()
        if self._alert_date != today:
            self._alerted_today.clear()
            self._alert_date = today

    # ── Tier 1: Volume confirmation ────────────────────────────────────────
    def _volume_confirmed(self, volume_ratio: float) -> bool:
        """Volume must be at least 1.2× the 20-day average."""
        return volume_ratio >= 1.2

    # ── Tier 1: Trend filter ───────────────────────────────────────────────
    def _above_ma50(self, price: float, ma50: float) -> bool:
        """Price must be above 50-day MA to take a BUY."""
        return price >= ma50

    # ── Tier 2: Earnings blackout ──────────────────────────────────────────
    def _in_earnings_blackout(self, symbol: str) -> bool:
        """Avoid entering within results season for known symbols."""
        month = date.today().month
        return symbol in EARNINGS_MONTHS.get(month, [])

    # ── Tier 3: Duplicate suppression ─────────────────────────────────────
    def already_alerted(self, symbol: str) -> bool:
        self._reset_daily_alerts()
        return symbol in self._alerted_today

    def mark_alerted(self, symbol: str):
        self._reset_daily_alerts()
        self._alerted_today.add(symbol)

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
        """Returns (entry_score 0-100, signal)."""
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
        elif score >= 55: signal = "BUY"
        elif score >= 40: signal = "WATCH"
        else:             signal = "SKIP"

        return score, signal

    def apply_filters(self, symbol: str, signal: str, tech_data: dict) -> Tuple[str, list]:
        """
        Apply all Tier 1/2/3 filters to a signal.
        Returns (final_signal, list_of_reasons_if_filtered).
        """
        if signal in ("SKIP", "WATCH"):
            return signal, []

        reasons = []

        # Tier 1a: Market regime
        regime = MarketRegime.get()
        if not regime["bullish"]:
            reasons.append(f"Market bearish (Nifty {regime['pct_above_ma']:.1f}% below MA20)")

        # Tier 1b: Volume confirmation
        vol_ratio = tech_data.get("volume_ratio", 1.0)
        if not self._volume_confirmed(vol_ratio):
            reasons.append(f"Low volume ({vol_ratio:.2f}× avg, need 1.2×)")

        # Tier 1c: Trend filter — price above MA50
        price  = tech_data.get("current_price", 0)
        ma50   = tech_data.get("ma50", 0)
        if ma50 > 0 and not self._above_ma50(price, ma50):
            reasons.append(f"Price below MA50 (₹{price:.0f} < ₹{ma50:.0f})")

        # Tier 2a: Earnings blackout
        if self._in_earnings_blackout(symbol):
            reasons.append("Earnings blackout period")

        # Tier 3: Duplicate suppression
        if self.already_alerted(symbol):
            reasons.append("Already alerted today")

        if reasons:
            return "FILTERED", reasons

        return signal, []

    # ── Exit Score ─────────────────────────────────────────────────────────
    def compute_exit_score(
        self,
        momentum_loss: float,
        volume_drop: float,
        trend_break: float,
        market_weakness: float,
        profit_exhaustion: float,
    ) -> Tuple[float, str]:
        """Returns (exit_score 0-100, decision)."""
        score = (
            0.35 * momentum_loss +
            0.20 * volume_drop +
            0.20 * trend_break +
            0.15 * market_weakness +
            0.10 * profit_exhaustion
        )
        score = round(max(0.0, min(100.0, score)), 2)

        if score > 70:   decision = "EXIT"
        elif score > 40: decision = "CAUTION"
        else:            decision = "HOLD"

        return score, decision

    # ── Component builders ─────────────────────────────────────────────────
    def technical_to_entry_components(self, tech_data: dict,
                                      sentiment_score: float,
                                      nifty_return: float = 0.0) -> dict:
        rsi              = tech_data.get("rsi", 50)
        volume_ratio     = tech_data.get("volume_ratio", 1.0)
        atr_ratio        = tech_data.get("atr_ratio", 1.0)
        price_vs_res     = tech_data.get("price_vs_resistance", 0.5)
        stock_return     = tech_data.get("stock_return_5d", 0.0)
        pattern_score    = tech_data.get("pattern_score", 50)

        accumulation     = min(100, volume_ratio * 50)
        compression      = max(0, 100 - (atr_ratio * 50))
        rs_diff          = stock_return - nifty_return
        relative_strength = min(100, max(0, 50 + rs_diff * 5))
        position         = max(0, min(100, (1 - price_vs_res) * 100))
        gap_percent      = tech_data.get("gap_percent", 0.0)
        overextended     = rsi > 80

        return {
            "accumulation":      accumulation,
            "compression":       compression,
            "relative_strength": relative_strength,
            "position":          position,
            "sentiment":         sentiment_score,
            "pattern":           pattern_score,
            "gap_percent":       gap_percent,
            "overextended":      overextended,
        }

    def technical_to_exit_components(self, tech_data: dict,
                                     entry_price: float,
                                     current_price: float,
                                     target: float,
                                     nifty_weakness: float = 0.0) -> dict:
        rsi          = tech_data.get("rsi", 50)
        volume_ratio = tech_data.get("volume_ratio", 1.0)
        price_vs_ma  = tech_data.get("price_vs_ma20", 1.0)
        macd_hist    = tech_data.get("macd_histogram", 0.0)

        momentum_loss = 0
        if rsi < 50:
            momentum_loss += (50 - rsi) * 2
        if macd_hist < 0:
            momentum_loss += min(40, abs(macd_hist) * 100)
        momentum_loss = min(100, momentum_loss)

        volume_drop  = max(0, min(100, (1 - volume_ratio) * 100)) if volume_ratio < 1 else 0
        trend_break  = max(0, min(100, (1 - price_vs_ma) * 200)) if price_vs_ma < 1 else 0
        market_weakness = min(100, max(0, nifty_weakness * 10))

        if target > entry_price and current_price > entry_price:
            progress = (current_price - entry_price) / (target - entry_price)
            profit_exhaustion = min(100, progress * 100)
        else:
            profit_exhaustion = 0

        return {
            "momentum_loss":    momentum_loss,
            "volume_drop":      volume_drop,
            "trend_break":      trend_break,
            "market_weakness":  market_weakness,
            "profit_exhaustion": profit_exhaustion,
        }
