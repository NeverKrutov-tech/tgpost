"""Render army joke with per-scene TTS sync."""
import sys, logging, os
from pathlib import Path
sys.path.insert(0, "src")
logging.basicConfig(level=logging.INFO)

from dotenv import load_dotenv
load_dotenv()

from tg_autopost.shorts_maker import render_short

joke = """Встречаются два друга:
— Слышал, ты в армию идёшь?
— Да, повестку принесли.
— А ты не бойся, там сейчас не как раньше.
— А что, кормить стали лучше?
— Ну, кормят раз в день. Зато вовремя.
— Это когда?
— В шесть утра. Причём независимо от того, который час.

Проходит месяц. Звонит друг:
— Ну как там в армии?
— Отлично! Научился спать с открытыми глазами, бегать строевым шагом во сне и есть ложкой, не просыпаясь.
— А что, кормят так же?
— Нет, теперь кормят два раза в день. Но кормёжка через день."""

print("Result:", render_short(joke, "army_joke_short.mp4", kie_api_key=os.getenv("KIE_API_KEY", "")))
