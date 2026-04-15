"""
BuzzFlow - Monitoring Engine
Runs 2-3x/day to compute exit scores for watchlist stocks and fire alerts.
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime

import yfinance as yf
import numpy as np

from watchlist_engine import WatchlistEngine
from scoring_engine import ScoringEngine
from alert_engine import AlertEngine


logger = logging.getLogger(__name__)


def _get_nifty_weakness() -> float:
    """Return a 0-100 weakness score for Nifty 50 based on recent price action."""
    try:
        nifty = yf.Ticker("^NSEI")
        hist = nifty.history(period="5d", interval="1d")
        if len(hist) < 2:
            return 0.0
        ret = (hist["Close"].iloc[-1] - hist["Close"].iloc[-2]) / hist["Close"].iloc[-2] * 100
        # Negative return → weakness
        weakness = max(0.0, -ret * 10)
        return min(100.0, weakness)
    except Exception as e:
        logger.warning(f"Could not fetch Nifty data: {e}")
        return 0.0


def _fetch_tech_data(symbol: str) -> Optional[dict]:
    """Fetch minimal technical data needed for exit scoring."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="30d", interval="1d")
        if hist.empty or len(hist) < 10:
            return None

        close = hist["Close"]
        volume = hist["Volume"]

        # RSI (14)
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = float((100 - 100 / (1 + rs)).iloc[-1])

        # MACD histogram
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9).mean()
        macd_hist = float((macd_line - signal_line).iloc[-1])

        # Volume ratio (current vs 20-day avg)
        vol_avg = float(volume.rolling(20).mean().iloc[-1])
        vol_ratio = float(volume.iloc[-1]) / max(vol_avg, 1)

        # Price vs MA20
        ma20 = float(close.rolling(20).mean().iloc[-1])
        price_vs_ma20 = float(close.iloc[-1]) / max(ma20, 0.01)

        return {
            "rsi": rsi,
            "macd_histogram": macd_hist,
            "volume_ratio": vol_ratio,
            "price_vs_ma20": price_vs_ma20,
            "current_price": float(close.iloc[-1])
        }
    except Exception as e:
        logger.error(f"Error fetching tech data for {symbol}: {e}")
        return None


