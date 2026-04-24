#!/usr/bin/env python3

"""

BuzzFlow - Production Scanner

Two-phase engine: fast technical pre-filter on 800+ stocks,

full analysis with news on top 50 candidates.

Outputs entry zones, breakout/pullback levels — NOT immediate BUY signals.

"""

import os

import logging

import argparse

import concurrent.futures

from datetime import datetime

from dataclasses import dataclass, field

from typing import List, Optional

import numpy as np

import pandas as pd

import yfinance as yf

from dotenv import load_dotenv

from news_engine import NewsEngine

from scoring_engine import ScoringEngine, MarketRegime

from watchlist_engine import WatchlistEngine

from alert_engine import AlertEngine

from trade_state import compute_opportunity_score

from delivery_engine import get_delivery_score

from universe_engine import get_universe, get_categories, get_universe_df

from database import init_db, save_scan_result, cleanup_db

from market_regime_engine import get_market_sentiment, format_sentiment_alert

load_dotenv()

logging.basicConfig(

    level=logging.INFO,

    format="%(asctime)s - %(levelname)s - %(message)s",

    handlers=[logging.FileHandler("buzzflow.log"), logging.StreamHandler()]

)

logger = logging.getLogger(__name__)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

@dataclass

class ScanResult:

    symbol: str

    company_name: str

    current_price: float

    entry_score: float

    signal: str

    confidence: str

    cap_tier: str             # "large" | "mid" | "small" | "micro"

    # Entry zone (not immediate BUY — user decides when to enter)

    entry_zone_low: float

    entry_zone_high: float

    breakout_level: float

    pullback_level: float

    entry_conditions: str

    stop_loss: float

    target_price: float

    risk_reward: float

    opportunity_score: float

    sentiment_score: float

    technical_score: float

    rsi: float

    volume_ratio: float

    delivery_score: float     # 0-100 from NSE bhavcopy delivery %

    risk_capital_pct: float   # 0.5 / 1.0 / 1.5 based on score

    qty_per_lakh: int         # shares per ₹1L capital

    news_headlines: List[str] = field(default_factory=list)

    timestamp: datetime = field(default_factory=datetime.now)

# ── Stock Universe ─────────────────────────────────────────────────────────

NIFTY_50 = [

    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",

    "HINDUNILVR.NS","ITC.NS","SBIN.NS","BHARTIARTL.NS","KOTAKBANK.NS",

    "AXISBANK.NS","ASIANPAINT.NS","MARUTI.NS","HCLTECH.NS","SUNPHARMA.NS",

    "TATAMOTORS.NS","WIPRO.NS","ULTRACEMCO.NS","TITAN.NS","BAJFINANCE.NS",

    "NESTLEIND.NS","POWERGRID.NS","NTPC.NS","BAJAJFINSV.NS","ONGC.NS",

    "ADANIENT.NS","JSWSTEEL.NS","COALINDIA.NS","TECHM.NS","TATACONSUM.NS",

    "HINDALCO.NS","GRASIM.NS","CIPLA.NS","DIVISLAB.NS","BRITANNIA.NS",

    "EICHERMOT.NS","DRREDDY.NS","HEROMOTOCO.NS","BPCL.NS","TATASTEEL.NS",

    "INDUSINDBK.NS","LT.NS","SBILIFE.NS","APOLLOHOSP.NS","HDFCLIFE.NS",

    "ADANIPORTS.NS","TATAPOWER.NS","M&M.NS","BAJAJ-AUTO.NS","SHREECEM.NS",

]

