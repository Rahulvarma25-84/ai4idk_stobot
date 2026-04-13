"""
BuzzFlow - Alert Engine (Telegram)
Sends alerts via Telegram Bot API. No external library needed.
"""

import logging
import os
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class AlertEngine:
    """
    Sends messages via Telegram Bot API.
    Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in .env
    """

    def __init__(self, token: str = None, chat_id: str = None):
        self.token = token or os.getenv("TELEGRAM_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self._enabled = bool(self.token and self.chat_id)
        if not self._enabled:
            logger.warning("Telegram not configured. Alerts will only be logged.")

    def send(self, message: str) -> bool:
        """Send a message. Returns True on success."""
        logger.info(f"ALERT: {message}")

        if not self._enabled:
            return False

        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            resp = requests.post(url, data={
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }, timeout=10)
            if resp.status_code == 200:
                return True
            else:
                logger.error(f"Telegram error {resp.status_code}: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
            return False

    def send_scan_summary(self, top_picks: list):
        """Send a formatted scan summary with top picks."""
        if not top_picks:
            return

        lines = ["📊 <b>BuzzFlow Morning Scan</b>", ""]
        for pick in top_picks[:5]:
            symbol = pick.get("symbol", "")
            score = pick.get("entry_score", 0)
            rec = pick.get("recommendation", "")
            entry = pick.get("entry_price", 0)
            target = pick.get("target_price", 0)
            sl = pick.get("stop_loss", 0)
            lines.append(
                f"🔹 <b>{symbol}</b> | Score: {score:.1f} | {rec}\n"
                f"   Entry: ₹{entry:.2f} | SL: ₹{sl:.2f} | Target: ₹{target:.2f}"
            )

        self.send("\n".join(lines))

    def test(self) -> bool:
        """Send a test message to verify configuration."""
        return self.send("✅ BuzzFlow alert system is working!")
