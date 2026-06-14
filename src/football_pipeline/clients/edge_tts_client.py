from __future__ import annotations

import subprocess
from pathlib import Path

from ..config import Settings


class EdgeTtsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # You can change this to a male voice like 'en-US-ChristopherNeural' or 'en-GB-RyanNeural'
        self.voice = getattr(settings, "edge_tts_voice", "en-GB-RyanNeural")

    def create_voiceover(self, text: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # We use the edge-tts CLI module to generate the audio
        command = [
            "python", "-m", "edge_tts",
            "--text", text,
            "--write-media", str(output_path),
            "--voice", self.voice,
            "--rate", "+10%" # Speed it up slightly for better retention
        ]
        
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Edge TTS failed: {exc.stderr}") from exc
            
        return output_path
