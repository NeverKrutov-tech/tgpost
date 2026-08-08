import re

# ponytail: the channel is literally "Анекдодик 18+" and one of its sources is
# a crude-humour channel, so raunchy jokes are the genre, not a defect. The
# old list blocked all of it (6% of the DB) and, being a plain substring
# match, also killed innocent jokes: "гей" matched Гейзенберг and геймер,
# "грудь" matched a joke about silicone women with nothing explicit in it.
# What stays here is only what would actually harm the channel: explicit
# pornography, slurs, and content that gets a channel restricted or a
# YouTube Short taken down.
HARD_BLOCK_KEYWORDS = [
    "\u043f\u043e\u0440\u043d\u043e", "\u043f\u043e\u0440\u043d\u0443\u0445",
    "\u043f\u043e\u0440\u043d\u043e\u0433\u0440\u0430\u0444",
    "\u043f\u0435\u0434\u043e\u0444\u0438\u043b", "\u0438\u0437\u043d\u0430\u0441\u0438\u043b",
    "\u0437\u043e\u043e\u0444\u0438\u043b", "\u0438\u043d\u0446\u0435\u0441\u0442",
    "\u043c\u0430\u043b\u043e\u043b\u0435\u0442\u043a",
    "\u043f\u0440\u043e\u0441\u0442\u0438\u0442\u0443\u0442",
    "\u0448\u043b\u044e\u0445",
    "\u043f\u0438\u0434\u043e\u0440", "\u043f\u0438\u0434\u0430\u0440",
    "\u043f\u0435\u0434\u0438\u043a",
    "\u0436\u0438\u0434\u043e\u0432", "\u043d\u0435\u0433\u0440\u0438\u0442\u043e\u0441",
    "\u0447\u0443\u0440\u043a", "\u0445\u0430\u0447\u0438",
]

# Whole-word only: these are short enough to hide inside ordinary words.
HARD_BLOCK_EXACT = [
    "\u0433\u0435\u0439", "\u0433\u0435\u0438",
]

_ADULT_RE = re.compile(
    r"(?<![\u0430-\u044F\u0451a-z])(" + "|".join(HARD_BLOCK_KEYWORDS) + r")"
    r"|(?<![\u0430-\u044F\u0451a-z])(" + "|".join(HARD_BLOCK_EXACT)
    + r")(?![\u0430-\u044F\u0451a-z])",
    re.I,
)

POLITICAL_KEYWORDS = [
    "\u0443\u043A\u0440\u0430\u0438\u043D",
    "\u043A\u0438\u0435\u0432",
    "\u0437\u0435\u043B\u0435\u043D\u0441\u043A", "\u0437\u0430\u043B\u0443\u0436\u043D",
    "\u043F\u0443\u0442\u0438\u043D",
    "\u0431\u0430\u0439\u0434\u0435\u043D",
    "\u0442\u0440\u0430\u043C\u043F",
    "\u043D\u0430\u0432\u0430\u043B\u044C\u043D",
    "\u0432\u043E\u0439\u043D",
    "\u0432\u043E\u0435\u043D\u043D\u044B\u0439 \u043A\u043E\u043D\u0444\u043B\u0438\u043A\u0442",
    "\u0441\u0430\u043D\u043A\u0446\u0438",
    "\u0441\u043F\u0435\u0446\u043E\u043F\u0435\u0440\u0430\u0446\u0438",
    "\u043C\u043E\u0431\u0438\u043B\u0438\u0437",
    "\u043F\u043E\u043B\u0438\u0442\u0438\u043A", "\u043F\u043E\u043B\u0438\u0442\u0438\u0447",
    "\u0432\u043B\u0430\u0441\u0442\u044C", "\u0432\u043B\u0430\u0441\u0442\u0438",
    "\u043F\u0440\u0435\u0437\u0438\u0434\u0435\u043D\u0442",
    "\u0434\u0435\u043F\u0443\u0442\u0430\u0442",
    "\u0433\u043E\u0441\u0443\u0434\u0430\u0440\u0441\u0442\u0432",
    "\u0440\u0435\u0436\u0438\u043C\u0430", "\u0434\u0438\u043A\u0442\u0430\u0442\u0443\u0440",
    "\u0434\u043E\u043D\u0431\u0430\u0441\u0441",
    "\u043B\u0443\u0433\u0430\u043D\u0441\u043A",
    "\u043B\u043D\u0440", "\u0434\u043D\u0440",
    "\u043D\u0430\u0446\u0438\u0441\u0442",
    "\u0444\u0430\u0448\u0438\u0441\u0442",
    "\u0431\u0430\u043D\u0434\u0435\u0440\u043E\u0432\u0446", "\u0431\u0430\u043D\u0434\u0435\u0440\u0430",
    "\u0445\u043E\u043B\u043E\u043A\u043E\u0441\u0442",
    "\u0448\u043E\u0439\u0433\u0443", "\u043C\u0438\u043D\u043E\u0431\u043E\u0440\u043E\u043D",
    "\u043A\u0440\u0435\u043C\u043B",
    "\u0432\u044B\u0431\u043E\u0440\u044B", "\u0432\u044B\u0431\u043E\u0440\u0430\u0445",
    "\u0432\u044B\u0431\u043E\u0440\u043E\u0432", "\u0433\u043E\u043B\u043E\u0441\u043E\u0432\u0430",
    "\u0441\u0442\u0430\u043B\u0438\u043D",
]

# Abbreviations need a boundary on *both* sides: "сво" as a prefix rule would
# swallow "свой"/"своё"/"по-своему", which is exactly the bug this replaced.
POLITICAL_ABBREVIATIONS = [
    "\u0441\u0432\u043E", "\u043B\u043D\u0440", "\u0434\u043D\u0440",
    "\u043D\u0430\u0442\u043E",
]

# ponytail: matched as whole words, not substrings. The old plain-substring
# check flagged every joke containing "свой"/"своё"/"по-своему" because the
# abbreviation "сво" was in the list - ordinary jokes were being dropped as
# political. Word-boundary matching keeps the abbreviation usable and lets
# stems ("полит", "украин") still cover inflected forms.
_POLITICAL_RE = re.compile(
    r"(?<![\u0430-\u044F\u0451a-z])(" + "|".join(POLITICAL_KEYWORDS) + r")"
    r"|(?<![\u0430-\u044F\u0451a-z])(" + "|".join(POLITICAL_ABBREVIATIONS)
    + r")(?![\u0430-\u044F\u0451a-z])",
    re.I,
)


def is_political(text: str) -> bool:
    return bool(_POLITICAL_RE.search(text))


def is_adult(text: str) -> bool:
    return bool(_ADULT_RE.search(text))


def is_flagged(text: str) -> bool:
    return is_political(text) or is_adult(text)
