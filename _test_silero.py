import torch
import soundfile as sf
import os
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'

language = 'ru'
model_id = 'v4_ru'
speaker = 'baya'

print('Downloading Silero model...')
model, _ = torch.hub.load(repo_or_dir='snakers4/silero-models', model='silero_tts',
                          language=language, speaker=model_id)
model.to('cpu')
print('Model loaded')

text = 'Здравствуйте! Это тестовый голос Силеро. Анекдот дня.'
audio = model.apply_tts(text=text, speaker=speaker, sample_rate=48000)

path = 'data/silero_test.wav'
sf.write(path, audio, 48000)
print(f'Saved: {os.path.getsize(path)} bytes')
