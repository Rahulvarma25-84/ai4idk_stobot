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

    def apply_filters(self, symbol: str, signal: str, tech: dict) -> Tuple[str, list]:
        """
        Apply Tier 1/2/3 filters.
        Returns (final_signal, [reasons]) — if filtered, signal = 'FILTERED'.
        """
        if signal in ("SKIP", "WATCH"):
            return signal, []

        reasons = []

        # Tier 1a: Market regime
        regime = MarketRegime.get()
        if not regime["bullish"]:
            reasons.append(f"Market bearish ({regime['pct_above_ma']:.1f}% below MA20)")

        # Tier 1b: Volume confirmation (≥1.2×)
        if tech.get("volume_ratio", 0) < 1.2:
            reasons.append(f"Low volume ({tech.get('volume_ratio',0):.2f}× avg)")

        # Tier 1c: Price above MA50
        price, ma50 = tech.get("current_price", 0), tech.get("ma50", 0)
        if ma50 > 0 and price < ma50 * 0.98:
            reasons.append(f"Price below MA50 (₹{price:.0f} < ₹{ma50:.0f})")

        # Tier 1d: RSI not overbought
        rsi = tech.get("rsi", 50)
        if rsi > 75:
            reasons.append(f"RSI overbought ({rsi:.0f})")

        # Tier 2: Earnings blackout
        if symbol in EARNINGS_MONTHS.get(date.today().month, []):
            reasons.append("Earnings blackout period")

        # Tier 3: Duplicate suppression
        if self.already_alerted(symbol):
            reasons.append("Already alerted today")

        if reasons:
            return "FILTERED", reasons
        return signal, []

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
