import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))

from football_pipeline.clients.chatterbox_tts_client import ChatterboxTtsClient

class MockSettings:
    pass

def test_chatterbox():
    settings = MockSettings()
    client = ChatterboxTtsClient(settings)
    
    text = "Hello world, this is a test of the new Chatterbox AI voice model."
    output_path = repo_root / "caption_test" / "test_voiceover.wav"
    
    # We expect a WAV file and a .words.json file
    res_path = client.create_voiceover(text, output_path)
    print(f"Generated: {res_path}")

if __name__ == "__main__":
    test_chatterbox()
