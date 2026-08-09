# Discussion Chat Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить третью inline-кнопку «💬 Обсудить» + текстовую строку «💬 Обсудить в чате →» в новых постах канала, чтобы пользователи могли попасть в чат обсуждений, несмотря на то что Telegram скрывает нативный значок перехода при наличии inline-кнопок.

**Architecture:** Новая env-переменная `DISCUSSION_CHAT_LINK` (опциональная, fail-safe). Если задана — `_build_keyboard` добавляет кнопку, `_build_text` добавляет текстовую строку. Если пустая — поведение идентично текущему. Применяется только к новым постам (без миграции старых). YAGNI — никакого рефакторинга `Settings`, `discussion_chat_link` читается точечно где нужно.

**Tech Stack:** Python 3.13/3.14, stdlib `unittest`, Render free tier.

## Global Constraints

- Терминал пользователя — CMD, но запуск через PowerShell-обёртку этого инструмента. Тесты: `py -m unittest tests.test_discussion_chat -v`.
- НЕ добавлять новых зависимостей — `unittest` из stdlib.
- Все Unicode-эмодзи в коде — `\U0001FXXX`-escape (Telegram HTML парсит), как уже сделано в `_build_keyboard` (`\U0001F4E4`, `\U0001F514`).
- `.env` в gitignore — коммитить нельзя, только `.env.example`.
- Render env — добавить через `render.yaml` (для новых деплоев), секрет GitHub Actions — добавить переменную в workflow (для ручных запусков).
- `discussion_chat_link` — опциональная переменная. Если не задана — ничего не ломается, поведение деградирует до текущего.
- Идемпотентность — операция чисто аддитивная (ничего не удаляется, ничего не переименовывается).
- Общаться с пользователем на русском. Не трогать ничего кроме явно описанных мест.

---

### Task 1: Кнопка «Обсудить» + текстовая строка в новых постах

**Files:**
- Modify: `src/tg_autopost/config.py:7-55`
- Modify: `src/tg_autopost/publisher.py:87-110, 171-178, 436`
- Modify: `.env.example`
- Modify: `render.yaml`
- Modify: `.github/workflows/publish.yml`
- Test: `tests/test_discussion_chat.py`

**Interfaces:**
- Consumes: `Settings` (config.py), `TelegramPublisher._build_keyboard` / `_build_text` (publisher.py).
- Produces:
  - `Settings.discussion_chat_link: str = ""` — новое поле.
  - `Settings.discussion_chat_link` загружается из env с валидацией (префикс `https://`/`http://`/`t.me/`); иначе warning + пусто.
  - `TelegramPublisher._build_keyboard` добавляет третью кнопку «💬 Обсудить» при непустом `discussion_chat_link`.
  - `_build_text(joke_text, rubric, post_number, preamble_override="", is_part2=False, channel_link="", discussion_chat_link="")` — новый параметр; при непустом добавляет `\n\n💬 Обсудить в чате → <link>`.
  - Вызов `_build_text` в `publisher.py:436` передаёт `discussion_chat_link=self.settings.discussion_chat_link`.

- [ ] **Step 1: Создать `tests/test_discussion_chat.py` с падающими тестами**

