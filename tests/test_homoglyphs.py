import unittest

from src.tg_autopost.content_filter import is_political
from src.tg_autopost.utils import build_hash, fold_homoglyphs, normalize_text


class FoldHomoglyphsTest(unittest.TestCase):
    def test_folds_latin_lookalikes_inside_cyrillic_word(self):
        # "Kaбинeт": K, a, e are Latin; the rest Cyrillic
        self.assertEqual(fold_homoglyphs("Kaбинeт"), "Кабинет")
        self.assertEqual(fold_homoglyphs("oкулиcтa"), "окулиста")
        self.assertEqual(fold_homoglyphs("Bижу"), "Вижу")
        self.assertEqual(fold_homoglyphs("нaxрeн"), "нахрен")

    def test_keeps_pure_latin_words_untouched(self):
        # Real Latin words must survive - they are not obfuscation.
        for word in ("Python", "Windows", "IT", "SMS", "BMW", "iPhone"):
            self.assertEqual(fold_homoglyphs(word), word)

    def test_keeps_standalone_non_russian_letter(self):
        # The eye-chart punchline "æ" is intentional, not a homoglyph attack.
        self.assertEqual(fold_homoglyphs("æ"), "æ")

    def test_mixed_sentence(self):
        src = "Программист пишет на Python в oфиce"
        self.assertEqual(fold_homoglyphs(src), "Программист пишет на Python в офисе")


class HomoglyphsDefeatFiltersTest(unittest.TestCase):
    """Homoglyphs used to bypass moderation entirely. After normalization the
    filters must see the real Cyrillic word."""

    def test_political_filter_catches_homoglyph_text(self):
        self.assertTrue(is_political(normalize_text("Шутка про украину")))
        self.assertTrue(is_political(normalize_text("Шутка про укрaину")))
        self.assertTrue(is_political(normalize_text("Анекдот где пyтин идет")))
        self.assertTrue(is_political(normalize_text("Разговор про пoлитика")))

    def test_rubric_keyword_matches_after_normalization(self):
        self.assertIn("работ", normalize_text("Начальник вызвал на рaботу").lower())


class DedupTest(unittest.TestCase):
    def test_same_joke_with_homoglyphs_has_same_hash(self):
        clean = "Кабинет окулиста. Какая буква?"
        homo = "Kaбинeт oкулиcтa. Kaкaя буквa?"
        self.assertEqual(build_hash(clean), build_hash(homo))


if __name__ == "__main__":
    unittest.main()
