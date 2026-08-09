import unittest

from src.tg_autopost.utils import quality_score

SHORT_DIALOGUE = "Муж звонит жене:\n- Дорогая, я в баре.\n- И что?\n- Я не знаю, зачем я здесь."

LONG_STORY = ("Жил-был мужик " * 40) + "\nИ тут пришла бабка."

ONE_LINER = "Жизнь слишком коротка, чтобы пить плохое вино."


class TestQualityScore(unittest.TestCase):
    def test_short_dialogue_beats_similar_long_story(self):
        self.assertGreater(quality_score(SHORT_DIALOGUE), quality_score(LONG_STORY))

    def test_short_dialogue_beats_one_liner(self):
        self.assertGreater(quality_score(SHORT_DIALOGUE), quality_score(ONE_LINER))


if __name__ == "__main__":
    unittest.main()
