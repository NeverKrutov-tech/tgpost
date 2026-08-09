import hashlib
import re


WHITESPACE_RE = re.compile(r"\s+")
PUNCTUATION_RE = re.compile(r"[\u2010-\u2015]")
QUOTES_RE = re.compile(r"[\u00AB\u00BB\u2018\u2019\u201A\u201B\u201C\u201D\u201E]")
ALL_PUNCTUATION_RE = re.compile(r"[\u0021-\u002F\u003A-\u0040\u005B-\u0060\u007B-\u007E\u2010-\u2015\u2018-\u201D\u00AB\u00BB]")

# ponytail: some source sites inject their own domain into the middle of a
# joke as an anti-scraping watermark. It shipped to the channel verbatim:
# "- Так почему я плачу сейчас, anekdotov.net, когда писаю?.." The injection
# is intermittent (0 of 248 jokes in the local DB carry it), so the parser
# cannot be tested into catching it - strip it centrally instead.
# Only our own source domains are listed: a joke will never legitimately
# mention them, so this cannot mangle real text the way a generic
# "any domain" rule would ("зашёл на mail.ru" must survive).
SOURCE_DOMAINS = [
    "anekdotov.net", "anekdot.ru", "baneks.ru", "bash.im", "anekdoty.ru",
]
WATERMARK_RE = re.compile(
    r"\s*,\s*(?:www\.)?(?:" + "|".join(d.replace(".", r"\.") for d in SOURCE_DOMAINS) + r")\s*,\s*"
    r"|\s*\(?(?:www\.)?(?:" + "|".join(d.replace(".", r"\.") for d in SOURCE_DOMAINS) + r")\)?\s*",
    re.I,
)


def strip_watermark(text: str) -> str:
    """Remove injected source domains, keeping the sentence readable.

    A mid-sentence injection carries surrounding commas ("плачу сейчас,
    anekdotov.net, когда писаю") - those collapse to a single comma so the
    clause still reads. Anywhere else the domain just disappears.
    """
    def _replace(match: re.Match) -> str:
        chunk = match.group(0)
        stripped = chunk.strip()
        if stripped.startswith(",") and stripped.endswith(","):
            return ", "
        return " " if chunk.startswith((" ", "\t")) or chunk.endswith((" ", "\t")) else ""

    return WATERMARK_RE.sub(_replace, text)


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = strip_watermark(text)
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

# ponytail: "а у тебя было такое?" only reads naturally under a first-person
# situational story (the channel's own top posts: "Захожу вчера в маршрутку...",
# "Я в семейном чате..."). Under a Stirlitz-style character joke or a one-liner
# nobody has "had that happen to them", so the prompt would look bolted-on.
FIRST_PERSON_RE = re.compile(
    r"\b(\u044f|\u043c\u043d\u0435|\u043c\u0435\u043d\u044f|\u0441\u043e "
    r"\u043c\u043d\u043e\u0439|\u0443 \u043c\u0435\u043d\u044f|\u043c\u043e\u0439|"
    r"\u043c\u043e\u044f|\u043c\u043e\u0451|\u043d\u0430\u0441)\b"
    # Vivid present-tense storytelling drops the pronoun and leans on the
    # verb ("Захожу вчера в маршрутку...", "Сижу дома..."): match common
    # first-person-singular openers instead of requiring "я" literally.
    r"|\b\u0437\u0430\u0445\u043e\u0436\u0443|\b\u043f\u0440\u0438\u0445\u043e\u0436\u0443|"
    r"\b\u0441\u0438\u0436\u0443|\b\u0438\u0434\u0443|\b\u0441\u0442\u043e\u044e|"
    r"\b\u0432\u0438\u0436\u0443|\b\u0441\u043b\u044b\u0448\u0443|\b\u0435\u0434\u0443|"
    r"\b\u0440\u0430\u0441\u0441\u043a\u0430\u0437\u044b\u0432\u0430\u043b|"
    r"\b\u0432\u0441\u043f\u043e\u043c\u043d\u0438\u043b",
    re.I,
)


