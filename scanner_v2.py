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
    Upgraded scanner using the new architecture:
    - Google News RSS for sentiment (free, no limits)
    - ScoringEngine for entry/exit scoring
    - WatchlistEngine for persistence
    - AlertEngine for Telegram
    """

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

    BANK_NIFTY = [
        "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS",
        "INDUSINDBK.NS", "BANDHANBNK.NS", "FEDERALBNK.NS", "RBLBANK.NS", "PNB.NS",
        "UNIONBANK.NS", "IDFCFIRSTB.NS", "AUBANK.NS"
    ]

    NIFTY_IT = [
        "TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS",
        "LTIM.NS", "MPHASIS.NS", "COFORGE.NS", "PERSISTENT.NS", "OFSS.NS"
    ]

    INDICES = {
        "nifty_50": NIFTY_50,
        "bank_nifty": BANK_NIFTY,
        "nifty_it": NIFTY_IT
    }

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

        # MA20
        ma20_s = close.rolling(20, min_periods=5).mean()
        ma20 = float(ma20_s.dropna().iloc[-1]) if not ma20_s.dropna().empty else current
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
            "pattern_score": 50.0  # placeholder; BuzzEnhancer provides this
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

            # Risk levels
            support = tech["support"]
            resistance = tech["resistance"]
            stop_loss = max(support, current_price * 0.95)
            target = min(resistance, current_price * 1.15) if resistance > current_price else current_price * 1.12

            risk = current_price - stop_loss
            reward = target - current_price
            rr = round(reward / max(risk, 0.01), 2)

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
        Run a full scan on the given index.
        Returns top results sorted by entry_score.
        """
        stocks = self.INDICES.get(index, self.NIFTY_50)
        logger.info(f"Scanning {len(stocks)} stocks in {index}...")

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            futures = {ex.submit(self._analyze_stock, s, portfolio_value): s for s in stocks}
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res and res.entry_score >= min_score:
                    results.append(res)

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
    parser.add_argument("--index", choices=["nifty_50", "bank_nifty", "nifty_it", "all"],
                        default="nifty_50")
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
