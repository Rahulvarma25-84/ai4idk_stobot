"""
BuzzFlow - News Engine (Google News RSS)
Replaces Reddit + NewsAPI with free, unlimited Google News RSS.
"""

import logging
import time
from typing import Dict, List
from urllib.parse import quote_plus

try:
    import feedparser
except ImportError:
    feedparser = None

logger = logging.getLogger(__name__)

POSITIVE_WORDS = [
    "growth", "profit", "upgrade", "strong", "bullish", "surge", "rally",
    "gain", "outperform", "beat", "record", "high", "buy", "positive",
    "expansion", "revenue", "dividend", "acquisition", "partnership", "launch"
]

NEGATIVE_WORDS = [
    "loss", "fall", "fraud", "decline", "bearish", "crash", "drop",
    "downgrade", "miss", "weak", "low", "sell", "negative", "debt",
    "lawsuit", "penalty", "recall", "layoff", "bankruptcy", "investigation"
]


class NewsEngine:
    """
    Fetches news from Google News RSS and scores sentiment.
    No API keys required. No rate limits.
    """

    def __init__(self):
        if feedparser is None:
            raise ImportError("feedparser is required: pip install feedparser")
        self._cache: Dict[str, dict] = {}
        self._cache_ttl = 300  # 5 minutes

    def _is_cached(self, key: str) -> bool:
        if key in self._cache:
            if time.time() - self._cache[key]["ts"] < self._cache_ttl:
                return True
        return False

    def fetch_headlines(self, query: str, max_results: int = 10) -> List[str]:
        """Fetch headlines from Google News RSS for a query."""
        cache_key = f"headlines_{query}"
        if self._is_cached(cache_key):
            return self._cache[cache_key]["data"]

        try:
            encoded = quote_plus(query)
            url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
            feed = feedparser.parse(url)
            headlines = [entry.title for entry in feed.entries[:max_results]]
            self._cache[cache_key] = {"data": headlines, "ts": time.time()}
            logger.info(f"Fetched {len(headlines)} headlines for '{query}'")
            return headlines
        except Exception as e:
            logger.error(f"Error fetching news for '{query}': {e}")
            return []

    def get_headlines_for_stock(self, ticker: str, company_name: str = "") -> List[str]:
        """Get headlines for a stock using multiple queries."""
        base = ticker.replace(".NS", "").replace(".BO", "")
        queries = [f"{base} stock India", f"{base} NSE"]
        if company_name:
            queries.append(f"{company_name} stock")

        all_headlines = []
        seen = set()
        for q in queries:
            for h in self.fetch_headlines(q, max_results=8):
                if h not in seen:
                    seen.add(h)
                    all_headlines.append(h)
        return all_headlines[:15]

    def sentiment_score(self, headlines: List[str]) -> float:
        """
        Score headlines using keyword matching.
        Returns normalized score 0-100 (50 = neutral).
        """
        if not headlines:
            return 50.0

        score = 0
        for h in headlines:
            h_lower = h.lower()
            for word in POSITIVE_WORDS:
                if word in h_lower:
                    score += 1
            for word in NEGATIVE_WORDS:
                if word in h_lower:
                    score -= 1

        # Normalize: map [-len, +len] → [0, 100]
        max_possible = len(headlines) * 3
        normalized = 50 + (score / max(max_possible, 1)) * 50
        return round(max(0.0, min(100.0, normalized)), 2)

    def get_buzz_score(self, ticker: str, company_name: str = "") -> dict:
        """
        Main method: fetch news + compute sentiment.
        Returns dict compatible with existing BuzzEngine interface.
        """
        headlines = self.get_headlines_for_stock(ticker, company_name)
        raw_score = self.sentiment_score(headlines)

        # Normalize to 0-1 for compatibility with existing scoring
        normalized = raw_score / 100.0

        return {
            "score": round(normalized, 4),
            "headlines": headlines,
            "headline_count": len(headlines),
            "raw_sentiment": raw_score,
            "price_levels": {}  # Kept for interface compatibility
        }
