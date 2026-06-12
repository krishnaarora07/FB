from __future__ import annotations

from pathlib import Path

from ..config import Settings
from ..http import request_bytes


class ElevenLabsClient:
    BASE_URL = "https://api.elevenlabs.io/v1"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.api_key = settings.require(settings.elevenlabs_api_key, "ELEVENLABS_API_KEY")

    def create_voiceover(self, text: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        audio = request_bytes(
            "POST",
            f"{self.BASE_URL}/text-to-speech/{self.settings.elevenlabs_voice_id}",
            params={"output_format": self.settings.elevenlabs_output_format},
            headers={
                "xi-api-key": self.api_key,
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
            },
            body={
                "text": text,
                "model_id": self.settings.elevenlabs_model_id,
                "voice_settings": {
                    "stability": 0.42,
                    "similarity_boost": 0.78,
                    "style": 0.35,
                    "use_speaker_boost": True,
                },
            },
        )
        output_path.write_bytes(audio)
        return output_path

