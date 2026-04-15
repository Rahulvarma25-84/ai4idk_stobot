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
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from database import (
    init_db, get_watchlist, get_trade_history, get_latest_scan_results,
    update_watchlist_status, remove_from_watchlist, add_to_watchlist, log_trade
)
from watchlist_engine import WatchlistEngine
from monitoring_engine import MonitoringEngine, _fetch_tech_data
from replacement_engine import ReplacementEngine
from performance_engine import compute_performance
from scoring_engine import MarketRegime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

init_db()

app = Flask(__name__, static_folder="static")
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
    return send_from_directory("static", "index.html")


# ── Market ─────────────────────────────────────────────────────────────────

@app.route("/api/market")
def market():
    return jsonify(MarketRegime.get())


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


# ── Performance ────────────────────────────────────────────────────────────

@app.route("/api/performance")
def performance():
    return jsonify(compute_performance())


@app.route("/api/trades")
def trades():
    symbol = request.args.get("symbol")
    return jsonify(get_trade_history(symbol))


if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
