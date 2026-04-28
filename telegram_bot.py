#!/usr/bin/env python3
"""
BuzzFlow - Telegram Command Bot
Listens for commands from the user and responds with live data.

Supported commands:
  /monitor   — run full position monitoring, reply with current watchlist status
  /watchlist — show all active positions with live price + PnL (no scoring run)
  /status    — market sentiment + Nifty regime summary
  /scan      — trigger a quick scan (large cap only, top 5) and reply results
  /help      — list all commands

Uses long-polling (getUpdates) — no webhook server needed.
Run as a background process alongside the dashboard:
    python telegram_bot.py

GitHub Actions: add a long-running job or run via a VPS/server.
"""

import os
import sys
import time
import logging
import threading
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("buzzflow.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = str(os.getenv("TELEGRAM_CHAT_ID", ""))

# Commands currently being processed (prevent duplicate runs)
_running: set = set()
_lock = threading.Lock()


# ── Telegram API helpers ───────────────────────────────────────────────────

def _api(method: str, **kwargs) -> dict:
    url  = f"https://api.telegram.org/bot{TOKEN}/{method}"
    resp = requests.post(url, json=kwargs, timeout=15)
    return resp.json()


def send(chat_id: str, text: str, parse_mode: str = "HTML") -> None:
    """Send a message, splitting if over Telegram's 4096 char limit."""
    limit = 4000
    for i in range(0, len(text), limit):
        chunk = text[i:i+limit]
        _api("sendMessage", chat_id=chat_id, text=chunk, parse_mode=parse_mode)


def send_typing(chat_id: str) -> None:
    _api("sendChatAction", chat_id=chat_id, action="typing")


# ── Security: only respond to the configured chat ─────────────────────────

def _is_authorised(chat_id: str) -> bool:
    return str(chat_id) == CHAT_ID


# ── Command handlers ───────────────────────────────────────────────────────

def handle_help(chat_id: str) -> None:
    send(chat_id, (
        "📋 <b>BuzzFlow Commands</b>\n\n"
        "/monitor   — run position monitoring + get full watchlist status\n"
        "/watchlist — show active positions with live price &amp; PnL (fast)\n"
        "/status    — market sentiment + Nifty regime\n"
        "/scan      — quick scan (large cap, top 5 signals)\n"
        "/help      — this message"
    ))


def handle_watchlist(chat_id: str) -> None:
    """Fast path — just fetch live prices from DB + yfinance, no scoring."""
    send_typing(chat_id)
    try:
        from database import get_watchlist
        from monitoring_engine import _fetch_tech_data

        positions = get_watchlist()
        active = [p for p in positions if p.get("status") not in ("CLOSED", "EXIT")]

        if not active:
            send(chat_id, "📭 No active positions in watchlist.")
            return

        lines = [f"📊 <b>Watchlist</b> — {datetime.now().strftime('%d %b %H:%M')}\n"]

        for pos in active:
            sym         = pos["symbol"]
            entry       = pos["entry_price"]
            sl          = pos.get("trailing_sl") or pos["stop_loss"]
            target      = pos["target"]
            trade_state = pos.get("trade_state", "—")
            action      = pos.get("suggested_action", "—")

            tech = _fetch_tech_data(sym)
            if tech:
                price = tech["current_price"]
                pnl   = round((price - entry) / entry * 100, 2)
                pnl_s = f"{pnl:+.2f}%"
                pnl_icon = "🟢" if pnl >= 0 else "🔴"
            else:
                price = entry
                pnl_s = "—"
                pnl_icon = "⚪"

            state_icon = {"STRONG": "💪", "NEUTRAL": "⚪", "WEAK": "🟡"}.get(trade_state, "⚪")

            lines.append(
                f"{pnl_icon} <b>{sym}</b> | Rs{price:.2f} ({pnl_s})\n"
                f"   Entry: Rs{entry:.2f} | SL: Rs{sl:.2f} | Target: Rs{target:.2f}\n"
                f"   {state_icon} {trade_state} → {action}"
            )

        send(chat_id, "\n\n".join(lines))

    except Exception as e:
        logger.error(f"handle_watchlist error: {e}")
        send(chat_id, f"❌ Error fetching watchlist: {e}")


def handle_monitor(chat_id: str) -> None:
    """Full monitoring run — scores, exit signals, trailing stops."""
    with _lock:
        if "monitor" in _running:
            send(chat_id, "⏳ Monitor is already running, please wait...")
            return
        _running.add("monitor")

    try:
        send_typing(chat_id)
        send(chat_id, "⚙️ Running position monitoring... (this takes ~30s)")

        from monitoring_engine import MonitoringEngine
        engine  = MonitoringEngine(telegram_token=TOKEN, telegram_chat_id=CHAT_ID)
        results = engine.run()

        if not results:
            send(chat_id, "📭 No active positions to monitor.")
            return

        lines = [f"📈 <b>Monitor Results</b> — {datetime.now().strftime('%d %b %H:%M')}\n"]

        for r in results:
            sym   = r["symbol"]
            price = r.get("current_price", 0)
            pnl   = r.get("pnl", 0)
            exit_s = r.get("exit_score", 0)
            opp_s  = r.get("opportunity_score", 0)
            state  = r.get("trade_state", "—")
            action = r.get("decision", "—")
            reason = r.get("reason", "")

            pnl_icon   = "🟢" if pnl >= 0 else "🔴"
            state_icon = {"STRONG": "💪", "NEUTRAL": "⚪", "WEAK": "🟡"}.get(state, "⚪")
            action_icon = {"HOLD": "✅", "EXIT": "🚨", "CAUTION": "⚠️", "MONITOR": "👁"}.get(action, "")

            lines.append(
                f"{pnl_icon} <b>{sym}</b> | Rs{price:.2f} | PnL: {pnl:+.2f}%\n"
                f"   Exit: {exit_s:.0f}/100 | Opp: {opp_s:.0f}/100\n"
                f"   {state_icon} {state} → {action_icon} {action}"
                + (f"\n   📝 {reason}" if reason else "")
            )

        # Summary line
        hold_n  = sum(1 for r in results if r.get("decision") == "HOLD")
        exit_n  = sum(1 for r in results if r.get("decision") == "EXIT")
        weak_n  = sum(1 for r in results if r.get("trade_state") == "WEAK")
        lines.append(
            f"\n<b>Summary:</b> {len(results)} positions | "
            f"✅ HOLD: {hold_n} | 🚨 EXIT: {exit_n} | 🟡 WEAK: {weak_n}"
        )

        send(chat_id, "\n\n".join(lines))

    except Exception as e:
        logger.error(f"handle_monitor error: {e}")
        send(chat_id, f"❌ Monitor failed: {e}")
    finally:
        with _lock:
            _running.discard("monitor")


def handle_status(chat_id: str) -> None:
    """Market sentiment + Nifty regime."""
    send_typing(chat_id)
    try:
        from market_regime_engine import get_market_sentiment, format_sentiment_alert
        send(chat_id, "⚙️ Fetching market sentiment...")
        s   = get_market_sentiment()
        msg = format_sentiment_alert(s)
        send(chat_id, msg)
    except Exception as e:
        logger.error(f"handle_status error: {e}")
        send(chat_id, f"❌ Status failed: {e}")


def handle_scan(chat_id: str) -> None:
    """Quick large-cap scan, top 5 results."""
    with _lock:
        if "scan" in _running:
            send(chat_id, "⏳ Scan is already running, please wait...")
            return
        _running.add("scan")

    try:
        send_typing(chat_id)
        send(chat_id, "🔍 Running quick scan (large cap, top 5)... (~60s)")

        from scanner_v2 import ScannerV2
        scanner = ScannerV2()
        results = scanner.scan(index="large", min_score=65, max_results=5)

        if not results:
            send(chat_id, "🔍 No setups found above score threshold right now.")
            return

        lines = [f"🔍 <b>Quick Scan — Large Cap</b> | {datetime.now().strftime('%d %b %H:%M')}\n"]

        for r in results:
            icon = "🟢" if r.signal == "STRONG_BUY" else "🔵"
            lines.append(
                f"{icon} <b>{r.symbol}</b> | Score: {r.entry_score:.0f} | {r.signal}\n"
                f"   Zone: Rs{r.entry_zone_low:.0f}–{r.entry_zone_high:.0f} | "
                f"SL: Rs{r.stop_loss:.2f} | Target: Rs{r.target_price:.2f}\n"
                f"   R:R: {r.risk_reward} | Delivery: {r.delivery_score:.0f}/100"
            )

        send(chat_id, "\n\n".join(lines))

    except Exception as e:
        logger.error(f"handle_scan error: {e}")
        send(chat_id, f"❌ Scan failed: {e}")
    finally:
        with _lock:
            _running.discard("scan")


# ── Command dispatcher ─────────────────────────────────────────────────────

HANDLERS = {
    "/monitor":   handle_monitor,
    "/watchlist": handle_watchlist,
    "/status":    handle_status,
    "/scan":      handle_scan,
    "/help":      handle_help,
    "/start":     handle_help,
}


def dispatch(chat_id: str, text: str) -> None:
    """Run the handler in a background thread so polling isn't blocked."""
    cmd = text.strip().split()[0].lower().split("@")[0]  # strip bot username suffix
    handler = HANDLERS.get(cmd)
    if handler:
        t = threading.Thread(target=handler, args=(chat_id,), daemon=True)
        t.start()
    else:
        send(chat_id, f"Unknown command: <code>{cmd}</code>\nSend /help for available commands.")


# ── Long-polling loop ──────────────────────────────────────────────────────

def run_bot() -> None:
    if not TOKEN or not CHAT_ID:
        logger.error("TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set. Bot cannot start.")
        sys.exit(1)

    logger.info(f"BuzzFlow Telegram bot started. Listening for commands from chat {CHAT_ID}...")
    send(CHAT_ID, "🤖 <b>BuzzFlow bot is online.</b>\nSend /help to see available commands.")

    offset = None

    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message"]}
            if offset:
                params["offset"] = offset

            resp = requests.get(
                f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                params=params,
                timeout=40
            )
            data = resp.json()

            if not data.get("ok"):
                logger.warning(f"getUpdates error: {data}")
                time.sleep(5)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1

                msg = update.get("message", {})
                if not msg:
                    continue

                chat_id = str(msg.get("chat", {}).get("id", ""))
                text    = msg.get("text", "").strip()

                if not text or not text.startswith("/"):
                    continue

                if not _is_authorised(chat_id):
                    logger.warning(f"Unauthorised access attempt from chat_id={chat_id}")
                    send(chat_id, "⛔ Unauthorised. This bot is private.")
                    continue

                logger.info(f"Command received: {text} from {chat_id}")
                dispatch(chat_id, text)

        except requests.exceptions.Timeout:
            # Normal for long-polling — just loop again
            continue
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    run_bot()
