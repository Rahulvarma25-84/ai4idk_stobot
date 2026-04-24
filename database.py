"""
BuzzFlow - Database Layer (SQLite)
Production schema with full trade lifecycle support.
"""

import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional
import os

logger = logging.getLogger(__name__)
DB_PATH = os.getenv("BUZZFLOW_DB", "buzzflow.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_connection()
    try:
        c = conn.cursor()

        # ── Watchlist ──────────────────────────────────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol            TEXT NOT NULL,
                company_name      TEXT DEFAULT '',
                entry_price       REAL NOT NULL,
                stop_loss         REAL NOT NULL,
                trailing_sl       REAL,
                target            REAL NOT NULL,
                entry_zone_low    REAL,
                entry_zone_high   REAL,
                breakout_level    REAL,
                pullback_level    REAL,
                entry_score       REAL DEFAULT 0,
                exit_score        REAL DEFAULT 0,
                opportunity_score REAL DEFAULT 0,
                trade_state       TEXT DEFAULT 'NEUTRAL',
                confidence        TEXT DEFAULT 'medium',
                risk_capital_pct  REAL DEFAULT 1.0,
                qty               INTEGER DEFAULT 0,
                status            TEXT DEFAULT 'WATCH',
                suggested_action  TEXT DEFAULT 'MONITOR',
                added_at          TEXT NOT NULL,
                updated_at        TEXT,
                notes             TEXT DEFAULT ''
            )
        """)

        # ── Trade log ──────────────────────────────────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS trades_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol       TEXT NOT NULL,
                action       TEXT NOT NULL,
                price        REAL NOT NULL,
                qty          INTEGER DEFAULT 0,
                exit_score   REAL,
                exit_reason  TEXT DEFAULT '',
                pnl_percent  REAL,
                pnl_abs      REAL,
                holding_days INTEGER DEFAULT 0,
                entry_score  REAL,
                timestamp    TEXT NOT NULL,
                notes        TEXT DEFAULT ''
            )
        """)

        # ── Scan results ───────────────────────────────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS scan_results (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol            TEXT NOT NULL,
                entry_score       REAL,
                exit_score        REAL DEFAULT 0,
                opportunity_score REAL DEFAULT 0,
                sentiment_score   REAL,
                technical_score   REAL,
                recommendation    TEXT,
                confidence        TEXT,
                trade_state       TEXT DEFAULT 'NEUTRAL',
                entry_price       REAL,
                entry_zone_low    REAL,
                entry_zone_high   REAL,
                breakout_level    REAL,
                pullback_level    REAL,
                stop_loss         REAL,
                target            REAL,
                rsi               REAL,
                volume_ratio      REAL,
                delivery_score    REAL DEFAULT 50,
                risk_reward       REAL,
                scanned_at        TEXT NOT NULL
            )
        """)

        # ── Replacement log ────────────────────────────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS replacement_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                weak_symbol     TEXT NOT NULL,
                strong_symbol   TEXT NOT NULL,
                weak_opp_score  REAL,
                strong_opp_score REAL,
                score_diff      REAL,
                triggered_at    TEXT NOT NULL,
                acted           INTEGER DEFAULT 0
            )
        """)

        conn.commit()
        logger.info("Database initialized.")
    finally:
        conn.close()


# ── Watchlist ──────────────────────────────────────────────────────────────

