"""
BuzzFlow - Delivery Volume Engine (yfinance-based)

NSE bhavcopy requires browser cookies and is unreliable for automation.
Instead we compute a delivery proxy from OHLCV data via yfinance.

Three signals combined into a delivery score (0-100):

1. Money Flow Ratio (MFR)
   MFR = (Close - Low) / (High - Low)
   High MFR (>0.6) = price closed near high = buyers in control = accumulation
   Low MFR (<0.4)  = price closed near low  = sellers in control = distribution

2. Volume Trend
   Is volume rising while price is rising? = institutional accumulation
   Is volume rising while price is falling? = distribution / selling

3. Chaikin Money Flow (CMF, 20-day)
   Industry-standard accumulation/distribution indicator.
   CMF > 0.1  = accumulation
   CMF < -0.1 = distribution
   CMF 0      = neutral

Delivery Score interpretation:
  >= 70  → ACCUMULATION  (institutions buying, high conviction)
  40-70  → NEUTRAL       (mixed signals)
  < 40   → DISTRIBUTION  (selling pressure, avoid entry)
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def _compute_delivery_proxy(hist: pd.DataFrame) -> dict:
    """
    Compute delivery proxy metrics from OHLCV data.
    hist: DataFrame with Open, High, Low, Close, Volume columns.
    """
    hist = hist.copy().dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    if len(hist) < 10:
        return {"delivery_score": 50.0, "signal": "NEUTRAL", "cmf": 0.0, "mfr": 0.5, "vol_trend": 0.0}

    close  = hist["Close"].astype(float)
    high   = hist["High"].astype(float)
    low    = hist["Low"].astype(float)
    volume = hist["Volume"].astype(float)

    # ── 1. Money Flow Ratio (last 5 days average) ──────────────────────
    hl_range = (high - low).replace(0, np.nan)
    mfr_series = (close - low) / hl_range
    mfr = float(mfr_series.tail(5).mean())  # 0-1

    # ── 2. Chaikin Money Flow (20-day) ─────────────────────────────────
    # CMF = sum(MFV) / sum(Volume) over 20 days
    # MFV = ((Close - Low) - (High - Close)) / (High - Low) * Volume
    mfv = ((close - low) - (high - close)) / hl_range * volume
    period = min(20, len(hist))
    cmf = float(mfv.tail(period).sum() / volume.tail(period).sum())

    # ── 3. Volume trend vs price trend ─────────────────────────────────
    # Positive = volume rising with price (accumulation)
    # Negative = volume rising with price falling (distribution)
    if len(hist) >= 5:
        price_change = float((close.iloc[-1] - close.iloc[-5]) / close.iloc[-5])
        vol_avg_recent = float(volume.tail(3).mean())
        vol_avg_prior  = float(volume.iloc[-8:-3].mean()) if len(hist) >= 8 else float(volume.mean())
        vol_change = (vol_avg_recent - vol_avg_prior) / max(vol_avg_prior, 1)
        # vol_trend: positive if volume and price move together
        vol_trend = price_change * vol_change * 100
    else:
        vol_trend = 0.0

    # ── Composite delivery score ────────────────────────────────────────
    # MFR score: 0-100 (0.6+ = 100, 0.4- = 0)
    mfr_score = max(0, min(100, (mfr - 0.3) / 0.4 * 100))

    # CMF score: 0-100 (-0.2 = 0, +0.2 = 100)
    cmf_score = max(0, min(100, (cmf + 0.2) / 0.4 * 100))

    # Vol trend score: 0-100
    vol_score = max(0, min(100, 50 + vol_trend * 5))

    # Weighted composite
    delivery_score = round(
        mfr_score * 0.35 +
        cmf_score * 0.45 +
        vol_score * 0.20,
        2
    )

    # Signal
    if delivery_score >= 65 and cmf > 0.05:
        signal = "ACCUMULATION"
    elif delivery_score < 40 or cmf < -0.05:
        signal = "DISTRIBUTION"
    else:
        signal = "NEUTRAL"

    return {
        "delivery_score": delivery_score,
        "signal":         signal,
        "cmf":            round(cmf, 4),
        "mfr":            round(mfr, 4),
        "vol_trend":      round(vol_trend, 2),
        "mfr_score":      round(mfr_score, 1),
        "cmf_score":      round(cmf_score, 1),
        "vol_score":      round(vol_score, 1),
    }


def get_delivery_data(symbol: str, hist: pd.DataFrame = None) -> Optional[dict]:
    """
    Get delivery proxy data for a symbol.
    If hist is provided (already fetched), reuse it — avoids duplicate API calls.
    Otherwise fetches 30 days of data.
    """
    try:
        if hist is None:
            hist = yf.Ticker(symbol).history(period="30d", interval="1d")
            if hist.empty or len(hist) < 10:
                return None

        result = _compute_delivery_proxy(hist)
        result["symbol"] = symbol
        return result

    except Exception as e:
        logger.warning(f"Delivery data failed for {symbol}: {e}")
        return None


def get_delivery_score(symbol: str, hist: pd.DataFrame = None) -> float:
    """
    Returns delivery score 0-100. Returns 50.0 (neutral) on failure.
    Pass hist to avoid a second yfinance call if you already have it.
    """
    data = get_delivery_data(symbol, hist)
    return data["delivery_score"] if data else 50.0
