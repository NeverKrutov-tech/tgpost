---
тип: дизайн
проект: tgpost
тег: #дизайн #engagement
дата: 2026-08-09
статус: согласован
---

# Дизайн: кнопка «Обсудить» + текстовая ссылка на чат

## Цель
Когда пост содержит inline-кнопки, Telegram скрывает нативный значок
перехода в обсуждение (это правило платформы). Решение — добавить третью
inline-кнопку «💬 Обсудить» со ссылкой на привязанный чат и текстовую
строку в конце поста. Дополнительный канал для аудитории попасть в чат
= рост комментариев, обсуждений, вовлечения.

## Решения (согласованы с пользователем 09.08)
1. **Только новые посты** — миграция старых не делаем.
2. **Третья inline-кнопка** в `_build_keyboard`: «💬 Обсудить» →
   `DISCUSSION_CHAT_LINK`.
3. **Текстовая строка** в `_build_text`: «💬 Обсудить в чате → <ссылка>».
4. **Fail-safe**: если `DISCUSSION_CHAT_LINK` пустая — поведение
   идентично текущему (без кнопки и без строки).
5. **Без рефакторинга** `_build_text` — просто добавляем второй параметр.

## Изменения по файлам

### 1. Новая переменная окружения
**Файл:** `src/tg_autopost/config.py:11,55`
- Добавить поле `Settings.discussion_chat_link: str = ""`.
- Загрузить из `os.getenv("DISCUSSION_CHAT_LINK", "").strip()`.
- Валидация: должно начинаться с `https://`, `http://` или `t.me/`.
  Если нет — логировать warning и оставить пустой.

**Файл:** `.env`, `.env.example`
- `.env`: добавить `DISCUSSION_CHAT_LINK=https://t.me/<chat_username>`.
- `.env.example`: `DISCUSSION_CHAT_LINK=` с комментарием «ссылка на чат обсуждений канала».

**Файл:** `render.yaml:13`
- Добавить `- key: DISCUSSION_CHAT_LINK`.

**Файл:** `.github/workflows/publish.yml:39`
- Добавить `echo "DISCUSSION_CHAT_LINK=${{ secrets.DISCUSSION_CHAT_LINK }}" >> .env`.

### 2. Кнопка в `_build_keyboard`
**Файл:** `src/tg_autopost/publisher.py:171-178`

```python
    def _build_keyboard(self, message_id: int | None = None) -> dict:
        buttons = []
        if message_id:
            share_url = f"https://tgpost-bot-l4wq.onrender.com/share/{message_id}"
            buttons.append([{"text": "\U0001F4E4 Поделиться", "url": share_url}])
        if self.settings.channel_link:
            buttons.append([{"text": "\U0001F514 Подписаться", "url": self.settings.channel_link}])
        if self.settings.discussion_chat_link:
            buttons.append([{"text": "\U0001F4AC Обсудить", "url": self.settings.discussion_chat_link}])
        return {"inline_keyboard": buttons}
```

### 3. Текстовая строка в `_build_text`
**Файл:** `src/tg_autopost/publisher.py:87-110`

```python
def _build_text(joke_text: str, rubric: dict, post_number: int, preamble_override: str = "", is_part2: bool = False, channel_link: str = "", discussion_chat_link: str = "") -> str:
    text = ...
    if channel_link:
        name = channel_link.rstrip("/").rsplit("/", 1)[-1]
        text += f"\n— @{name}"
    if discussion_chat_link:
        text += f"\n\n\U0001F4AC Обсудить в чате → {discussion_chat_link}"
    return text
```

**Вызов** (publisher.py:436) — добавить `discussion_chat_link=self.settings.discussion_chat_link`.

### 4. Тесты
**Файл:** `tests/test_discussion_chat.py` — новый.

Тесты:
- `test_button_added_when_link_set` — `_build_keyboard` содержит «Обсудить».
- `test_button_absent_when_link_empty` — пустая `discussion_chat_link` → нет кнопки.
- `test_text_appended_when_link_set` — `_build_text` добавляет строку.
- `test_text_unmodified_when_link_empty` — нет строки.

### 5. Не делаем (YAGNI)
- Миграция старых постов через `editMessageReplyMarkup`.
- Рефакторинг `_build_text` (читать из settings).
- Текстовая строка в `_build_observation` / `_build_caption` (для мемов и наблюдений).
- Изменение порядка кнопок в `_build_keyboard`.

## Связанные
- [[Статистика-TGStat-2026-08-04]] — упоминает linked_chat_id = -1004398655146.
- [[КОНТЕКСТ]] — чат обсуждений привязан 07.08.2026.
