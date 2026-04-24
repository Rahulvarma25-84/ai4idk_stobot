"""
BuzzFlow - Alert Engine (Telegram)
Sends alerts via Telegram Bot API. No external library needed.
"""

import logging
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Fix Windows console encoding so emojis don't crash the logger
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class AlertEngine:

    def __init__(self, token: str = None, chat_id: str = None):
        self.token   = token   or os.getenv("TELEGRAM_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self._enabled = bool(self.token and self.chat_id)
        if not self._enabled:
            logger.warning("Telegram not configured. Alerts will only be logged.")

    def send(self, message: str) -> bool:
        # Log a safe ASCII version so Windows console never crashes
        safe = message.encode("ascii", "replace").decode("ascii")
        logger.info(f"ALERT: {safe}")

        if not self._enabled:
            return False
        try:
            url  = f"https://api.telegram.org/bot{self.token}/sendMessage"
            resp = requests.post(url, data={
                "chat_id":    self.chat_id,
                "text":       message,
                "parse_mode": "HTML",
            }, timeout=10)
            if resp.status_code == 200:
                return True
            logger.error(f"Telegram {resp.status_code}: {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def test(self) -> bool:
        return self.send("BuzzFlow alert system is working!")
