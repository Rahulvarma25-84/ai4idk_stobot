"""
BuzzFlow - Database Migration
Adds all new columns to existing buzzflow.db without losing data.
Run once: python migrate_db.py
"""

import sqlite3
import os

DB_PATH = os.getenv("BUZZFLOW_DB", "buzzflow.db")
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()


def add_col(table, col, typedef):
    existing = [row[1] for row in c.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
        print(f"  + {table}.{col}")
    else:
        print(f"  . {table}.{col} (exists)")


print("Migrating scan_results...")
add_col("scan_results", "trade_state",       "TEXT DEFAULT 'NEUTRAL'")
add_col("scan_results", "entry_zone_low",    "REAL")
add_col("scan_results", "entry_zone_high",   "REAL")
add_col("scan_results", "breakout_level",    "REAL")
add_col("scan_results", "pullback_level",    "REAL")
add_col("scan_results", "rsi",               "REAL")
add_col("scan_results", "volume_ratio",      "REAL")
add_col("scan_results", "delivery_score",    "REAL DEFAULT 50")
add_col("scan_results", "risk_reward",       "REAL")
add_col("scan_results", "opportunity_score", "REAL DEFAULT 0")
add_col("scan_results", "exit_score",        "REAL DEFAULT 0")

print("\nMigrating watchlist...")
add_col("watchlist", "exit_score",        "REAL DEFAULT 0")
add_col("watchlist", "opportunity_score", "REAL DEFAULT 0")
add_col("watchlist", "trade_state",       "TEXT DEFAULT 'NEUTRAL'")
add_col("watchlist", "suggested_action",  "TEXT DEFAULT 'MONITOR'")
add_col("watchlist", "trailing_sl",       "REAL")
add_col("watchlist", "entry_zone_low",    "REAL")
add_col("watchlist", "entry_zone_high",   "REAL")
add_col("watchlist", "breakout_level",    "REAL")
add_col("watchlist", "pullback_level",    "REAL")
add_col("watchlist", "risk_capital_pct",  "REAL DEFAULT 1.0")
add_col("watchlist", "qty",               "INTEGER DEFAULT 0")

print("\nMigrating trades_log...")
add_col("trades_log", "qty",          "INTEGER DEFAULT 0")
add_col("trades_log", "pnl_abs",      "REAL")
add_col("trades_log", "holding_days", "INTEGER DEFAULT 0")
add_col("trades_log", "entry_score",  "REAL")

print("\nChecking replacement_log table...")
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
if "replacement_log" not in tables:
    conn.execute("""
        CREATE TABLE replacement_log (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            weak_symbol      TEXT NOT NULL,
            strong_symbol    TEXT NOT NULL,
            weak_opp_score   REAL,
            strong_opp_score REAL,
            score_diff       REAL,
            triggered_at     TEXT NOT NULL,
            acted            INTEGER DEFAULT 0
        )
    """)
    print("  + replacement_log (created)")
else:
    print("  . replacement_log (exists)")

conn.commit()
conn.close()
print("\nMigration complete. You can now run the scanner.")
