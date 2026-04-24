"""
BuzzFlow Dashboard — Flask REST API
Serves the React dashboard and all data endpoints.
"""

import os
import sys
import logging
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
STATIC_DIR   = os.path.join(BASE_DIR, "static")

# Also support running from project root: python dashboard/app.py
if not os.path.isdir(STATIC_DIR):
    STATIC_DIR = os.path.join(os.getcwd(), "dashboard", "static")

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from database import (
    init_db, get_watchlist, get_trade_history, get_latest_scan_results,
    update_watchlist_status, remove_from_watchlist, add_to_watchlist, log_trade
)
from watchlist_engine import WatchlistEngine
from monitoring_engine import MonitoringEngine, _fetch_tech_data
from replacement_engine import ReplacementEngine
from performance_engine import compute_performance
from scoring_engine import MarketRegime
from universe_engine import get_universe_stats, get_universe_df
from alert_engine import AlertEngine
from market_regime_engine import get_market_sentiment, format_sentiment_alert

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

init_db()

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
CORS(app)

wl  = WatchlistEngine()
mon = MonitoringEngine(
    telegram_token=os.getenv("TELEGRAM_TOKEN"),
    telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID")
)
rep = ReplacementEngine(
    telegram_token=os.getenv("TELEGRAM_TOKEN"),
    telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID")
)

# ── UI ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


# ── Market ─────────────────────────────────────────────────────────────────

@app.route("/api/market")
def market():
    return jsonify(MarketRegime.get())


@app.route("/api/market/sentiment")
def market_sentiment():
    """
    Full multi-signal market sentiment analysis.
    Includes composite score, regime, bearish warning, and all 6 signal scores.
    Pass ?force=1 to bypass 2-hour cache.
    """
    force = request.args.get("force", "0") == "1"
    return jsonify(get_market_sentiment(force=force))


