"""
BuzzFlow - Universe Engine
Reads stock universe from data/universe.csv.

To update the CSV from NSE:
    python update_universe.py

The CSV is committed to git — scanner always works offline.
"""

import logging
import os
from pathlib import Path
from typing import List, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

UNIVERSE_CSV = Path("data/universe.csv")

_cache: Optional[pd.DataFrame] = None


def _invalidate_cache():
    """Call this after updating universe.csv to force reload on next access."""
    global _cache
    _cache = None


def _load() -> pd.DataFrame:
    global _cache
    if _cache is not None:
        return _cache
    if not UNIVERSE_CSV.exists():
        raise FileNotFoundError(
            f"{UNIVERSE_CSV} not found. Run: python update_universe.py"
        )
    df = pd.read_csv(UNIVERSE_CSV)
    df["ticker"]   = df["ticker"].str.strip().str.upper()
    df["category"] = df["category"].str.strip().str.lower()
    df["cap_tier"] = df["cap_tier"].str.strip().str.lower()
    _cache = df
    logger.info(f"Universe loaded: {len(df)} stocks from {UNIVERSE_CSV}")
    return df


def get_universe(
    cap_tier: str = None,       # "large", "mid", "small", or None for all
    category: str = None,       # "banking", "nifty_it", "pharma", etc.
    index_name: str = None,     # "nifty50", "nifty500", etc.
) -> List[str]:
    """
    Returns list of Yahoo Finance tickers (e.g. 'RELIANCE.NS').
    Filters by cap_tier, category, or index_name if provided.
    """
    df = _load()

    if cap_tier:
        df = df[df["cap_tier"] == cap_tier.lower()]
    if category:
        df = df[df["category"] == category.lower()]
    if index_name:
        df = df[df["index_name"] == index_name.lower()]

    return df["ticker"].tolist()


def get_universe_df(
    cap_tier: str = None,
    category: str = None,
    index_name: str = None,
) -> pd.DataFrame:
    """Returns full DataFrame with all metadata columns."""
    df = _load()
    if cap_tier:
        df = df[df["cap_tier"] == cap_tier.lower()]
    if category:
        df = df[df["category"] == category.lower()]
    if index_name:
        df = df[df["index_name"] == index_name.lower()]
    return df.reset_index(drop=True)


def get_stock_info(ticker: str) -> Optional[Dict]:
    """Returns metadata dict for a single ticker, or None if not found."""
    df = _load()
    row = df[df["ticker"] == ticker.upper()]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


def get_categories() -> List[str]:
    """Returns all available category names."""
    return sorted(_load()["category"].unique().tolist())


def get_universe_stats() -> Dict:
    df = _load()
    return {
        "total":       len(df),
        "large_cap":   len(df[df["cap_tier"] == "large"]),
        "mid_cap":     len(df[df["cap_tier"] == "mid"]),
        "small_cap":   len(df[df["cap_tier"] == "small"]),
        "micro_cap":   len(df[df["cap_tier"] == "micro"]),
        "categories":  df["category"].value_counts().to_dict(),
        "updated_at":  df["updated_at"].iloc[0] if "updated_at" in df.columns else "unknown",
    }


if __name__ == "__main__":
    stats = get_universe_stats()
    print(f"\nUniverse: {stats['total']} stocks | Updated: {stats['updated_at']}")
    print(f"Large: {stats['large_cap']} | Mid: {stats['mid_cap']} | Small: {stats['small_cap']}")
    print(f"Categories: {stats['categories']}")
