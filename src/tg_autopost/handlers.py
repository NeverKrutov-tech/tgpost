import datetime
import html
import logging
import re
import time
from typing import Any

import requests

from .config import Settings
from .database import Database
from .levels import get_level

logger = logging.getLogger(__name__)

POLL_TIMEOUT = 60
CB_APPROVE = "approve"
CB_REJECT = "reject"
TIP_STARS = 10

START_TEXT = (
    "\U0001F44B <b>Привет!</b>\n\n"
    "Я бот для сбора анекдотов. Хочешь поделиться смешной историей?\n"
    "Просто отправь мне текст анекдота — и он уйдёт на модерацию.\n"
    "Лучшие публикуются в канале с указанием автора!\n\n"
    "\U0001F514 <a href=\"https://t.me/Anetdodik\">Подпишись на канал!</a> — каждый день свежие анекдоты!\n\n"
    "Команды:\n"
    "/submit — прислать анекдот\n"
    "/subscribe — получать анекдот дня в личку\n"
    "/invite — получить реферальную ссылку\n"
    "/register — стать автором\n"
    "/my_stats — моя статистика\n"
    "/author @username — профиль автора"
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
            "allowed_updates": ["message", "callback_query", "pre_checkout_query"],
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
        user = msg.get("from", {})
        uid, username, full_name = _get_author_link(user)

        payment = msg.get("successful_payment")
        if payment:
            payload = payment.get("invoice_payload", "")
            try:
                _, sub_id_str, author_id_str = payload.split(":")
                sub_id = int(sub_id_str)
                author_id = int(author_id_str)
                amount = payment["total_amount"]
            except (ValueError, KeyError):
                return
            self.db.save_tip(sub_id, author_id, amount, uid)
            label, emoji = get_level(self.db.get_author_published_count(author_id))
            _send_message(
                self.settings.bot_token, chat_id,
                f"\u2B50 Спасибо! {amount} \u2B50 отправлены автору.\n"
                f"Твой донат помогает развивать канал! \U0001F389",
            )
            logger.info("Tip: %s stars from user %s to author %s for submission %s", amount, uid, author_id, sub_id)
            return

        text = msg.get("text", "")
        if not text.strip():
            return

        if text.startswith("/start"):
            if text.startswith("/start ref_"):
                try:
                    ref_id = int(text.split("ref_", 1)[1].split()[0])
                except (ValueError, IndexError):
                    _send_message(self.settings.bot_token, chat_id, START_TEXT)
                    return
                self.db.save_referral(ref_id, uid)
                _send_message(
                    self.settings.bot_token, chat_id,
                    f"\U0001F44B <b>Привет!</b> Ты пришёл по ссылке! "
                    f"Обязательно подпишись на канал @Anetdodik — каждый день свежие анекдоты! \U0001F923\n\n"
                    f"{START_TEXT}",
                )
                logger.info("Referral tracked: %s -> %s", ref_id, uid)
                return
            if text.startswith("/start tip_"):
                try:
                    sub_id = int(text.split("tip_", 1)[1].split()[0])
                except (ValueError, IndexError):
                    _send_message(self.settings.bot_token, chat_id, START_TEXT)
                    return
                sub = self.db.get_submission_author(sub_id)
                if sub is None:
                    _send_message(self.settings.bot_token, chat_id, "\u274C Анекдот не найден.")
                    return
                author_display = _author_display(sub["author_username"], sub["author_name"])
                invoice = _api_call(
                    self.settings.bot_token, "sendInvoice",
                    {
                        "chat_id": chat_id,
                        "title": "\u041F\u043E\u0434\u0434\u0435\u0440\u0436\u043A\u0430 \u0430\u0432\u0442\u043E\u0440\u0430",
                        "description": f"\u041E\u0442\u043F\u0440\u0430\u0432\u044C {TIP_STARS} \u2B50 {author_display} \u0437\u0430 \u0430\u043D\u0435\u043A\u0434\u043E\u0442",
                        "payload": f"tip:{sub_id}:{sub['author_id']}",
                        "currency": "XTR",
                        "prices": [{"label": f"\u0410\u0432\u0442\u043E\u0440\u0443 {author_display}", "amount": TIP_STARS}],
                    },
                )
                if invoice is None:
                    _send_message(
                        self.settings.bot_token, chat_id,
                        "\u26A0\uFE0F Не удалось создать платёж. Попробуй позже.",
                    )
                return
            if text.startswith("/start cont_"):
                try:
                    content_id = int(text.split("cont_", 1)[1].split()[0])
                except (ValueError, IndexError):
                    _send_message(self.settings.bot_token, chat_id, START_TEXT)
                    return
                self._handle_locked_content(chat_id, uid, content_id)
                return
            _send_message(self.settings.bot_token, chat_id, START_TEXT)
            return

        if text.startswith("/subscribe") or text.startswith("/sub"):
            ok = self.db.subscribe_user(uid, username)
            if ok:
                _send_message(
                    self.settings.bot_token, chat_id,
                    "\U0001F514 <b>Ты подписан на ежедневный анекдот!</b>\n"
                    "Каждый вечер я буду присылать лучший анекдот дня.\n"
                    "Отписаться — /unsubscribe",
                )
            else:
                _send_message(
                    self.settings.bot_token, chat_id,
                    "\u2705 Ты уже подписан! Отписаться — /unsubscribe",
                )
            return

        if text.startswith("/unsubscribe") or text.startswith("/unsub"):
            ok = self.db.unsubscribe_user(uid)
            if ok:
                _send_message(
                    self.settings.bot_token, chat_id,
                    "\u274C Ты отписан от ежедневной рассылки.",
                )
            else:
                _send_message(
                    self.settings.bot_token, chat_id,
                    "\u274C Ты и так не был подписан. /subscribe — чтобы подписаться",
                )
            return

        if text.startswith("/submit"):
            _send_message(self.settings.bot_token, chat_id, SUBMIT_TEXT)
            return

        if text.startswith("/register"):
            args = text[len("/register"):].strip()
            if args:
                ok = self.db.register_author(uid, username, args)
                if ok:
                    _send_message(
                        self.settings.bot_token, chat_id,
                        f"\u2705 Ты зарегистрирован как автор <b>{html.escape(args)}</b>!\n"
                        "Твои анекдоты будут публиковаться с этим именем.",
                    )
                else:
                    existing = self.db.get_author_by_telegram_id(uid)
                    if existing:
                        self.db.update_author_name(uid, args)
                        _send_message(
                            self.settings.bot_token, chat_id,
                            f"\u2705 Имя обновлено на <b>{html.escape(args)}</b>!",
                        )
                    else:
                        _send_message(
                            self.settings.bot_token, chat_id,
                            "\u26A0\uFE0F Ошибка регистрации. Попробуй позже.",
                        )
            else:
                _send_message(
                    self.settings.bot_token, chat_id,
                    "\u270F\uFE0F <b>Регистрация автора</b>\n\n"
                    "Чтобы зарегистрироваться, напиши:\n"
                    "<code>/register Имя Фамилия</code>\n\n"
                    "Например: <code>/register Иван Петров</code>\n\n"
                    "После регистрации твои анекдоты будут выходить с твоим именем.",
                )
            return

        if text.startswith("/my_stats"):
            author = self.db.get_author_by_telegram_id(uid)
            if author is None:
                self.db.register_author(uid, username, full_name or f"User {uid}")
                author = self.db.get_author_by_telegram_id(uid)
            count = self.db.get_author_published_count(uid)
            label, emoji = get_level(count)
            top = self.db.get_top_authors(limit=50)
            rank = next((i + 1 for i, a in enumerate(top) if a["telegram_id"] == uid), None)
            display = author["name"]
            msg = (
                f"\U0001F4CA <b>Моя статистика</b>\n\n"
                f"Имя: <b>{html.escape(display)}</b>\n"
                f"Уровень: {emoji} <b>{label}</b>\n"
                f"Опубликовано: <b>{count}</b>\n"
            )
            if rank:
                msg += f"Место в топе: <b>{rank}</b> из {len(top)}\n"
            msg += f"\nПрисылай ещё — /submit"
            _send_message(self.settings.bot_token, chat_id, msg)
            return

        if text.startswith("/invite"):
            ref_count = self.db.get_referral_count(uid)
            bot_username = self._get_bot_username()
            ref_link = f"https://t.me/{bot_username}?start=ref_{uid}"
            msg = (
                f"\U0001F517 <b>Твоя реферальная ссылка:</b>\n"
                f"<code>{html.escape(ref_link)}</code>\n\n"
                f"\U0001F4C8 Приведено друзей: <b>{ref_count}</b>\n\n"
                f"\U0001F389 Делись ссылкой с друзьями и поднимайся в топе рефералов!\n"
                f"Топ рефералов: https://tgpost-bot-l4wq.onrender.com/top"
            )
            _send_message(self.settings.bot_token, chat_id, msg)
            return

        if text.startswith("/author"):
            target = text[len("/author"):].strip().lstrip("@")
            if not target:
                _send_message(
                    self.settings.bot_token, chat_id,
                    "\u2139\uFE0F Напиши: /author @username\nНапример: /author @ivanov",
                )
                return
            author = self.db.get_author_by_username(target)
            if author is None:
                _send_message(
                    self.settings.bot_token, chat_id,
                    f"\u274C Автор @{html.escape(target)} не найден.",
                )
                return
            count = self.db.get_author_published_count(author["telegram_id"])
            label, emoji = get_level(count)
            msg = (
                f"{emoji} <b>{html.escape(author['name'])}</b>\n"
                f"@{author['username']}\n\n"
                f"\U0001F3C5 Уровень: <b>{label}</b>\n"
                f"\U0001F4DD Опубликовано: <b>{count}</b> анекдотов\n"
            )
            if author["bio"]:
                msg += f"\n\uD83D\uDCDD {html.escape(author['bio'])}"
            _send_message(self.settings.bot_token, chat_id, msg)
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

    def _handle_locked_content(self, chat_id: int, user_id: int, content_id: int) -> None:
        content = self.db.get_locked_content(content_id)
        if content is None:
            _send_message(self.settings.bot_token, chat_id, "\u274C \u041A\u043E\u043D\u0442\u0435\u043D\u0442 \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D.")
            return
        try:
            resp = _api_call(self.settings.bot_token, "getChatMember", {
                "chat_id": self.settings.channel_id,
                "user_id": user_id,
            })
            if resp and resp.get("ok"):
                status = resp.get("result", {}).get("status", "")
                if status in ("member", "administrator", "creator"):
                    _send_message(self.settings.bot_token, chat_id, content)
                    return
        except Exception:
            logger.exception("Failed to check chat member")
        link = self.settings.channel_link
        _send_message(
            self.settings.bot_token, chat_id,
            "\U0001F512 \u042D\u0442\u043E\u0442 \u043A\u043E\u043D\u0442\u0435\u043D\u0442 \u0434\u043E\u0441\u0442\u0443\u043F\u0435\u043D \u0442\u043E\u043B\u044C\u043A\u043E \u043F\u043E\u0434\u043F\u0438\u0441\u0447\u0438\u043A\u0430\u043C \u043A\u0430\u043D\u0430\u043B\u0430.\n"
            "\u041F\u043E\u0434\u043F\u0438\u0448\u0438\u0441\u044C, \u0447\u0442\u043E\u0431\u044B \u043F\u0440\u043E\u0447\u0438\u0442\u0430\u0442\u044C \u043F\u0440\u043E\u0434\u043E\u043B\u0436\u0435\u043D\u0438\u0435!",
            reply_markup={
                "inline_keyboard": [
                    [{"text": "\U0001F447 \u041F\u043E\u0434\u043F\u0438\u0441\u0430\u0442\u044C\u0441\u044F", "url": link}]
                ]
            },
        )

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

    def _handle_pre_checkout_query(self, query: dict) -> None:
        query_id = query.get("id", "")
        payload = query.get("invoice_payload", "")
        if payload.startswith("tip:"):
            _api_call(self.settings.bot_token, "answerPreCheckoutQuery", {
                "pre_checkout_query_id": query_id,
                "ok": True,
            })
        else:
            _api_call(self.settings.bot_token, "answerPreCheckoutQuery", {
                "pre_checkout_query_id": query_id,
                "ok": False,
                "error_message": "Неизвестный платёж",
            })

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
            elif "pre_checkout_query" in update:
                self._handle_pre_checkout_query(update["pre_checkout_query"])
            elif "message" in update:
                self._handle_message(update["message"])

        self._try_send_daily_joke()

    def _try_send_daily_joke(self) -> None:
        today = datetime.datetime.today().strftime("%Y-%m-%d")
        last = self.db.get_meta("daily_joke_date", "")
        if last == today:
            return
        hour = datetime.datetime.today().hour
        if hour < 18:
            return
        # pick a random published joke
        text = None
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT text FROM jokes WHERE published_at IS NOT NULL ORDER BY RANDOM() LIMIT 1"
            ).fetchone()
            if row:
                text = row["text"]
        if not text:
            return
        subscribers = self.db.get_all_subscribers()
        for sub in subscribers:
            try:
                _send_message(
                    self.settings.bot_token, sub["user_id"],
                    f"\U0001F4EC <b>Анекдот дня</b>\n\n{html.escape(text)}\n\n"
                    f"\u2014 @Anetdodik\n\n"
                    f"Отписаться: /unsubscribe",
                )
            except Exception:
                logger.warning("Failed to send daily joke to user %s", sub["user_id"])
        self.db.set_meta("daily_joke_date", today)
        logger.info("Daily joke sent to %s subscribers", len(subscribers))

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
