from __future__ import annotations

import logging

import requests

LOGGER = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str | None, chat_id: str | None, dry_run: bool = False) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.dry_run = dry_run

    def send(self, message: str) -> None:
        if self.dry_run:
            print(message)
            return
        if not self.bot_token or not self.chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required unless --dry-run is used")

        response = requests.post(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            json={
                "chat_id": self.chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=12,
        )
        response.raise_for_status()
        LOGGER.info("Sent Telegram alert")
