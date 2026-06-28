import datetime
import html
import logging
import random
from pathlib import Path

import requests

from .config import Settings
from .database import Database
from .image_gen import fits_in_image, generate_joke_image, generate_repost_card
from .rubrics import classify_emoji, get_hashtags, get_preamble, get_today_rubric, is_jubilee

logger = logging.getLogger(__name__)

IMAGE_RATIO = 0.2
DICE_RATIO = 0.15
BATTLE_EVERY = 5
OBSERVATION_RATIO = 0.1
REPOST_CARD_RATIO = 0.3
REACTION_PROMPT_RATIO = 0.4
FRIDAY_PROMPT_DAYS = [4]
SUNDAY_DIGEST_DAYS = [6]


def _split_two_part(text: str) -> tuple[str, str] | None:
    parts = text.split("\n\n")
    if len(parts) < 2:
        lines = text.split("\n")
        if len(lines) < 6:
            return None
        mid = len(lines) // 2
        return "\n".join(lines[:mid]), "\n".join(lines[mid:])
    mid = len(parts) // 2
    return "\n\n".join(parts[:mid]), "\n\n".join(parts[mid:])


def _build_text(joke_text: str, rubric: dict, post_number: int, preamble_override: str = "", is_part2: bool = False) -> str:
    topic_emoji = rubric["emoji"]
    content_emoji = classify_emoji(joke_text)
    emoji_line = f"{topic_emoji} {content_emoji}".strip()
    safe_text = html.escape(joke_text)
    preamble = preamble_override or get_preamble(joke_text)
    jubilee = is_jubilee(post_number)
    header = ""
    if preamble:
        header = f"<i>{html.escape(preamble)}</i>\n"
    if is_part2:
        header = "<i>\u041F\u0440\u043E\u0434\u043E\u043B\u0436\u0435\u043D\u0438\u0435:</i>\n"
    body = f"{header}{safe_text}" if header else safe_text
    hashtags = get_hashtags(joke_text)
    return f"<b>{emoji_line}</b>\n\n{body}\n\n{hashtags}\n\u2500\u2500\u2500\n\u0412\u044B\u043F\u0443\u0441\u043A #{post_number}{jubilee}"


def _build_observation(text: str, post_number: int) -> str:
    safe_text = html.escape(text)
    hashtags = get_hashtags(text)
    return f"\U0001F914 <b>\u041D\u0430\u0431\u043B\u044E\u0434\u0435\u043D\u0438\u0435</b>\n\n{safe_text}\n\n{hashtags}\n\u2500\u2500\u2500\n\u0412\u044B\u043F\u0443\u0441\u043A #{post_number}"


def _build_caption(post_number: int) -> str:
    jubilee = is_jubilee(post_number)
    return f"\u0412\u044B\u043F\u0443\u0441\u043A #{post_number}{jubilee}"


def _truncate_joke(text: str, max_len: int = 80) -> str:
    return text.replace("\n", " ")[:max_len].rstrip() + "\u2026"


def _author_display(username: str | None, name: str | None) -> str:
    if username:
        return f"@{username}"
    return name or "\u0410\u043D\u043E\u043D\u0438\u043C"


