import html
import logging
import re
import time
from typing import Any

import requests

from .config import Settings
from .database import Database

logger = logging.getLogger(__name__)

POLL_TIMEOUT = 60
CB_APPROVE = "approve"
CB_REJECT = "reject"

START_TEXT = (
    "\U0001F44B <b>Привет!</b>\n\n"
    "Я бот для сбора анекдотов. Хочешь поделиться смешной историей?\n"
    "Просто отправь мне текст анекдота — и он уйдёт на модерацию.\n"
    "Лучшие публикуются в канале с указанием автора!"
)

SUBMIT_TEXT = (
    "\U0001F4DD <b>Отправка анекдота</b>\n\n"
    "Просто напиши мне текст анекдота в этом чате.\n"
    "Можно добавлять диалоги, шутки, истории — что угодно!\n\n"
    "После модерации лучшие попадают в канал."
)


def _api_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _api_call(token: str, method: str, json: dict | None = None, timeout: int = 30) -> dict | None:
    try:
        resp = requests.post(_api_url(token, method), json=json, timeout=timeout)
        data = resp.json()
        if data.get("ok"):
            return data
        logger.warning("Telegram API %s error: %s", method, data.get("description"))
    except Exception as e:
        logger.error("Telegram API %s failed: %s", method, e)
    return None


def _send_message(token: str, chat_id: int | str, text: str, parse_mode: str = "HTML", reply_markup: dict | None = None) -> dict | None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _api_call(token, "sendMessage", payload)


def _edit_message_reply_markup(token: str, chat_id: int | str, message_id: int, reply_markup: dict | None = None) -> None:
    _api_call(token, "editMessageReplyMarkup", {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": reply_markup,
    })


def _answer_callback_query(token: str, callback_query_id: str, text: str | None = None) -> None:
    payload: dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    _api_call(token, "answerCallbackQuery", payload)


def _build_moderation_keyboard(joke_id: int) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "\u2705 Approve", "callback_data": f"{CB_APPROVE}:{joke_id}"},
                {"text": "\u274C Reject", "callback_data": f"{CB_REJECT}:{joke_id}"},
            ]
        ]
    }


def _author_display(username: str | None, name: str | None) -> str:
    if username:
        return f"@{username}"
    return name or f"ID {0}"


def _get_author_link(user: dict) -> tuple[int, str | None, str | None]:
    uid = user["id"]
    username = user.get("username")
    first = user.get("first_name", "")
    last = user.get("last_name", "")
    full_name = f"{first} {last}".strip() or None
    return uid, username, full_name


