"""
BuzzFlow - Market Regime Engine
Multi-signal market sentiment analysis with bearish prediction.

Signals used (weighted composite):
  1. Nifty trend         (20% ) — price vs MA20, MA50
  2. Momentum divergence (20% ) — RSI + MACD on Nifty itself
  3. Breadth             (20% ) — % of Nifty500 stocks above MA50 (sampled)
  4. Sector rotation     (15% ) — defensive vs cyclical relative strength
  5. Volatility proxy    (15% ) — Nifty ATR expansion (fear gauge)
  6. Small-cap stress    (10% ) — Nifty Smallcap 100 vs Nifty divergence

Regime levels:
  STRONGLY_BULLISH  composite >= 70
  BULLISH           composite >= 55
  NEUTRAL           composite >= 40
  CAUTION           composite >= 25
  BEARISH           composite <  25
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ── Tickers ────────────────────────────────────────────────────────────────
NIFTY          = "^NSEI"
NIFTY_SMALLCAP = "^CNXSC"          # Nifty Smallcap 100
NIFTY_BANK     = "^NSEBANK"

# Defensive sectors (hold up in bear markets)
DEFENSIVES = ["HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS",
              "SUNPHARMA.NS", "CIPLA.NS", "DRREDDY.NS", "POWERGRID.NS", "NTPC.NS"]

# Cyclicals (lead bull markets, fall first in bear)
CYCLICALS  = ["TATAMOTORS.NS", "TATASTEEL.NS", "JSWSTEEL.NS", "ADANIENT.NS",
              "BAJFINANCE.NS", "INDUSINDBK.NS", "AXISBANK.NS", "HINDALCO.NS"]

# Breadth sample — representative cross-section of Nifty500
BREADTH_SAMPLE = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",
    "SBIN.NS","BHARTIARTL.NS","KOTAKBANK.NS","AXISBANK.NS","MARUTI.NS",
    "HCLTECH.NS","SUNPHARMA.NS","TATAMOTORS.NS","WIPRO.NS","TITAN.NS",
    "BAJFINANCE.NS","NTPC.NS","POWERGRID.NS","ONGC.NS","COALINDIA.NS",
    "ADANIENT.NS","JSWSTEEL.NS","TECHM.NS","HINDALCO.NS","GRASIM.NS",
    "CIPLA.NS","DIVISLAB.NS","BRITANNIA.NS","EICHERMOT.NS","DRREDDY.NS",
    "HEROMOTOCO.NS","BPCL.NS","TATASTEEL.NS","LT.NS","APOLLOHOSP.NS",
    "TRENT.NS","ZOMATO.NS","DIXON.NS","POLYCAB.NS","HAVELLS.NS",
    "LUPIN.NS","AUROPHARMA.NS","TVSMOTOR.NS","ASHOKLEY.NS","NMDC.NS",
    "DEEPAKNTR.NS","SRF.NS","DLF.NS","GODREJPROP.NS","IRCTC.NS",
]


class MarketSentimentEngine:
    """
    Predicts market direction using 6 independent signals.
    Cached for 2 hours — expensive to compute (breadth scan).
    """

    _cache: Optional[dict] = None
    _cache_time: Optional[datetime] = None
    CACHE_MINUTES = 120

    @classmethod
    def get(cls, force: bool = False) -> dict:
        now = datetime.now()
        if (not force and cls._cache and cls._cache_time and
                (now - cls._cache_time).total_seconds() < cls.CACHE_MINUTES * 60):
            return cls._cache

        result = cls._compute()
        cls._cache = result
        cls._cache_time = now
        return result

    @classmethod
    def _compute(cls) -> dict:
        signals = {}

        # 1. Nifty trend signal
        signals["trend"] = cls._nifty_trend_signal()

        # 2. Momentum divergence
        signals["momentum"] = cls._momentum_divergence_signal()

        # 3. Market breadth
        signals["breadth"] = cls._breadth_signal()

        # 4. Sector rotation
        signals["rotation"] = cls._sector_rotation_signal()

        # 5. Volatility / fear proxy
        signals["volatility"] = cls._volatility_signal()

        # 6. Small-cap stress
        signals["smallcap_stress"] = cls._smallcap_stress_signal()

        # Weighted composite (0-100, higher = more bullish)
        weights = {
            "trend":            0.20,
            "momentum":         0.20,
            "breadth":          0.20,
            "rotation":         0.15,
            "volatility":       0.15,
            "smallcap_stress":  0.10,
        }

        composite = sum(signals[k] * weights[k] for k in weights if signals[k] is not None)

        # Normalise if any signal failed (returned None → treat as neutral 50)
        for k in weights:
            if signals[k] is None:
                signals[k] = 50.0
                composite += 50.0 * weights[k]

        composite = round(composite, 1)

        # Regime label
        if composite >= 70:
            regime = "STRONGLY_BULLISH"
        elif composite >= 55:
            regime = "BULLISH"
        elif composite >= 40:
            regime = "NEUTRAL"
        elif composite >= 25:
            regime = "CAUTION"
        else:
            regime = "BEARISH"

        # Bearish prediction flag — fires early (CAUTION or worse)
        bearish_warning = composite < 40

        # Fetch Nifty price for display
        nifty_price = 0.0
        try:
            hist = yf.Ticker(NIFTY).history(period="5d", interval="1d")
            if not hist.empty:
                nifty_price = round(float(hist["Close"].iloc[-1]), 2)
        except Exception:
            pass

        return {
            "composite_score":  composite,
            "regime":           regime,
            "bearish_warning":  bearish_warning,
            "bullish":          composite >= 55,
            "nifty_price":      nifty_price,
            "signals": {
                "trend_score":          round(signals["trend"], 1),
                "momentum_score":       round(signals["momentum"], 1),
                "breadth_score":        round(signals["breadth"], 1),
                "rotation_score":       round(signals["rotation"], 1),
                "volatility_score":     round(signals["volatility"], 1),
                "smallcap_stress":      round(signals["smallcap_stress"], 1),
            },
            "computed_at": datetime.now().isoformat(),
        }

    # ── Signal 1: Nifty Trend ──────────────────────────────────────────────
    @classmethod
    def _nifty_trend_signal(cls) -> float:
        """
        Score 0-100.
        100 = strongly above both MAs, 0 = deeply below both MAs.
        """
        try:
            hist = yf.Ticker(NIFTY).history(period="90d", interval="1d")
            if hist.empty or len(hist) < 50:
                return 50.0
            close = hist["Close"].astype(float)
            price = float(close.iloc[-1])
            ma20  = float(close.rolling(20).mean().iloc[-1])
            ma50  = float(close.rolling(50, min_periods=20).mean().iloc[-1])

            pct_vs_ma20 = (price - ma20) / ma20 * 100
            pct_vs_ma50 = (price - ma50) / ma50 * 100

            # Each MA contributes 50 pts; ±3% = full swing
            score_ma20 = min(100, max(0, 50 + pct_vs_ma20 * (50 / 3)))
            score_ma50 = min(100, max(0, 50 + pct_vs_ma50 * (50 / 3)))

            return round((score_ma20 * 0.6 + score_ma50 * 0.4), 1)
        except Exception as e:
            logger.warning(f"Trend signal failed: {e}")
            return 50.0

    # ── Signal 2: Momentum Divergence ─────────────────────────────────────
    @classmethod
    def _momentum_divergence_signal(cls) -> float:
        """
        RSI + MACD on Nifty itself.
        Bearish divergence = price making highs but RSI/MACD weakening.
        Score 0-100.
        """
        try:
            hist = yf.Ticker(NIFTY).history(period="90d", interval="1d")
            if hist.empty or len(hist) < 30:
                return 50.0
            close = hist["Close"].astype(float)

            # RSI
            delta = close.diff()
            gain  = delta.clip(lower=0).rolling(14, min_periods=5).mean()
            loss  = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()
            rs    = gain / loss.replace(0, np.nan)
            rsi   = float((100 - 100 / (1 + rs)).dropna().iloc[-1])

            # MACD histogram
            ema12     = close.ewm(span=12, min_periods=5).mean()
            ema26     = close.ewm(span=26, min_periods=10).mean()
            macd_line = ema12 - ema26
            signal_l  = macd_line.ewm(span=9, min_periods=3).mean()
            macd_hist = float((macd_line - signal_l).dropna().iloc[-1])

            # RSI score: 30-70 range maps to 0-100
            rsi_score = min(100, max(0, (rsi - 30) / 40 * 100))

            # MACD score: positive histogram = bullish
            # Normalise by recent ATR of histogram
            hist_series = (macd_line - signal_l).dropna()
            hist_std    = float(hist_series.rolling(20).std().iloc[-1]) or 1.0
            macd_score  = min(100, max(0, 50 + (macd_hist / hist_std) * 25))

            return round(rsi_score * 0.5 + macd_score * 0.5, 1)
        except Exception as e:
            logger.warning(f"Momentum signal failed: {e}")
            return 50.0

    # ── Signal 3: Market Breadth ───────────────────────────────────────────
    @classmethod
    def _breadth_signal(cls) -> float:
        """
        % of sampled stocks above their 50-day MA.
        > 70% = bullish breadth (score ~80-100)
        < 40% = bearish breadth (score ~0-30)
        """
        try:
            import concurrent.futures

            def _above_ma50(sym: str) -> Optional[bool]:
                try:
                    h = yf.Ticker(sym).history(period="90d", interval="1d")
                    if h.empty or len(h) < 50:
                        return None
                    c = h["Close"].astype(float)
                    ma50 = float(c.rolling(50, min_periods=20).mean().iloc[-1])
                    return float(c.iloc[-1]) > ma50
                except Exception:
                    return None

            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
                futs = {ex.submit(_above_ma50, s): s for s in BREADTH_SAMPLE}
                for f in concurrent.futures.as_completed(futs):
                    r = f.result()
                    if r is not None:
                        results.append(r)

            if not results:
                return 50.0

            pct_above = sum(results) / len(results) * 100
            # Map 0-100% → score 0-100 with 50% = neutral
            score = min(100, max(0, (pct_above - 30) / 40 * 100))
            logger.info(f"Breadth: {pct_above:.1f}% above MA50 ({len(results)} stocks) → score {score:.0f}")
            return round(score, 1)
        except Exception as e:
            logger.warning(f"Breadth signal failed: {e}")
            return 50.0

    # ── Signal 4: Sector Rotation ──────────────────────────────────────────
    @classmethod
    def _sector_rotation_signal(cls) -> float:
        """
        Cyclicals outperforming defensives = risk-on = bullish.
        Defensives outperforming = risk-off = bearish.
        Score 0-100.
        """
        try:
            def _avg_return(tickers, period_days=10) -> float:
                returns = []
                for sym in tickers:
                    try:
                        h = yf.Ticker(sym).history(period="30d", interval="1d")
                        if len(h) >= period_days:
                            c = h["Close"].astype(float)
                            ret = (float(c.iloc[-1]) - float(c.iloc[-period_days])) / float(c.iloc[-period_days]) * 100
                            returns.append(ret)
                    except Exception:
                        pass
                return float(np.mean(returns)) if returns else 0.0

            cyc_ret = _avg_return(CYCLICALS)
            def_ret = _avg_return(DEFENSIVES)

            spread = cyc_ret - def_ret   # positive = cyclicals leading = bullish
            # ±5% spread = full swing
            score = min(100, max(0, 50 + spread * (50 / 5)))
            logger.info(f"Rotation: cyclicals {cyc_ret:.2f}% vs defensives {def_ret:.2f}% → spread {spread:.2f}% → score {score:.0f}")
            return round(score, 1)
        except Exception as e:
            logger.warning(f"Rotation signal failed: {e}")
            return 50.0

    # ── Signal 5: Volatility / Fear Proxy ─────────────────────────────────
    @classmethod
    def _volatility_signal(cls) -> float:
        """
        ATR expansion on Nifty = fear rising = bearish.
        We compare 5-day ATR vs 20-day ATR.
        ATR ratio > 1.5 = high fear → low score.
        ATR ratio < 0.8 = calm market → high score.
        Score 0-100 (inverted — high volatility = low score).
        """
        try:
            hist = yf.Ticker(NIFTY).history(period="60d", interval="1d")
            if hist.empty or len(hist) < 25:
                return 50.0
            high  = hist["High"].astype(float)
            low   = hist["Low"].astype(float)
            close = hist["Close"].astype(float)

            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low  - close.shift()).abs()
            ], axis=1).max(axis=1)

            atr5  = float(tr.rolling(5,  min_periods=3).mean().iloc[-1]) or 1.0
            atr20 = float(tr.rolling(20, min_periods=10).mean().iloc[-1]) or 1.0
            ratio = atr5 / max(atr20, 0.001)

            # ratio 0.5 → score 100 (very calm), ratio 2.0 → score 0 (very fearful)
            score = min(100, max(0, (2.0 - ratio) / 1.5 * 100))
            logger.info(f"Volatility: ATR5/ATR20 = {ratio:.2f} → score {score:.0f}")
            return round(score, 1)
        except Exception as e:
            logger.warning(f"Volatility signal failed: {e}")
            return 50.0

    # ── Signal 6: Small-Cap Stress ─────────────────────────────────────────
    @classmethod
    def _smallcap_stress_signal(cls) -> float:
        """
        Small caps underperform large caps before broad market tops.
        Nifty Smallcap 100 vs Nifty 50 relative performance over 10 days.
        Score 0-100.
        """
        try:
            sc_hist = yf.Ticker(NIFTY_SMALLCAP).history(period="30d", interval="1d")
            nf_hist = yf.Ticker(NIFTY).history(period="30d", interval="1d")

            if sc_hist.empty or nf_hist.empty or len(sc_hist) < 10 or len(nf_hist) < 10:
                return 50.0

            sc_ret = float((sc_hist["Close"].iloc[-1] - sc_hist["Close"].iloc[-10]) / sc_hist["Close"].iloc[-10] * 100)
            nf_ret = float((nf_hist["Close"].iloc[-1] - nf_hist["Close"].iloc[-10]) / nf_hist["Close"].iloc[-10] * 100)

            spread = sc_ret - nf_ret   # positive = small caps leading = healthy risk appetite
            # ±5% spread = full swing
            score = min(100, max(0, 50 + spread * (50 / 5)))
            logger.info(f"SmallCap stress: SC {sc_ret:.2f}% vs Nifty {nf_ret:.2f}% → spread {spread:.2f}% → score {score:.0f}")
            return round(score, 1)
        except Exception as e:
            logger.warning(f"SmallCap stress signal failed: {e}")
            return 50.0


def get_market_sentiment(force: bool = False) -> dict:
    """Public API — returns full sentiment dict."""
    return MarketSentimentEngine.get(force=force)


def format_sentiment_alert(sentiment: dict) -> str:
    """Format a Telegram-ready market sentiment message."""
    regime = sentiment["regime"]
    score  = sentiment["composite_score"]
    sigs   = sentiment["signals"]

    icons = {
        "STRONGLY_BULLISH": "🟢",
        "BULLISH":          "📈",
        "NEUTRAL":          "⚪",
        "CAUTION":          "🟡",
        "BEARISH":          "🔴",
    }
    icon = icons.get(regime, "⚪")

    lines = [
        f"{icon} <b>Market Sentiment: {regime}</b> (Score: {score}/100)",
        f"Nifty: ₹{sentiment['nifty_price']:,.0f}",
        "",
        f"📊 Signal Breakdown:",
        f"  Trend:          {sigs['trend_score']:.0f}/100",
        f"  Momentum:       {sigs['momentum_score']:.0f}/100",
        f"  Breadth:        {sigs['breadth_score']:.0f}/100",
        f"  Sector Rotation:{sigs['rotation_score']:.0f}/100",
        f"  Volatility:     {sigs['volatility_score']:.0f}/100",
        f"  SmallCap Stress:{sigs['smallcap_stress']:.0f}/100",
    ]

    if sentiment["bearish_warning"]:
        lines += [
            "",
            "⚠️ <b>BEARISH WARNING</b>: Multiple signals deteriorating.",
            "Consider reducing position sizes and tightening stop losses.",
        ]

    return "\n".join(lines)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print("Computing market sentiment (this takes ~30s for breadth scan)...")
    s = get_market_sentiment(force=True)
    print(f"\nRegime: {s['regime']} | Score: {s['composite_score']}/100")
    print(f"Bearish Warning: {s['bearish_warning']}")
    print(f"Signals: {s['signals']}")
    print(f"\nTelegram message preview:\n{format_sentiment_alert(s)}")