```python
import os
import unittest
from unittest.mock import patch

from src.tg_autopost.config import load_settings
from src.tg_autopost.publisher import _build_text


class TestDiscussionChatLink(unittest.TestCase):
    def setUp(self):
        os.environ["BOT_TOKEN"] = "test:token"
        os.environ["CHANNEL_ID"] = "-100123"
        os.environ["CHANNEL_LINK"] = "https://t.me/main"
        os.environ["DISCUSSION_CHAT_LINK"] = "https://t.me/chat"

    def tearDown(self):
        for k in ("BOT_TOKEN", "CHANNEL_ID", "CHANNEL_LINK", "DISCUSSION_CHAT_LINK"):
            os.environ.pop(k, None)

    def test_settings_has_discussion_chat_link(self):
        s = load_settings()
        self.assertEqual(s.discussion_chat_link, "https://t.me/chat")

    def test_settings_discussion_chat_link_empty_when_unset(self):
        os.environ.pop("DISCUSSION_CHAT_LINK", None)
        s = load_settings()
        self.assertEqual(s.discussion_chat_link, "")

    def test_settings_discussion_chat_link_invalid_prefix_warns_and_clears(self):
        os.environ["DISCUSSION_CHAT_LINK"] = "javascript:alert(1)"
        s = load_settings()
        self.assertEqual(s.discussion_chat_link, "")

    def test_settings_accepts_tme_short_link(self):
        os.environ["DISCUSSION_CHAT_LINK"] = "t.me/chat"
        s = load_settings()
        self.assertEqual(s.discussion_chat_link, "t.me/chat")

    def test_build_text_appends_discussion_line(self):
        text = _build_text(
            "Анекдот текст.",
            {"preamble": ""},
            1,
            preamble_override="",
            is_part2=False,
            channel_link="",
            discussion_chat_link="https://t.me/chat",
        )
        self.assertIn("💬 Обсудить в чате → https://t.me/chat", text)

    def test_build_text_omits_discussion_when_empty(self):
        text = _build_text(
            "Анекдот.",
            {"preamble": ""},
            1,
            preamble_override="",
            is_part2=False,
            channel_link="",
            discussion_chat_link="",
        )
        self.assertNotIn("Обсудить", text)

    def test_build_keyboard_adds_button_when_link_set(self):
        from src.tg_autopost.publisher import TelegramPublisher
        from types import SimpleNamespace
        publisher = TelegramPublisher.__new__(TelegramPublisher)
        publisher.settings = SimpleNamespace(
            channel_link="https://t.me/main",
            discussion_chat_link="https://t.me/chat",
        )
        kb = publisher._build_keyboard(message_id=42)
        flat = [b for row in kb["inline_keyboard"] for b in row]
        texts = [b["text"] for b in flat]
        self.assertIn("💬 Обсудить", texts)
        self.assertEqual([b for b in flat if b["text"] == "💬 Обсудить"][0]["url"],
                         "https://t.me/chat")

    def test_build_keyboard_no_button_when_link_empty(self):
        from src.tg_autopost.publisher import TelegramPublisher
        from types import SimpleNamespace
        publisher = TelegramPublisher.__new__(TelegramPublisher)
        publisher.settings = SimpleNamespace(
            channel_link="https://t.me/main",
            discussion_chat_link="",
        )
        kb = publisher._build_keyboard(message_id=42)
        flat = [b for row in kb["inline_keyboard"] for b in row]
        texts = [b["text"] for b in flat]
        self.assertNotIn("💬 Обсудить", texts)
```

- [ ] **Step 2: Запустить тесты — должны упасть**

Run: `py -m unittest tests.test_discussion_chat -v`
Expected: FAIL (`Settings has no field 'discussion_chat_link'` → `AttributeError`)

- [ ] **Step 3: Добавить поле в `Settings`**

В `src/tg_autopost/config.py`, в dataclass `Settings` (после строки 11 `channel_link: str = ""`):

```python
    discussion_chat_link: str = ""
```

В функции `load_settings()` (после строки 55 `channel_link=...`):

```python
        discussion_chat_link=_validate_discussion_chat_link(os.getenv("DISCUSSION_CHAT_LINK", "").strip()),
```

Добавить helper `_validate_discussion_chat_link` в начало файла (после импортов):

```python
import logging

logger = logging.getLogger(__name__)


def _validate_discussion_chat_link(raw: str) -> str:
    """Валидация ссылки на чат обсуждений. Допустимы только http(s) и t.me/ —
    остальное считается небезопасным и сбрасывается в пустое значение с warning."""
    if not raw:
        return ""
    if raw.startswith(("https://", "http://", "t.me/")):
        return raw
    logger.warning("DISCUSSION_CHAT_LINK has invalid prefix %r, clearing", raw[:20])
    return ""
```

- [ ] **Step 4: Запустить тесты Settings — должны пройти**

Run: `py -m unittest tests.test_discussion_chat.TestDiscussionChatLink.test_settings_has_discussion_chat_link -v`
Expected: PASS

- [ ] **Step 5: Добавить параметр в `_build_text`**

В `src/tg_autopost/publisher.py`, заменить сигнатуру (строка 87):

```python
def _build_text(joke_text: str, rubric: dict, post_number: int, preamble_override: str = "", is_part2: bool = False, channel_link: str = "", discussion_chat_link: str = "") -> str:
```

В конце функции (после блока `if channel_link:` который добавляет подпись канала):

```python
    if discussion_chat_link:
        text += f"\n\n💬 Обсудить в чате → {discussion_chat_link}"
    return text
```

Прочитать текущий конец функции, чтобы вставить в правильное место.

