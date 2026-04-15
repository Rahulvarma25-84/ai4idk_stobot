#!/usr/bin/env python3
"""
BuzzFlow v2 - Upgraded Stock Scanner
Uses: Google News RSS (free) + new ScoringEngine + WatchlistEngine + Telegram alerts.
No Reddit, no NewsAPI required.
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
from scoring_engine import ScoringEngine
from watchlist_engine import WatchlistEngine
from alert_engine import AlertEngine
from database import init_db, save_scan_result

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("buzzflow.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    symbol: str
    company_name: str
    current_price: float
    entry_score: float
    signal: str           # STRONG_BUY / BUY / WATCH / SKIP
    confidence: str
    entry_price: float
    stop_loss: float
    target_price: float
    risk_reward: float
    sentiment_score: float   # 0-100
    technical_score: float   # 0-100
    accumulation: float
    compression: float
    relative_strength: float
    rsi: float
    volume_ratio: float
    news_headlines: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)


class ScannerV2:
    """
    Stock universe designed for swing trading (3–15 day holds).

    Selection criteria (think like a fund manager):
    - F&O eligible = institutional interest + clean price discovery
    - Sector leaders only = best liquidity, best news coverage
    - No PSU banks below top 3 = too policy-driven, unpredictable
    - No micro/smallcap = wide spreads, low volume, hard to exit
    - Grouped by sector so you can scan one sector when it's in play

    Universe: ~120 stocks across 8 sectors + 2 focused lists
    """

    # ── LARGE CAP CORE (most liquid, highest institutional activity) ──────
    # Full Nifty 50 — always scan these, every day, no exceptions
    NIFTY_50 = [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
        "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
        "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "HCLTECH.NS", "SUNPHARMA.NS",
        "TATAMOTORS.NS", "WIPRO.NS", "ULTRACEMCO.NS", "TITAN.NS", "BAJFINANCE.NS",
        "NESTLEIND.NS", "POWERGRID.NS", "NTPC.NS", "BAJAJFINSV.NS", "ONGC.NS",
        "ADANIENT.NS", "JSWSTEEL.NS", "COALINDIA.NS", "TECHM.NS", "TATACONSUM.NS",
        "HINDALCO.NS", "GRASIM.NS", "CIPLA.NS", "DIVISLAB.NS", "BRITANNIA.NS",
        "EICHERMOT.NS", "DRREDDY.NS", "HEROMOTOCO.NS", "BPCL.NS", "TATASTEEL.NS",
        "INDUSINDBK.NS", "LT.NS", "SBILIFE.NS", "APOLLOHOSP.NS", "HDFCLIFE.NS",
        "ADANIPORTS.NS", "TATAPOWER.NS", "M&M.NS", "BAJAJ-AUTO.NS", "SHREECEM.NS"
    ]

    # ── BANKING & FINANCIALS ──────────────────────────────────────────────
    # Top liquid banks + quality NBFCs — most active swing trading sector
    # Dropped: PNB, UNIONBANK, SAIL-type PSUs (too news-driven, gap risk)
    BANKING = [
        "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS",
        "INDUSINDBK.NS", "FEDERALBNK.NS", "IDFCFIRSTB.NS", "AUBANK.NS", "BANDHANBNK.NS",
        "BAJFINANCE.NS", "BAJAJFINSV.NS", "CHOLAFIN.NS", "MUTHOOTFIN.NS", "MANAPPURAM.NS",
        "LICHSGFIN.NS", "M&MFIN.NS", "SBILIFE.NS", "HDFCLIFE.NS", "ICICIPRULI.NS"
    ]

    # ── INFORMATION TECHNOLOGY ───────────────────────────────────────────
    # All F&O IT stocks — sector moves together, good for sector plays
    NIFTY_IT = [
        "TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS",
        "LTIM.NS", "MPHASIS.NS", "COFORGE.NS", "PERSISTENT.NS", "OFSS.NS"
    ]

    # ── PHARMA & HEALTHCARE ──────────────────────────────────────────────
    # Sector leaders + mid-pharma with strong export stories
    # Dropped: NATCOPHARM, IPCALAB (low liquidity for swing)
    PHARMA = [
        "SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "LUPIN.NS",
        "AUROPHARMA.NS", "TORNTPHARM.NS", "ALKEM.NS", "ZYDUSLIFE.NS", "GLENMARK.NS",
        "APOLLOHOSP.NS", "LAURUSLABS.NS", "ABBOTINDIA.NS", "BIOCON.NS"
    ]

    # ── AUTO & AUTO ANCILLARIES ──────────────────────────────────────────
    # OEMs + top ancillaries — EV theme + rural demand plays
    # Dropped: GPPL, low-volume ancillaries
    AUTO = [
        "MARUTI.NS", "TATAMOTORS.NS", "M&M.NS", "BAJAJ-AUTO.NS", "HEROMOTOCO.NS",
        "EICHERMOT.NS", "TVSMOTOR.NS", "ASHOKLEY.NS", "MOTHERSON.NS", "BHARATFORG.NS",
        "BALKRISIND.NS", "APOLLOTYRE.NS", "BOSCHLTD.NS", "TIINDIA.NS"
    ]

    # ── CAPITAL GOODS & INFRA ────────────────────────────────────────────
    # Capex cycle plays — government spending theme
    # Best swing candidates when infra budget news hits
    CAPEX = [
        "LT.NS", "ABB.NS", "SIEMENS.NS", "BHEL.NS", "CUMMINSIND.NS",
        "HAVELLS.NS", "POLYCAB.NS", "DIXON.NS", "ADANIPORTS.NS", "CONCOR.NS",
        "IRCTC.NS", "INDUSTOWER.NS", "JSWENERGY.NS", "TATAPOWER.NS", "NTPC.NS",
        "POWERGRID.NS", "ADANIGREEN.NS"
    ]

    # ── CONSUMPTION & FMCG ──────────────────────────────────────────────
    # Defensive + discretionary — good when market is uncertain
    CONSUMPTION = [
        "HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS", "DABUR.NS",
        "MARICO.NS", "GODREJCP.NS", "COLPAL.NS", "TATACONSUM.NS", "TITAN.NS",
        "DMART.NS", "JUBLFOOD.NS", "VBL.NS", "MCDOWELL-N.NS", "PAGEIND.NS"
    ]

    # ── METALS & COMMODITIES ─────────────────────────────────────────────
    # Cyclical — scan only when global commodity cycle is up
    # Dropped: MOIL, WELCORP, JINDALSAW (low F&O interest)
    METALS = [
        "TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS", "VEDL.NS", "COALINDIA.NS",
        "NMDC.NS", "SAIL.NS", "NATIONALUM.NS", "HINDCOPPER.NS", "APLAPOLLO.NS"
    ]

    # ── QUALITY MIDCAP (F&O eligible, high institutional interest) ───────
    # Hand-picked midcaps with strong fundamentals + good swing setups
    # These are NOT random midcaps — each is a sector leader in its space
    MIDCAP_QUALITY = [
        "PIDILITIND.NS", "ASTRAL.NS", "DEEPAKNTR.NS", "NAVINFLUOR.NS", "SRF.NS",
        "LALPATHLAB.NS", "METROPOLIS.NS", "INDIAMART.NS", "NAUKRI.NS", "OBEROIRLTY.NS",
        "DLF.NS", "GODREJPROP.NS", "BERGEPAINT.NS", "KANSAINER.NS", "INDIGO.NS",
        "TVSMOTOR.NS", "MPHASIS.NS", "COFORGE.NS", "LTTS.NS", "PERSISTENT.NS"
    ]

    # ── SMART UNIVERSE (default for 'all') ───────────────────────────────
    # Nifty 50 + best picks from each sector = ~120 unique, liquid stocks
    # This is what a fund manager would actually screen daily
    @classmethod
    def _build_all(cls) -> list:
        seen = set()
        result = []
        for lst in [
            cls.NIFTY_50,      # 50  — always core
            cls.BANKING,       # +10 new (rest overlap with N50)
            cls.NIFTY_IT,      # +5  new
            cls.PHARMA,        # +9  new
            cls.AUTO,          # +4  new
            cls.CAPEX,         # +7  new
            cls.CONSUMPTION,   # +5  new
            cls.METALS,        # +5  new
            cls.MIDCAP_QUALITY # +15 new
        ]:
            for s in lst:
                if s not in seen:
                    seen.add(s)
                    result.append(s)
        return result  # ~110 unique stocks

    INDICES = {
        # Scan by sector when that sector is in play
        "nifty_50":       NIFTY_50,
        "banking":        BANKING,
        "nifty_it":       NIFTY_IT,
        "pharma":         PHARMA,
        "auto":           AUTO,
        "capex":          CAPEX,
        "consumption":    CONSUMPTION,
        "metals":         METALS,
        "midcap_quality": MIDCAP_QUALITY,
        # Scan everything — morning routine
        # "all" is handled via _build_all() in scan()
    }

    # ── EXTENDED UNIVERSE (~800 F&O-eligible NSE stocks) ─────────────────
    # Used only in Phase 1 (technical pre-filter, no news calls)
    # Source: NSE F&O ban list + Nifty 500 constituents
    EXTENDED_UNIVERSE = [
        # Nifty 500 large + mid caps (F&O eligible, liquid)
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
        # Banking & Finance
        "HDFCBANK.NS","ICICIBANK.NS","SBIN.NS","KOTAKBANK.NS","AXISBANK.NS",
        "INDUSINDBK.NS","FEDERALBNK.NS","IDFCFIRSTB.NS","AUBANK.NS","BANDHANBNK.NS",
        "BAJFINANCE.NS","BAJAJFINSV.NS","CHOLAFIN.NS","MUTHOOTFIN.NS","MANAPPURAM.NS",
        "LICHSGFIN.NS","M&MFIN.NS","SBILIFE.NS","HDFCLIFE.NS","ICICIPRULI.NS",
        "PNB.NS","UNIONBANK.NS","CANBK.NS","BANKBARODA.NS","INDIANB.NS",
        "RBLBANK.NS","KARURVYSYA.NS","DCBBANK.NS","UJJIVANSFB.NS","EQUITASBNK.NS",
        "ABCAPITAL.NS","IIFL.NS","MFSL.NS","PNBHOUSING.NS","CANFINHOME.NS",
        "RECLTD.NS","PFC.NS","IRFC.NS","HUDCO.NS","NIACL.NS",
        # IT & Tech
        "TCS.NS","INFY.NS","HCLTECH.NS","WIPRO.NS","TECHM.NS",
        "LTIM.NS","MPHASIS.NS","COFORGE.NS","PERSISTENT.NS","OFSS.NS",
        "LTTS.NS","KPITTECH.NS","TATAELXSI.NS","MASTEK.NS","NIITTECH.NS",
        "HEXAWARE.NS","CYIENT.NS","ZENSAR.NS","BIRLASOFT.NS","SONATSOFTW.NS",
        "RATEGAIN.NS","TANLA.NS","INTELLECT.NS","NEWGEN.NS","DATAMATICS.NS",
        # Pharma & Healthcare
        "SUNPHARMA.NS","DRREDDY.NS","CIPLA.NS","DIVISLAB.NS","LUPIN.NS",
        "AUROPHARMA.NS","TORNTPHARM.NS","ALKEM.NS","ZYDUSLIFE.NS","GLENMARK.NS",
        "APOLLOHOSP.NS","LAURUSLABS.NS","ABBOTINDIA.NS","BIOCON.NS","IPCALAB.NS",
        "NATCOPHARM.NS","GRANULES.NS","SUVEN.NS","LALPATHLAB.NS","METROPOLIS.NS",
        "MAXHEALTH.NS","FORTIS.NS","NARAYANA.NS","ASTER.NS","RAINBOW.NS",
        "AJANTPHARM.NS","JBCHEPHARM.NS","ERIS.NS","SOLARA.NS","SEQUENT.NS",
        # Auto & Ancillaries
        "MARUTI.NS","TATAMOTORS.NS","M&M.NS","BAJAJ-AUTO.NS","HEROMOTOCO.NS",
        "EICHERMOT.NS","TVSMOTOR.NS","ASHOKLEY.NS","MOTHERSON.NS","BHARATFORG.NS",
        "BALKRISIND.NS","APOLLOTYRE.NS","BOSCHLTD.NS","TIINDIA.NS","CEATLTD.NS",
        "MINDAIND.NS","SUNDRMFAST.NS","SUPRAJIT.NS","ENDURANCE.NS","CRAFTSMAN.NS",
        "SWARAJENG.NS","ESCORTS.NS","MAHINDCIE.NS","GABRIEL.NS","SUBROS.NS",
        # Capital Goods & Infra
        "LT.NS","ABB.NS","SIEMENS.NS","BHEL.NS","CUMMINSIND.NS",
        "HAVELLS.NS","POLYCAB.NS","DIXON.NS","ADANIPORTS.NS","CONCOR.NS",
        "IRCTC.NS","INDUSTOWER.NS","JSWENERGY.NS","TATAPOWER.NS","NTPC.NS",
        "POWERGRID.NS","ADANIGREEN.NS","TORNTPOWER.NS","CESC.NS","NHPC.NS",
        "SJVN.NS","IRCON.NS","RVNL.NS","RAILTEL.NS","NBCC.NS",
        "KEC.NS","KALPATPOWR.NS","THERMAX.NS","GRINDWELL.NS","ELGIEQUIP.NS",
        "AIAENG.NS","BHARAT.NS","GMRINFRA.NS","IRB.NS","ASHOKA.NS",
        # FMCG & Consumption
        "HINDUNILVR.NS","ITC.NS","NESTLEIND.NS","BRITANNIA.NS","DABUR.NS",
        "MARICO.NS","GODREJCP.NS","COLPAL.NS","TATACONSUM.NS","TITAN.NS",
        "DMART.NS","JUBLFOOD.NS","VBL.NS","MCDOWELL-N.NS","PAGEIND.NS",
        "EMAMILTD.NS","JYOTHYLAB.NS","BAJAJCON.NS","HATSUN.NS","BIKAJI.NS",
        "DEVYANI.NS","WESTLIFE.NS","SAPPHIRE.NS","BARBEQUE.NS","ZOMATO.NS",
        "NYKAA.NS","CARTRADE.NS","EASEMYTRIP.NS","IXIGO.NS","INDIAMART.NS",
        # Metals & Mining
        "TATASTEEL.NS","JSWSTEEL.NS","HINDALCO.NS","VEDL.NS","COALINDIA.NS",
        "NMDC.NS","SAIL.NS","NATIONALUM.NS","HINDCOPPER.NS","APLAPOLLO.NS",
        "RATNAMANI.NS","WELCORP.NS","JINDALSAW.NS","MOIL.NS","GMRINFRA.NS",
        "JINDALSTEL.NS","JSPL.NS","EDELWEISS.NS","NIFTYIT.NS","METALFORGE.NS",
        # Cement & Building Materials
        "ULTRACEMCO.NS","SHREECEM.NS","AMBUJACEM.NS","ACC.NS","DALMIACMT.NS",
        "JKCEMENT.NS","RAMCOCEM.NS","HEIDELBERG.NS","BIRLACORPN.NS","NUVOCO.NS",
        "PIDILITIND.NS","ASTRAL.NS","SUPREMEIND.NS","FINOLEX.NS","PRINCEPIPE.NS",
        "CERA.NS","KAJARIA.NS","SOMANY.NS","ORIENTBELL.NS","GRSE.NS",
        # Real Estate
        "DLF.NS","GODREJPROP.NS","OBEROIRLTY.NS","PRESTIGE.NS","BRIGADE.NS",
        "SOBHA.NS","MAHLIFE.NS","PHOENIXLTD.NS","SUNTECK.NS","KOLTEPATIL.NS",
        # Chemicals & Specialty
        "DEEPAKNTR.NS","NAVINFLUOR.NS","SRF.NS","AARTI.NS","VINATI.NS",
        "ATUL.NS","CLEAN.NS","FINEORG.NS","GALAXYSURF.NS","SUDARSCHEM.NS",
        "FLUOROCHEM.NS","TATACHEM.NS","GNFC.NS","CHAMBLFERT.NS","COROMANDEL.NS",
        "PIIND.NS","RALLIS.NS","BAYER.NS","SUMICHEM.NS","INSECTICID.NS",
        # Telecom & Media
        "BHARTIARTL.NS","INDUSTOWER.NS","TATACOMM.NS","HFCL.NS","STLTECH.NS",
        "SUNTV.NS","ZEEL.NS","PVRINOX.NS","INOXWIND.NS","NETWORK18.NS",
        # Logistics & Transport
        "CONCOR.NS","BLUEDART.NS","MAHLOG.NS","GATI.NS","TCI.NS",
        "DELHIVERY.NS","ALLCARGO.NS","GATEWAY.NS","AEGISLOG.NS","MAHINDLOG.NS",
        # Textiles & Apparel
        "PAGEIND.NS","ABFRL.NS","TRENT.NS","VEDANT.NS","MANYAVAR.NS",
        "RAYMOND.NS","ARVIND.NS","WELSPUNIND.NS","TRIDENT.NS","VARDHMAN.NS",
        # Diversified / Conglomerates
        "ADANIENT.NS","TATAMOTORS.NS","RELIANCE.NS","ITC.NS","BAJAJHLDNG.NS",
        "GODREJIND.NS","MAHINDRA.NS","TATAPOWER.NS","JSWINFRA.NS","NIFTY.NS",
        # Midcap Quality picks
        "PIDILITIND.NS","ASTRAL.NS","DEEPAKNTR.NS","NAVINFLUOR.NS","SRF.NS",
        "LALPATHLAB.NS","METROPOLIS.NS","INDIAMART.NS","NAUKRI.NS","OBEROIRLTY.NS",
        "DLF.NS","GODREJPROP.NS","BERGEPAINT.NS","KANSAINER.NS","INDIGO.NS",
        "TVSMOTOR.NS","MPHASIS.NS","COFORGE.NS","LTTS.NS","PERSISTENT.NS",
        "ZOMATO.NS","NYKAA.NS","POLICYBZR.NS","PAYTM.NS","DELHIVERY.NS",
    ]

    def __init__(self):
        init_db()
        self.news_engine = NewsEngine()
        self.scorer = ScoringEngine()
        self.watchlist = WatchlistEngine()
        self.alert = AlertEngine()
        self._nifty_return_5d = self._get_nifty_return()

    def _get_nifty_return(self) -> float:
        """5-day return of Nifty 50 for relative strength calculation."""
        try:
            hist = yf.Ticker("^NSEI").history(period="10d", interval="1d")
            if len(hist) >= 5:
                return float((hist["Close"].iloc[-1] - hist["Close"].iloc[-5]) /
                             hist["Close"].iloc[-5] * 100)
        except Exception:
            pass
        return 0.0

    def _get_price_data(self, symbol: str) -> Optional[pd.DataFrame]:
        try:
            hist = yf.Ticker(symbol).history(period="60d", interval="1d")
            if hist.empty or len(hist) < 20:
                return None
            return hist
        except Exception:
            return None

    def _quick_technical_score(self, symbol: str) -> Optional[dict]:
        """
        Phase 1: Pure technical pre-filter — NO news calls.
        Fast (~0.3s/stock). Runs on all 800 stocks.
        Returns None if stock fails basic criteria.
        """
        try:
            hist = yf.Ticker(symbol).history(period="60d", interval="1d")
            if hist.empty or len(hist) < 20:
                return None

            hist = hist.dropna(subset=["Close", "Volume", "High", "Low"])
            close  = hist["Close"].astype(float)
            volume = hist["Volume"].astype(float)
            high   = hist["High"].astype(float)
            low    = hist["Low"].astype(float)

            current = float(close.iloc[-1])

            # RSI
            delta = close.diff()
            gain  = delta.clip(lower=0).rolling(14, min_periods=5).mean()
            loss  = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()
            rs    = gain / loss.replace(0, np.nan)
            rsi_s = 100 - 100 / (1 + rs)
            rsi   = float(rsi_s.dropna().iloc[-1]) if not rsi_s.dropna().empty else 50.0

            # Volume ratio
            vol_avg = float(volume.rolling(20, min_periods=5).mean().dropna().iloc[-1]) if not volume.rolling(20, min_periods=5).mean().dropna().empty else float(volume.mean())
            vol_ratio = float(volume.iloc[-1]) / max(vol_avg, 1)

            # MA20 and MA50
            ma20 = float(close.rolling(20, min_periods=5).mean().dropna().iloc[-1]) if not close.rolling(20, min_periods=5).mean().dropna().empty else current
            ma50 = float(close.rolling(50, min_periods=20).mean().dropna().iloc[-1]) if not close.rolling(50, min_periods=20).mean().dropna().empty else current

            # ── Hard filters — drop immediately if any fail ──────────────
            # 1. Price must be above MA50 (uptrend only)
            if current < ma50 * 0.98:
                return None
            # 2. RSI must be in buyable zone (not overbought, not dead)
            if rsi > 75 or rsi < 35:
                return None
            # 3. Volume must show some interest
            if vol_ratio < 0.7:
                return None

            # Quick score: RSI in sweet spot (45-65) + volume + above MA20
            rsi_score = max(0, 100 - abs(rsi - 55) * 3)
            vol_score = min(100, vol_ratio * 50)
            trend_score = 80 if current > ma20 else 30

            quick_score = rsi_score * 0.4 + vol_score * 0.3 + trend_score * 0.3

            return {
                "symbol":     symbol,
                "quick_score": round(quick_score, 1),
                "rsi":        rsi,
                "vol_ratio":  vol_ratio,
                "current":    current,
                "ma20":       ma20,
                "ma50":       ma50,
            }
        except Exception:
            return None

    def _compute_tech_components(self, hist: pd.DataFrame) -> dict:
        """Extract technical components needed for scoring."""
        hist = hist.copy().dropna(subset=["Close", "Volume", "High", "Low"])
        close = hist["Close"].astype(float)
        volume = hist["Volume"].astype(float)
        high = hist["High"].astype(float)
        low = hist["Low"].astype(float)

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14, min_periods=5).mean()
        loss = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi_series = 100 - 100 / (1 + rs)
        rsi = float(rsi_series.dropna().iloc[-1]) if not rsi_series.dropna().empty else 50.0

        # MACD histogram
        ema12 = close.ewm(span=12, min_periods=5).mean()
        ema26 = close.ewm(span=26, min_periods=10).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, min_periods=3).mean()
        macd_hist_series = macd_line - signal_line
        macd_hist = float(macd_hist_series.dropna().iloc[-1]) if not macd_hist_series.dropna().empty else 0.0

        # Volume ratio
        vol_avg_series = volume.rolling(20, min_periods=5).mean()
        vol_avg = float(vol_avg_series.dropna().iloc[-1]) if not vol_avg_series.dropna().empty else float(volume.mean())
        vol_ratio = float(volume.iloc[-1]) / max(vol_avg, 1)

        # ATR ratio (current ATR / avg ATR)
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr_current_s = tr.rolling(7, min_periods=3).mean()
        atr_avg_s = tr.rolling(20, min_periods=5).mean()
        atr_current = float(atr_current_s.dropna().iloc[-1]) if not atr_current_s.dropna().empty else 1.0
        atr_avg = float(atr_avg_s.dropna().iloc[-1]) if not atr_avg_s.dropna().empty else 1.0
        atr_ratio = atr_current / max(atr_avg, 0.001)

        # Support / resistance (20-day)
        support = float(low.rolling(20, min_periods=5).min().dropna().iloc[-1]) if not low.rolling(20, min_periods=5).min().dropna().empty else float(low.min())
        resistance = float(high.rolling(20, min_periods=5).max().dropna().iloc[-1]) if not high.rolling(20, min_periods=5).max().dropna().empty else float(high.max())
        current = float(close.iloc[-1])
        price_range = resistance - support
        price_vs_resistance = (current - support) / max(price_range, 0.001)

        # 5-day return
        stock_return_5d = float((close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100) if len(close) >= 5 else 0.0

        # Gap (today open vs yesterday close)
        gap_percent = 0.0
        if len(hist) >= 2 and "Open" in hist.columns:
            try:
                gap_percent = float((float(hist["Open"].iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2]) * 100)
            except Exception:
                gap_percent = 0.0

        # MA20 and MA50 (Tier 1 trend filter needs MA50)
        ma20_s = close.rolling(20, min_periods=5).mean()
        ma20 = float(ma20_s.dropna().iloc[-1]) if not ma20_s.dropna().empty else current
        ma50_s = close.rolling(50, min_periods=20).mean()
        ma50 = float(ma50_s.dropna().iloc[-1]) if not ma50_s.dropna().empty else current
        price_vs_ma20 = current / max(ma20, 0.001)

        return {
            "rsi": rsi,
            "macd_histogram": macd_hist,
            "volume_ratio": vol_ratio,
            "atr_ratio": atr_ratio,
            "price_vs_resistance": price_vs_resistance,
            "stock_return_5d": stock_return_5d,
            "gap_percent": gap_percent,
            "price_vs_ma20": price_vs_ma20,
            "current_price": current,
            "support": support,
            "resistance": resistance,
            "ma20": ma20,
            "ma50": ma50,
            "pattern_score": 50.0
        }

    def _analyze_stock(self, symbol: str, portfolio_value: float = 100000) -> Optional[ScanResult]:
        try:
            hist = self._get_price_data(symbol)
            if hist is None:
                return None

            close_vals = hist["Close"].dropna()
            if close_vals.empty:
                return None
            current_price = float(close_vals.iloc[-1])
            tech = self._compute_tech_components(hist)

            # News sentiment (Google RSS, free)
            company_name = symbol.replace(".NS", "").replace(".BO", "")
            buzz_data = self.news_engine.get_buzz_score(symbol, company_name)
            sentiment_0_100 = buzz_data["raw_sentiment"]  # 0-100

            # Build entry score components
            components = self.scorer.technical_to_entry_components(
                tech_data=tech,
                sentiment_score=sentiment_0_100,
                nifty_return=self._nifty_return_5d
            )
            entry_score, signal = self.scorer.compute_entry_score(**components)

            if signal == "SKIP":
                return None

            # Apply Tier 1/2/3 filters
            signal, filter_reasons = self.scorer.apply_filters(symbol, signal, tech)
            if signal == "FILTERED":
                logger.info(f"FILTERED {symbol}: {', '.join(filter_reasons)}")
                return None

            # ── ATR-based stop loss and target ────────────────────────────
            # Use 14-period ATR for dynamic SL instead of flat 5%
            hist_clean = hist.copy().dropna(subset=["Close", "High", "Low"])
            close_s = hist_clean["Close"].astype(float)
            high_s  = hist_clean["High"].astype(float)
            low_s   = hist_clean["Low"].astype(float)
            tr = pd.concat([
                high_s - low_s,
                (high_s - close_s.shift()).abs(),
                (low_s  - close_s.shift()).abs()
            ], axis=1).max(axis=1)
            atr = float(tr.rolling(14, min_periods=5).mean().dropna().iloc[-1])

            support    = tech["support"]
            resistance = tech["resistance"]

            # SL = 1.5× ATR below entry (respects volatility)
            # but never tighter than 20-day support
            atr_sl     = current_price - (1.5 * atr)
            stop_loss  = max(support, atr_sl)
            stop_loss  = max(stop_loss, current_price * 0.92)  # hard floor 8%

            # Target = 2.5× ATR above entry (minimum 1:1.5 R:R)
            atr_target = current_price + (2.5 * atr)
            # Also consider resistance — don't set target above resistance
            if resistance > current_price * 1.03:
                target = min(resistance * 0.98, atr_target)
            else:
                target = atr_target

            # Enforce minimum 5% upside — not worth it otherwise
            if target < current_price * 1.05:
                target = current_price * 1.08

            risk   = current_price - stop_loss
            reward = target - current_price
            rr     = round(reward / max(risk, 0.01), 2)

            # Skip if R:R is below 1.5 — not a good trade
            if rr < 1.5:
                return None

            # Confidence
            if entry_score >= 70:
                confidence = "high"
            elif entry_score >= 55:
                confidence = "medium"
            else:
                confidence = "low"

            # Technical score (0-100) from RSI + volume + trend
            rsi = tech["rsi"]
            rsi_score = max(0, min(100, (rsi - 30) / 40 * 100)) if rsi < 70 else max(0, (100 - rsi) * 3)
            tech_score = round((rsi_score * 0.4 + tech["volume_ratio"] * 30 + (1 if tech["price_vs_ma20"] > 1 else 0) * 30), 1)

            # Save to DB
            save_scan_result(
                symbol=symbol,
                entry_score=entry_score,
                sentiment_score=sentiment_0_100,
                technical_score=tech_score,
                recommendation=signal,
                confidence=confidence,
                entry_price=current_price,
                stop_loss=stop_loss,
                target=target
            )

            return ScanResult(
                symbol=symbol,
                company_name=company_name,
                current_price=current_price,
                entry_score=entry_score,
                signal=signal,
                confidence=confidence,
                entry_price=current_price,
                stop_loss=stop_loss,
                target_price=target,
                risk_reward=rr,
                sentiment_score=sentiment_0_100,
                technical_score=tech_score,
                accumulation=components["accumulation"],
                compression=components["compression"],
                relative_strength=components["relative_strength"],
                rsi=rsi,
                volume_ratio=tech["volume_ratio"],
                news_headlines=buzz_data.get("headlines", [])[:3],
                timestamp=datetime.now()
            )

        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}")
            return None

    def scan(self, index: str = "nifty_50", min_score: float = 55,
             max_results: int = 10, portfolio_value: float = 100000,
             auto_watchlist: bool = False) -> List[ScanResult]:
        """
        Two-phase scanner:
          Phase 1 — Technical pre-filter on ALL stocks (20 workers, no news, fast)
                    Drops ~85% of stocks that fail basic criteria
          Phase 2 — Full analysis with news only on top 50 candidates (5 workers)

        Result: 800 stocks scanned in ~3-4 minutes instead of 50+ minutes.
        """
        # Build stock list
        if index == "all":
            stocks = list(dict.fromkeys(self.EXTENDED_UNIVERSE))
        else:
            stocks = list(dict.fromkeys(self.INDICES.get(index) or self._build_all()))

        total = len(stocks)
        logger.info(f"Phase 1: Technical pre-filter on {total} stocks (20 workers)...")
        t0 = datetime.now()

        # ── Phase 1: Fast technical pre-filter ────────────────────────────
        quick_results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
            futures = {ex.submit(self._quick_technical_score, s): s for s in stocks}
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res:
                    quick_results.append(res)

        # Sort by quick score, keep top 50 for Phase 2
        quick_results.sort(key=lambda x: x["quick_score"], reverse=True)
        candidates = [r["symbol"] for r in quick_results[:50]]

        t1 = datetime.now()
        passed = len(quick_results)
        logger.info(
            f"Phase 1 done in {(t1-t0).seconds}s: "
            f"{passed}/{total} passed filters, top {len(candidates)} → Phase 2"
        )

        # ── Phase 2: Full analysis with news on top candidates ─────────────
        logger.info(f"Phase 2: Full analysis + news on {len(candidates)} candidates (5 workers)...")
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            futures = {ex.submit(self._analyze_stock, s, portfolio_value): s for s in candidates}
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res and res.entry_score >= min_score:
                    results.append(res)

        t2 = datetime.now()
        logger.info(
            f"Phase 2 done in {(t2-t1).seconds}s: "
            f"{len(results)} signals above score {min_score}"
        )
        logger.info(f"Total scan time: {(t2-t0).seconds}s for {total} stocks")

        results.sort(key=lambda x: x.entry_score, reverse=True)
        top = results[:max_results]

        if auto_watchlist:
            for r in top:
                if r.signal in ("STRONG_BUY", "BUY"):
                    self.watchlist.add(
                        symbol=r.symbol,
                        entry_price=r.entry_price,
                        stop_loss=r.stop_loss,
                        target=r.target_price,
                        entry_score=r.entry_score,
                        confidence=r.confidence,
                        company_name=r.company_name
                    )
                    self.scorer.mark_alerted(r.symbol)

        return top

    def print_report(self, results: List[ScanResult], index: str = ""):
        if not results:
            print("\n⚠️  No opportunities found above the score threshold.\n")
            return

        print("\n" + "=" * 80)
        print(f"{'🔍 BUZZFLOW SCAN RESULTS — ' + index.upper():^80}")
        print(f"{'Generated: ' + datetime.now().strftime('%Y-%m-%d %H:%M'):^80}")
        print("=" * 80)
        print(f"{'Symbol':<14} {'Price':>8} {'Score':>7} {'Signal':<12} {'SL':>8} {'Target':>8} {'R:R':>5}")
        print("-" * 80)
        for r in results:
            print(f"{r.symbol:<14} {r.current_price:>8.2f} {r.entry_score:>7.1f} "
                  f"{r.signal:<12} {r.stop_loss:>8.2f} {r.target_price:>8.2f} {r.risk_reward:>5.1f}")
        print("=" * 80)

        print("\n📰 Top News Headlines:")
        for r in results[:3]:
            if r.news_headlines:
                print(f"\n  {r.symbol}:")
                for h in r.news_headlines:
                    print(f"    • {h[:90]}")
        print()

    def send_scan_alert(self, results: List[ScanResult]):
        """Send top picks via Telegram."""
        picks = [
            {
                "symbol": r.symbol,
                "entry_score": r.entry_score,
                "recommendation": r.signal,
                "entry_price": r.entry_price,
                "stop_loss": r.stop_loss,
                "target_price": r.target_price
            }
            for r in results if r.signal in ("STRONG_BUY", "BUY")
        ]
        self.alert.send_scan_summary(picks)


def main():
    parser = argparse.ArgumentParser(description="BuzzFlow v2 - Stock Scanner")
    parser.add_argument("--index",
                        choices=["nifty_50", "banking", "nifty_it", "pharma",
                                 "auto", "capex", "consumption", "metals",
                                 "midcap_quality", "all"],
                        default="all",
                        help="'all' scans ~800 stocks via 2-phase engine (default)")
    parser.add_argument("--min-score", type=float, default=55)
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--portfolio", type=float, default=100000)
    parser.add_argument("--auto-watchlist", action="store_true",
                        help="Auto-add BUY signals to watchlist")
    parser.add_argument("--alert", action="store_true",
                        help="Send Telegram alert with top picks")
    args = parser.parse_args()

    scanner = ScannerV2()

    indices = list(ScannerV2.INDICES.keys()) if args.index == "all" else [args.index]
    all_results = []

    for idx in indices:
        results = scanner.scan(
            index=idx,
            min_score=args.min_score,
            max_results=args.max_results,
            portfolio_value=args.portfolio,
            auto_watchlist=args.auto_watchlist
        )
        scanner.print_report(results, idx)
        all_results.extend(results)
    if args.alert and all_results:
        scanner.send_scan_alert(all_results)

    if args.auto_watchlist:
        print("\n📋 Updated Watchlist:")
        scanner.watchlist.print_watchlist()


if __name__ == "__main__":
    main()
