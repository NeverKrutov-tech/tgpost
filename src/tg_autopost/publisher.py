import datetime
import html
import logging
import os
import random
from pathlib import Path

import requests

from .config import Settings
from .content_filter import is_flagged
from .database import Database
from .handlers import PollingHandler
from .image_gen import fits_in_image, generate_joke_image, generate_repost_card
from .levels import get_level
from .rubrics import classify_emoji, get_hashtags, get_preamble, get_today_rubric, is_jubilee
from .shorts_maker import render_short, upload_short
from .youtube import get_channel_stats, get_latest_videos

logger = logging.getLogger(__name__)

IMAGE_RATIO = 0.2
DICE_RATIO = 0.15
BATTLE_EVERY = 5
OBSERVATION_RATIO = 0.1
REPOST_CARD_RATIO = 0.3
REACTION_PROMPT_RATIO = 0.4
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
    return f"<b>{emoji_line}</b>\n\n{body}\n\n{hashtags}"


def _build_observation(text: str) -> str:
    safe_text = html.escape(text)
    hashtags = get_hashtags(text)
    return f"\U0001F914 <b>\u041D\u0430\u0431\u043B\u044E\u0434\u0435\u043D\u0438\u0435</b>\n\n{safe_text}\n\n{hashtags}"


def _build_caption(post_number: int) -> str:
    jubilee = is_jubilee(post_number)
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
        share = self._share_button()
        buttons = []
        if share:
            buttons.extend(share["inline_keyboard"])
        buttons.append([
            {"text": "\u2B50 \u041F\u043E\u0431\u043B\u0430\u0433\u043E\u0434\u0430\u0440\u0438\u0442\u044C \u0430\u0432\u0442\u043E\u0440\u0430", "url": tip_url}
        ])
        self._post_message({
            "chat_id": self.settings.channel_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": buttons},
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

    def _send_observation(self, text: str) -> bool:
        payload = {
            "chat_id": self.settings.channel_id,
            "text": _build_observation(text),
            "parse_mode": "HTML",
        }
        self._post_message(payload)
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
        original_hash = joke.content_hash
        p1_hash = original_hash + "_p1"
        self.db.save_pending_part(
            original_hash, part2, joke.source_name,
            joke.external_id + "_p2", original_hash + "_p2",
        )
        self.db.mark_published(original_hash)
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
                f"\n\n\U0001F3C6 <b>\u0422\u043E\u043F \u0430\u0432\u0442\u043E\u0440\u043E\u0432</b>\n"
                f"{chr(10).join(author_lines)}"
            )
        result += "\n\n#\u0434\u0430\u0439\u0434\u0436\u0435\u0441\u0442 #\u043B\u0443\u0447\u0448\u0435\u0435"
        self.db.mark_special_post("sunday_digest")
        self._post_message({
            "chat_id": self.settings.channel_id,
            "text": result,
            "parse_mode": "HTML",
        })
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
        if not render_short(joke["text"], str(output), hf_token=self.settings.hf_token, cf_account_id=self.settings.cf_account_id, cf_api_token=self.settings.cf_api_token):
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

        if self.db.count_pending_quiz() > 0:
            return self._send_quiz_answer()

        pending = self.db.get_pending_part()
        if pending:
            result = self._send_text(pending, rubric, is_part2=True)
            self.db.delete_pending_part(pending.content_hash)
            return result

        if self.db.count_approved_submissions() > 0:
            return self._send_subscriber_joke()

        post_number = self.db.count_published() + 1

        if today.weekday() in SUNDAY_DIGEST_DAYS and not self.db.has_special_post_today("sunday_digest"):
            if self._send_weekly_digest():
                return True

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
                if len(joke.text) < 200 and random.random() < OBSERVATION_RATIO:
                    self.db.mark_published(joke.content_hash)
                    return self._send_observation(joke.text)
                if len(joke.text) > 600 and _split_two_part(joke.text):
                    result = self._handle_two_part(joke, rubric)
                    if result:
                        return result
                quiz = self._try_make_quiz(joke, rubric)
                if quiz is True:
                    return True
                if random.random() < REPOST_CARD_RATIO and fits_in_image(joke.text):
                    return self._send_repost_card(joke)
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

        if len(joke.text) < 200 and random.random() < OBSERVATION_RATIO:
            self.db.mark_published(joke.content_hash)
            return self._send_observation(joke.text)

        if len(joke.text) > 600 and _split_two_part(joke.text):
            result = self._handle_two_part(joke, rubric)
            if result:
                return result

        quiz = self._try_make_quiz(joke, rubric)
        if quiz is True:
            return True

        if random.random() < REPOST_CARD_RATIO and fits_in_image(joke.text):
            return self._send_repost_card(joke)
        if random.random() < IMAGE_RATIO and fits_in_image(joke.text):
            return self._send_image(joke, rubric)
        return self._send_text(joke, rubric)