EXTENDED_UNIVERSE = list(dict.fromkeys(NIFTY_50 + [

    # Banking & Finance

    "FEDERALBNK.NS","IDFCFIRSTB.NS","AUBANK.NS","BANDHANBNK.NS","RBLBANK.NS",

    "CHOLAFIN.NS","MUTHOOTFIN.NS","MANAPPURAM.NS","LICHSGFIN.NS","M&MFIN.NS",

    "ICICIPRULI.NS","PNB.NS","UNIONBANK.NS","CANBK.NS","BANKBARODA.NS",

    "RECLTD.NS","PFC.NS","IRFC.NS","ABCAPITAL.NS","PNBHOUSING.NS",

    # IT

    "LTIM.NS","MPHASIS.NS","COFORGE.NS","PERSISTENT.NS","OFSS.NS",

    "LTTS.NS","KPITTECH.NS","TATAELXSI.NS","CYIENT.NS","BSOFT.NS",

    # Pharma

    "LUPIN.NS","AUROPHARMA.NS","TORNTPHARM.NS","ALKEM.NS","ZYDUSLIFE.NS",

    "GLENMARK.NS","LAURUSLABS.NS","ABBOTINDIA.NS","BIOCON.NS","IPCALAB.NS",

    "GRANULES.NS","LALPATHLAB.NS","METROPOLIS.NS","MAXHEALTH.NS","FORTIS.NS",

    # Auto

    "TVSMOTOR.NS","ASHOKLEY.NS","MOTHERSON.NS","BHARATFORG.NS","BALKRISIND.NS",

    "APOLLOTYRE.NS","BOSCHLTD.NS","TIINDIA.NS","CEATLTD.NS","ESCORTS.NS",

    # Capital Goods & Infra

    "ABB.NS","SIEMENS.NS","BHEL.NS","CUMMINSIND.NS","HAVELLS.NS",

    "POLYCAB.NS","DIXON.NS","IRCTC.NS","INDUSTOWER.NS","JSWENERGY.NS",

    "TORNTPOWER.NS","NHPC.NS","SJVN.NS","RVNL.NS","NBCC.NS",

    "KEC.NS","THERMAX.NS","AIAENG.NS","GMRINFRA.NS","IRB.NS",

    # FMCG & Consumption

    "DABUR.NS","MARICO.NS","GODREJCP.NS","COLPAL.NS","EMAMILTD.NS",

    "DMART.NS","JUBLFOOD.NS","VBL.NS","UBL.NS","PAGEIND.NS",

    "TRENT.NS","ZOMATO.NS","NYKAA.NS","INDIAMART.NS","NAUKRI.NS",

    # Metals

    "NMDC.NS","SAIL.NS","NATIONALUM.NS","HINDCOPPER.NS","APLAPOLLO.NS",
    "JINDALSTEL.NS","VEDL.NS",

    # Cement & Building

    "AMBUJACEM.NS","ACC.NS","DALMIACEM.NS","JKCEMENT.NS","RAMCOCEM.NS",

    "PIDILITIND.NS","ASTRAL.NS","SUPREMEIND.NS","POLYCAB.NS",

    # Chemicals

    "DEEPAKNTR.NS","NAVINFLUOR.NS","SRF.NS","AARTIIND.NS","VINATIORGA.NS",

    "ATUL.NS","FINEORG.NS","TATACHEM.NS","GNFC.NS","CHAMBLFERT.NS",

    "COROMANDEL.NS","PIIND.NS","FLUOROCHEM.NS",

    # Real Estate

    "DLF.NS","GODREJPROP.NS","OBEROIRLTY.NS","PRESTIGE.NS","BRIGADE.NS",

    # Midcap Quality

    "MPHASIS.NS","COFORGE.NS","LTTS.NS","PERSISTENT.NS","KPITTECH.NS",

    "LALPATHLAB.NS","METROPOLIS.NS","BERGEPAINT.NS","KANSAINER.NS","INDIGO.NS",

    "POLICYBZR.NS","DELHIVERY.NS","IRCTC.NS","RAILTEL.NS","CONCOR.NS",

]))

SECTOR_MAP = {

    "nifty_50":    NIFTY_50,

    "banking":     ["HDFCBANK.NS","ICICIBANK.NS","SBIN.NS","KOTAKBANK.NS","AXISBANK.NS","INDUSINDBK.NS","FEDERALBNK.NS","IDFCFIRSTB.NS","AUBANK.NS","BANDHANBNK.NS","BAJFINANCE.NS","BAJAJFINSV.NS","CHOLAFIN.NS","MUTHOOTFIN.NS","MANAPPURAM.NS","LICHSGFIN.NS","M&MFIN.NS","SBILIFE.NS","HDFCLIFE.NS","ICICIPRULI.NS"],

    "nifty_it":    ["TCS.NS","INFY.NS","HCLTECH.NS","WIPRO.NS","TECHM.NS","LTIM.NS","MPHASIS.NS","COFORGE.NS","PERSISTENT.NS","OFSS.NS"],

    "pharma":      ["SUNPHARMA.NS","DRREDDY.NS","CIPLA.NS","DIVISLAB.NS","LUPIN.NS","AUROPHARMA.NS","TORNTPHARM.NS","ALKEM.NS","ZYDUSLIFE.NS","GLENMARK.NS","APOLLOHOSP.NS","LAURUSLABS.NS","ABBOTINDIA.NS","BIOCON.NS"],

    "auto":        ["MARUTI.NS","TATAMOTORS.NS","M&M.NS","BAJAJ-AUTO.NS","HEROMOTOCO.NS","EICHERMOT.NS","TVSMOTOR.NS","ASHOKLEY.NS","MOTHERSON.NS","BHARATFORG.NS","BALKRISIND.NS","APOLLOTYRE.NS","BOSCHLTD.NS","TIINDIA.NS"],

    "capex":       ["LT.NS","ABB.NS","SIEMENS.NS","BHEL.NS","CUMMINSIND.NS","HAVELLS.NS","POLYCAB.NS","DIXON.NS","ADANIPORTS.NS","IRCTC.NS","INDUSTOWER.NS","JSWENERGY.NS","TATAPOWER.NS","NTPC.NS","POWERGRID.NS","ADANIGREEN.NS","RVNL.NS"],

    "consumption": ["HINDUNILVR.NS","ITC.NS","NESTLEIND.NS","BRITANNIA.NS","DABUR.NS","MARICO.NS","GODREJCP.NS","COLPAL.NS","TATACONSUM.NS","TITAN.NS","DMART.NS","JUBLFOOD.NS","VBL.NS","UBL.NS","PAGEIND.NS"],

    "metals":      ["TATASTEEL.NS","JSWSTEEL.NS","HINDALCO.NS","VEDL.NS","COALINDIA.NS","NMDC.NS","SAIL.NS","NATIONALUM.NS","HINDCOPPER.NS","APLAPOLLO.NS"],

    "chemicals":   ["DEEPAKNTR.NS","NAVINFLUOR.NS","SRF.NS","AARTIIND.NS","VINATIORGA.NS","ATUL.NS","FINEORG.NS","TATACHEM.NS","GNFC.NS","CHAMBLFERT.NS","COROMANDEL.NS","PIIND.NS","FLUOROCHEM.NS"],

}

