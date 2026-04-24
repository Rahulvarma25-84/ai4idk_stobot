"""
BuzzFlow - Monitoring Engine
Runs 2-3x/day. Updates exit scores, trade states, trailing stops.
Sends alerts ONLY when action is needed. No spam.
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime

import yfinance as yf
import numpy as np

from watchlist_engine import WatchlistEngine
from scoring_engine import ScoringEngine
from alert_engine import AlertEngine
from trade_state import classify_trade_state, compute_opportunity_score, compute_trailing_stop
from delivery_engine import get_delivery_score

logger = logging.getLogger(__name__)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def _get_nifty_weakness() -> float:
    try:
        hist = yf.Ticker("^NSEI").history(period="5d", interval="1d")
        if len(hist) < 2:
            return 0.0
        ret = (hist["Close"].iloc[-1] - hist["Close"].iloc[-2]) / hist["Close"].iloc[-2] * 100
        return min(100.0, max(0.0, -ret * 10))
    except Exception as e:
        logger.warning(f"Nifty data failed: {e}")
        return 0.0


def _fetch_tech_data(symbol: str) -> Optional[dict]:
    try:
        hist = yf.Ticker(symbol).history(period="30d", interval="1d")
        if hist.empty or len(hist) < 10:
            return None
        close  = hist["Close"].astype(float)
        volume = hist["Volume"].astype(float)

        # RSI
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14, min_periods=5).mean()
        loss  = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi_s = 100 - 100 / (1 + rs)
        rsi   = float(rsi_s.dropna().iloc[-1]) if not rsi_s.dropna().empty else 50.0

        # MACD
        ema12 = close.ewm(span=12, min_periods=5).mean()
        ema26 = close.ewm(span=26, min_periods=10).mean()
        macd_line = ema12 - ema26
        macd_hist = float((macd_line - macd_line.ewm(span=9, min_periods=3).mean()).dropna().iloc[-1]) if not (macd_line - macd_line.ewm(span=9, min_periods=3).mean()).dropna().empty else 0.0

        # Volume ratio
        vol_avg   = float(volume.rolling(20, min_periods=5).mean().dropna().iloc[-1]) if not volume.rolling(20, min_periods=5).mean().dropna().empty else float(volume.mean())
        vol_ratio = float(volume.iloc[-1]) / max(vol_avg, 1)

        # MA20
        ma20_s = close.rolling(20, min_periods=5).mean()
        ma20   = float(ma20_s.dropna().iloc[-1]) if not ma20_s.dropna().empty else float(close.iloc[-1])

        # Recent low (5-day)
        low = hist["Low"].astype(float)
        recent_low = float(low.rolling(5, min_periods=2).min().dropna().iloc[-1]) if not low.rolling(5, min_periods=2).min().dropna().empty else float(low.iloc[-1])

        # Delivery proxy — reuse hist, no extra API call
        delivery_score = get_delivery_score(symbol, hist)

        return {
            "rsi": rsi, "macd_histogram": macd_hist,
            "volume_ratio": vol_ratio,
            "price_vs_ma20": float(close.iloc[-1]) / max(ma20, 0.01),
            "current_price": float(close.iloc[-1]),
            "recent_low": recent_low,
            "delivery_score": delivery_score,
        }
    except Exception as e:
        logger.error(f"Tech data failed for {symbol}: {e}")
        return None


class MonitoringEngine:

    def __init__(self, telegram_token: str = None, telegram_chat_id: str = None):
        self.watchlist = WatchlistEngine()
        self.scorer    = ScoringEngine()
        self.alert     = AlertEngine(token=telegram_token, chat_id=telegram_chat_id)

    def run(self) -> List[Dict]:
        active = self.watchlist.get_active()
        if not active:
            logger.info("Monitoring: watchlist empty.")
            return []

        nifty_weakness = _get_nifty_weakness()
        results = []

        for pos in active:
            symbol      = pos["symbol"]
            entry_price = pos["entry_price"]
            stop_loss   = pos["stop_loss"]
            target      = pos["target"]
            entry_score = pos.get("entry_score", 0) or 0
            qty         = pos.get("qty", 0) or 0

            # ── Sanity check ───────────────────────────────────────────
            if stop_loss >= entry_price or target <= entry_price:
                logger.warning(f"INVALID entry for {symbol} — removing")
                self.watchlist.close_position(symbol, entry_price,
                    exit_reason="INVALID_ENTRY", entry_price=entry_price)
                continue

            tech = _fetch_tech_data(symbol)
            if tech is None:
                logger.warning(f"No data for {symbol}, skipping")
                continue

            current_price = tech["current_price"]
            pnl_pct = round((current_price - entry_price) / entry_price * 100, 2)

            # ── Hard stop loss ─────────────────────────────────────────
            trailing_sl = pos.get("trailing_sl") or stop_loss
            effective_sl = max(stop_loss, trailing_sl)

            if current_price <= effective_sl:
                self.watchlist.close_position(
                    symbol, current_price, exit_score=100,
                    exit_reason="STOP_LOSS_HIT", entry_price=entry_price, qty=qty)
                msg = (f"🛑 <b>STOP LOSS HIT: {symbol}</b>\n"
                       f"Price: Rs {current_price:.2f} | SL: Rs {effective_sl:.2f}\n"
                       f"PnL: {pnl_pct:+.2f}%")
                self.alert.send(msg)
                results.append({"symbol": symbol, "decision": "EXIT",
                                 "reason": "STOP_LOSS_HIT", "pnl": pnl_pct,
                                 "current_price": current_price, "exit_score": 100})
                continue

            # ── Target hit → partial profit ────────────────────────────
            if current_price >= target:
                self.watchlist.close_position(
                    symbol, current_price, exit_score=0,
                    exit_reason="TARGET_HIT", entry_price=entry_price, qty=qty)
                msg = (f"🎯 <b>TARGET HIT: {symbol}</b>\n"
                       f"Price: Rs {current_price:.2f} | Target: Rs {target:.2f}\n"
                       f"Profit: +{pnl_pct:.2f}%")
                self.alert.send(msg)
                results.append({"symbol": symbol, "decision": "EXIT",
                                 "reason": "TARGET_HIT", "pnl": pnl_pct,
                                 "current_price": current_price, "exit_score": 0})
                continue

            # ── Trailing stop update ───────────────────────────────────
            new_trailing = compute_trailing_stop(
                entry_price, current_price, stop_loss, tech["recent_low"])

            # ── Exit score ─────────────────────────────────────────────
            exit_components = self.scorer.technical_to_exit_components(
                tech, entry_price, current_price, target, nifty_weakness)

            # Delivery distribution → boost momentum_loss component
            delivery_score = tech.get("delivery_score", 50)
            if delivery_score < 40:  # distribution signal
                distribution_penalty = (40 - delivery_score) * 0.5  # up to 20 pts
                exit_components["momentum_loss"] = min(100, exit_components["momentum_loss"] + distribution_penalty)

            exit_score, _ = self.scorer.compute_exit_score(**exit_components)

            # ── Momentum score ─────────────────────────────────────────
            momentum = self.scorer.compute_momentum_score(tech)

            # ── Opportunity score ──────────────────────────────────────
            opp_score = compute_opportunity_score(entry_score, exit_score, momentum)

            # ── Trade state ────────────────────────────────────────────
            state_result = classify_trade_state(
                exit_score, opp_score, current_price,
                entry_price, effective_sl, pnl_pct)

            # ── Update DB ──────────────────────────────────────────────
            self.watchlist.update_scores(
                symbol=symbol, exit_score=exit_score,
                opportunity_score=opp_score,
                trade_state=state_result.state,
                suggested_action=state_result.suggested_action,
                trailing_sl=new_trailing if new_trailing > stop_loss else None,
                notes=f"exit={exit_score:.0f} opp={opp_score:.0f} pnl={pnl_pct:+.1f}%"
            )

            result = {
                "symbol": symbol, "current_price": current_price,
                "entry_price": entry_price, "pnl": pnl_pct,
                "exit_score": exit_score, "opportunity_score": opp_score,
                "trade_state": state_result.state,
                "decision": state_result.suggested_action,
                "reason": state_result.reason,
                "trailing_sl": new_trailing,
            }
            results.append(result)

            # ── Alerts — only when action needed ──────────────────────
            if state_result.state == "WEAK":
                if state_result.suggested_action == "EXIT":
                    self.watchlist.close_position(
                        symbol, current_price, exit_score=exit_score,
                        exit_reason="EXIT_SIGNAL", entry_price=entry_price, qty=qty)
                    msg = (f"⚠️ <b>EXIT SIGNAL: {symbol}</b>\n"
                           f"Exit Score: {exit_score:.0f}/100\n"
                           f"Price: Rs {current_price:.2f} | PnL: {pnl_pct:+.2f}%\n"
                           f"{state_result.reason}")
                    self.alert.send(msg)
                else:
                    msg = (f"🟡 <b>CAUTION: {symbol}</b>\n"
                           f"Exit Score: {exit_score:.0f}/100 | State: WEAK\n"
                           f"Price: Rs {current_price:.2f} | PnL: {pnl_pct:+.2f}%\n"
                           f"{state_result.reason}")
                    self.alert.send(msg)

            elif state_result.state == "STRONG" and new_trailing > stop_loss:
                # Notify trailing stop update silently (no alert spam)
                logger.info(f"TRAIL {symbol}: SL moved to Rs {new_trailing:.2f}")

            logger.info(f"Monitor {symbol}: exit={exit_score:.0f} opp={opp_score:.0f} "
                        f"state={state_result.state} pnl={pnl_pct:+.1f}%")

        if results:
            weak_count = sum(1 for r in results if r.get("trade_state") == "WEAK")
            exit_count = sum(1 for r in results if r.get("decision") == "EXIT")
            hold_count = sum(1 for r in results if r.get("decision") == "HOLD")
            self.alert.send(
                f"Monitor Summary: {len(results)} checked | "
                f"HOLD: {hold_count} | EXIT: {exit_count} | WEAK: {weak_count}"
            )

        return results

    def print_report(self, results: List[Dict]):
        if not results:
            print("\n  No active positions.\n")
            return
        print(f"\n{'='*90}")
        print(f"  MONITORING REPORT - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'='*90}")
        print(f"  {'Symbol':<14} {'Price':>8} {'PnL%':>7} {'Exit':>6} {'Opp':>6} {'State':<10} {'Action'}")
        print(f"  {'-'*84}")
        for r in results:
            pnl_s  = f"{r['pnl']:+.2f}%" if r.get("pnl") is not None else "-"
            exit_s = f"{r['exit_score']:.0f}" if r.get("exit_score") is not None else "-"
            opp_s  = f"{r['opportunity_score']:.0f}" if r.get("opportunity_score") is not None else "-"
            price_s = f"{r['current_price']:.2f}" if r.get("current_price") else "-"
            print(f"  {r['symbol']:<14} {price_s:>8} {pnl_s:>7} {exit_s:>6} {opp_s:>6} "
                  f"{r.get('trade_state','?'):<10} {r.get('decision','?')}")
        print(f"{'='*90}\n")
