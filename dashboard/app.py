"""
BuzzFlow Dashboard — Flask Web App
Serves the dashboard UI and REST API for watchlist management.
"""

import os
import sys
import logging
from datetime import datetime, date

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

# Add parent directory to path so we can import BuzzFlow modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from database import (
    init_db, get_watchlist, get_trade_history,
    get_latest_scan_results, update_watchlist_status,
    remove_from_watchlist, add_to_watchlist, log_trade
)
from watchlist_engine import WatchlistEngine
from monitoring_engine import MonitoringEngine, _fetch_tech_data
from scoring_engine import MarketRegime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

init_db()

app = Flask(__name__, static_folder="static")
CORS(app)

wl_engine  = WatchlistEngine()
mon_engine = MonitoringEngine(
    telegram_token=os.getenv("TELEGRAM_TOKEN"),
    telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID")
)

# ── Serve dashboard UI ─────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ── Market Regime ──────────────────────────────────────────────────────────

@app.route("/api/market")
def market_regime():
    regime = MarketRegime.get()
    return jsonify(regime)


# ── Watchlist ──────────────────────────────────────────────────────────────

@app.route("/api/watchlist")
def get_watchlist_api():
    items = get_watchlist()
    # Enrich with live price + PnL
    enriched = []
    for w in items:
        tech = _fetch_tech_data(w["symbol"]) if w["status"] not in ("CLOSED",) else None
        live_price = tech["current_price"] if tech else None
        pnl = None
        if live_price and w["entry_price"]:
            pnl = round((live_price - w["entry_price"]) / w["entry_price"] * 100, 2)
        enriched.append({**w, "live_price": live_price, "pnl_percent": pnl})
    return jsonify(enriched)


@app.route("/api/watchlist", methods=["POST"])
def add_watchlist():
    data = request.json
    required = ["symbol", "entry_price", "stop_loss", "target"]
    if not all(k in data for k in required):
        return jsonify({"error": f"Required fields: {required}"}), 400

    rr = round((data["target"] - data["entry_price"]) /
               max(data["entry_price"] - data["stop_loss"], 0.01), 2)
    row_id = add_to_watchlist(
        symbol=data["symbol"].upper(),
        entry_price=float(data["entry_price"]),
        stop_loss=float(data["stop_loss"]),
        target=float(data["target"]),
        entry_score=data.get("entry_score"),
        confidence=data.get("confidence", "medium"),
        company_name=data.get("company_name", ""),
        notes=f"R:R={rr} | {data.get('notes', '')}".strip(" |")
    )
    return jsonify({"id": row_id, "message": f"Added {data['symbol']} to watchlist"}), 201


@app.route("/api/watchlist/<symbol>/status", methods=["PATCH"])
def update_status(symbol):
    data = request.json
    status = data.get("status")
    valid = ("WATCH", "BUY", "CAUTION", "EXIT", "CLOSED")
    if status not in valid:
        return jsonify({"error": f"Status must be one of {valid}"}), 400
    update_watchlist_status(symbol.upper(), status, data.get("notes", ""))
    return jsonify({"message": f"{symbol} status → {status}"})


@app.route("/api/watchlist/<symbol>/close", methods=["POST"])
def close_position(symbol):
    data = request.json
    exit_price = data.get("exit_price")
    if not exit_price:
        return jsonify({"error": "exit_price required"}), 400

    # Get entry price for PnL
    items = get_watchlist()
    entry_price = next((w["entry_price"] for w in items
                        if w["symbol"] == symbol.upper()), None)
    pnl = None
    if entry_price:
        pnl = round((float(exit_price) - entry_price) / entry_price * 100, 2)

    log_trade(
        symbol=symbol.upper(),
        action="EXIT",
        price=float(exit_price),
        exit_reason=data.get("reason", "MANUAL"),
        pnl_percent=pnl,
        notes=data.get("notes", "")
    )
    remove_from_watchlist(symbol.upper())
    return jsonify({"message": f"Closed {symbol} @ {exit_price}", "pnl_percent": pnl})


@app.route("/api/watchlist/<symbol>", methods=["DELETE"])
def delete_watchlist(symbol):
    remove_from_watchlist(symbol.upper())
    return jsonify({"message": f"Removed {symbol}"})


# ── Monitor (run on demand) ────────────────────────────────────────────────

@app.route("/api/monitor", methods=["POST"])
def run_monitor():
    results = mon_engine.run()
    return jsonify(results)


# ── Scan Results ───────────────────────────────────────────────────────────

@app.route("/api/scans")
def scan_results():
    limit = int(request.args.get("limit", 50))
    results = get_latest_scan_results(limit)
    return jsonify(results)


# ── Trade History / Performance ────────────────────────────────────────────

@app.route("/api/trades")
def trade_history():
    symbol = request.args.get("symbol")
    trades = get_trade_history(symbol)
    return jsonify(trades)


@app.route("/api/performance")
def performance():
    trades = get_trade_history()
    closed = [t for t in trades if t.get("pnl_percent") is not None]
    if not closed:
        return jsonify({
            "total_trades": 0, "win_rate": 0, "avg_pnl": 0,
            "total_pnl": 0, "best_trade": None, "worst_trade": None
        })

    wins   = [t for t in closed if t["pnl_percent"] > 0]
    losses = [t for t in closed if t["pnl_percent"] <= 0]
    pnls   = [t["pnl_percent"] for t in closed]

    return jsonify({
        "total_trades":  len(closed),
        "winning_trades": len(wins),
        "losing_trades":  len(losses),
        "win_rate":       round(len(wins) / len(closed) * 100, 1),
        "avg_pnl":        round(sum(pnls) / len(pnls), 2),
        "total_pnl":      round(sum(pnls), 2),
        "best_trade":     max(closed, key=lambda t: t["pnl_percent"]),
        "worst_trade":    min(closed, key=lambda t: t["pnl_percent"]),
        "trades":         closed
    })


if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
