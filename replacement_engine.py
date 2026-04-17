"""
BuzzFlow - Replacement Engine
ONLY triggers when a current position is WEAK AND a strong candidate exists.
NOT a constant "better stock" suggester. Capital preservation first.
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime

from database import get_watchlist, get_latest_scan_results, log_replacement
from alert_engine import AlertEngine

logger = logging.getLogger(__name__)

MIN_SCORE_DIFF = 20      # Opportunity score difference to trigger replacement
MIN_ENTRY_SCORE = 70     # Replacement candidate must score ≥ 70


class ReplacementEngine:

    def __init__(self, telegram_token: str = None, telegram_chat_id: str = None):
        self.alert = AlertEngine(token=telegram_token, chat_id=telegram_chat_id)

    def run(self) -> List[Dict]:
        """
        Check active positions for WEAK state.
        If WEAK, look for a strong replacement candidate from latest scan.
        Only suggest replacement if score diff ≥ 20 and candidate score ≥ 70.
        """
        active   = [w for w in get_watchlist() if w["status"] not in ("CLOSED","EXIT")]
        weak     = [w for w in active if w.get("trade_state") == "WEAK"]
        scans    = get_latest_scan_results(limit=50)
        active_symbols = {w["symbol"] for w in active}

        suggestions = []

        for pos in weak:
            weak_sym   = pos["symbol"]
            weak_score = pos.get("opportunity_score") or 0

            # Find best replacement not already in watchlist
            candidates = [
                s for s in scans
                if s["symbol"] not in active_symbols
                and s.get("entry_score", 0) >= MIN_ENTRY_SCORE
                and (s.get("opportunity_score") or 0) - weak_score >= MIN_SCORE_DIFF
            ]

            if not candidates:
                continue

            best = max(candidates, key=lambda x: x.get("opportunity_score") or 0)
            diff = round((best.get("opportunity_score") or 0) - weak_score, 1)

            suggestion = {
                "weak_symbol":    weak_sym,
                "weak_opp_score": weak_score,
                "weak_pnl":       pos.get("notes", ""),
                "strong_symbol":  best["symbol"],
                "strong_score":   best.get("entry_score", 0),
                "strong_opp":     best.get("opportunity_score", 0),
                "score_diff":     diff,
                "entry_zone":     f"₹{best.get('entry_zone_low',0):.0f}–{best.get('entry_zone_high',0):.0f}",
                "stop_loss":      best.get("stop_loss", 0),
                "target":         best.get("target", 0),
            }
            suggestions.append(suggestion)

            # Log to DB
            log_replacement(
                weak_symbol=weak_sym, strong_symbol=best["symbol"],
                weak_score=weak_score, strong_score=best.get("opportunity_score", 0)
            )

            # Send alert
            msg = (
                f"🔁 <b>REPLACEMENT SUGGESTED</b>\n\n"
                f"❌ Exit: <b>{weak_sym}</b> (Opp Score: {weak_score:.0f} — WEAK)\n"
                f"✅ Enter: <b>{best['symbol']}</b> (Entry Score: {best.get('entry_score',0):.0f} | Opp: {best.get('opportunity_score',0):.0f})\n\n"
                f"Score improvement: +{diff:.0f} points\n"
                f"Entry Zone: {suggestion['entry_zone']}\n"
                f"SL: ₹{suggestion['stop_loss']:.2f} | Target: ₹{suggestion['target']:.2f}\n\n"
                f"<i>This is a suggestion. You decide whether to act.</i>"
            )
            self.alert.send(msg)
            logger.info(f"Replacement: {weak_sym} → {best['symbol']} (diff={diff:.0f})")

        return suggestions

    def print_report(self, suggestions: List[Dict]):
        if not suggestions:
            print("\n  No replacement suggestions. All positions are NEUTRAL or STRONG.\n")
            return
        print(f"\n{'='*80}")
        print(f"  REPLACEMENT SUGGESTIONS — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'='*80}")
        for s in suggestions:
            print(f"\n  EXIT:  {s['weak_symbol']} (Opp Score: {s['weak_opp_score']:.0f} — WEAK)")
            print(f"  ENTER: {s['strong_symbol']} (Entry: {s['strong_score']:.0f} | Opp: {s['strong_opp']:.0f})")
            print(f"  Zone:  {s['entry_zone']} | SL: ₹{s['stop_loss']:.2f} | Target: ₹{s['target']:.2f}")
            print(f"  Score improvement: +{s['score_diff']:.0f} points")
        print(f"\n{'='*80}\n")
