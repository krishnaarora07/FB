from __future__ import annotations

import json
from pathlib import Path
import modal

from src.football_pipeline.config import Settings

class FishSpeechClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_voiceover(self, text: str, output_path: Path, ref_audio_bytes: bytes = None, ref_text: str = None) -> Path:
        """Generate voiceover WAV via Modal and an empty .words.json to trigger fallback subtitle timing."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            import whisper_timestamped as whisper
        except ImportError as exc:
            raise RuntimeError(
                "Dependencies missing. Ensure whisper-timestamped is installed."
            ) from exc

        if ref_audio_bytes:
            print("  Auto-transcribing reference audio to ensure perfect voice cloning sync...")
            import tempfile
            import os
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                tf.write(ref_audio_bytes)
                tf_path = tf.name
            
            whisper_model = whisper.load_model("base", device="cpu")
            ref_audio_data = whisper.load_audio(tf_path)
            ref_result = whisper.transcribe(whisper_model, ref_audio_data, language="en")
            ref_text = ref_result["text"].strip()
            print(f"  Reference text set to: '{ref_text}'")
            os.remove(tf_path)

        print("  Calling Fish Speech 1.5 on Modal... (This might take a moment to boot)")
        
        wav_output_path = output_path.with_suffix('.wav')
        
        generate_voiceover = modal.Function.from_name("avatar-pipeline", "generate_voiceover")
        wav_bytes = generate_voiceover.remote(text, ref_audio_bytes, ref_text)
        
        with open(wav_output_path, "wb") as f:
            f.write(wav_bytes)
            
        print(f"  Fish Speech generation complete. Saved to {wav_output_path.name}")
        
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
