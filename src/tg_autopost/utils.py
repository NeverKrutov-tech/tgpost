import hashlib
import re


WHITESPACE_RE = re.compile(r"\s+")
PUNCTUATION_RE = re.compile(r"[\u2010-\u2015]")
QUOTES_RE = re.compile(r"[\u00AB\u00BB\u2018\u2019\u201A\u201B\u201C\u201D\u201E]")
ALL_PUNCTUATION_RE = re.compile(r"[\u0021-\u002F\u003A-\u0040\u005B-\u0060\u007B-\u007E\u2010-\u2015\u2018-\u201D\u00AB\u00BB]")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = PUNCTUATION_RE.sub("-", text)
    text = QUOTES_RE.sub("\u0022", text)
    lines = text.split("\n")
    result = []
    prev_empty = False
    for line in lines:
        cleaned = WHITESPACE_RE.sub(" ", line).strip()
        if not cleaned:
            if not prev_empty:
                result.append("")
                prev_empty = True
        else:
            result.append(cleaned)
            prev_empty = False
    while result and not result[-1]:
        result.pop()
    return "\n".join(result)


def build_hash(text: str) -> str:
    normalized = normalize_text(text).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def dedup_key(text: str) -> str:
    result = ALL_PUNCTUATION_RE.sub(" ", text)
    result = WHITESPACE_RE.sub(" ", result).strip()
    result = result.lower()
    return result


# ponytail: source_views only compare inside one source (site jokes have 0),
# so ranking happens on the text itself. Weights come from what actually got
# views on the channel: dialogue and short story beats beat one-liners.
DIALOGUE_RE = re.compile(r"^\s*[-\u2014\u2013]\s*\S", re.M)
STALE_MARKERS = (
    "\u0448\u0442\u0438\u0440\u043b\u0438\u0446",       # Штирлиц
    "\u0432\u043e\u0432\u043e\u0447\u043a\u0430",       # Вовочка
    "\u043f\u043e\u0440\u0443\u0447\u0438\u043a \u0440\u0436\u0435\u0432\u0441\u043a",
    "\u043d\u043e\u0432\u044b\u0439 \u0440\u0443\u0441\u0441\u043a",
)
LOW_EFFORT_MARKERS = (
    "\u0440\u0436\u0430\u043a\u0430",
    "\u0443\u0433\u0430\u0440",
    "\u043f\u043e\u0434\u0431\u043e\u0440\u043a\u0430",
)


def quality_score(text: str) -> float:
    """Rank an unpublished joke: higher means more likely to land well.

    Deliberately cheap and explainable - no model, no network. Tuned against
    the channel's own top posts (long dialogue-driven stories outperformed
    short one-liners by roughly 4x in views).
    """
    if not text:
        return 0.0
    body = normalize_text(text)
    length = len(body)
    if length < 40:
        return 0.0

    score = 0.0

    # Sweet spot: long enough to build a scene, short enough to read in feed.
    if 150 <= length <= 700:
        score += 3.0
    elif 80 <= length < 150:
        score += 1.5
    elif length > 1200:
        score -= 1.0

    # Dialogue drives the channel's best-performing posts.
    turns = len(DIALOGUE_RE.findall(body))
    score += min(turns, 4) * 1.0

    # A punchline usually lands on its own final line.
    lines = [ln for ln in body.split("\n") if ln.strip()]
    if len(lines) >= 2 and len(lines[-1]) < 120:
        score += 1.0

    low = body.lower()
    # Heavy: these are the jokes everyone has heard a hundred times. Even a
    # well-built dialogue cannot save them, so the penalty has to outweigh it.
    if any(m in low for m in STALE_MARKERS):
        score -= 3.5
    if any(m in low for m in LOW_EFFORT_MARKERS):
        score -= 1.0

    # Emoji spam and SHOUTING read as low-effort reposts.
    if sum(1 for c in body if c in "\U0001F300\U0001F600\U0001F44D\U0001F525\u2764") > 3:
        score -= 1.0
    letters = [c for c in body if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.5:
        score -= 2.0

    return max(score, 0.0)