def add_to_watchlist(symbol: str, entry_price: float, stop_loss: float,
                     target: float, entry_score: float = 0,
                     confidence: str = "medium", company_name: str = "",
                     entry_zone_low: float = None, entry_zone_high: float = None,
                     breakout_level: float = None, pullback_level: float = None,
                     risk_capital_pct: float = 1.0, qty: int = 0,
                     notes: str = "") -> int:
    conn = get_connection()
    try:
        now = datetime.now().isoformat()
        c = conn.cursor()
        normalized_symbol = symbol.upper()

        # Prevent duplicate active positions for the same symbol.
        existing = c.execute(
            """
            SELECT id FROM watchlist
            WHERE symbol=? AND status NOT IN ('CLOSED','EXIT')
            ORDER BY id DESC LIMIT 1
            """,
            (normalized_symbol,),
        ).fetchone()

        if existing:
            c.execute("""
                UPDATE watchlist
                SET company_name=?, entry_price=?, stop_loss=?, target=?,
                    entry_zone_low=?, entry_zone_high=?, breakout_level=?, pullback_level=?,
                    entry_score=?, confidence=?, risk_capital_pct=?, qty=?,
                    status='WATCH', trade_state='NEUTRAL', updated_at=?, notes=?
                WHERE id=?
            """, (company_name, entry_price, stop_loss, target,
                  entry_zone_low, entry_zone_high, breakout_level, pullback_level,
                  entry_score, confidence, risk_capital_pct, qty, now, notes, existing["id"]))
            conn.commit()
            logger.info(f"Updated existing watchlist row for {normalized_symbol} (id={existing['id']})")
            return int(existing["id"])

        c.execute("""
            INSERT INTO watchlist
            (symbol, company_name, entry_price, stop_loss, target,
             entry_zone_low, entry_zone_high, breakout_level, pullback_level,
             entry_score, confidence, risk_capital_pct, qty,
             status, trade_state, added_at, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'WATCH','NEUTRAL',?,?)
        """, (normalized_symbol, company_name, entry_price, stop_loss, target,
              entry_zone_low, entry_zone_high, breakout_level, pullback_level,
              entry_score, confidence, risk_capital_pct, qty, now, notes))
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
            c.execute(
                "SELECT * FROM watchlist WHERE status=? ORDER BY id DESC",
                (status,),
            )
        else:
            c.execute("SELECT * FROM watchlist ORDER BY id DESC")

        rows = [dict(row) for row in c.fetchall()]

        # Deduplicate: keep only one row per symbol.
        # For active symbols: keep the most recent active row.
        # For closed symbols: keep only the most recent closed row.
        # This ensures active/closed/all tabs are always consistent.
        seen = {}  # symbol -> best row
        for row in rows:
            sym = row.get("symbol")
            is_active = row.get("status") not in ("CLOSED", "EXIT")
            if sym not in seen:
                seen[sym] = row
            else:
                existing = seen[sym]
                existing_active = existing.get("status") not in ("CLOSED", "EXIT")
                # Active always beats closed
                if is_active and not existing_active:
                    seen[sym] = row
                # Among same type, keep higher id (more recent)
                elif is_active == existing_active and row["id"] > existing["id"]:
                    seen[sym] = row

        result = list(seen.values())
        result.sort(key=lambda r: (r.get("entry_score") or 0), reverse=True)
        return result
    finally:
        conn.close()


def update_watchlist_scores(symbol: str, exit_score: float,
                             opportunity_score: float, trade_state: str,
                             suggested_action: str, trailing_sl: float = None,
                             notes: str = ""):
    conn = get_connection()
    try:
        now = datetime.now().isoformat()
        conn.execute("""
            UPDATE watchlist
            SET exit_score=?, opportunity_score=?, trade_state=?,
                suggested_action=?, trailing_sl=COALESCE(?,trailing_sl),
                updated_at=?, notes=?
            WHERE symbol=? AND status NOT IN ('CLOSED','EXIT')
        """, (exit_score, opportunity_score, trade_state,
              suggested_action, trailing_sl, now, notes, symbol.upper()))
        conn.commit()
    finally:
        conn.close()


def update_watchlist_status(symbol: str, status: str, notes: str = ""):
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE watchlist SET status=?, updated_at=?, notes=?
            WHERE symbol=? AND status NOT IN ('CLOSED')
        """, (status, datetime.now().isoformat(), notes, symbol.upper()))
        conn.commit()
    finally:
        conn.close()


def remove_from_watchlist(symbol: str):
    """Mark active positions as CLOSED (soft delete)."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE watchlist SET status='CLOSED', updated_at=? WHERE symbol=? AND status!='CLOSED'",
            (datetime.now().isoformat(), symbol.upper())
        )
        conn.commit()
    finally:
        conn.close()


