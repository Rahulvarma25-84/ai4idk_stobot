#!/usr/bin/env python3
"""
BuzzFlow - Universe Updater
Fetches NSE index constituent lists and merges them into data/universe.csv.

Run this once a month (or after NSE rebalancing):
    python update_universe.py

The CSV is committed to git so the scanner always has a local copy.
GitHub Actions can also run this on a schedule.
"""

import os
import sys
import logging
import requests
import pandas as pd
from io import StringIO
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

OUT_PATH = Path("data/universe.csv")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Referer": "https://www.nseindia.com/",
}

# NSE archives — free, no auth, no cookies needed
_NSE_CSVS = {
    "nifty50":     "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    "nifty100":    "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
    "nifty200":    "https://archives.nseindia.com/content/indices/ind_nifty200list.csv",
    "nifty500":    "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    "midcap150":   "https://archives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    "smallcap250": "https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
}

# Sector → category mapping (for scan filters)
_SECTOR_CATEGORY = {
    "Financial Services":          "banking",
    "Information Technology":      "nifty_it",
    "Pharmaceuticals":             "pharma",
    "Healthcare":                  "pharma",
    "Automobile and Auto Components": "auto",
    "Capital Goods":               "capex",
    "Construction":                "capex",
    "Power":                       "capex",
    "Infrastructure":              "capex",
    "Fast Moving Consumer Goods":  "consumption",
    "Consumer Durables":           "consumption",
    "Textiles":                    "consumption",
    "Metals & Mining":             "metals",
    "Oil Gas & Consumable Fuels":  "metals",
    "Chemicals":                   "chemicals",
    "Fertilisers & Agrochemicals": "chemicals",
    "Realty":                      "realty",
    "Media Entertainment & Publication": "media",
    "Telecommunication":           "telecom",
    "Services":                    "services",
    "Forest Materials":            "others",
    "Diversified":                 "others",
}


def _fetch_csv(name: str, url: str) -> pd.DataFrame:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"  {name}: HTTP {resp.status_code}")
            return pd.DataFrame()
        df = pd.read_csv(StringIO(resp.text))
        df.columns = [c.strip() for c in df.columns]
        logger.info(f"  {name}: {len(df)} stocks")
        return df
    except Exception as e:
        logger.error(f"  {name}: {e}")
        return pd.DataFrame()


def update():
    logger.info("Fetching NSE index constituent lists...")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    frames = []
    for name, url in _NSE_CSVS.items():
        df = _fetch_csv(name, url)
        if df.empty:
            continue
        # Normalise columns — NSE uses "Symbol", "Company Name", "Industry"
        if "Symbol" not in df.columns:
            logger.warning(f"  {name}: no Symbol column, skipping")
            continue
        df = df.rename(columns={
            "Symbol":       "symbol",
            "Company Name": "company",
            "Industry":     "industry",
            "Series":       "series",
            "ISIN Code":    "isin",
        })
        df["index_name"] = name
        frames.append(df[["symbol","company","industry","series","isin","index_name"]])

    if not frames:
        logger.error("All NSE fetches failed. Universe not updated.")
        sys.exit(1)

    combined = pd.concat(frames, ignore_index=True)

    # Keep only EQ series (exclude BE, SM, etc.)
    if "series" in combined.columns:
        combined = combined[combined["series"].str.strip() == "EQ"]

    # Deduplicate — keep the row from the broadest index (nifty500 > midcap150 etc.)
    index_priority = {"nifty50":1,"nifty100":2,"nifty200":3,"nifty500":4,"midcap150":5,"smallcap250":6}
    combined["_priority"] = combined["index_name"].map(index_priority).fillna(9)
    combined = combined.sort_values("_priority")
    combined = combined.drop_duplicates(subset="symbol", keep="first")
    combined = combined.drop(columns=["_priority"])

    # Add Yahoo Finance ticker (append .NS)
    combined["ticker"] = combined["symbol"].str.strip().str.upper() + ".NS"

    # Add scan category based on industry
    combined["industry"] = combined["industry"].str.strip()
    combined["category"] = combined["industry"].map(_SECTOR_CATEGORY).fillna("others")

    # Add market cap tier based on index membership
    def _cap_tier(idx):
        if idx in ("nifty50","nifty100"):   return "large"
        if idx in ("nifty200","nifty500"):  return "mid"
        return "small"
    combined["cap_tier"] = combined["index_name"].apply(_cap_tier)

    # Add metadata
    combined["updated_at"] = datetime.now().strftime("%Y-%m-%d")

    # Final column order
    combined = combined[[
        "ticker","symbol","company","industry","category",
        "cap_tier","index_name","isin","updated_at"
    ]].sort_values("ticker").reset_index(drop=True)

    combined.to_csv(OUT_PATH, index=False)
    logger.info(f"\nSaved {len(combined)} stocks to {OUT_PATH}")
    logger.info(f"Categories: {combined['category'].value_counts().to_dict()}")
    logger.info(f"Cap tiers:  {combined['cap_tier'].value_counts().to_dict()}")
    print(f"\nDone. {len(combined)} stocks in {OUT_PATH}")
    print(combined[["ticker","company","industry","category","cap_tier"]].head(10).to_string(index=False))


if __name__ == "__main__":
    update()
