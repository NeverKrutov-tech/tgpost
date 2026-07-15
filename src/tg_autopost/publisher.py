import datetime
import html
import json
import logging
import os
import random
from pathlib import Path

import requests

from .config import Settings
from .content_filter import is_flagged
from .database import Database
from .handlers import PollingHandler
from .horoscope import generate_horoscope
from .anti_advice import generate_anti_advice
from .crossposter import post_to_vk
from .image_gen import fits_in_image, generate_joke_image, generate_repost_card
from .levels import get_level
from .rubrics import classify_emoji, get_hashtags, get_preamble, get_today_rubric, is_jubilee
from .shorts_maker import render_short, upload_short
from .youtube import get_channel_stats, get_latest_videos

logger = logging.getLogger(__name__)

IMAGE_RATIO = 0.2
VIDEO_RATIO = 0.08
DICE_RATIO = 0.15
BATTLE_EVERY = 5
OBSERVATION_RATIO = 0.1
REPOST_CARD_RATIO = 0.3
REACTION_PROMPT_RATIO = 0.4
MEME_ANALYSIS_RATIO = 0.15
HEADLINE_RATIO = 0.15
QUIZ_RATIO = 0.08
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


def _split_headline(text: str) -> tuple[str, str] | None:
    lines = text.strip().split("\n")
    if len(lines) < 2:
        return None
    last = lines[-1].strip()
    if not last or len(last) > 100:
        return None
    setup = "\n".join(lines[:-1]).strip()
    if len(setup) < 150:
        return None
    return setup, last


def _build_text(joke_text: str, rubric: dict, post_number: int, preamble_override: str = "", is_part2: bool = False, channel_link: str = "") -> str:
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
    signature = ""
    if channel_link:
        name = channel_link.rstrip("/").rsplit("/", 1)[-1]
        signature = f"\n— @{name}"
    return f"<b>{emoji_line}</b>\n\n{body}\n\n{hashtags}{signature}"


def _build_observation(text: str, channel_link: str = "") -> str:
    safe_text = html.escape(text)
    hashtags = get_hashtags(text)
    signature = ""
    if channel_link:
        name = channel_link.rstrip("/").rsplit("/", 1)[-1]
        signature = f"\n— @{name}"
    return f"\U0001F914 <b>\u041D\u0430\u0431\u043B\u044E\u0434\u0435\u043D\u0438\u0435</b>\n\n{safe_text}\n\n{hashtags}{signature}"