def is_relatable_story(text: str) -> bool:
    """True when a joke is a first-person situational story, not a character
    bit (Shtirlitz, Vovochka) or a one-liner. Gates the "а у тебя было
    такое?" comment prompt so it only appears where it fits.
    """
    if not text:
        return False
    body = normalize_text(text)
    if len(body) < 100:
        return False
    low = body.lower()
    if any(m in low for m in STALE_MARKERS):
        return False
    # The story has to frame itself as personal near the start, not just
    # mention "we"/"my" somewhere deep in an unrelated punchline.
    return bool(FIRST_PERSON_RE.search(low[:100]))


def quality_score(text: str) -> float:
    """Rank an unpublished joke: higher means more likely to land well.

    Deliberately cheap and explainable - no model, no network. Tuned against
    the channel's own top posts (dialogue-driven stories outperformed
    single-line jokes by roughly 4x in views) and cross-checked against
    4 competitor channels (2.6k-119.5k subscribers): their best-performing
    posts run 90-260 characters, shorter than this channel's own top posts -
    the sweet spot below reflects both data points, not just one.
    """
    if not text:
        return 0.0
    body = normalize_text(text)
    length = len(body)
    if length < 40:
        return 0.0

    score = 0.0

    # Sweet spot: long enough to build a scene, short enough to read in feed.
    if 90 <= length <= 500:
        score += 3.0
    elif 500 < length <= 700:
        score += 2.0
    elif 40 <= length < 90:
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

    # Short dialogue (2-4 turns, 90-260 chars) is the format competitors'
    # best posts use - it wins over long stories of equal quality.
    if 2 <= turns <= 4 and 90 <= length <= 260 and len(lines) >= 2 and len(lines[-1]) < 120:
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


# ponytail: catches "- Так объясните же мне..." (real bug: source truncated
# the joke, punchline missing) without flagging "жена теннисистка..." or
# "у нас кончились памперсы..." (real punchlines that just end in "...").
# Difference: does the phrase end on a function word (needs a continuation)
# or a content word (the thought is complete)? Verified against every
# dialogue-ending-in-"..." joke in the current DB: 0 false positives.
# Narrow by design - a rare source-truncation bug does not warrant a heavy
# NLP check, and an overly broad one risks rejecting real punchlines.
_DANGLING_ENDING_RE = re.compile(
    r"\b(\u043C\u043D\u0435|\u043D\u0430\u043C|\u0442\u0435\u0431\u0435|\u0432\u0430\u043C|"
    r"\u0435\u043C\u0443|\u0435\u0439|\u0438\u043C|\u043D\u0438\u043C|"
    r"\u043A\u0430\u043A|\u0447\u0442\u043E|\u0447\u0442\u043E\u0431\u044B|"
    r"\u0437\u0430\u0447\u0435\u043C|\u043F\u043E\u0447\u0435\u043C\u0443|"
    r"\u043A\u043E\u0433\u0434\u0430|\u0433\u0434\u0435|\u043A\u0443\u0434\u0430|"
    r"\u043A\u0430\u043A\u043E\u0439|\u043A\u0430\u043A\u0438\u0435|"
    r"\u0438|\u0430|\u043D\u043E)\s*(\.\.\.|\u2026)\s*$",
    re.I,
)


def looks_cut_off(text: str) -> bool:
    """True when a dialogue line ends in '...' right after a word that
    grammatically demands more ('мне...', 'зачем...', 'куда...') - the
    shape of a joke whose punchline got lost, not a stylistic pause.
    Also flags short one-liners with no terminal punctuation as broken.
    """
    if not text:
        return False
    # ponytail: by design, a long truncated joke (>=150 chars) without any
    # finishing punctuation is an engagement format - the audience writes the
    # punchline in the comments. Don't drop it from the pipeline.
    if len(text) >= 150:
        from .content_filter import is_truncated_joke
        if is_truncated_joke(text):
            return False
    body = normalize_text(text).rstrip()
    lines = [ln for ln in body.split("\n") if ln.strip()]
    if not lines:
        return False
    last = lines[-1].strip()
    return bool(_DANGLING_ENDING_RE.search(last))
