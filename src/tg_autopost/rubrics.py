import datetime
import random
import re

# ponytail: plain "in" substring matching turned "который" into a false
# "кот" (animal) hit - real post: an Africa/tribal-chief joke got tagged
# #животные and prefaced "Мой питомец сегодня:". A left word-boundary fixes
# most of it ("лицензия" no longer matches "цен"), but a short stem that also
# opens an unrelated word still slips through, so those are listed here.
# Audited 08.08.2026 against common Russian words; only genuine mismatches
# are excluded - same-root hits ("раб" -> "работа") must keep matching.
_KEYWORD_EXCLUDE = {
    "кот": ("котор", "котлет"),
    "пап": ("папер", "папк"),
    "бар": ("барон", "барабан", "бармен", "барбекю", "бархат", "барыш"),
    "вин": ("винт", "виноват"),
    "дед": ("дедлайн",),
    "дет": ("детектив", "детал"),
    "лис": ("лист",),
    "мам": ("мамонт", "мамб"),
    "мыш": ("мышлен",),
    "муж": ("мужеств", "мужик", "мужчин"),
}


def _keyword_hits(text_lower: str, keyword: str) -> bool:
    kw = keyword.lower()
    excludes = _KEYWORD_EXCLUDE.get(kw, ())
    start = 0
    while True:
        idx = text_lower.find(kw, start)
        if idx == -1:
            return False
        at_word_start = idx == 0 or not text_lower[idx - 1].isalpha()
        if at_word_start and not any(text_lower.startswith(ex, idx) for ex in excludes):
            return True
        start = idx + 1


def _any_keyword_hits(text_lower: str, keywords: list[str]) -> bool:
    return any(_keyword_hits(text_lower, kw) for kw in keywords)


RUBRICS = [
    {
        "name": "Семейное",
        "emoji": "👨‍👩‍👧‍👦",
        "days": [0],
        "keywords": ["жен", "муж", "дет", "сын", "дочк", "тещ", "свекров",
                     "мам", "пап", "бабушк", "дедушк", "семь", "семейн",
                     "родител", "жена", "мужа", "брат", "сестр", "внук",
                     "зят", "невестк", "снох"],
    },
    {
        "name": "Рабочее",
        "emoji": "💼",
        "days": [1],
        "keywords": ["работ", "начальник", "офис", "шеф", "директор",
                     "коллег", "зарплат", "увол", "босс", "фирм", "компани",
                     "клиент", "сотрудник", "ваканс", "завод", "бухгалтер",
                     "менеджер", "программист", "собесед"],
    },
    {
        "name": "Животные",
        "emoji": "🐱",
        "days": [2],
        "keywords": ["кот", "кошк", "собак", "пёс", "попуга", "хомяк",
                     "лошад", "коров", "свин", "куриц", "петух", "медвед",
                     "волк", "лис", "зайц", "белк", "ёж", "мыш", "крыс",
                     "обезьян", "слон", "животн", "звер", "рыбк", "птиц"],
    },
    {
        "name": "Армейское",
        "emoji": "🎖️",
        "days": [3],
        "keywords": ["арми", "воен", "солдат", "офицер", "казарм",
                     "прапорщик", "генерал", "полковник", "майор", "сержант",
                     "дед", "дембель", "призыв", "служб", "танк", "войн",
                     "штаб", "устав", "наряд"],
    },
    {
        "name": "Чёрный юмор",
        "emoji": "💀",
        "days": [4],
        "keywords": ["умер", "смерт", "похорон", "гроб", "труп", "покойник",
                     "кладбищ", "кров", "уби", "мертв", "сдох", "погиб",
                     "катастроф", "авари", "могил", "ритуал"],
    },
    {
        "name": "Застольное",
        "emoji": "🍻",
        "days": [5],
        "keywords": ["пив", "водк", "выпив", "пьян", "алкогол", "бар",
                     "ресторан", "тост", "налив", "бутылк", "коньяк", "вин",
                     "самогон", "закуск", "гулянк", "праздник", "стол"],
    },
    {
        "name": "Жизненное",
        "emoji": "🤷",
        "days": [6],
        "keywords": [],
    },
]

HOLIDAYS = [
    (1, 1, "Новый год", "🎄"),
    (1, 14, "Старый Новый год", "🎉"),
    (2, 14, "День влюблённых", "❤️"),
    (2, 23, "День защитника", "🎖️"),
    (3, 8, "Женский день", "🌷"),
    (4, 1, "День смеха", "😂"),
    (5, 1, "Первое мая", "🎉"),
    (5, 9, "День Победы", "🏅"),
    (6, 1, "День детей", "🍭"),
    (6, 12, "День России", "🇷🇺"),
    (9, 1, "День знаний", "🎓"),
    (10, 5, "День учителя", "📚"),
    (10, 31, "Хэллоуин", "🎃"),
    (12, 31, "Новый год", "🎄"),
]