- [ ] **Step 6: Запустить тесты `_build_text` — должны пройти**

Run: `py -m unittest tests.test_discussion_chat.TestDiscussionChatLink.test_build_text_appends_discussion_line tests.test_discussion_chat.TestDiscussionChatLink.test_build_text_omits_discussion_when_empty -v`
Expected: PASS

- [ ] **Step 7: Обновить вызов `_build_text` (publisher.py:436)**

Заменить:

```python
        text = _build_text(joke.text, rubric, post_number, preamble_override, is_part2, self.settings.channel_link)
```

на:

```python
        text = _build_text(joke.text, rubric, post_number, preamble_override, is_part2, self.settings.channel_link, discussion_chat_link=self.settings.discussion_chat_link)
```

- [ ] **Step 8: Добавить кнопку в `_build_keyboard`**

В `src/tg_autopost/publisher.py:171-178`, после блока `if self.settings.channel_link:`:

```python
        if self.settings.discussion_chat_link:
            buttons.append([{"text": "\U0001F4AC Обсудить", "url": self.settings.discussion_chat_link}])
        return {"inline_keyboard": buttons}
```

- [ ] **Step 9: Запустить все тесты плана — должны пройти**

Run: `py -m unittest tests.test_discussion_chat -v`
Expected: PASS (8 tests)

- [ ] **Step 10: Полный прогон + проверка синтаксиса**

Run: `py -m unittest discover -s tests -v` → все 30+ тестов PASS
Run: `py -c "import ast; [ast.parse(open(f, encoding='utf-8').read()) for f in ['src/tg_autopost/config.py','src/tg_autopost/publisher.py']]"` → `syntax ok`

- [ ] **Step 11: Обновить `.env.example`**

Добавить строку:

```
DISCUSSION_CHAT_LINK=https://t.me/your_chat
```

С комментарием:

```
# Ссылка на чат обсуждений канала. Если пусто — кнопка «Обсудить» и текстовая ссылка не добавляются.
```

- [ ] **Step 12: Обновить `render.yaml`**

В блоке `envVars:` (после `CHANNEL_LINK`) добавить:

```yaml
      - key: DISCUSSION_CHAT_LINK
        sync: false
```

- [ ] **Step 13: Обновить `.github/workflows/publish.yml`**

В блоке создания `.env` (после `echo "CHANNEL_LINK=..."`) добавить:

```yaml
          echo "DISCUSSION_CHAT_LINK=${{ secrets.DISCUSSION_CHAT_LINK }}" >> .env
```

- [ ] **Step 14: Коммит**

```bash
git add src/tg_autopost/config.py src/tg_autopost/publisher.py tests/test_discussion_chat.py .env.example render.yaml .github/workflows/publish.yml
git commit -m "feat: add discussion chat button + text link to channel posts"
```

- [ ] **Step 15: (После деплоя) Добавить секреты**

Render env: добавить `DISCUSSION_CHAT_LINK` (через UI — нет доступа из моего хоста).
GitHub Secrets: добавить `DISCUSSION_CHAT_LINK` (через UI — потребует email-код).

Эти шаги делает пользователь вручную, если хочет активировать фичу. Без них переменная пустая → поведение идентично текущему (fail-safe).

## Self-Review

**1. Spec coverage:**
- Кнопка «💬 Обсудить» в `_build_keyboard` → Task 1 Step 8. ✅
- Текстовая строка в `_build_text` → Task 1 Steps 5+7. ✅
- Fail-safe (пустая переменная) → Task 1 Steps 3 (валидация) + 8 (if-guard). ✅
- Только новые посты → все шаги меняют только код публикации. ✅
- Нет рефакторинга → дизайн явно YAGNI; шаги минимальные. ✅
- Тесты для keyboard и text → Task 1 Step 1. ✅
- Env/конфигурация (.env.example, render.yaml, workflow) → Steps 11-13. ✅

**2. Placeholder scan:** Все шаги содержат конкретный код. Нет TBD/TODO.

**3. Type consistency:**
- `Settings.discussion_chat_link: str = ""` (Step 3) — используется в `_build_keyboard` (Step 8) и `_build_text` (Step 7). ✅
- `_build_text(..., discussion_chat_link="")` (Step 5) — вызов с keyword-arg (Step 7). ✅
- `TelegramPublisher._build_keyboard` (Step 8) — использует `self.settings.discussion_chat_link`. ✅
