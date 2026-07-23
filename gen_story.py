import sys, logging
logging.basicConfig(level=logging.INFO)
sys.path.insert(0, "src")
from tg_autopost.image_gen import generate_story_image

text = "Муж жене: Дорогая, я сегодня задержусь на работе. Жена: Хорошо, я пока покормлю кота твоим ужином."
path = generate_story_image(text, "Anetdodik")
print("Story image saved:", path)