def _build_caption(post_number: int, channel_link: str = "") -> str:
    jubilee = is_jubilee(post_number)
    if channel_link:
        name = channel_link.rstrip("/").rsplit("/", 1)[-1]
        if jubilee:
            jubilee += "\n"
        jubilee += f"— @{name}"
    return jubilee


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

    def _channel_username(self) -> str:
        link = self.settings.channel_link
        return link.rstrip("/").rsplit("/", 1)[-1] if link else ""

    def _share_url(self, message_id: int | None = None) -> str:
        if message_id:
            return f"https://tgpost-bot-l4wq.onrender.com/p/{message_id}"
        return self.settings.channel_link or ""

    def _build_keyboard(self, message_id: int | None = None) -> dict:
        buttons = []
        if message_id:
            share_url = f"https://tgpost-bot-l4wq.onrender.com/share/{message_id}"
            buttons.append([{"text": "\uD83D\uDCE4 \u041F\u043E\u0434\u0435\u043B\u0438\u0442\u044C\u0441\u044F", "url": share_url}])
        if self.settings.channel_link:
            buttons.append([{"text": "\U0001F514 \u041F\u043E\u0434\u043F\u0438\u0441\u0430\u0442\u044C\u0441\u044F", "url": self.settings.channel_link}])
        return {"inline_keyboard": buttons}

    def _edit_post_keyboard(self, chat_id: int | str, message_id: int) -> None:
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.settings.bot_token}/editMessageReplyMarkup",
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "reply_markup": self._build_keyboard(message_id),
                },
                timeout=self.settings.http_timeout,
            )
        except Exception:
            pass

    def _edit_post_keyboard_raw(self, chat_id: int | str, message_id: int, reply_markup: dict) -> None:
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.settings.bot_token}/editMessageReplyMarkup",
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "reply_markup": reply_markup,
                },
                timeout=self.settings.http_timeout,
            )
        except Exception:
            pass

    def _bot_link(self) -> str:
        return f"https://t.me/{self._get_bot_username()}"

    def _welcome_new_members(self) -> None:
        try:
            current = self._get_member_count()
            prev = int(self.db.get_meta("member_count", "0"))
            self.db.set_meta("member_count", str(current))
            diff = current - prev
            if diff >= 3 and prev > 0:
                self._post_message({
                    "chat_id": self.settings.channel_id,
                    "text": (
                        f"\U0001F44B <b>\u0414\u043E\u0431\u0440\u043E \u043F\u043E\u0436\u0430\u043B\u043E\u0432\u0430\u0442\u044C!</b> "
                        f"\u0420\u0430\u0434\u044B \u043D\u043E\u0432\u044B\u043C \u043F\u043E\u0434\u043F\u0438\u0441\u0447\u0438\u043A\u0430\u043C \u2014 "
                        f"\u0432\u0430\u0441 \u0443\u0436\u0435 {current} \U0001F389\n\n"
                        f"\u041F\u0440\u0438\u0441\u044B\u043B\u0430\u0439\u0442\u0435 \u0441\u0432\u043E\u0438 "
                        f"\u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u0431\u043E\u0442\u0443 "
                        f"@postbotanekdodik_bot \u2014 \u043B\u0443\u0447\u0448\u0438\u0435 \u043F\u043E\u043F\u0430\u0434\u0443\u0442 "
                        f"\u0432 \u043A\u0430\u043D\u0430\u043B!"
                    ),
                    "parse_mode": "HTML",
                })
                logger.info("Welcome post sent — %s new subscribers", diff)
        except Exception:
            logger.exception("Failed to check member count")

    def _post_message(self, payload: dict) -> dict:
        had_custom_markup = "reply_markup" in payload
        if not had_custom_markup:
            payload["reply_markup"] = self._build_keyboard()
        payload.setdefault("disable_web_page_preview", True)
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
        if not had_custom_markup:
            msg_id = data.get("result", {}).get("message_id")
            if msg_id:
                self._edit_post_keyboard(payload["chat_id"], msg_id)
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
        self.db.register_author(sub["author_id"], sub["author_username"], sub["author_name"] or f"User {sub['author_id']}")
        author = _author_display(sub["author_username"], sub["author_name"])
        count = self.db.get_author_published_count(sub["author_id"]) + 1
        label, emoji = get_level(count)
        safe_text = html.escape(sub["text"])
        hashtags = get_hashtags(sub["text"])
        author_line = f"{emoji} <b>\u0410\u0432\u0442\u043E\u0440:</b> {author}"
        author_line += f" \u2022 {label}"
        if count >= 5:
            author_line += f" \u2022 {count} \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u043E\u0432"
        text = (
            f"\U0001F4EC <b>\u0410\u0432\u0442\u043E\u0440\u0441\u043A\u0438\u0439 \u0430\u043D\u0435\u043A\u0434\u043E\u0442</b>\n\n"
            f"{safe_text}\n\n{author_line}\n{hashtags}"
        )
        bot_username = self._get_bot_username()
        tip_url = f"https://t.me/{bot_username}?start=tip_{sub['id']}"
        buttons = [
            [{"text": "\uD83D\uDCE4 \u041F\u043E\u0434\u0435\u043B\u0438\u0442\u044C\u0441\u044F", "url": "https://t.me/share/url?url=" + self.settings.channel_link}],
            [{"text": "\u2B50 \u041F\u043E\u0431\u043B\u0430\u0433\u043E\u0434\u0430\u0440\u0438\u0442\u044C \u0430\u0432\u0442\u043E\u0440\u0430", "url": tip_url}],
        ]
        result = self._post_message({
            "chat_id": self.settings.channel_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": buttons},
        })
        self.db.mark_submission_published(sub["id"])
        msg_id = result.get("result", {}).get("message_id")
        if msg_id:
            post_url = f"https://tgpost-bot-l4wq.onrender.com/p/{msg_id}"
            buttons[0][0]["url"] = f"https://t.me/share/url?url={post_url}"
            self._edit_post_keyboard_raw(self.settings.channel_id, msg_id, {"inline_keyboard": buttons})
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
        result = self._post_message({"chat_id": self.settings.channel_id, "text": text, "parse_mode": "HTML"})
        msg_id = result.get("result", {}).get("message_id")
        if msg_id:
            self.db.mark_special_post("friday_prompt")
            self.db.set_meta(f"special_friday_prompt_msgid_{datetime.datetime.today().strftime('%Y-%m-%d')}", str(msg_id))
        Path("data/friday_marker.txt").write_text(datetime.datetime.today().strftime("%Y-%m-%d"))
        logger.info("Published Friday prompt (msg_id=%s)", msg_id)
        return True

    def _send_quiz_answer(self) -> bool:
        quiz = self.db.get_pending_quiz()
        if quiz is None:
            return False
        safe_text = html.escape(quiz["full_text"])
        text = (
            f"\U0001F44F <b>\u0410 \u0432\u043E\u0442 \u043A\u0430\u043A \u0437\u0430\u043A\u0430\u043D\u0447\u0438\u0432\u0430\u043B\u0441\u044F \u0442\u043E\u0442 \u0430\u043D\u0435\u043A\u0434\u043E\u0442</b>\n\n"
            f"{safe_text}\n\n#\u043A\u0432\u0438\u0437 #\u043E\u0442\u0432\u0435\u0442"
        )
        self._post_message({
            "chat_id": self.settings.channel_id,
            "text": text,
            "parse_mode": "HTML",
        })
        self.db.delete_pending_quiz(quiz["id"])
        logger.info("Published quiz answer")
        return True

    def _try_make_quiz(self, joke, rubric: dict) -> bool | None:
        if random.random() >= QUIZ_RATIO:
            return None
        lines = joke.text.strip().split("\n")
        if len(lines) < 3:
            return None
        last_line = lines[-1].strip()
        if not last_line.startswith("-") and not last_line.startswith("\u2014"):
            return None
        truncated = "\n".join(lines[:-1]).strip()
        if len(truncated) < 60:
            return None
        bot_username = self._get_bot_username()
        safe_truncated = html.escape(truncated)
        text = (
            f"\u2753 <b>\u0417\u0430\u043A\u043E\u043D\u0447\u0438 \u0430\u043D\u0435\u043A\u0434\u043E\u0442</b>\n\n"
            f"{safe_truncated}\n\n"
            f"\u2193 \u041F\u0438\u0448\u0438 \u0441\u0432\u043E\u0439 \u0432\u0430\u0440\u0438\u0430\u043D\u0442 \u0431\u043E\u0442\u0443 @{bot_username}\n"
            f"\u041B\u0443\u0447\u0448\u0438\u0435 \u043E\u043F\u0443\u0431\u043B\u0438\u043A\u0443\u0435\u043C \u0432 \u0441\u043B\u0435\u0434\u0443\u044E\u0449\u0435\u043C \u0432\u044B\u043F\u0443\u0441\u043A\u0435!"
        )
        self._post_message({
            "chat_id": self.settings.channel_id,
            "text": text,
            "parse_mode": "HTML",
        })
        self.db.save_quiz(truncated, joke.text, last_line)
        self.db.mark_published(joke.content_hash)
        logger.info("Published quiz prompt for joke: %s", joke.external_id)
        return True

    def _send_text(self, joke, rubric: dict, preamble_override: str = "", is_part2: bool = False, reply_to: int = 0) -> int:
        post_number = self.db.count_published() + 1
        text = _build_text(joke.text, rubric, post_number, preamble_override, is_part2, self.settings.channel_link)
        payload = {
            "chat_id": self.settings.channel_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        data = self._post_message(payload)
        msg_id = data["result"]["message_id"]
        self.db.mark_published(joke.content_hash, msg_id)
        logger.info("Published text joke: %s (msg_id=%s)", joke.external_id, msg_id)
        if not is_part2:
            if random.random() < DICE_RATIO:
                self._send_dice()
            if self.settings.vk_token:
                from .rubrics import strip_html
                clean_text = strip_html(text)
                hashtags = " ".join(get_hashtags(rubric))
                vk_msg = f"{clean_text}\n\n{hashtags}\n\n— Подпишись: t.me/{self.settings.channel_link.split('/')[-1]}"
                post_to_vk(self.settings.vk_token, self.settings.vk_owner_id, vk_msg)
        return msg_id

    def _send_observation(self, text: str) -> bool:
        payload = {
            "chat_id": self.settings.channel_id,
            "text": _build_observation(text, self.settings.channel_link),
            "parse_mode": "HTML",
        }
        self._post_message(payload)
        return True

    def _send_horoscope(self) -> int:
        text = generate_horoscope()
        payload = {
            "chat_id": self.settings.channel_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        data = self._post_message(payload)
        msg_id = data["result"]["message_id"]
        logger.info("Published morning horoscope")
        self._send_dice()
        return msg_id

    def _send_anti_advice(self) -> int:
        text = generate_anti_advice()
        payload = {
            "chat_id": self.settings.channel_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        data = self._post_message(payload)
        msg_id = data["result"]["message_id"]
        logger.info("Published anti-advice of the day")
        return msg_id

    def _publish_meme(self) -> bool:
        joke = self.db.get_unpublished_meme()
        if joke is None:
            logger.info("No unpublished memes available")
            return False
        return self._send_meme_image(joke)

    def _send_story(self) -> bool:
        try:
            from .image_gen import generate_story_image
            joke = self.db.get_next_unpublished()
            if joke is None:
                joke = self.db.get_next_popular_unpublished()
            if joke is None:
                logger.info("No jokes available for story")
                return False
            text = joke.text
            if text.startswith("MEME:"):
                text = text.split("\n", 1)[1].strip() if "\n" in text else ""
            if not text:
                return False
            src_name = self.settings.channel_link.rstrip("/").rsplit("/", 1)[-1] if self.settings.channel_link else "Anetdodik"
            image_path = generate_story_image(text, src_name)
            with open(image_path, "rb") as f:
                r = requests.post(
                    f"https://api.telegram.org/bot{self.settings.bot_token}/sendStory",
                    data={"chat_id": self.settings.channel_id},
                    files={"photo": f},
                    timeout=self.settings.http_timeout,
                )
            Path(image_path).unlink(missing_ok=True)
            if r.ok and r.json().get("ok"):
                self.db.mark_published(joke.content_hash)
                logger.info("Posted story: %s", joke.external_id)
                return True
            logger.warning("sendStory failed: %s", r.text)
            return False
        except Exception as e:
            logger.warning("Failed to send story: %s", e)
            return False

    def _send_photo(self, img_url: str, caption: str, content_hash: str) -> bool:
        try:
            resp = requests.get(img_url, timeout=20)
            resp.raise_for_status()
            ext = img_url.rsplit(".", 1)[-1].lower()
            fname = f"meme_{content_hash}.{ext}"
            path = Path("data") / fname
            path.write_bytes(resp.content)
            with open(path, "rb") as f:
                r = requests.post(
                    f"https://api.telegram.org/bot{self.settings.bot_token}/sendPhoto",
                    data={
                        "chat_id": self.settings.channel_id,
                        "caption": caption,
                        "parse_mode": "HTML",
                        "reply_markup": json.dumps(self._build_keyboard()),
                    },
                    files={"photo": f},
                    timeout=self.settings.http_timeout,
                )
            path.unlink(missing_ok=True)
            payload = r.json()
            if not r.ok or not payload.get("ok"):
                raise RuntimeError(f"Telegram API error: {payload.get('description', 'unknown')}")
            self.db.mark_published(content_hash)
            return True
        except Exception as e:
            logger.warning("Failed to send photo: %s", e)
            return False

    def _send_meme_image(self, joke) -> bool:
        text = joke.text
        if not text.startswith("MEME:"):
            return False
        rest = text[len("MEME:"):]
        img_url = rest.split("\n")[0].strip()
        caption = "\n".join(rest.split("\n")[1:]).strip()[:200]
        logger.info("Publishing meme image: %s", img_url)
        return self._send_photo(img_url, caption, joke.content_hash)

    def _send_video(self, joke) -> bool:
        try:
            from .video_gen import generate_video
            video_path = generate_video(joke.text)
            with open(video_path, "rb") as f:
                r = requests.post(
                    f"https://api.telegram.org/bot{self.settings.bot_token}/sendVideo",
                    data={
                        "chat_id": self.settings.channel_id,
                        "caption": f"\U0001F3AC \u0410\u043D\u0435\u043A\u0434\u043E\u0442 \u0432 \u0432\u0438\u0434\u0435\u043E\u0444\u043E\u0440\u043C\u0430\u0442\u0435",
                        "parse_mode": "HTML",
                        "reply_markup": json.dumps(self._build_keyboard()),
                    },
                    files={"video": f},
                    timeout=120,
                )
            Path(video_path).unlink(missing_ok=True)
            data = r.json()
            if not r.ok or not data.get("ok"):
                raise RuntimeError(f"Telegram API error: {data.get('description', 'unknown')}")
            self.db.mark_published(joke.content_hash)
            logger.info("Published video joke: %s", joke.external_id)
            return True
        except Exception as e:
            logger.warning("Failed to send video: %s", e)
            return False

    _ANALYSIS_TEMPLATES = [
        "Контекст: {title}. Соль мема в том, что ситуация узнаваема до зубной боли. "
        "Ирония строится на контрасте между ожиданием и реальностью.",
        "Этот мем работает за счёт неожиданного твиста. Сначала {low_title}, "
        "а потом — бам! — полная противоположность. Классика жанра.",
        "Почему это смешно? Потому что {low_title}. Автор поймал идеальный "
        "тайминг и узнаваемый паттерн. Именно так это и работает в реальной жизни.",
        "Главный приём здесь — гипербола и самоирония. {title}. "
        "Смех сквозь слёзы узнавания — вот рецепт этого мема.",
        "Формула мема: ситуация + неожиданная развязка. {title} — "
        "идеальный пример. Чем больше контекста, тем смешнее.",
    ]

    def _build_meme_analysis(self, title: str) -> str:
        template = random.choice(self._ANALYSIS_TEMPLATES)
        low = title[0].lower() + title[1:] if len(title) > 1 else title.lower()
        analysis = template.format(title=title, low_title=low)
        return f"\U0001F9D0 <b>\u0420\u0430\u0437\u0431\u043E\u0440 \u043C\u0435\u043C\u0430</b>\n\n{html.escape(analysis)}\n\n#\u0440\u0430\u0437\u0431\u043E\u0440\u043C\u0435\u043C\u0430 #\u0430\u043D\u0430\u0442\u043E\u043C\u0438\u044F\u044E\u043C\u043E\u0440\u0430"

    def _send_meme_analysis(self, joke) -> bool:
        text = joke.text
        if not text.startswith("MEME:"):
            return False
        rest = text[len("MEME:"):]
        img_url = rest.split("\n")[0].strip()
        title = "\n".join(rest.split("\n")[1:]).strip()[:200]
        analysis = self._build_meme_analysis(title)
        logger.info("Publishing meme analysis: %s", img_url)
        return self._send_photo(img_url, analysis, joke.content_hash)

    def _send_headline_joke(self, joke, rubric: dict) -> bool:
        split = _split_headline(joke.text)
        if split is None:
            return False
        setup, punchline = split
        logger.info("Publishing headline joke: %s", joke.external_id)
        # post setup as a regular text, get its message_id
        joke.text = setup
        msg_id = self._send_text(joke, rubric)
        # post punchline as a reply
        payload = {
            "chat_id": self.settings.channel_id,
            "text": html.escape(punchline),
            "parse_mode": "HTML",
            "reply_to_message_id": msg_id,
        }
        self._post_message(payload)
        return True

    def _send_image(self, joke, rubric: dict) -> bool:
        post_number = self.db.count_published() + 1
        image_path = generate_joke_image(joke.text, post_number, rubric_name=rubric.get("name"))
        caption = _build_caption(post_number, self.settings.channel_link)

        with open(image_path, "rb") as f:
            response = requests.post(
                f"https://api.telegram.org/bot{self.settings.bot_token}/sendPhoto",
                data={"chat_id": self.settings.channel_id, "caption": caption, "reply_markup": json.dumps(self._build_keyboard())},
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

        msg_id = payload.get("result", {}).get("message_id")
        if msg_id:
            self._edit_post_keyboard(self.settings.channel_id, msg_id)

        self.db.mark_published(joke.content_hash)
        logger.info("Published image joke: %s", joke.external_id)
        return True

    def _handle_two_part(self, joke, rubric: dict) -> bool:
        split = _split_two_part(joke.text)
        if split is None:
            return False
        part1, part2 = split
        self.db.mark_published(joke.content_hash)
        joke.text = part1.strip()
        msg_id = self._send_text(joke, rubric, "\u0427\u0438\u0442\u0430\u0439\u0442\u0435 \u043F\u0440\u043E\u0434\u043E\u043B\u0436\u0435\u043D\u0438\u0435 \u0432 \u0441\u043B\u0435\u0434\u0443\u044E\u0449\u0435\u043C \u0432\u044B\u043F\u0443\u0441\u043A\u0435:")
        self.db.save_pending_part(joke.content_hash, part2.strip(), joke.source_name, joke.external_id, joke.content_hash, msg_id)
        return True

    def _send_pending_part(self, rubric: dict) -> bool:
        pending = self.db.get_pending_part()
        if pending is None:
            return False
        joke, part1_msg_id = pending
        self._send_text(joke, rubric, is_part2=True, reply_to=part1_msg_id)
        self.db.delete_pending_part(joke.content_hash)
        logger.info("Published continuation for part1 msg %s", part1_msg_id)
        return True

    def _handle_battle(self, rubric: dict) -> bool:
        joke1 = self.db.get_next_unpublished()
        if joke1 is None:
            return False
        self.db.mark_published(joke1.content_hash)
        joke2 = self.db.get_next_unpublished()
        if joke2 is None:
            return False
        self.db.add_shorts_candidate(joke1.text)
        self.db.add_shorts_candidate(joke2.text)
        post_number = self.db.count_published() + 1
        battle_text = (
            f"\u2694\uFE0F <b>\u0411\u0430\u0442\u0442\u043B \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u043E\u0432!</b>\n\n"
            f"<b>1.</b> {html.escape(joke1.text)}\n\n\u2500\u2500\u2500\n\n"
            f"<b>2.</b> {html.escape(joke2.text)}"
        )
        self._post_message({
            "chat_id": self.settings.channel_id,
            "text": battle_text,
            "parse_mode": "HTML",
        })
        self._post_poll(joke1.text, joke2.text, post_number)
        self.db.mark_published(joke2.content_hash)
        logger.info("Published battle: %s vs %s", joke1.external_id, joke2.external_id)
        return True

    def _send_repost_card(self, joke) -> bool:
        post_number = self.db.count_published() + 1
        image_path = generate_repost_card(joke.text)
        caption = _build_caption(post_number, self.settings.channel_link)

        with open(image_path, "rb") as f:
            response = requests.post(
                f"https://api.telegram.org/bot{self.settings.bot_token}/sendPhoto",
                data={"chat_id": self.settings.channel_id, "caption": caption, "reply_markup": json.dumps(self._build_keyboard())},
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

        msg_id = payload.get("result", {}).get("message_id")
        if msg_id:
            self._edit_post_keyboard(self.settings.channel_id, msg_id)

        self.db.mark_published(joke.content_hash)
        logger.info("Published repost card: %s", joke.external_id)
        return True

    def _send_reaction_summary(self) -> bool:
        reaction = self.db.get_random_unpublished_reaction()
        if reaction is None:
            return False
        author = _author_display(None, reaction["username"])
        text = (
            f"\U0001F4AC <b>\u0420\u0435\u0430\u043A\u0446\u0438\u044F \u043F\u043E\u0434\u043F\u0438\u0441\u0447\u0438\u043A\u0430</b>\n\n"
            f"{html.escape(reaction['text'])}\n\n"
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

    def _get_member_count(self) -> int:
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.settings.bot_token}/getChatMemberCount",
                json={"chat_id": self.settings.channel_id},
                timeout=self.settings.http_timeout,
            )
            data = resp.json()
            if data.get("ok"):
                return int(data["result"])
        except Exception:
            pass
        prev = self.db.get_meta("member_count", "0")
        return int(prev) if prev else 0

    def _digest_posted_today(self) -> bool:
        today_str = datetime.datetime.today().strftime("%Y-%m-%d")
        if os.environ.get("SUNDAY_DIGEST_MARKER") == today_str:
            logger.info("Sunday digest already posted today (verified via repo marker file)")
            return True
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.settings.bot_token}/getUpdates",
                json={"allowed_updates": ["channel_post"], "limit": 1},
                timeout=15,
            )
            data = resp.json()
            if data.get("ok"):
                for update in data.get("result", []):
                    post = update.get("channel_post", {})
                    if post.get("text") and "#\u0434\u0430\u0439\u0434\u0436\u0435\u0441\u0442" in post.get("text", ""):
                        logger.info("Sunday digest found in recent getUpdates")
                        return True
        except Exception:
            pass
        return False

    def _send_weekly_digest(self) -> bool:
        jokes = self.db.get_recent_published(limit=3, days=7)
        if not jokes:
            return False
        members = self._get_member_count()
        self.db.set_meta("member_count", str(members))
        lines = []
        for i, joke in enumerate(jokes, 1):
            text = joke.text.replace("\n", " ")[:200].rstrip() + "\u2026" if len(joke.text) > 200 else joke.text
            lines.append(f"<b>{i}.</b> {html.escape(text)}")
        result = (
            f"\U0001F4C5 <b>\u041B\u0443\u0447\u0448\u0435\u0435 \u0437\u0430 \u043D\u0435\u0434\u0435\u043B\u044E</b>\n\n"
            f"\U0001F389 \u041D\u0430\u0441 \u0443\u0436\u0435 <b>{members}</b>!\n\n"
            f"{chr(10).join(lines)}"
        )
        yt_stats = get_channel_stats(self.settings.youtube_api_key, self.settings.youtube_channel_id)
        if yt_stats:
            result += (
                f"\n\n\U0001F3A5 <b>YouTube</b>\n"
                f"\U0001F4CA {yt_stats['subscribers']} \u043F\u043E\u0434\u043F\u0438\u0441\u0447\u0438\u043A\u043E\u0432\n"
                f"\U0001F3AC {yt_stats['videos']} \u0432\u0438\u0434\u0435\u043E"
            )
        top_authors = self.db.get_top_authors(limit=3)
        if top_authors:
            author_lines = []
            for i, a in enumerate(top_authors, 1):
                display = f"@{a['username']}" if a["username"] else a["name"]
                author_lines.append(f"<b>{i}.</b> {html.escape(display)} \u2014 {a['jokes_count']}")
            result += (
                f"\n\n\U0001F3C6 <b>\u0422\u041E\u041F \u0430\u0432\u0442\u043E\u0440\u043E\u0432</b>\n"
                f"{chr(10).join(author_lines)}"
            )
        result += "\n\n#\u0434\u0430\u0439\u0434\u0436\u0435\u0441\u0442 #\u043B\u0443\u0447\u0448\u0435\u0435"
        self._post_message({
            "chat_id": self.settings.channel_id,
            "text": result,
            "parse_mode": "HTML",
        })
        self.db.mark_special_post("sunday_digest")
        Path("data/sunday_digest_marker.txt").write_text(datetime.datetime.today().strftime("%Y-%m-%d"))
        return True

    def _handle_youtube(self) -> bool:
        api_key = self.settings.youtube_api_key
        channel_id = self.settings.youtube_channel_id
        if not api_key or not channel_id:
            return False

        stats = get_channel_stats(api_key, channel_id)
        if stats is None:
            return False

        last_id = self.db.get_youtube_last_video_id()
        videos = get_latest_videos(api_key, channel_id, limit=3)
        new_videos = [v for v in videos if v["id"] != last_id] if last_id else []

        if new_videos and last_id:
            v = new_videos[0]
            self.db.set_youtube_last_video_id(v["id"])
            text = (
                f"\U0001F3A5 <b>\u041D\u043E\u0432\u043E\u0435 \u0432\u0438\u0434\u0435\u043E \u043D\u0430 YouTube!</b>\n\n"
                f"{html.escape(v['title'])}\n\n"
                f"\uD83D\uDC49 https://youtu.be/{v['id']}\n\n"
                f"#youtube #\u0448\u043E\u0440\u0442\u0441"
            )
            self._post_message({
                "chat_id": self.settings.channel_id,
                "text": text,
                "parse_mode": "HTML",
            })
            logger.info("Published YouTube video announcement: %s", v["id"])
            return True

        if not last_id:
            self.db.set_youtube_last_video_id(videos[0]["id"] if videos else "")
            return False

        return False

    def _make_short(self) -> bool:
        if not self.settings.youtube_refresh_token:
            return False
        candidates = self.db.get_shorts_candidates(limit=1)
        if not candidates:
            return False
        joke = candidates[0]

        if is_flagged(joke["text"]):
            self.db.delete_shorts_candidate(joke["id"])
            logger.warning("Skipping flagged joke for short: %s ...", joke["text"].replace("\n", " ")[:60])
            return False

        output = Path("data/shorts") / f"short_{joke['id']}.mp4"
        if not render_short(joke["text"], str(output), kie_api_key=self.settings.kie_api_key):
            return False
        preview = joke["text"].replace("\n", " ")[:80].rstrip() + "\u2026"
        vid = upload_short(
            str(output),
            title=preview,
            description="\u0410\u043D\u0435\u043A\u0434\u043E\u0442 \u0438\u0437 Telegram @Anetdodik",
            refresh_token=self.settings.youtube_refresh_token,
            client_id=self.settings.youtube_client_id,
            client_secret=self.settings.youtube_client_secret,
            privacy_status="private",
        )
        output.unlink(missing_ok=True)
        if vid:
            self.db.delete_shorts_candidate(joke["id"])
            logger.info("Posted short: https://youtu.be/%s", vid)
            return True
        return False

    def _friday_prompt_posted_today(self) -> bool:
        today_str = datetime.datetime.today().strftime("%Y-%m-%d")
        if os.environ.get("FRIDAY_MARKER") == today_str:
            logger.info("Friday prompt already posted (verified via repo marker file)")
            return True
        msg_id_key = f"special_friday_prompt_msgid_{today_str}"
        stored_msg_id = self.db.get_meta(msg_id_key)
        if stored_msg_id:
            try:
                resp = requests.post(
                    f"https://api.telegram.org/bot{self.settings.bot_token}/editMessageReplyMarkup",
                    json={"chat_id": self.settings.channel_id, "message_id": int(stored_msg_id)},
                    timeout=10,
                )
                if resp.json().get("ok"):
                    logger.info("Friday prompt verified via stored message_id %s", stored_msg_id)
                    return True
            except Exception:
                pass

        try:
            today_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
            day_start = today_ts - (today_ts % 86400)
            logger.info("Scanning getUpdates for Friday prompt (day_start=%s)", day_start)
            for page in range(50):
                resp = requests.post(
                    f"https://api.telegram.org/bot{self.settings.bot_token}/getUpdates",
                    json={"allowed_updates": ["channel_post"], "limit": 100},
                    timeout=25,
                )
                data = resp.json()
                if not data.get("ok"):
                    logger.warning("getUpdates failed: %s", data.get("description", "unknown"))
                    return False
                updates = data.get("result", [])
                if not updates:
                    logger.info("getUpdates scan complete: no more updates after %d pages", page)
                    break
                logger.info("getUpdates page %d: got %d channel_post updates", page, len(updates))
                for update in updates:
                    post = update.get("channel_post", {})
                    if not post:
                        continue
                    chat_id = str(post.get("chat", {}).get("id", ""))
                    if chat_id != str(self.settings.channel_id):
                        continue
                    post_date = post.get("date", 0)
                    if post_date < day_start:
                        continue
                    text = post.get("text", "") or post.get("caption", "")
                    if "\U0001F4DD" in text and "\u041F\u044F\u0442\u043D\u0438\u0447\u043D\u044B\u0439" in text:
                        logger.info("Friday prompt found in getUpdates at update_id=%s, date=%s", update["update_id"], post_date)
                        return True
            logger.info("getUpdates scan complete: checked %d pages, Friday prompt not found", page)
            return False
        except Exception as e:
            logger.warning("Telegram Friday prompt check failed: %s", e)
            return False

    def publish_next(self) -> bool:
        today = datetime.datetime.today()
        rubric = get_today_rubric()

        try:
            handler = PollingHandler(self.settings, self.db)
            handler.poll_once()
            logger.info("Processed pending bot updates")
        except Exception:
            logger.exception("Failed to poll bot updates")

        self._welcome_new_members()

        if self._send_pending_part(rubric):
            return True

        if self.db.count_pending_quiz() > 0:
            return self._send_quiz_answer()

        if self.db.count_approved_submissions() > 0:
            return self._send_subscriber_joke()

        post_number = self.db.count_published() + 1

        # TODO: re-enable after fixing dedup
        #if today.weekday() in SUNDAY_DIGEST_DAYS:
        #    if self._digest_posted_today():
        #        logger.info("Sunday digest already posted today (verified via Telegram)")
        #    elif self._send_weekly_digest():
        #        return True

        if today.weekday() in FRIDAY_PROMPT_DAYS:
            if self._friday_prompt_posted_today():
                logger.info("Friday prompt already posted today (verified via Telegram channel)")
            elif not self.db.has_special_post_today("friday_prompt"):
                return self._send_friday_prompt()

        if post_number % BATTLE_EVERY == 0 and post_number > 0:
            return self._handle_battle(rubric)

        if self.db.count_unpublished_reactions() > 0:
            return self._send_reaction_summary()

        if self._handle_youtube():
            return True

        if True and self.db.count_shorts_candidates() > 0:
            if self._make_short():
                logger.info("Short posted, continuing with regular post")

        if rubric["keywords"]:
            if random.random() < 0.8:
                joke = self.db.get_next_unpublished_matching(rubric["keywords"])
            else:
                joke = self.db.get_next_unpublished()
            if joke:
                if joke.text.startswith("MEME:"):
                    if random.random() < MEME_ANALYSIS_RATIO:
                        return self._send_meme_analysis(joke)
                    return self._send_meme_image(joke)
                if len(joke.text) < 200 and random.random() < OBSERVATION_RATIO:
                    self.db.mark_published(joke.content_hash)
                    return self._send_observation(joke.text)
                if random.random() < HEADLINE_RATIO and _split_headline(joke.text):
                    return self._send_headline_joke(joke, rubric)
                if len(joke.text) > 600 and _split_two_part(joke.text):
                    result = self._handle_two_part(joke, rubric)
                    if result:
                        return result
                quiz = self._try_make_quiz(joke, rubric)
                if quiz is True:
                    return True
                if random.random() < REPOST_CARD_RATIO and fits_in_image(joke.text):
                    return self._send_repost_card(joke)
                if random.random() < VIDEO_RATIO and len(joke.text) > 100:
                    return self._send_video(joke)
                if random.random() < IMAGE_RATIO and fits_in_image(joke.text):
                    return self._send_image(joke, rubric)
                return self._send_text(joke, rubric)

        if random.random() < 0.8:
            joke = self.db.get_next_popular_unpublished()
        else:
            joke = None
        if joke is None:
            joke = self.db.get_next_unpublished()
        if joke is None:
            logger.info("No unpublished jokes available")
            return False

        if joke.text.startswith("MEME:"):
            if random.random() < MEME_ANALYSIS_RATIO:
                return self._send_meme_analysis(joke)
            return self._send_meme_image(joke)

        if len(joke.text) < 200 and random.random() < OBSERVATION_RATIO:
            self.db.mark_published(joke.content_hash)
            return self._send_observation(joke.text)

        if random.random() < HEADLINE_RATIO and _split_headline(joke.text):
            return self._send_headline_joke(joke, rubric)

        if len(joke.text) > 600 and _split_two_part(joke.text):
            result = self._handle_two_part(joke, rubric)
            if result:
                return result

        quiz = self._try_make_quiz(joke, rubric)
        if quiz is True:
            return True

        if random.random() < REPOST_CARD_RATIO and fits_in_image(joke.text):
            return self._send_repost_card(joke)
        if random.random() < VIDEO_RATIO and len(joke.text) > 100:
            return self._send_video(joke)
        if random.random() < IMAGE_RATIO and fits_in_image(joke.text):
            return self._send_image(joke, rubric)
        return self._send_text(joke, rubric)