def hard_delete_watchlist_row(row_id: int):
    """Permanently delete a single watchlist row by id (used for closed rows)."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM watchlist WHERE id=?", (row_id,))
        conn.commit()
        logger.info(f"Hard deleted watchlist row id={row_id}")
    finally:
        conn.close()


# ── Trade log ──────────────────────────────────────────────────────────────

def log_trade(symbol: str, action: str, price: float,
              qty: int = 0, exit_score: float = None,
              exit_reason: str = "", pnl_percent: float = None,
              pnl_abs: float = None, holding_days: int = 0,
              entry_score: float = None, notes: str = ""):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO trades_log
            (symbol, action, price, qty, exit_score, exit_reason,
             pnl_percent, pnl_abs, holding_days, entry_score, timestamp, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (symbol.upper(), action, price, qty, exit_score, exit_reason,
              pnl_percent, pnl_abs, holding_days, entry_score,
              datetime.now().isoformat(), notes))
        conn.commit()
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


# ── Scan results ───────────────────────────────────────────────────────────

def save_scan_result(symbol: str, entry_score: float, sentiment_score: float,
                     technical_score: float, recommendation: str, confidence: str,
                     entry_price: float, stop_loss: float, target: float,
                     entry_zone_low: float = None, entry_zone_high: float = None,
                     breakout_level: float = None, pullback_level: float = None,
                     rsi: float = None, volume_ratio: float = None,
                     delivery_score: float = 50, risk_reward: float = None,
                     opportunity_score: float = 0, trade_state: str = "NEUTRAL"):
    """
    Upsert scan result for a symbol.
    If a row for this symbol already exists from today, UPDATE it in place.
    Otherwise INSERT a new row.
    This ensures the dashboard always shows fresh values after every scan,
    even if the stock was filtered out for alerting purposes.
    """
    conn = get_connection()
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        now   = datetime.now().isoformat()
        sym   = symbol.upper()

        existing = conn.execute(
            "SELECT id FROM scan_results WHERE symbol=? AND scanned_at LIKE ? ORDER BY id DESC LIMIT 1",
            (sym, f"{today}%")
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE scan_results SET
                    entry_score=?, sentiment_score=?, technical_score=?,
                    recommendation=?, confidence=?, trade_state=?, entry_price=?,
                    entry_zone_low=?, entry_zone_high=?, breakout_level=?, pullback_level=?,
                    stop_loss=?, target=?, rsi=?, volume_ratio=?, delivery_score=?,
                    risk_reward=?, opportunity_score=?, scanned_at=?
                WHERE id=?
            """, (entry_score, sentiment_score, technical_score,
                  recommendation, confidence, trade_state, entry_price,
                  entry_zone_low, entry_zone_high, breakout_level, pullback_level,
                  stop_loss, target, rsi, volume_ratio, delivery_score,
                  risk_reward, opportunity_score, now, existing["id"]))
        else:
            conn.execute("""
                INSERT INTO scan_results
                (symbol, entry_score, sentiment_score, technical_score,
                 recommendation, confidence, trade_state, entry_price,
                 entry_zone_low, entry_zone_high, breakout_level, pullback_level,
                 stop_loss, target, rsi, volume_ratio, delivery_score, risk_reward,
                 opportunity_score, scanned_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (sym, entry_score, sentiment_score, technical_score,
                  recommendation, confidence, trade_state, entry_price,
                  entry_zone_low, entry_zone_high, breakout_level, pullback_level,
                  stop_loss, target, rsi, volume_ratio, delivery_score, risk_reward,
                  opportunity_score, now))
        conn.commit()
    finally:
        conn.close()


def get_latest_scan_results(limit: int = 50) -> List[Dict]:
    """Return the most recent scan result per symbol, ordered by entry_score."""
    conn = get_connection()
    try:
        c = conn.cursor()
        # Get latest id per symbol first (compatible with all SQLite versions)
        c.execute("""
            SELECT sr.*
            FROM scan_results sr
            INNER JOIN (
                SELECT symbol, MAX(id) AS max_id
                FROM scan_results
                GROUP BY symbol
            ) latest ON sr.symbol = latest.symbol AND sr.id = latest.max_id
            ORDER BY sr.entry_score DESC, sr.scanned_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()


# ── Database Maintenance ──────────────────────────────────────────────────

def cleanup_db(
    scan_keep_days: int = 7,
    closed_watchlist_keep_days: int = 30,
    replacement_keep_days: int = 30,
) -> dict:
    """
    Routine DB cleanup. Safe to run after every scan.

    - scan_results:    keep only the latest row per symbol + purge rows
                       older than `scan_keep_days` days
    - watchlist:       hard-delete CLOSED/EXIT rows older than
                       `closed_watchlist_keep_days` days
    - replacement_log: purge rows older than `replacement_keep_days` days
    - trades_log:      never deleted (permanent performance record)

    Returns dict with counts of deleted rows per table.
    """
    conn = get_connection()
    deleted = {}
    try:
        from datetime import timedelta
        now = datetime.now()

        # ── scan_results: delete old duplicate rows ────────────────────
        # Keep only the single latest row per symbol (highest id).
        # Then also purge any row older than scan_keep_days even if it's
        # the only row for that symbol (stale signal, no longer relevant).
        cutoff_scan = (now - timedelta(days=scan_keep_days)).isoformat()

        # Step 1: delete non-latest rows per symbol
        r1 = conn.execute("""
            DELETE FROM scan_results
            WHERE id NOT IN (
                SELECT MAX(id) FROM scan_results GROUP BY symbol
            )
        """)

        # Step 2: delete latest rows that are too old
        r2 = conn.execute(
            "DELETE FROM scan_results WHERE scanned_at < ?",
            (cutoff_scan,)
        )

        deleted["scan_results"] = r1.rowcount + r2.rowcount

        # ── watchlist: purge old closed positions ──────────────────────
        cutoff_wl = (now - timedelta(days=closed_watchlist_keep_days)).isoformat()
        r3 = conn.execute("""
            DELETE FROM watchlist
            WHERE status IN ('CLOSED', 'EXIT')
            AND COALESCE(updated_at, added_at) < ?
        """, (cutoff_wl,))
        deleted["watchlist_closed"] = r3.rowcount

        # ── replacement_log: purge old entries ────────────────────────
        cutoff_rep = (now - timedelta(days=replacement_keep_days)).isoformat()
        r4 = conn.execute(
            "DELETE FROM replacement_log WHERE triggered_at < ?",
            (cutoff_rep,)
        )
        deleted["replacement_log"] = r4.rowcount

        conn.commit()

        # Reclaim disk space after deletions
        conn.execute("VACUUM")

        logger.info(
            f"DB cleanup: scan_results -{deleted['scan_results']} | "
            f"watchlist_closed -{deleted['watchlist_closed']} | "
            f"replacement_log -{deleted['replacement_log']}"
        )
        return deleted
    except Exception as e:
        logger.error(f"DB cleanup failed: {e}")
        return {}
    finally:
        conn.close()



def log_replacement(weak_symbol: str, strong_symbol: str,
                    weak_score: float, strong_score: float):
    conn = get_connection()
    try:
        diff = round(strong_score - weak_score, 2)
        conn.execute("""
            INSERT INTO replacement_log
            (weak_symbol, strong_symbol, weak_opp_score, strong_opp_score,
             score_diff, triggered_at)
            VALUES (?,?,?,?,?,?)
        """, (weak_symbol.upper(), strong_symbol.upper(),
              weak_score, strong_score, diff, datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()
