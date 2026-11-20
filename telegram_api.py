"""
Minimal Telegram Bot API client using raw aiohttp.
No python-telegram-bot dependency — works on any Python 3.8+
"""
import asyncio
import logging
import aiohttp

logger = logging.getLogger(__name__)

BASE = "https://api.telegram.org/bot{token}/{method}"


class TelegramAPI:
    def __init__(self, token: str):
        self.token = token
        self._session: aiohttp.ClientSession | None = None
        self._offset = 0

    def _url(self, method: str) -> str:
        return BASE.format(token=self.token, method=method)

    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=35)
            )
        return self._session

    async def call(self, method: str, **kwargs) -> dict | None:
        session = await self._session_get()
        try:
            async with session.post(self._url(method), json=kwargs) as r:
                data = await r.json()
                if not data.get("ok"):
                    logger.warning(f"TG {method} error: {data.get('description')}")
                return data
        except Exception as e:
            logger.error(f"TG call {method} failed: {e}")
            return None

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def send_message(self, chat_id, text, parse_mode="Markdown",
                           reply_markup=None) -> dict | None:
        payload = dict(chat_id=chat_id, text=text, parse_mode=parse_mode)
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.call("sendMessage", **payload)

    async def edit_message_text(self, chat_id, message_id, text,
                                parse_mode="Markdown", reply_markup=None):
        payload = dict(chat_id=chat_id, message_id=message_id,
                       text=text, parse_mode=parse_mode)
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.call("editMessageText", **payload)

    async def answer_callback_query(self, callback_query_id,
                                    text="", show_alert=False):
        return await self.call("answerCallbackQuery",
                               callback_query_id=callback_query_id,
                               text=text, show_alert=show_alert)

    async def get_updates(self, timeout=25) -> list:
        data = await self.call("getUpdates",
                               offset=self._offset,
                               timeout=timeout,
                               allowed_updates=["message", "callback_query"])
        if not data or not data.get("ok"):
            return []
        updates = data.get("result", [])
        if updates:
            self._offset = updates[-1]["update_id"] + 1
        return updates


# ── Keyboard builders (pure dicts — no library needed) ────────────────────────

def inline_keyboard(*rows):
    """Build an InlineKeyboardMarkup dict."""
    return {
        "inline_keyboard": [
            [{"text": text, "callback_data": cb} for text, cb in row]
            for row in rows
        ]
    }
