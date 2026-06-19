import json
from pathlib import Path
from src.football_pipeline.moviepy_edit import _words_to_ass

words = [
  {"text": "Hello", "offset": 10000000, "duration": 5000000}
]
words_json = Path('test.words.json')
words_json.write_text(json.dumps(words), encoding='utf-8')

ass_path = Path('test.ass')
_words_to_ass(words_json, ass_path)
print(ass_path.read_text(encoding='utf-8'))