class TelegramPublisher:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self._bot_username: str | None = None

    def _get_bot_username(self) -> str:
        if self._bot_username is None:
            try:
                resp = requests.post(
                    f"https://api.telegram.org/bot{self.settings.bot_token}/getMe",
                    timeout=10,
                )
                data = resp.json()
                if data.get("ok"):
                    self._bot_username = data["result"]["username"]
            except Exception:
                self._bot_username = "\u0431\u043E\u0442"
        return self._bot_username

    def _share_button(self) -> dict | None:
        link = self.settings.channel_link
        if not link:
            return None
        share_url = f"https://t.me/share/url?url={link}"
        return {
            "inline_keyboard": [
                [{"text": "\uD83D\uDCE4 \u041F\u043E\u0434\u0435\u043B\u0438\u0442\u044C\u0441\u044F", "url": share_url}]
            ]
        }

    def _post_message(self, payload: dict) -> dict:
        share = self._share_button()
        if share and "reply_markup" not in payload:
            payload["reply_markup"] = share
        response = requests.post(
            f"https://api.telegram.org/bot{self.settings.bot_token}/sendMessage",
            json=payload,
            timeout=self.settings.http_timeout,
        )
        if not response.ok:
            raise RuntimeError(f"Telegram API error {response.status_code}: {response.text}")
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data.get('description', 'unknown')}")
        return data

    def _post_poll(self, joke1: str, joke2: str, post_number: int) -> dict:
        response = requests.post(
            f"https://api.telegram.org/bot{self.settings.bot_token}/sendPoll",
            json={
                "chat_id": self.settings.channel_id,
                "question": "\u2694\uFE0F \u0411\u0430\u0442\u0442\u043B \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u043E\u0432! \u041A\u0430\u043A\u043E\u0439 \u0441\u043C\u0435\u0448\u043D\u0435\u0435?",
                "options": [_truncate_joke(joke1), _truncate_joke(joke2)],
                "is_anonymous": True,
                "type": "regular",
            },
            timeout=self.settings.http_timeout,
        )
        if not response.ok:
            raise RuntimeError(f"Telegram API error {response.status_code}: {response.text}")
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data.get('description', 'unknown')}")
        return data

    def _send_dice(self) -> None:
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.settings.bot_token}/sendDice",
                json={"chat_id": self.settings.channel_id, "emoji": "\uD83C\uDFB2"},
                timeout=self.settings.http_timeout,
            )
        except Exception:
            pass

    def _send_subscriber_joke(self) -> bool:
        sub = self.db.get_next_approved_submission()
        if sub is None:
            return False
        post_number = self.db.count_published() + 1
        author = _author_display(sub["author_username"], sub["author_name"])
        safe_text = html.escape(sub["text"])
        hashtags = get_hashtags(sub["text"])
        text = (
            f"\U0001F4EC <b>\u0410\u0432\u0442\u043E\u0440\u0441\u043A\u0438\u0439 \u0430\u043D\u0435\u043A\u0434\u043E\u0442</b>\n\n"
            f"{safe_text}\n\n{hashtags}\n\u2500\u2500\u2500\n"
            f"\u0412\u044B\u043F\u0443\u0441\u043A #{post_number}\n"
            f"\u041F\u0440\u0438\u0441\u043B\u0430\u043B(\u0430): {author}"
        )
        self._post_message({
            "chat_id": self.settings.channel_id,
            "text": text,
            "parse_mode": "HTML",
        })
        self.db.mark_submission_published(sub["id"])
        logger.info("Published subscriber joke #%s from %s", sub["id"], author)
        if random.random() < DICE_RATIO:
            self._send_dice()
        return True

    def _send_friday_prompt(self) -> bool:
        bot_username = self._get_bot_username()
        text = (
            "\U0001F4DD <b>\u041F\u044F\u0442\u043D\u0438\u0447\u043D\u044B\u0439 \u043F\u0440\u0435\u0434\u043B\u043E\u0436\u043A\u0430!</b>\n\n"
            "\u0415\u0441\u0442\u044C \u0441\u043C\u0435\u0448\u043D\u043E\u0439 \u0430\u043D\u0435\u043A\u0434\u043E\u0442 \u0438\u043B\u0438 \u0438\u0441\u0442\u043E\u0440\u0438\u044F? "
            "\u041F\u0440\u0438\u0448\u043B\u0438 \u0435\u0433\u043E \u0431\u043E\u0442\u0443 \u0432 \u043B\u0438\u0447\u043A\u0443:\n"
            f"@{bot_username}\n\n"
            "\u041B\u0443\u0447\u0448\u0438\u0439 \u043E\u043F\u0443\u0431\u043B\u0438\u043A\u0443\u0435\u043C \u0432 \u0441\u0443\u0431\u0431\u043E\u0442\u0443 \u0441 \u0443\u043A\u0430\u0437\u0430\u043D\u0438\u0435\u043C \u0430\u0432\u0442\u043E\u0440\u0430!"
        )
        self._post_message({"chat_id": self.settings.channel_id, "text": text, "parse_mode": "HTML"})
        logger.info("Published Friday prompt")
        return True

    def _send_text(self, joke, rubric: dict, preamble_override: str = "", is_part2: bool = False) -> bool:
        post_number = self.db.count_published() + 1
        text = _build_text(joke.text, rubric, post_number, preamble_override, is_part2)
        payload = {
            "chat_id": self.settings.channel_id,
            "text": text,
            "parse_mode": "HTML",
        }
        self._post_message(payload)
        self.db.mark_published(joke.content_hash)
        logger.info("Published text joke: %s", joke.external_id)
        if not is_part2 and random.random() < DICE_RATIO:
            self._send_dice()
        return True

    def _send_observation(self, text: str, post_number: int) -> bool:
        payload = {
            "chat_id": self.settings.channel_id,
            "text": _build_observation(text, post_number),
            "parse_mode": "HTML",
        }
        self._post_message(payload)
        logger.info("Published observation: #%s", post_number)
        return True

    def _send_image(self, joke, rubric: dict) -> bool:
        post_number = self.db.count_published() + 1
        image_path = generate_joke_image(joke.text, post_number, rubric_name=rubric.get("name"))
        caption = _build_caption(post_number)

        with open(image_path, "rb") as f:
            response = requests.post(
                f"https://api.telegram.org/bot{self.settings.bot_token}/sendPhoto",
                data={"chat_id": self.settings.channel_id, "caption": caption},
                files={"photo": f},
                timeout=self.settings.http_timeout,
            )

        Path(image_path).unlink(missing_ok=True)

        try:
            payload = response.json()
        except ValueError:
            payload = {"ok": False, "description": response.text}

        if not response.ok or not payload.get("ok"):
            description = payload.get("description", "Unknown Telegram API error")
            error_code = payload.get("error_code", response.status_code)
            raise RuntimeError(f"Telegram API error {error_code}: {description}")

        self.db.mark_published(joke.content_hash)
        logger.info("Published image joke: %s", joke.external_id)
        return True

    def _handle_two_part(self, joke, rubric: dict) -> bool:
        split = _split_two_part(joke.text)
        if split is None:
            return False
        part1, part2 = split
        p1_hash = joke.content_hash + "_p1"
        self.db.save_pending_part(
            joke.content_hash, part2, joke.source_name,
            joke.external_id + "_p2", joke.content_hash + "_p2",
        )
        joke.text = part1.strip()
        joke.content_hash = p1_hash
        return self._send_text(joke, rubric, "\u0427\u0438\u0442\u0430\u0439\u0442\u0435 \u043F\u0440\u043E\u0434\u043E\u043B\u0436\u0435\u043D\u0438\u0435 \u0432 \u0441\u043B\u0435\u0434\u0443\u044E\u0449\u0435\u043C \u0432\u044B\u043F\u0443\u0441\u043A\u0435:")

    def _handle_battle(self, rubric: dict) -> bool:
        joke1 = self.db.get_next_unpublished()
        if joke1 is None:
            return False
        joke2 = self.db.get_next_unpublished()
        if joke2 is None:
            return False
        post_number = self.db.count_published() + 1
        battle_text = (
            f"\u2694\uFE0F <b>\u0411\u0430\u0442\u0442\u043B \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u043E\u0432!</b>\n\n"
            f"<b>1.</b> {html.escape(joke1.text)}\n\n\u2500\u2500\u2500\n\n"
            f"<b>2.</b> {html.escape(joke2.text)}\n\n\u2500\u2500\u2500\n"
            f"\u0412\u044B\u043F\u0443\u0441\u043A #{post_number}"
        )
        self._post_message({
            "chat_id": self.settings.channel_id,
            "text": battle_text,
            "parse_mode": "HTML",
        })
        self._post_poll(joke1.text, joke2.text, post_number)
        self.db.mark_published(joke1.content_hash)
        self.db.mark_published(joke2.content_hash)
        logger.info("Published battle: %s vs %s", joke1.external_id, joke2.external_id)
        return True

    def _send_repost_card(self, joke) -> bool:
        post_number = self.db.count_published() + 1
        image_path = generate_repost_card(joke.text)
        caption = _build_caption(post_number)
        with open(image_path, "rb") as f:
            response = requests.post(
                f"https://api.telegram.org/bot{self.settings.bot_token}/sendPhoto",
                data={"chat_id": self.settings.channel_id, "caption": caption},
                files={"photo": f},
                timeout=self.settings.http_timeout,
            )
        Path(image_path).unlink(missing_ok=True)
        try:
            payload = response.json()
        except ValueError:
            payload = {"ok": False, "description": response.text}
        if not response.ok or not payload.get("ok"):
            description = payload.get("description", "Unknown Telegram API error")
            error_code = payload.get("error_code", response.status_code)
            raise RuntimeError(f"Telegram API error {error_code}: {description}")
        self.db.mark_published(joke.content_hash)
        logger.info("Published repost card: %s", joke.external_id)
        return True

    def _send_reaction_summary(self, post_number: int) -> bool:
        reaction = self.db.get_random_unpublished_reaction()
        if reaction is None:
            return False
        author = _author_display(None, reaction["username"])
        text = (
            f"\U0001F4AC <b>\u0420\u0435\u0430\u043A\u0446\u0438\u044F \u043F\u043E\u0434\u043F\u0438\u0441\u0447\u0438\u043A\u0430</b>\n\n"
            f"{html.escape(reaction['text'])}\n\n\u2500\u2500\u2500\n"
            f"\u0412\u044B\u043F\u0443\u0441\u043A #{post_number}\n"
            f"\u041E\u0442\u043F\u0440\u0430\u0432\u0438\u043B(\u0430): {author}"
        )
        self._post_message({
            "chat_id": self.settings.channel_id,
            "text": text,
            "parse_mode": "HTML",
        })
        self.db.mark_reaction_published(reaction["id"])
        logger.info("Published reaction summary #%s", reaction["id"])
        return True

    def _send_weekly_digest(self, post_number: int) -> bool:
        jokes = self.db.get_recent_published(limit=3, days=7)
        if not jokes:
            return False
        lines = []
        for i, joke in enumerate(jokes, 1):
            text = joke.text.replace("\n", " ")[:200].rstrip() + "\u2026" if len(joke.text) > 200 else joke.text
            lines.append(f"<b>{i}.</b> {html.escape(text)}")
        text = (
            f"\U0001F4C5 <b>\u041B\u0443\u0447\u0448\u0435\u0435 \u0437\u0430 \u043D\u0435\u0434\u0435\u043B\u044E</b>\n\n"
            f"{chr(10).join(lines)}\n\n"
            f"#\u0434\u0430\u0439\u0434\u0436\u0435\u0441\u0442 #\u043B\u0443\u0447\u0448\u0435\u0435\n"
            f"\u2500\u2500\u2500\n"
            f"\u0412\u044B\u043F\u0443\u0441\u043A #{post_number}"
        )
        self._post_message({
            "chat_id": self.settings.channel_id,
            "text": text,
            "parse_mode": "HTML",
        })
        logger.info("Published weekly digest #%s", post_number)
        return True

    def publish_next(self) -> bool:
        today = datetime.datetime.today()
        rubric = get_today_rubric()

        pending = self.db.get_pending_part()
        if pending:
            result = self._send_text(pending, rubric, is_part2=True)
            self.db.delete_pending_part(pending.content_hash)
            return result

        if self.db.count_approved_submissions() > 0:
            return self._send_subscriber_joke()

        post_number = self.db.count_published() + 1

        if today.weekday() in SUNDAY_DIGEST_DAYS and self.db.count_published_today() == 0:
            if self._send_weekly_digest(post_number):
                return True

        if today.weekday() in FRIDAY_PROMPT_DAYS and self.db.count_published_today() == 0:
            return self._send_friday_prompt()

        if post_number % BATTLE_EVERY == 0 and post_number > 0:
            return self._handle_battle(rubric)

        if self.db.count_unpublished_reactions() > 0:
            return self._send_reaction_summary(post_number)

        if rubric["keywords"]:
            joke = self.db.get_next_unpublished_matching(rubric["keywords"])
            if joke:
                if len(joke.text) < 200 and random.random() < OBSERVATION_RATIO:
                    self.db.mark_published(joke.content_hash)
                    return self._send_observation(joke.text, post_number)
                if len(joke.text) > 600 and _split_two_part(joke.text):
                    result = self._handle_two_part(joke, rubric)
                    if result:
                        return result
                if random.random() < REPOST_CARD_RATIO and fits_in_image(joke.text):
                    return self._send_repost_card(joke)
                if random.random() < IMAGE_RATIO and fits_in_image(joke.text):
                    return self._send_image(joke, rubric)
                return self._send_text(joke, rubric)

        joke = self.db.get_next_unpublished()
        if joke is None:
            logger.info("No unpublished jokes available")
            return False

        if len(joke.text) < 200 and random.random() < OBSERVATION_RATIO:
            self.db.mark_published(joke.content_hash)
            return self._send_observation(joke.text, post_number)

        if len(joke.text) > 600 and _split_two_part(joke.text):
            result = self._handle_two_part(joke, rubric)
            if result:
                return result

        if random.random() < REPOST_CARD_RATIO and fits_in_image(joke.text):
            return self._send_repost_card(joke)
        if random.random() < IMAGE_RATIO and fits_in_image(joke.text):
            return self._send_image(joke, rubric)
        return self._send_text(joke, rubric)