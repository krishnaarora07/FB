from __future__ import annotations

from pathlib import Path

from ..config import Settings

try:
    from gtts import gTTS
except ImportError:
    pass


class GTTSClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_voiceover(self, text: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Use Google Text-to-Speech (gTTS)
        tts = gTTS(text=text, lang='en', tld='co.uk', slow=False)
        tts.save(str(output_path))
            
        return output_path