@app.route("/api/health")
def health():
    watchlist = get_watchlist()
    active = [w for w in watchlist if w.get("status") not in ("CLOSED", "EXIT")]
    return jsonify({
        "status": "ok",
        "server_time": datetime.now().isoformat(),
        "telegram_configured": bool(os.getenv("TELEGRAM_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
        "watchlist_total": len(watchlist),
        "watchlist_active": len(active),
        "scan_rows_latest": len(get_latest_scan_results(limit=50)),
    })


@app.route("/api/telegram/test", methods=["POST"])
def telegram_test():
    alert = AlertEngine(
        token=os.getenv("TELEGRAM_TOKEN"),
        chat_id=os.getenv("TELEGRAM_CHAT_ID")
    )
    ok = alert.send("✅ BuzzFlow telegram pipeline test: dashboard-triggered message.")
    if not ok:
        return jsonify({"status": "error", "message": "Telegram send failed. Check token/chat id."}), 500
    return jsonify({"status": "ok", "message": "Telegram test sent."})


# ── Watchlist ──────────────────────────────────────────────────────────────

@app.route("/api/watchlist")
def get_watchlist_api():
    items = get_watchlist()
    enriched = []
    for w in items:
        tech = _fetch_tech_data(w["symbol"]) if w["status"] not in ("CLOSED",) else None
        live = tech["current_price"] if tech else None
        pnl  = round((live - w["entry_price"]) / w["entry_price"] * 100, 2) if live and w["entry_price"] else None
        enriched.append({**w, "live_price": live, "pnl_percent": pnl})
    return jsonify(enriched)


@app.route("/api/watchlist", methods=["POST"])
def add_watchlist():
    d = request.json
    req = ["symbol","entry_price","stop_loss","target"]
    if not all(k in d for k in req):
        return jsonify({"error": f"Required: {req}"}), 400
    ep, sl, tg = float(d["entry_price"]), float(d["stop_loss"]), float(d["target"])
    if sl >= ep:
        return jsonify({"error": "stop_loss must be below entry_price"}), 400
    if tg <= ep:
        return jsonify({"error": "target must be above entry_price"}), 400
    row_id = add_to_watchlist(
        symbol=d["symbol"].upper(), entry_price=ep, stop_loss=sl, target=tg,
        entry_score=d.get("entry_score", 0), confidence=d.get("confidence","medium"),
        company_name=d.get("company_name",""),
        entry_zone_low=d.get("entry_zone_low"), entry_zone_high=d.get("entry_zone_high"),
        breakout_level=d.get("breakout_level"), pullback_level=d.get("pullback_level"),
        risk_capital_pct=d.get("risk_capital_pct", 1.0), qty=d.get("qty", 0),
        notes=d.get("notes","")
    )
    return jsonify({"id": row_id, "message": f"Added {d['symbol']}"}), 201


@app.route("/api/watchlist/<symbol>/status", methods=["PATCH"])
def update_status(symbol):
    d = request.json
    status = d.get("status")
    if status not in ("WATCH","BUY","CAUTION","EXIT","CLOSED","HOLD"):
        return jsonify({"error": "Invalid status"}), 400
    update_watchlist_status(symbol.upper(), status, d.get("notes",""))
    return jsonify({"message": f"{symbol} → {status}"})


@app.route("/api/watchlist/<symbol>/close", methods=["POST"])
def close_position(symbol):
    d = request.json
    exit_price = d.get("exit_price")
    if not exit_price:
        return jsonify({"error": "exit_price required"}), 400
    items = get_watchlist()
    pos = next((w for w in items if w["symbol"] == symbol.upper()), None)
    entry_price = pos["entry_price"] if pos else None
    qty = pos.get("qty", 0) if pos else 0
    pnl = round((float(exit_price) - entry_price) / entry_price * 100, 2) if entry_price else None
    log_trade(symbol=symbol.upper(), action="EXIT", price=float(exit_price),
              qty=qty, exit_reason=d.get("reason","MANUAL"), pnl_percent=pnl,
              notes=d.get("notes",""))
    remove_from_watchlist(symbol.upper())
    return jsonify({"message": f"Closed {symbol}", "pnl_percent": pnl})


@app.route("/api/watchlist/<symbol>", methods=["DELETE"])
def delete_watchlist(symbol):
    """
    For active positions: soft-close (status=CLOSED).
    For already-closed positions: hard delete the row by id.
    Accepts optional ?id=<row_id> to target a specific row.
    """
    from database import hard_delete_watchlist_row
    row_id = request.args.get("id", type=int)

    items = get_watchlist()
    pos = next((w for w in items if w["symbol"] == symbol.upper()), None)

    if pos and pos.get("status") in ("CLOSED", "EXIT"):
        # Already closed — hard delete this specific row
        target_id = row_id or pos["id"]
        hard_delete_watchlist_row(target_id)
    else:
        # Active — soft close
        remove_from_watchlist(symbol.upper())

    return jsonify({"message": f"Removed {symbol}"})


# ── Monitor ────────────────────────────────────────────────────────────────

@app.route("/api/monitor", methods=["POST"])
def run_monitor():
    results = mon.run()
    return jsonify(results)


@app.route("/api/replacement", methods=["POST"])
def run_replacement():
    suggestions = rep.run()
    return jsonify(suggestions)


@app.route("/api/replacement")
def get_replacements():
    """Get latest replacement suggestions from DB."""
    from database import get_connection
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM replacement_log ORDER BY triggered_at DESC LIMIT 20"
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


# ── Scans ──────────────────────────────────────────────────────────────────

@app.route("/api/scans")
def scan_results():
    limit = int(request.args.get("limit", 100))
    return jsonify(get_latest_scan_results(limit))


@app.route("/api/scans/categories")
def scan_categories():
    """
    Available scanner universes for manual runs from dashboard.
    Kept in sync with scanner_v2 SECTOR_MAP keys.
    """
    from scanner_v2 import SECTOR_MAP

    labels = {
        "all": "All Universe",
        "nifty_50": "Nifty 50",
        "banking": "Banking",
        "nifty_it": "Nifty IT",
        "pharma": "Pharma",
        "auto": "Auto",
        "capex": "Capex & Infra",
        "consumption": "Consumption",
        "metals": "Metals",
        "chemicals": "Chemicals",
    }

    options = [{"value": "all", "label": labels["all"]}]
    for key in SECTOR_MAP.keys():
        options.append({"value": key, "label": labels.get(key, key.replace("_", " ").title())})
    return jsonify(options)


@app.route("/api/scans/run", methods=["POST"])
def run_manual_scan():
    """
    Manual scan trigger from dashboard.
    This complements (does not replace) scheduled GitHub automation.
    """
    payload = request.json or {}
    index = str(payload.get("index", "all"))
    min_score = float(payload.get("min_score", 65))
    max_results = int(payload.get("max_results", 20))
    auto_watchlist = bool(payload.get("auto_watchlist", False))
    send_alert = bool(payload.get("alert", False))

    from scanner_v2 import ScannerV2, SECTOR_MAP

    allowed_indices = {"all", *SECTOR_MAP.keys()}
    if index not in allowed_indices:
        return jsonify({"error": f"Invalid index: {index}"}), 400

    scanner = ScannerV2()
    results = scanner.scan(
        index=index,
        min_score=min_score,
        max_results=max_results,
        auto_watchlist=auto_watchlist,
    )

    if send_alert:
        scanner.send_morning_alert(results)

    return jsonify({
        "status": "ok",
        "index": index,
        "min_score": min_score,
        "max_results": max_results,
        "auto_watchlist": auto_watchlist,
        "alert": send_alert,
        "signals_found": len(results),
        "top_symbols": [r.symbol for r in results[:5]],
    })


# ── Performance ────────────────────────────────────────────────────────────

@app.route("/api/performance")
def performance():
    return jsonify(compute_performance())


@app.route("/api/trades")
def trades():
    symbol = request.args.get("symbol")
    return jsonify(get_trade_history(symbol))


@app.route("/api/universe")
def universe():
    """Universe stats + optional filtered list."""
    category = request.args.get("category")
    cap_tier = request.args.get("cap_tier")
    if category or cap_tier:
        df = get_universe_df(cap_tier=cap_tier, category=category)
        return jsonify(df.to_dict(orient="records"))
    return jsonify(get_universe_stats())


if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