SEASONAL_KEYWORDS = {
    "зима": ["мороз", "снег", "лёд", "новый год", "ёлка", "санк"],
    "весна": ["весн", "солнц", "тепл", "капел", "март"],
    "лето": ["отпуск", "море", "жара", "пляж", "дача", "солнц", "отдых"],
    "осень": ["осен", "дожд", "слякот", "школ"],
}


def get_season_keywords() -> list[str]:
    month = datetime.datetime.today().month
    if month in (12, 1, 2):
        return SEASONAL_KEYWORDS["зима"]
    if month in (3, 4, 5):
        return SEASONAL_KEYWORDS["весна"]
    if month in (6, 7, 8):
        return SEASONAL_KEYWORDS["лето"]
    return SEASONAL_KEYWORDS["осень"]

# ponytail: a preamble that asserts a scene ("Я в лифте с начальником:")
# needs the joke to actually contain that scene, and keyword overlap only
# proves the topic. Audit 08.08.2026: ~40% of posts got a preamble and most
# contradicted the text under them - "Я в семейном чате:" over a joke about
# a keyboard typo, "Кот говорит:" where no cat speaks. Three rounds of
# tightening the keyword rules still left ~9 of 12 mismatched, because no
# keyword rule can verify a scene.
# So only neutral topic labels survive: they restate the subject rather than
# invent a setting, which keyword matching *can* guarantee.
PREAMBLES = [
    (["жен", "муж", "дет", "дочк", "тещ", "свекров", "семь"], [
        "Семейное, наболевшее:",
        "Что никогда не меняется:",
    ]),
    (["работ", "начальник", "офис", "шеф", "директор", "коллег", "увол", "босс", "собесед"], [
        "Рабочие будни:",
        "Про работу без прикрас:",
    ]),
    (["кот", "кошк", "собак", "пёс", "попуга", "хомяк", "животн", "звер"], [
        "Животные — это вам не шутки:",
        "Про братьев наших меньших:",
    ]),
    (["арми", "воен", "солдат", "офицер", "казарм", "дембель", "призыв", "служб"], [
        "Армейское:",
        "Что никогда не меняется:",
    ]),
    (["умер", "смерт", "похорон", "гроб", "труп", "покойник", "погиб"], [
        "Ненормальное, но жизненное:",
    ]),
    (["пив", "водк", "выпив", "пьян", "алкогол", "бар", "тост", "бутылк", "самогон", "рюмк", "стопк"], [
        "За жизнь! Хотя бывает и такое:",
        "Застольное:",
    ]),
    (["любов", "свидан", "девушк", "парн", "ромаш", "целова", "свадьб"], [
        "Любовь — это:",
        "Про отношения:",
    ]),
    (["врач", "больниц", "доктор", "медик", "лекар"], [
        "Медицинское:",
    ]),
    (["машин", "автомобил", "тачк", "водител", "гаи", "дпс"], [
        "Про авто без купюр:",
        "Дорожное:",
    ]),
    (["школ", "учител", "урок", "студент", "экзамен", "ученик"], [
        "Что не так с образованием:",
        "Школьное:",
    ]),
    (["деньг", "цен", "миллионер", "богат", "бедн", "финанс"], [
        "Про деньги:",
    ]),
    (["компьютер", "интернет", "телефон", "гаджет", "айфон", "ноутбук"], [
        "Технологии будущего по-русски:",
        "Цифровое:",
    ]),
]

