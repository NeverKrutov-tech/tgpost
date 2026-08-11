"""Фильтр рекламы в источниках: воронка «Продолжение: + VPN» должна
отбрасываться, а обычные анекдоты про впн/подписку — нет (на ложно-срабатывания).
"""
import unittest

from src.tg_autopost.sources.telegram_channel import AD_PHRASES as WEB_AD


def _is_ad(text: str, phrases) -> bool:
    low = text.lower()
    return any(p in low for p in phrases)


class AdVpnFunnelRejectedTest(unittest.TestCase):
    def test_repost_funnel_vpn_post_is_rejected(self):
        post = (
            "\U0001F4BC\n\n"
            "\u041F\u0440\u043E\u0434\u043E\u043B\u0436\u0435\u043D\u0438\u0435:\n"
            "\u0410\u043D\u0435\u043A\u0434\u043E\u0442\u044B | \u041F\u043E\u0434\u043F\u0438\u0441\u0430\u0442\u044C\u0441\u044F\n\n"
            "\U0001F420\n"
            "Skip VPN\n"
            "- \u0412\u041F\u041D \u043D\u043E\u0432\u043E\u0433\u043E \u043F\u043E\u043A\u043E\u043B\u0435\u043D\u0438\u044F. "
            "\u041E\u0431\u0445\u043E\u0434 \u0432\u0441\u0435\u0445 \u0431\u0435\u043B\u044B\u0445 \u0441\u043F\u0438\u0441\u043A\u043E\u0432.\n"
            "\u0412\u0441\u0435\u0433\u043E \u0437\u0430 99\u20BD \u0432 \u043C\u0435\u0441\u044F\u0446"
        )
        self.assertTrue(_is_ad(post, WEB_AD), "web source must reject the funnel")

    def test_continuation_header_alone_rejected(self):
        self.assertTrue(_is_ad("\u041F\u0440\u043E\u0434\u043E\u043B\u0436\u0435\u043D\u0438\u0435:", WEB_AD))

    def test_bare_vpn_word_is_not_enough_to_reject(self):
        # Решение: голое "впн"/"vpn" НЕ признак рекламы (ложные срабатывания на
        # шутках про VPN). Рекламная воронка всегда несёт специфичную фразу.
        self.assertFalse(_is_ad("Скачал впн и всё работает", WEB_AD))
        self.assertTrue(_is_ad("Skip VPN - обход всех белых списков", WEB_AD))

    def test_normal_joke_about_vpn_is_NOT_rejected(self):
        # Ложное срабатывание было бы бедой: юмор про VPN не является рекламой.
        joke = "- Ты как ВПН пользуешься?\n- А что это?\n- Ну, чтобы заблокированное открывать.\n- А, нет, у меня всё и так видно."
        # В этом тексте нет ни одной AD-фразы целиком (только слово "ВПН" внутри).
        self.assertFalse(_is_ad(joke, WEB_AD))

    def test_vpn_word_as_substring_does_not_false_positive_on_random_words(self):
        # "впн" не должен ловить обычные слова - проверяем, что фраза именно рекламная.
        self.assertFalse(_is_ad("Купил новые наушники, звук отличный", WEB_AD))


if __name__ == "__main__":
    unittest.main()
