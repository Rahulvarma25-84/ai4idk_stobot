"""
BuzzFlow - Database Layer (SQLite)
Handles watchlist, trade logs, and stock scan results.
"""

import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional
import os

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("BUZZFLOW_DB", "buzzflow.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    try:
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                company_name TEXT,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                target REAL NOT NULL,
                entry_score REAL,
                confidence TEXT,
                status TEXT DEFAULT 'WATCH',
                added_at TEXT NOT NULL,
                updated_at TEXT,
                notes TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS trades_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                price REAL NOT NULL,
                exit_score REAL,
                exit_reason TEXT,
                pnl_percent REAL,
                timestamp TEXT NOT NULL,
                notes TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS scan_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                entry_score REAL,
                sentiment_score REAL,
                technical_score REAL,
                recommendation TEXT,
                confidence TEXT,
                entry_price REAL,
                stop_loss REAL,
                target REAL,
                scanned_at TEXT NOT NULL
            )
        """)

        conn.commit()
        logger.info("Database initialized.")
    finally:
        conn.close()


# ── Watchlist ──────────────────────────────────────────────────────────────

def add_to_watchlist(symbol: str, entry_price: float, stop_loss: float,
                     target: float, entry_score: float = None,
                     confidence: str = None, company_name: str = "",
                     notes: str = "") -> int:
    conn = get_connection()
    try:
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute("""
            INSERT INTO watchlist
            (symbol, company_name, entry_price, stop_loss, target,
             entry_score, confidence, status, added_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'WATCH', ?, ?)
        """, (symbol.upper(), company_name, entry_price, stop_loss,
              target, entry_score, confidence, now, notes))
        conn.commit()
        row_id = c.lastrowid
        logger.info(f"Added {symbol} to watchlist (id={row_id})")
        return row_id
    finally:
        conn.close()


def get_watchlist(status: str = None) -> List[Dict]:
    conn = get_connection()
    try:
        c = conn.cursor()
        if status:
            c.execute("SELECT * FROM watchlist WHERE status=? ORDER BY added_at DESC", (status,))
        else:
            c.execute("SELECT * FROM watchlist ORDER BY added_at DESC")
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()


def update_watchlist_status(symbol: str, status: str, notes: str = ""):
    """Update status: WATCH → BUY / CAUTION / EXIT / CLOSED"""
    conn = get_connection()
    try:
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute("""
            UPDATE watchlist SET status=?, updated_at=?, notes=?
            WHERE symbol=? AND status NOT IN ('CLOSED')
        """, (status, now, notes, symbol.upper()))
        conn.commit()
        logger.info(f"Updated {symbol} watchlist status → {status}")
    finally:
        conn.close()


def remove_from_watchlist(symbol: str):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE watchlist SET status='CLOSED', updated_at=? WHERE symbol=?",
                  (datetime.now().isoformat(), symbol.upper()))
        conn.commit()
    finally:
        conn.close()


# ── Trade Log ──────────────────────────────────────────────────────────────

def log_trade(symbol: str, action: str, price: float,
              exit_score: float = None, exit_reason: str = "",
              pnl_percent: float = None, notes: str = ""):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO trades_log
            (symbol, action, price, exit_score, exit_reason, pnl_percent, timestamp, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol.upper(), action, price, exit_score, exit_reason,
              pnl_percent, datetime.now().isoformat(), notes))
        conn.commit()
        logger.info(f"Logged trade: {action} {symbol} @ {price}")
    finally:
        conn.close()


def get_trade_history(symbol: str = None) -> List[Dict]:
    conn = get_connection()
    try:
        c = conn.cursor()
        if symbol:
            c.execute("SELECT * FROM trades_log WHERE symbol=? ORDER BY timestamp DESC", (symbol.upper(),))
        else:
            c.execute("SELECT * FROM trades_log ORDER BY timestamp DESC")
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()


# ── Scan Results ───────────────────────────────────────────────────────────

def save_scan_result(symbol: str, entry_score: float, sentiment_score: float,
                     technical_score: float, recommendation: str,
                     confidence: str, entry_price: float,
                     stop_loss: float, target: float):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO scan_results
            (symbol, entry_score, sentiment_score, technical_score,
             recommendation, confidence, entry_price, stop_loss, target, scanned_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol.upper(), entry_score, sentiment_score, technical_score,
              recommendation, confidence, entry_price, stop_loss, target,
              datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()


def get_latest_scan_results(limit: int = 20) -> List[Dict]:
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT * FROM scan_results
            ORDER BY scanned_at DESC LIMIT ?
        """, (limit,))
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()
