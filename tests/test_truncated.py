import unittest

from src.tg_autopost.content_filter import is_truncated_joke, looks_cut_off


TRUNCATED = (
    "Шерлок Холмс и доктор Ватсон летят на воздушном шаре. "
    "Вдруг поднимается сильный ветер, и они теряют ориентацию. "
    "Когда ветер стихает, они понимают, что застряли на вершине высокой башни. "
    'Холмс говорит: "Watson, мы должны выбраться отсюда!\n'
    "И вот однажды случается, что опоры моста роняют машину с полицейским в воду"
)

COMPLETE_DIALOGUE = (
    "- Вчера мой кот сломал вазу.\n"
    "- И что ты сделал?\n"
    "- Подарил ему новую"
)

COMPLETE_STORY = "Жил-был мужик. Он работал, ел, спал. И умер. Конец."

ONE_LINER = "Жизнь коротка."


class TestTruncated(unittest.TestCase):
    def test_truncated_joke_detected(self):
        self.assertTrue(is_truncated_joke(TRUNCATED))

    def test_complete_dialogue_not_truncated(self):
        self.assertFalse(is_truncated_joke(COMPLETE_DIALOGUE))

    def test_complete_story_not_truncated(self):
        self.assertFalse(is_truncated_joke(COMPLETE_STORY))

    def test_one_liner_not_truncated(self):
        self.assertFalse(is_truncated_joke(ONE_LINER))

    def test_truncated_joke_passes_looks_cut_off(self):
        self.assertFalse(looks_cut_off(TRUNCATED))


if __name__ == "__main__":
    unittest.main()
