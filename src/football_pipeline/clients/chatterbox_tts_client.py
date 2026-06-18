from __future__ import annotations

import json
from pathlib import Path

from ..config import Settings

class ChatterboxTtsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_voiceover(self, text: str, output_path: Path) -> Path:
        """Generate voiceover WAV and an empty .words.json to trigger fallback subtitle timing."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            import torchaudio as ta
            from chatterbox.tts import ChatterboxTTS
        except ImportError as exc:
            raise RuntimeError(
                "Chatterbox dependencies are missing. Ensure chatterbox-tts, torch, and torchaudio are installed."
            ) from exc

        # Initialize model in CPU mode for maximum compatibility across environments (e.g. GitHub Actions)
        print("  Loading Chatterbox TTS model... (This might take a minute)")
        model = ChatterboxTTS.from_pretrained(device="cpu")
        
        print("  Synthesizing audio with Chatterbox...")
        # Ensure output is a .wav since torchaudio typically saves as WAV
        wav_output_path = output_path.with_suffix('.wav')
        
        wav = model.generate(text)
        ta.save(str(wav_output_path), wav, model.sr)
        
        # Write an empty words.json. 
        # This will instruct moviepy_edit.py to automatically fallback and mathematically 
        # distribute subtitle timings evenly across the duration of the audio clip.
        words_path = wav_output_path.with_suffix('.words.json')
        words_path.write_text("[]", encoding='utf-8')
        
        print(f"  Chatterbox generation complete. Saved to {wav_output_path.name}")
        return wav_output_path