class ScannerV2:

    """

    Production swing trading scanner.

    Phase 1: Technical pre-filter on 800+ stocks (20 workers, ~3s)

    Phase 2: Full analysis + news on top 50 candidates (5 workers, ~40s)

    Total: ~1 minute for entire universe.

    """

    def __init__(self):

        init_db()

        self.news_engine = NewsEngine()

        self.scorer = ScoringEngine()

        self.watchlist = WatchlistEngine()

        self.alert = AlertEngine()

        self._nifty_return_5d = self._get_nifty_return()

    def _get_nifty_return(self) -> float:

        try:

            hist = yf.Ticker("^NSEI").history(period="10d", interval="1d")

            if len(hist) >= 5:

                return float((hist["Close"].iloc[-1] - hist["Close"].iloc[-5]) / hist["Close"].iloc[-5] * 100)

        except Exception:

            pass

        return 0.0

    def _get_price_data(self, symbol: str) -> Optional[pd.DataFrame]:

        try:

            hist = yf.Ticker(symbol).history(period="60d", interval="1d")

            return hist if not hist.empty and len(hist) >= 20 else None

        except Exception:

            return None

    def _compute_tech(self, hist: pd.DataFrame) -> dict:

        """Full technical component extraction."""

        hist = hist.copy().dropna(subset=["Close","Volume","High","Low"])

        close  = hist["Close"].astype(float)

        volume = hist["Volume"].astype(float)

        high   = hist["High"].astype(float)

        low    = hist["Low"].astype(float)

        def safe_last(s): return float(s.dropna().iloc[-1]) if not s.dropna().empty else 0.0

        # RSI

        delta = close.diff()

        gain  = delta.clip(lower=0).rolling(14, min_periods=5).mean()

        loss  = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()

        rs    = gain / loss.replace(0, np.nan)

        rsi   = safe_last(100 - 100 / (1 + rs))

        # MACD

        ema12 = close.ewm(span=12, min_periods=5).mean()

        ema26 = close.ewm(span=26, min_periods=10).mean()

        macd_line = ema12 - ema26

        macd_hist = safe_last(macd_line - macd_line.ewm(span=9, min_periods=3).mean())

        # Volume ratio

        vol_avg   = safe_last(volume.rolling(20, min_periods=5).mean()) or float(volume.mean())

        vol_ratio = float(volume.iloc[-1]) / max(vol_avg, 1)

        # ATR ratio

        tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)

        atr7  = safe_last(tr.rolling(7, min_periods=3).mean()) or 1.0

        atr20 = safe_last(tr.rolling(20, min_periods=5).mean()) or 1.0

        atr_ratio = atr7 / max(atr20, 0.001)

        atr14 = safe_last(tr.rolling(14, min_periods=5).mean()) or float(close.iloc[-1]) * 0.02

        # Support / resistance (20-day)

        support    = safe_last(low.rolling(20, min_periods=5).min()) or float(low.min())

        resistance = safe_last(high.rolling(20, min_periods=5).max()) or float(high.max())

        current    = float(close.iloc[-1])

        price_range = resistance - support

        price_vs_res = (current - support) / max(price_range, 0.001)

        # MAs

        ma20 = safe_last(close.rolling(20, min_periods=5).mean()) or current

        ma50 = safe_last(close.rolling(50, min_periods=20).mean()) or current

        # 5-day return

        ret5 = float((close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100) if len(close) >= 5 else 0.0

        # Gap

        gap = 0.0

        if len(hist) >= 2 and "Open" in hist.columns:

            try: gap = float((float(hist["Open"].iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2]) * 100)

            except: pass

        # Recent low (for trailing stop)

        recent_low = safe_last(low.rolling(5, min_periods=2).min()) or float(low.iloc[-1])

        return {

            "rsi": rsi, "macd_histogram": macd_hist,

            "volume_ratio": vol_ratio, "atr_ratio": atr_ratio, "atr14": atr14,

            "price_vs_resistance": price_vs_res, "stock_return_5d": ret5,

            "gap_percent": gap, "price_vs_ma20": current / max(ma20, 0.001),

            "current_price": current, "support": support, "resistance": resistance,

            "ma20": ma20, "ma50": ma50, "recent_low": recent_low,

            "pattern_score": 50.0,

        }

    def _quick_filter(self, symbol: str, cap_tier: str = "large") -> Optional[dict]:

        """Phase 1: Fast pre-filter. No news. ~0.3s/stock."""

        try:

            hist = yf.Ticker(symbol).history(period="60d", interval="1d")

            if hist.empty or len(hist) < 20:

                return None

            hist = hist.dropna(subset=["Close","Volume","High","Low"])

            close  = hist["Close"].astype(float)

            volume = hist["Volume"].astype(float)

            current = float(close.iloc[-1])

            # RSI

            delta = close.diff()

            gain  = delta.clip(lower=0).rolling(14, min_periods=5).mean()

            loss  = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()

            rs    = gain / loss.replace(0, np.nan)

            rsi_s = 100 - 100 / (1 + rs)

            rsi   = float(rsi_s.dropna().iloc[-1]) if not rsi_s.dropna().empty else 50.0

            # MA50

            ma50_s = close.rolling(50, min_periods=20).mean()

            ma50   = float(ma50_s.dropna().iloc[-1]) if not ma50_s.dropna().empty else current

            # Volume ratio

            vol_avg = float(volume.rolling(20, min_periods=5).mean().dropna().iloc[-1]) if not volume.rolling(20, min_periods=5).mean().dropna().empty else float(volume.mean())

            vol_ratio = float(volume.iloc[-1]) / max(vol_avg, 1)

            # Cap-tier aware hard filters
            tier = (cap_tier or "large").lower()
            rsi_max   = 70 if tier in ("small", "micro") else 73 if tier == "mid" else 75
            vol_floor = 1.5 if tier in ("small", "micro") else 1.3 if tier == "mid" else 1.2

            if current < ma50 * 0.97: return None   # below MA50

            if rsi > rsi_max or rsi < 30: return None

            if vol_ratio < vol_floor * 0.5: return None  # pre-filter uses half threshold

            # Quick score

            rsi_score   = max(0, 100 - abs(rsi - 55) * 3)

            vol_score   = min(100, vol_ratio * 50)

            trend_score = 80 if current > float(close.rolling(20, min_periods=5).mean().dropna().iloc[-1] if not close.rolling(20, min_periods=5).mean().dropna().empty else current) else 30

            return {

                "symbol":      symbol,

                "cap_tier":    cap_tier,

                "quick_score": round(rsi_score * 0.4 + vol_score * 0.3 + trend_score * 0.3, 1),

                "rsi":         rsi,

                "vol_ratio":   vol_ratio,

                "current":     current,

            }

        except Exception:

            return None

    def _risk_tier(self, score: float, cap_tier: str = "large") -> tuple:

        """Returns (risk_capital_pct, confidence) based on entry score and cap tier."""

        params = self.scorer.cap_tier_params(cap_tier)

        max_risk = params["risk_cap_pct"]

        if score >= 70:   return min(max_risk, 1.5), "high"

        elif score >= 65: return min(max_risk, 1.0), "high"

        elif score >= 60: return min(max_risk, 0.5), "medium"

        else:             return 0.0, "low"

    def _position_size(self, entry: float, sl: float,

                        risk_pct: float, capital: float = 100000) -> int:

        """qty = (capital × risk_pct%) / (entry - sl)"""

        risk_per_share = entry - sl

        if risk_per_share <= 0:

            return 0

        risk_amount = capital * (risk_pct / 100)

        return max(0, int(risk_amount / risk_per_share))

    def _analyze_stock(self, symbol: str, capital: float = 100000,

                       cap_tier: str = "large") -> Optional[ScanResult]:

        try:

            hist = self._get_price_data(symbol)

            if hist is None:

                return None

            close_vals = hist["Close"].dropna()

            if close_vals.empty:

                return None

            current_price = float(close_vals.iloc[-1])

            tech = self._compute_tech(hist)

            # News sentiment

            company = symbol.replace(".NS","").replace(".BO","")

            buzz    = self.news_engine.get_buzz_score(symbol, company)

            sentiment = buzz["raw_sentiment"]

            # Delivery volume proxy (CMF + Money Flow Ratio from OHLCV)

            delivery_score = get_delivery_score(symbol, hist)

            # Cap-tier params
            tier_params = self.scorer.cap_tier_params(cap_tier)

            # Reject if delivery too low for this tier (manipulation guard for small caps)
            if delivery_score < tier_params["delivery_min"] and cap_tier in ("small", "micro"):
                logger.info(f"SKIP {symbol} ({cap_tier}): delivery {delivery_score:.0f} < {tier_params['delivery_min']}")
                return None

            # Entry score — adjust sentiment weight for small/micro caps
            components = self.scorer.technical_to_entry_components(
                tech, sentiment, self._nifty_return_5d)

            # Override accumulation with real delivery score (stronger signal)
            components["accumulation"] = delivery_score

            # Boost sentiment weight for small/micro (more news-driven)
            if cap_tier in ("small", "micro") and tier_params["sentiment_weight"] > 0.10:
                extra = tier_params["sentiment_weight"] - 0.10
                components["sentiment"] = min(100, sentiment * (1 + extra))

            entry_score, signal = self.scorer.compute_entry_score(**components)

            if signal == "SKIP":

                return None

            # ── Always save scores to DB before filter check ───────────
            # This ensures the dashboard always shows fresh values even if
            # the stock is filtered out for alerting (duplicate suppression,
            # low volume, bearish market, etc.)
            atr_pre    = tech["atr14"]
            sl_pre     = max(tech["support"], current_price - tier_params["atr_sl_mult"] * atr_pre)
            sl_pre     = max(sl_pre, current_price * tier_params["max_sl_pct"])
            tgt_pre    = current_price + tier_params["atr_target_mult"] * atr_pre
            tgt_pre    = max(tgt_pre, current_price * tier_params["min_target_pct"])
            risk_pre   = current_price - sl_pre
            reward_pre = tgt_pre - current_price
            rr_pre     = round(reward_pre / max(risk_pre, 0.01), 2)
            momentum_pre = self.scorer.compute_momentum_score(tech)
            opp_pre      = compute_opportunity_score(entry_score, 0, momentum_pre)
            rsi_pre      = tech["rsi"]
            rsi_s_pre    = max(0, min(100, (rsi_pre-30)/40*100)) if rsi_pre < 70 else max(0, (100-rsi_pre)*3)
            tech_score_pre = round(rsi_s_pre*0.4 + tech["volume_ratio"]*30 + (30 if tech["price_vs_ma20"]>1 else 0), 1)

            save_scan_result(
                symbol=symbol, entry_score=entry_score,
                sentiment_score=sentiment, technical_score=tech_score_pre,
                recommendation=signal, confidence="medium",
                entry_price=current_price, stop_loss=sl_pre, target=tgt_pre,
                entry_zone_low=round(tech["support"] * 1.005, 2),
                entry_zone_high=round(current_price * 1.01, 2),
                breakout_level=round(tech["resistance"] * 0.995, 2),
                pullback_level=round(tech["ma20"] * 1.002, 2),
                rsi=rsi_pre, volume_ratio=tech["volume_ratio"],
                delivery_score=delivery_score,
                risk_reward=rr_pre, opportunity_score=opp_pre, trade_state="NEUTRAL"
            )

            # Apply cap-tier aware filters

            signal, filter_reasons = self.scorer.apply_filters(symbol, signal, tech, cap_tier=cap_tier)

            if signal == "FILTERED":

                logger.info(f"FILTERED {symbol} ({cap_tier}): {', '.join(filter_reasons)}")

                return None

            # ── ATR-based SL and target (cap-tier adjusted) ────────────
            atr = tech["atr14"]

            support    = tech["support"]

            resistance = tech["resistance"]

            sl_mult     = tier_params["atr_sl_mult"]
            tgt_mult    = tier_params["atr_target_mult"]
            max_sl_pct  = tier_params["max_sl_pct"]
            min_tgt_pct = tier_params["min_target_pct"]

            stop_loss = max(support, current_price - sl_mult * atr)

            stop_loss = max(stop_loss, current_price * max_sl_pct)

            atr_target = current_price + tgt_mult * atr

            target = min(resistance * 0.98, atr_target) if resistance > current_price * 1.03 else atr_target

            target = max(target, current_price * min_tgt_pct)

            risk   = current_price - stop_loss

            reward = target - current_price

            rr     = round(reward / max(risk, 0.01), 2)

            if rr < tier_params["min_rr"]:

                return None

            # ── Entry zone (not immediate BUY) ─────────────────────────

            entry_zone_low  = round(support * 1.005, 2)

            entry_zone_high = round(current_price * 1.01, 2)

            breakout_level  = round(resistance * 0.995, 2)

            pullback_level  = round(tech["ma20"] * 1.002, 2)

            entry_conditions = (

                f"Enter between Rs{entry_zone_low}–Rs{entry_zone_high} on volume confirmation. "

                f"Breakout above Rs{breakout_level} is aggressive entry. "

                f"Pullback to Rs{pullback_level} (MA20) is conservative entry."

            )

            # ── Risk tier ──────────────────────────────────────────────

            risk_pct, confidence = self._risk_tier(entry_score, cap_tier)

            qty = self._position_size(current_price, stop_loss, risk_pct, capital)

            # ── Opportunity score ──────────────────────────────────────

            momentum = self.scorer.compute_momentum_score(tech)

            opp_score = compute_opportunity_score(entry_score, 0, momentum)

            # ── Technical score ────────────────────────────────────────

            rsi = tech["rsi"]

            rsi_s = max(0, min(100, (rsi-30)/40*100)) if rsi < 70 else max(0, (100-rsi)*3)

            tech_score = round(rsi_s*0.4 + tech["volume_ratio"]*30 + (30 if tech["price_vs_ma20"]>1 else 0), 1)

            # ── Save final refined scores to DB (overwrites the pre-filter save) ──

            save_scan_result(

                symbol=symbol, entry_score=entry_score,

                sentiment_score=sentiment, technical_score=tech_score,

                recommendation=signal, confidence=confidence,

                entry_price=current_price, stop_loss=stop_loss, target=target,

                entry_zone_low=entry_zone_low, entry_zone_high=entry_zone_high,

                breakout_level=breakout_level, pullback_level=pullback_level,

                rsi=rsi, volume_ratio=tech["volume_ratio"],

                delivery_score=delivery_score,

                risk_reward=rr, opportunity_score=opp_score, trade_state="NEUTRAL"

            )

            return ScanResult(

                symbol=symbol, company_name=company,

                current_price=current_price, entry_score=entry_score,

                signal=signal, confidence=confidence,

                cap_tier=cap_tier,

                entry_zone_low=entry_zone_low, entry_zone_high=entry_zone_high,

                breakout_level=breakout_level, pullback_level=pullback_level,

                entry_conditions=entry_conditions,

                stop_loss=round(stop_loss, 2), target_price=round(target, 2),

                risk_reward=rr, opportunity_score=opp_score,

                sentiment_score=sentiment, technical_score=tech_score,

                rsi=rsi, volume_ratio=tech["volume_ratio"],

                delivery_score=delivery_score,

                risk_capital_pct=risk_pct, qty_per_lakh=qty,

                news_headlines=buzz.get("headlines", [])[:3],

                timestamp=datetime.now()

            )

        except Exception as e:

            logger.error(f"Error analyzing {symbol}: {e}")

            return None

    def scan(self, index: str = "all", min_score: float = 65,

             max_results: int = 10, capital: float = 100000,

             auto_watchlist: bool = False) -> List[ScanResult]:

        """

        Two-phase scan with cap-tier grouping.

        Phase 1: 20 workers, pure technical pre-filter.

        Phase 2: 5 workers, full analysis + news, top 50 candidates per tier.

        Returns results sorted by cap tier: large → mid → small.

        """

        # ── Market sentiment check ─────────────────────────────────────
        sentiment = get_market_sentiment()
        if sentiment["bearish_warning"]:
            logger.warning(
                f"BEARISH WARNING: composite={sentiment['composite_score']} "
                f"regime={sentiment['regime']} — small/micro caps blocked"
            )

        # ── Build per-tier stock lists ─────────────────────────────────
        if index == "all":
            # Run all tiers
            tier_stocks = {
                "large": get_universe(cap_tier="large"),
                "mid":   get_universe(cap_tier="mid"),
                "small": get_universe(cap_tier="small"),
            }
        elif index in ("large", "mid", "small", "micro"):
            tier_stocks = {index: get_universe(cap_tier=index)}
        elif index in get_categories():
            # Sector scan — tag each stock with its cap tier from universe
            df = get_universe_df(category=index)
            tier_stocks = {}
            for tier in df["cap_tier"].unique():
                tickers = df[df["cap_tier"] == tier]["ticker"].tolist()
                if tickers:
                    tier_stocks[tier] = tickers
        elif index in ("nifty50","nifty100","nifty200","nifty500","midcap150","smallcap250"):
            df = get_universe_df(index_name=index)
            tier_stocks = {}
            for tier in df["cap_tier"].unique():
                tickers = df[df["cap_tier"] == tier]["ticker"].tolist()
                if tickers:
                    tier_stocks[tier] = tickers
        else:
            # Fallback curated list — treat as large
            tier_stocks = {"large": SECTOR_MAP.get(index, NIFTY_50)}

        # Deduplicate within each tier
        for t in tier_stocks:
            tier_stocks[t] = list(dict.fromkeys(tier_stocks[t]))

        # ── Skip small caps entirely in bearish market ─────────────────
        if sentiment["bearish_warning"]:
            for blocked in ("small", "micro"):
                if blocked in tier_stocks:
                    logger.warning(f"Dropping {blocked} cap scan — bearish market")
                    del tier_stocks[blocked]

        t0 = datetime.now()
        all_results: List[ScanResult] = []

        for tier, stocks in tier_stocks.items():
            total = len(stocks)
            logger.info(f"Phase 1 [{tier}]: pre-filter {total} stocks...")

            quick = []

            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:

                futs = {ex.submit(self._quick_filter, s, tier): s for s in stocks}

                for f in concurrent.futures.as_completed(futs):

                    r = f.result()

                    if r:

                        quick.append(r)

            quick.sort(key=lambda x: x["quick_score"], reverse=True)

            candidates = [r["symbol"] for r in quick[:50]]

            t1 = datetime.now()

            logger.info(f"Phase 1 [{tier}]: {len(quick)}/{total} passed in {(t1-t0).seconds}s -> {len(candidates)} to Phase 2")

            tier_results = []

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:

                futs = {ex.submit(self._analyze_stock, s, capital, tier): s for s in candidates}

                for f in concurrent.futures.as_completed(futs):

                    r = f.result()

                    if r and r.entry_score >= min_score:

                        tier_results.append(r)

            tier_results.sort(key=lambda x: x.entry_score, reverse=True)

            # Per-tier result cap: large=10, mid=8, small=5
            tier_cap = {"large": 10, "mid": 8, "small": 5, "micro": 3}.get(tier, max_results)

            all_results.extend(tier_results[:min(tier_cap, max_results)])

            logger.info(f"Phase 2 [{tier}]: {len(tier_results)} signals, keeping {min(tier_cap, max_results)}")

        t2 = datetime.now()

        logger.info(f"Total scan: {len(all_results)} signals in {(t2-t0).seconds}s")

        # ── Post-scan DB cleanup ───────────────────────────────────────
        cleanup_db()

        if auto_watchlist:

            for r in all_results:

                if r.signal in ("STRONG_BUY", "BUY") and r.risk_capital_pct > 0:

                    self.watchlist.add(

                        symbol=r.symbol, entry_price=r.current_price,

                        stop_loss=r.stop_loss, target=r.target_price,

                        entry_score=r.entry_score, confidence=r.confidence,

                        company_name=r.company_name,

                        entry_zone_low=r.entry_zone_low,

                        entry_zone_high=r.entry_zone_high,

                        breakout_level=r.breakout_level,

                        pullback_level=r.pullback_level,

                        risk_capital_pct=r.risk_capital_pct,

                        qty=r.qty_per_lakh,

                        notes=f"R:R={r.risk_reward} tier={r.cap_tier}"

                    )

                    self.scorer.mark_alerted(r.symbol)

        return all_results

    def print_report(self, results: List[ScanResult], index: str = ""):

        sentiment = get_market_sentiment()

        regime_str = sentiment["regime"]

        score_str  = f"{sentiment['composite_score']:.0f}/100"

        print(f"\n{'='*95}")

        print(f"  BUZZFLOW SCAN -- {index.upper() or 'ALL'} | {datetime.now().strftime('%Y-%m-%d %H:%M')}")

        print(f"  Market Sentiment: {regime_str} ({score_str}) | Nifty Rs{sentiment['nifty_price']:,.0f}")

        if sentiment["bearish_warning"]:

            print(f"  *** BEARISH WARNING — reduce position sizes, tighten stops ***")

        print(f"{'='*95}")

        if not results:

            print(f"\n  No setups found above score threshold.\n")

            return

        # Group by cap tier
        tier_order  = ["large", "mid", "small", "micro"]
        tier_labels = {"large": "LARGE CAP", "mid": "MID CAP", "small": "SMALL CAP", "micro": "MICRO CAP"}

        grouped = {}
        for r in results:
            grouped.setdefault(r.cap_tier, []).append(r)

        header = f"  {'Symbol':<14} {'Score':>6} {'Signal':<12} {'Entry Zone':>20} {'SL':>8} {'Target':>8} {'R:R':>5} {'Risk%':>6} {'Deliv':>6}"

        for tier in tier_order:

            if tier not in grouped:

                continue

            tier_results = grouped[tier]

            print(f"\n  ── {tier_labels.get(tier, tier.upper())} ({len(tier_results)} setups) {'─'*55}")

            print(header)

            print(f"  {'-'*93}")

            for r in tier_results:

                zone = f"Rs{r.entry_zone_low:.0f}-{r.entry_zone_high:.0f}"

                print(f"  {r.symbol:<14} {r.entry_score:>6.1f} {r.signal:<12} {zone:>20} "

                      f"{r.stop_loss:>8.2f} {r.target_price:>8.2f} {r.risk_reward:>5.1f} "

                      f"{r.risk_capital_pct:>5.1f}% {r.delivery_score:>5.0f}")

        print(f"\n{'='*95}")

        print(f"\n  Entry Conditions (top 3):")

        for r in results[:3]:

            print(f"\n  {r.symbol} [{r.cap_tier.upper()}]:")

            safe_cond = r.entry_conditions.encode("ascii", "replace").decode("ascii")

            print(f"    {safe_cond}")

            if r.news_headlines:

                print(f"    News: {r.news_headlines[0][:80]}")

        print()

    def send_morning_alert(self, results: List[ScanResult]):

        sentiment = get_market_sentiment()

        regime = sentiment["regime"]

        score  = sentiment["composite_score"]

        icons  = {"STRONGLY_BULLISH":"🟢","BULLISH":"📈","NEUTRAL":"⚪","CAUTION":"🟡","BEARISH":"🔴"}

        r_icon = icons.get(regime, "⚪")

        lines = [

            f"📊 <b>BuzzFlow Morning Scan</b>",

            f"{r_icon} Market: {regime} ({score:.0f}/100) | Nifty Rs{sentiment['nifty_price']:,.0f}",

        ]

        if sentiment["bearish_warning"]:

            lines.append("⚠️ <b>BEARISH WARNING</b> — tighten stops, reduce size")

        lines.append("")

        if not results:

            lines.append("No setups cleared the configured score/risk filters in this run.")

            self.alert.send("\n".join(lines))

            return

        # Group by tier
        tier_order  = ["large", "mid", "small", "micro"]
        tier_labels = {"large": "Large Cap", "mid": "Mid Cap", "small": "Small Cap", "micro": "Micro Cap"}
        grouped = {}
        for r in results:
            grouped.setdefault(r.cap_tier, []).append(r)

        for tier in tier_order:

            if tier not in grouped:

                continue

            lines.append(f"<b>── {tier_labels[tier]} ──</b>")

            for r in grouped[tier][:4]:

                icon = "🟢" if r.signal == "STRONG_BUY" else "🔵"

                lines.append(

                    f"{icon} <b>{r.symbol}</b> | Score: {r.entry_score:.0f} | {r.signal}\n"

                    f"   Zone: Rs{r.entry_zone_low:.0f}-{r.entry_zone_high:.0f} | "

                    f"SL: Rs{r.stop_loss:.2f} | Target: Rs{r.target_price:.2f} | R:R: {r.risk_reward}\n"

                    f"   Risk: {r.risk_capital_pct}% capital | Delivery: {r.delivery_score:.0f}/100"

                )

            lines.append("")

        self.alert.send("\n".join(lines))

def main():

    parser = argparse.ArgumentParser(description="BuzzFlow Scanner")

    parser.add_argument("--index",
                        default="all",
                        help="all | large | mid | nifty50 | nifty500 | banking | pharma | nifty_it | auto | capex | consumption | metals | chemicals | realty | telecom | services")

    parser.add_argument("--min-score", type=float, default=65)

    parser.add_argument("--refresh-universe", action="store_true",
                        help="Force re-fetch NSE universe (ignores 24h cache)")

    parser.add_argument("--max-results", type=int, default=10)

    parser.add_argument("--capital", type=float, default=100000)

    parser.add_argument("--auto-watchlist", action="store_true")

    parser.add_argument("--alert", action="store_true")

    args = parser.parse_args()

    # Force refresh universe if requested
    if args.refresh_universe:
        from universe_engine import refresh_universe
        refresh_universe(force=True)

    scanner = ScannerV2()

    results = scanner.scan(

        index=args.index, min_score=args.min_score,

        max_results=args.max_results, capital=args.capital,

        auto_watchlist=args.auto_watchlist

    )

    scanner.print_report(results, args.index)

    if args.alert:

        scanner.send_morning_alert(results)

if __name__ == "__main__":

    main()

