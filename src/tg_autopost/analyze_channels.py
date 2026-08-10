"""Анализ частоты постинга каналов-конкурентов.

Парсит t.me/s/<channel> (без JS, как telegram_channel.py), считает посты
за сегодня/вчера/7 дней и выводит среднее в день. Запуск с VPN, т.к.
t.me/s блокируется в некоторых сетях:

    py -m src.tg_autopost.analyze_channels

Или с кастомным списком:
    py -m src.tg_autopost.analyze_channels --channels x0xotyh,anekdot_x

Вывод — таблица: канал, подписчики, сегодня, вчера, 7 дней, ср/день.
"""

import argparse
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup

# Каналы-конкуренты из бенчмарка 08.08 (наш канал @Anetdodik — для сравнения)
DEFAULT_CHANNELS = [
    "X0xoTyH",          # Хохотун — 2.6k подписчиков
    "anekdot_x",        # Anekdot X — 14.5k
    "baneksru",         # Анекдоты категории Б — 49.8k
    "platinum_aneks",   # Платиновые анекдоты — 119.5k
    "Anetdodik",        # Наш канал
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
}

_MSG_RE = re.compile(r"tgme_widget_message_wrap")
_DT_RE = re.compile(r"datetime=\"([^\"]+)\"")
_SUB_RE = re.compile(r"([\d\s.,]+)\s*([KkМм]?)\s*(?:subscriber|подписчик)")


def _parse_subscribers(soup) -> int:
    el = soup.select_one("div.tgme_channel_info_count")
    if not el:
        return 0
    m = _SUB_RE.search(el.get_text(" ", strip=True))
    if not m:
        return 0
    num_str = m.group(1).replace("\u00A0", "").replace(",", ".").replace(" ", "")
    num = float(num_str)
    suffix = m.group(2).lower()
    if suffix in ("k", "к"):
        num *= 1000
    elif suffix in ("m", "м"):
        num *= 1_000_000
    return int(num)


def _parse_post_dates(html: str):
    """Возвращает список date для каждого поста (по datetime атрибуту)."""
    dates = []
    for match in _MSG_RE.finditer(html):
        start = match.end()
        chunk = html[start : start + 1200]
        dtm = _DT_RE.search(chunk)
        if not dtm:
            continue
        try:
            ts = datetime.fromisoformat(dtm.group(1).replace("Z", "+00:00"))
            dates.append(ts.date())
        except ValueError:
            continue
    return dates


def analyze(channel: str, days: int = 7) -> dict:
    url = f"https://t.me/s/{channel}"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    subscribers = _parse_subscribers(soup)
    dates = _parse_post_dates(resp.text)
    today = date.today()
    cutoff = today - timedelta(days=days - 1)
    recent = [d for d in dates if d >= cutoff]
    by_day = Counter(d for d in recent)
    return {
        "channel": channel,
        "subscribers": subscribers,
        "today": by_day[today],
        "yesterday": by_day[today - timedelta(days=1)],
        "posts_7d": len(recent),
        "avg_per_day": round(len(recent) / days, 1),
        "days_with_posts": len(by_day),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Анализ частоты постинга конкурентов")
    parser.add_argument(
        "--channels",
        help="Список каналов через запятую (default: 5 известных)",
    )
    parser.add_argument("--days", type=int, default=7, help="Окно анализа (default 7)")
    args = parser.parse_args(argv)

    channels = args.channels.split(",") if args.channels else DEFAULT_CHANNELS

    print(f"{'Канал':<22}{'Подписчики':>12}{'Сегодня':>8}{'Вчера':>8}{'7дн':>6}{'ср/день':>9}")
    print("-" * 70)
    for ch in channels:
        try:
            r = analyze(ch.strip(), days=args.days)
            print(
                f"{r['channel']:<22}{r['subscribers']:>12,}{r['today']:>8}"
                f"{r['yesterday']:>8}{r['posts_7d']:>6}{r['avg_per_day']:>9}"
            )
        except requests.RequestException as e:
            print(f"{ch:<22} ERROR: {type(e).__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"{ch:<22} ERROR: {type(e).__name__}: {e}")

    print()
    print("Пояснение: t.me/s показывает ограниченное число постов (обычно 20).")
    print("Если канал постит >20 раз в день, цифры занижены — ср/день будет")
    print("ближе к числу постов, видимых в окне (обычно 10-20).")


if __name__ == "__main__":
    main()
