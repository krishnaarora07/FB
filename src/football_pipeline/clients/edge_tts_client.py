from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ..config import Settings


class EdgeTtsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.voice = getattr(settings, "edge_tts_voice", "en-GB-RyanNeural")

    def create_voiceover(self, text: str, output_path: Path) -> Path:
        """Generate voiceover MP3 and a matching .words.json with millisecond timestamps."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError(
                "edge-tts is not installed. Run: pip install edge-tts"
            ) from exc

        words_path = output_path.with_suffix('.words.json')

        async def _generate() -> list[dict]:
            communicate = edge_tts.Communicate(text, self.voice, rate='+10%')
            words: list[dict] = []
            audio_chunks: list[bytes] = []
            async for chunk in communicate.stream():
                if chunk['type'] == 'audio':
                    audio_chunks.append(chunk['data'])
                elif chunk['type'] == 'WordBoundary':
                    words.append({
                        'text': chunk['text'],
                        'offset': chunk['offset'],
                        'duration': chunk['duration'],
                    })
            output_path.write_bytes(b''.join(audio_chunks))
            return words

        words = asyncio.run(_generate())

        if not words:
            print("  WARNING: edge-tts returned zero word boundaries. Captions will be empty.")
        else:
            print(f"  Got {len(words)} word boundaries from edge-tts.")

        words_path.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding='utf-8')

        return output_path