class PollingHandler:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self._offset = 0
        self._running = False

    def _get_updates(self) -> list[dict]:
        payload: dict[str, Any] = {
            "offset": self._offset,
            "timeout": POLL_TIMEOUT,
            "allowed_updates": ["message", "callback_query"],
        }
        data = _api_call(self.settings.bot_token, "getUpdates", payload, timeout=POLL_TIMEOUT + 10)
        if data is None:
            return []
        return data.get("result", [])

    @staticmethod
    def _is_reaction(text: str) -> bool:
        emoji_count = len(re.findall(r"[\U00010000-\U0010FFFF]", text))
        emoji_ratio = emoji_count / max(len(text), 1)
        word_count = len(text.split())
        text_len = len(text.strip())
        if emoji_ratio > 0.3:
            return True
        if emoji_count > 0 and text_len < 20 and word_count <= 2:
            return True
        return False

    def _handle_message(self, msg: dict) -> None:
        chat = msg.get("chat", {})
        if chat.get("type") != "private":
            return

        chat_id = chat["id"]
        text = msg.get("text", "")
        user = msg.get("from", {})
        uid, username, full_name = _get_author_link(user)

        if not text.strip():
            return

        if text.startswith("/start"):
            _send_message(self.settings.bot_token, chat_id, START_TEXT)
            return

        if text.startswith("/submit"):
            _send_message(self.settings.bot_token, chat_id, SUBMIT_TEXT)
            return

        if self._is_reaction(text):
            self.db.save_reaction(text.strip(), uid, username)
            _send_message(
                self.settings.bot_token, chat_id,
                "\U0001F44D Спасибо за реакцию! Твоё мнение может появиться в следующем выпуске.",
            )
            return

        if len(text) < 10:
            _send_message(self.settings.bot_token, chat_id, "\u26A0\uFE0F Слишком коротко. Напиши полноценный анекдот.")
            return

        joke_id = self.db.save_submitted_joke(text.strip(), uid, username, full_name)

        _send_message(
            self.settings.bot_token, chat_id,
            f"\u2705 Спасибо! Твой анекдот (#{joke_id}) отправлен на модерацию.\n"
            "Лучшие публикуются в канале с указанием автора!",
        )

        self._notify_admin(joke_id, text, uid, username, full_name)

    def _notify_admin(self, joke_id: int, text: str, author_id: int, username: str | None, name: str | None) -> None:
        admin_id = self.settings.admin_id
        if admin_id is None:
            logger.warning("ADMIN_ID not set, cannot forward submission #%s", joke_id)
            return

        preview = text.replace("\n", " ")[:200].rstrip() + "\u2026" if len(text) > 200 else text
        msg_text = (
            f"\U0001F4E8 <b>Новый анекдот</b> (#{joke_id})\n\n"
            f"{html.escape(preview)}\n\n"
            f"\u2500\u2500\u2500\n"
            f"<b>Автор:</b> {_author_display(username, name)} (ID: {author_id})"
        )

        result = _send_message(
            self.settings.bot_token,
            admin_id,
            msg_text,
            reply_markup=_build_moderation_keyboard(joke_id),
        )
        if result:
            msg_id = result.get("result", {}).get("message_id")
            if msg_id:
                self.db.set_moderator_message(joke_id, msg_id)

    def _handle_callback(self, cb: dict) -> None:
        data = cb.get("data", "")
        cb_id = cb.get("id", "")
        msg = cb.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        message_id = msg.get("message_id")

        admin_id = self.settings.admin_id
        if admin_id is not None and chat_id != admin_id:
            _answer_callback_query(self.settings.bot_token, cb_id, "\u26A0\uFE0F Только админ может модерировать")
            return

        try:
            action, raw_id = data.split(":", 1)
            joke_id = int(raw_id)
        except (ValueError, IndexError):
            _answer_callback_query(self.settings.bot_token, cb_id, "\u274C Ошибка")
            return

        if action == CB_APPROVE:
            ok = self.db.approve_submission(joke_id)
            if ok:
                _edit_message_reply_markup(self.settings.bot_token, chat_id, message_id)
                _send_message(
                    self.settings.bot_token, chat_id,
                    f"\u2705 Анекдот #{joke_id} одобрен! Будет опубликован в ближайшее время.",
                )
                _answer_callback_query(self.settings.bot_token, cb_id, "\u2705 Одобрено!")
                self._notify_author(joke_id, approved=True)
            else:
                _answer_callback_query(self.settings.bot_token, cb_id, "\u26A0\uFE0F Уже обработано")
        elif action == CB_REJECT:
            ok = self.db.reject_submission(joke_id)
            if ok:
                _edit_message_reply_markup(self.settings.bot_token, chat_id, message_id)
                _send_message(
                    self.settings.bot_token, chat_id,
                    f"\u274C Анекдот #{joke_id} отклонён.",
                )
                _answer_callback_query(self.settings.bot_token, cb_id, "\u274C Отклонено")
                self._notify_author(joke_id, approved=False)
            else:
                _answer_callback_query(self.settings.bot_token, cb_id, "\u26A0\uFE0F Уже обработано")

    def _notify_author(self, joke_id: int, approved: bool) -> None:
        author = self.db.get_submission_author(joke_id)
        if author is None:
            logger.warning("Could not find submission %s to notify author", joke_id)
            return
        author_id = author["author_id"]
        if approved:
            _send_message(
                self.settings.bot_token, author_id,
                f"\U0001F389 Твой анекдот (#{joke_id}) прошёл модерацию! Скоро он появится в канале.",
            )
        else:
            _send_message(
                self.settings.bot_token, author_id,
                f"\uD83D\uDE22 К сожалению, твой анекдот (#{joke_id}) не прошёл модерацию.\n"
                "Попробуй отправить другой!",
            )

    def poll_once(self) -> None:
        updates = self._get_updates()
        for update in updates:
            self._offset = update["update_id"] + 1

            if "callback_query" in update:
                self._handle_callback(update["callback_query"])
            elif "message" in update:
                self._handle_message(update["message"])

    def run_forever(self) -> None:
        self._running = True
        logger.info("Polling handler started")
        while self._running:
            try:
                self.poll_once()
            except Exception:
                logger.exception("Polling error")
                time.sleep(5)

    def stop(self) -> None:
        self._running = False