EMOJI_PATTERNS = [
    (re.compile(r"\b(жен|муж|дет|сын|доч|тещ|свекров|мам|пап|бабк|дед|семь)\b", re.I), "👨‍👩‍👧‍👦"),
    (re.compile(r"\b(работ|начальник|офис|шеф|директор|зарплат|увол|босс)\b", re.I), "💼"),
    (re.compile(r"\b(кот|кошк|собак|пёс|попуга|хомяк|животн|звер|лошад|коров)\b", re.I), "🐱"),
    (re.compile(r"\b(арми|воен|солдат|офицер|служб)\b", re.I), "🎖️"),
    (re.compile(r"\b(умер|смерт|похорон|гроб|труп|покойник|кладбищ|кров|уби|погиб)\b", re.I), "💀"),
    (re.compile(r"\b(пив|водк|выпив|пьян|алкогол|бар|тост|налив|бутылк)\b", re.I), "🍻"),
    (re.compile(r"\b(врач|больниц|доктор|медик|лекар|хирург)\b", re.I), "🏥"),
    (re.compile(r"\b(деньг|цен|коп|миллионер|богат|бедн|финанс)\b", re.I), "💰"),
    (re.compile(r"\b(любов|свидан|девушк|парн|ромаш|целова|свадьб|невест)\b", re.I), "❤️"),
    (re.compile(r"\b(компьютер|интернет|телефон|гаджет|айфон|ноутбук)\b", re.I), "📱"),
    (re.compile(r"\b(машин|автомобил|тачк|водител|гаи|дпс)\b", re.I), "🚗"),
    (re.compile(r"\b(школ|учител|урок|студент|экзамен|ученик|класс)\b", re.I), "🎓"),
    (re.compile(r"\b(полиц|мент|милиц)\b", re.I), "🚔"),
    (re.compile(r"\b(спорт|футбол|хоккей|тренер|олимпиад|матч)\b", re.I), "⚽"),
    (re.compile(r"\b(путин|депутат|президент|правительств|госдум|выбор)\b", re.I), "🏛️"),
]


def get_today_rubric() -> dict:
    today = datetime.datetime.today()
    md = (today.month, today.day)
    for month, day, name, emoji in HOLIDAYS:
        if (month, day) == md:
            return {"name": name, "emoji": emoji, "keywords": get_season_keywords()}
    dow = today.weekday()
    for rubric in RUBRICS:
        if dow in rubric["days"]:
            result = dict(rubric)
            result["keywords"] = rubric["keywords"] + get_season_keywords()
            return result
    return RUBRICS[-1]


def classify_emoji(text: str) -> str:
    seen = []
    for pattern, emoji in EMOJI_PATTERNS:
        if pattern.search(text):
            if emoji not in seen:
                seen.append(emoji)
    return " ".join(seen)


def matches_rubric(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    lower = text.lower()
    return _any_keyword_hits(lower, keywords)


def get_preamble(text: str) -> str:
    """Neutral topic label for a joke, or "" when the topic is unclear.

    See the PREAMBLES comment: scene-asserting headers were removed because
    keyword matching cannot verify a scene. What is left only restates the
    subject, so a keyword hit is enough to make it true - no first-person or
    dialogue gating needed.
    """
    body = text.strip()
    if not body:
        return ""
    lower = body.lower()
    for keywords, options in PREAMBLES:
        if _any_keyword_hits(lower, keywords):
            return random.choice(options)
    return ""


KEYWORD_HASHTAGS = [
    (["жен", "муж", "дет", "сын", "доч", "тещ", "свекров", "семь", "мам", "пап", "бабушк"], "#семья"),
    (["работ", "офис", "шеф", "директор", "коллег", "зарплат", "увол", "босс", "собесед"], "#рабочее"),
    (["кот", "кошк", "собак", "пёс", "попуга", "хомяк", "животн", "звер"], "#животные"),
    (["арми", "воен", "солдат", "офицер", "казарм", "дембель", "призыв", "служб"], "#армия"),
    (["умер", "смерт", "похорон", "гроб", "труп", "покойник", "погиб"], "#черныйюмор"),
    (["пив", "водк", "выпив", "пьян", "алкогол", "бар", "тост", "самогон"], "#застолье"),
    (["школ", "учител", "урок", "студент", "экзамен", "ученик"], "#школа"),
    (["любов", "свидан", "девушк", "парн", "целова", "свадьб"], "#любовь"),
    (["врач", "больниц", "доктор", "медик", "лекар"], "#медицина"),
    (["машин", "автомобил", "водител", "гаи", "дпс"], "#авто"),
    (["деньг", "цен", "миллионер", "богат", "бедн"], "#деньги"),
    (["компьютер", "интернет", "телефон", "гаджет", "айфон"], "#технологии"),
    (["спорт", "футбол", "хоккей", "тренер", "матч"], "#спорт"),
    (["путин", "депутат", "политик", "правительств"], "#политика"),
]


def get_hashtags(text: str) -> str:
    lower = text.lower()
    found = []
    for keywords, hashtag in KEYWORD_HASHTAGS:
        if _any_keyword_hits(lower, keywords):
            if hashtag not in found:
                found.append(hashtag)
    if not found:
        return "#анекдот #юмор"
    return " ".join(found)


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def is_jubilee(post_number: int) -> str:
    if post_number == 1:
        return ""
    if post_number % 100 == 0:
        return "\n\n\U0001F389 Юбилей! Это уже {} выпуск! Спасибо, что читаете! ❤️".format(post_number)
    if post_number % 50 == 0:
        return "\n\n\U0001F389 Уже {} выпусков! Спасибо, что вы с нами! ❤️".format(post_number)
    return ""
