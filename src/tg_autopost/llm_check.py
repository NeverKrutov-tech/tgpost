"""Semantic check for jokes that keyword rules cannot do.

ponytail: this only answers one question - "is the text cut off?" - because
that is the one thing the cheap rules provably cannot see and the one defect
that reached the channel (the вождь joke published without its punchline).

Rating humour was tried first and dropped: llama-3.1-8b returned 8/10 for 13
of 15 real jokes, so it carries no signal. Detecting truncation scored 13/14
with zero missed breakages, which is the useful half.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

MODEL = "@cf/meta/llama-3.1-8b-instruct"
_TIMEOUT = 20

_PROMPT = (
    "Ты проверяешь ОДНУ вещь: текст анекдота оборван или дописан до конца?\n"
    "Не оценивай юмор. Не обращай внимания на цифры, суммы, звёздочки, "
    "смайлики, опечатки и грубые слова - это НЕ обрыв.\n\n"
    "truncated=true только если текст физически обрывается: последнее "
    "предложение не закончено, вопрос задан но ответа нет, "
    "завязка есть но развязки нет.\n"
    "truncated=false если текст логически завершён, даже если он очень "
    "короткий, это каламбур, афоризм или одна строка.\n\n"
    "Примеры truncated=true:\n"
    '- "Приходит мужик к врачу и говорит: - Доктор, у меня"\n'
    '- "- Плакал ли я, когда слон разорвал мне спину? - Нет, вождь! '
    '- Так объясните же мне..."\n\n'
    "Примеры truncated=false:\n"
    '- "Муж: «Дорого?»" -> каламбур завершён\n'
    '- "Илон Маск запускает соцсеть - только буква X. Просто X. $44 млрд." '
    "-> завершено, цифры не мешают\n"
    '- "Вовочка: «Сколько будет 2+2 на математике?» Учитель: «...Вон из '
    'класса»." -> развязка есть\n\n'
    'Верни ТОЛЬКО JSON: {"truncated": true|false}'
)


def is_truncated(text: str, account_id: str, api_token: str) -> bool:
    """True when the model is confident the joke lost its ending.

    Returns False on any failure - a missing answer must never block
    publishing, the cheap filters still apply.
    """
    if not text or not account_id or not api_token:
        return False

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{MODEL}"
    payload = json.dumps({
        "messages": [
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": text[:1200]},
        ],
        "max_tokens": 30,
        "temperature": 0.0,
    }).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            body = json.load(response)
        content = body["result"]["choices"][0]["message"]["content"]
        start, end = content.find("{"), content.rfind("}")
        verdict = json.loads(content[start:end + 1])
        return bool(verdict.get("truncated"))
    except Exception:
        logger.warning("LLM truncation check unavailable, allowing joke", exc_info=True)
        return False
