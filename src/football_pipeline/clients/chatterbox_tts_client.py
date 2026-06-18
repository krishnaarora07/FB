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
            import whisper_timestamped as whisper
        except ImportError as exc:
            raise RuntimeError(
                "Dependencies missing. Ensure chatterbox-tts, torch, torchaudio, and whisper-timestamped are installed."
            ) from exc

        # Initialize model in CPU mode for maximum compatibility across environments (e.g. GitHub Actions)
        print("  Loading Chatterbox TTS model... (This might take a minute)")
        model = ChatterboxTTS.from_pretrained(device="cpu")
        
        print("  Synthesizing audio with Chatterbox...")
        # Ensure output is a .wav since torchaudio typically saves as WAV
        wav_output_path = output_path.with_suffix('.wav')
        
        wav = model.generate(text)
        ta.save(str(wav_output_path), wav, model.sr)
        print(f"  Chatterbox generation complete. Saved to {wav_output_path.name}")
        
        # ---------------------------------------------------------
        # Whisper Forced Alignment for Subtitle Sync
        # ---------------------------------------------------------
        print("  Running Whisper AI to map perfect word-level timestamps...")
        
        whisper_model = whisper.load_model("base", device="cpu")
        audio = whisper.load_audio(str(wav_output_path))
        
        # Transcribe the audio we just generated to get the exact start/end times
        result = whisper.transcribe(whisper_model, audio, language="en")
        
        words_data = []
        # Convert Whisper's floating point seconds to Edge-TTS 100-nanosecond format
        for segment in result.get("segments", []):
            for w in segment.get("words", []):
                start_s = w["start"]
                end_s = w["end"]
                
                offset_100ns = int(start_s * 10_000_000)
                duration_100ns = int((end_s - start_s) * 10_000_000)
                
                words_data.append({
                    "text": w["text"],
                    "offset": offset_100ns,
                    "duration": duration_100ns
                })
        
        words_path = wav_output_path.with_suffix('.words.json')
        words_path.write_text(json.dumps(words_data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"  Whisper alignment complete. Mapped {len(words_data)} words.")
        
        return wav_output_path
