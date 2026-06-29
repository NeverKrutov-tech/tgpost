LEVELS = [
    (0, "Новичок", ""),
    (5, "Писатель", "\u270F\uFE0F"),
    (15, "Юморист", "\U0001F604"),
    (30, "Комедиант", "\uD83C\uDFAD"),
    (50, "Легенда", "\U0001F451"),
]


def get_level(count: int) -> tuple[str, str]:
    label = LEVELS[0][1]
    emoji = LEVELS[0][2]
    threshold = 0
    for t, l, e in LEVELS:
        if count >= t:
            threshold = t
            label = l
            emoji = e
    return label, emoji