class MonitoringEngine:
    """
    Monitors active watchlist positions and generates exit signals.
    Designed to run 2-3 times per day (morning, midday, afternoon).
    """

    def __init__(self, telegram_token: str = None, telegram_chat_id: str = None):
        self.watchlist = WatchlistEngine()
        self.scorer = ScoringEngine()
        self.alert = AlertEngine(token=telegram_token, chat_id=telegram_chat_id)

    def run(self) -> List[Dict]:
        """
        Main monitoring loop. Returns list of monitoring results.
        """
        active = self.watchlist.get_active()
        if not active:
            logger.info("Monitoring: watchlist is empty.")
            return []

        nifty_weakness = _get_nifty_weakness()
        results = []

        for position in active:
            symbol = position["symbol"]
            entry_price = position["entry_price"]
            stop_loss = position["stop_loss"]
            target = position["target"]

            tech = _fetch_tech_data(symbol)
            if tech is None:
                logger.warning(f"Skipping {symbol}: no data")
                continue

            current_price = tech["current_price"]

            # ── Sanity check: skip invalid watchlist entries ───────────────
            # SL must be below entry, target must be above entry
            if stop_loss >= entry_price:
                logger.warning(f"SKIPPING {symbol}: SL ₹{stop_loss} >= Entry ₹{entry_price} — invalid entry, removing")
                self.watchlist.close_position(symbol, entry_price, exit_reason="INVALID_ENTRY", entry_price=entry_price)
                continue
            if target <= entry_price:
                logger.warning(f"SKIPPING {symbol}: Target ₹{target} <= Entry ₹{entry_price} — invalid entry, removing")
                self.watchlist.close_position(symbol, entry_price, exit_reason="INVALID_ENTRY", entry_price=entry_price)
                continue

            # Hard stop-loss / target hit check
            if current_price <= stop_loss:
                pnl = round(((current_price - entry_price) / entry_price) * 100, 2)
                self.watchlist.close_position(
                    symbol, current_price, exit_score=100,
                    exit_reason="STOP_LOSS_HIT", entry_price=entry_price
                )
                msg = (f"🛑 STOP LOSS HIT: {symbol}\n"
                       f"Price: ₹{current_price:.2f} | SL: ₹{stop_loss:.2f}\n"
                       f"PnL: {pnl}%")
                self.alert.send(msg)
                results.append({"symbol": symbol, "decision": "EXIT", "reason": "STOP_LOSS_HIT",
                                 "exit_score": 100, "current_price": current_price, "pnl": pnl})
                continue

            if current_price >= target:
                pnl = round(((current_price - entry_price) / entry_price) * 100, 2)
                self.watchlist.close_position(
                    symbol, current_price, exit_score=0,
                    exit_reason="TARGET_HIT", entry_price=entry_price
                )
                msg = (f"🎯 TARGET HIT: {symbol}\n"
                       f"Price: ₹{current_price:.2f} | Target: ₹{target:.2f}\n"
                       f"Profit: +{pnl}%")
                self.alert.send(msg)
                results.append({"symbol": symbol, "decision": "EXIT", "reason": "TARGET_HIT",
                                 "exit_score": 0, "current_price": current_price, "pnl": pnl})
                continue

            # Compute exit score
            components = self.scorer.technical_to_exit_components(
                tech_data=tech,
                entry_price=entry_price,
                current_price=current_price,
                target=target,
                nifty_weakness=nifty_weakness
            )
            exit_score, decision = self.scorer.compute_exit_score(**components)

            pnl = round(((current_price - entry_price) / entry_price) * 100, 2)

            result = {
                "symbol": symbol,
                "current_price": current_price,
                "entry_price": entry_price,
                "pnl": pnl,
                "exit_score": exit_score,
                "decision": decision,
                "components": components
            }
            results.append(result)

            # Update watchlist status
            self.watchlist.update_status(symbol, decision,
                                         notes=f"exit_score={exit_score:.1f} pnl={pnl}%")

            # Send alerts for EXIT / CAUTION
            if decision == "EXIT":
                self.watchlist.close_position(
                    symbol, current_price, exit_score=exit_score,
                    exit_reason="EXIT_SIGNAL", entry_price=entry_price
                )
                msg = (f"⚠️ EXIT SIGNAL: {symbol}\n"
                       f"Exit Score: {exit_score:.1f}/100\n"
                       f"Price: ₹{current_price:.2f} | PnL: {pnl}%\n"
                       f"Reason: Momentum/trend weakening")
                self.alert.send(msg)

            elif decision == "CAUTION":
                msg = (f"🟡 CAUTION: {symbol}\n"
                       f"Exit Score: {exit_score:.1f}/100\n"
                       f"Price: ₹{current_price:.2f} | PnL: {pnl}%\n"
                       f"Consider tightening stop loss.")
                self.alert.send(msg)

            logger.info(f"Monitor {symbol}: score={exit_score:.1f} → {decision} | PnL={pnl}%")

        return results

    def print_report(self, results: List[Dict]):
        if not results:
            print("\n📊 No active positions to monitor.\n")
            return

        print("\n" + "=" * 70)
        print(f"{'📊 MONITORING REPORT — ' + datetime.now().strftime('%Y-%m-%d %H:%M'):^70}")
        print("=" * 70)
        print(f"{'Symbol':<12} {'Price':>8} {'PnL%':>7} {'ExitScore':>10} {'Decision'}")
        print("-" * 70)
        for r in results:
            pnl_str = f"{r['pnl']:+.2f}%" if r.get("pnl") is not None and not (isinstance(r['pnl'], float) and r['pnl'] != r['pnl']) else "-"
            score_str = f"{r['exit_score']:.1f}" if r.get("exit_score") is not None else "-"
            price_str = f"{r['current_price']:.2f}" if r.get("current_price") and r['current_price'] == r['current_price'] else "-"
            print(f"{r['symbol']:<12} {price_str:>8} {pnl_str:>7} "
                  f"{score_str:>10} {r['decision']}")
        print("=" * 70 + "\n")
