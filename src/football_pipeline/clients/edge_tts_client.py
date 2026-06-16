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
        
        import sys
        import tempfile
        import subprocess
        
        words_path = output_path.with_suffix('.words.json')
        
        script = f"""
import asyncio
import edge_tts
import json

async def main():
    text = {repr(text)}
    voice = {repr(self.voice)}
    communicate = edge_tts.Communicate(text, voice, rate='+10%')
    
    words = []
    with open({repr(str(output_path))}, 'wb') as f:
        async for chunk in communicate.stream():
            if chunk['type'] == 'audio':
                f.write(chunk['data'])
            elif chunk['type'] == 'WordBoundary':
                words.append({{
                    'text': chunk['text'],
                    'offset': chunk['offset'],
                    'duration': chunk['duration']
                }})
                
    with open({repr(str(words_path))}, 'w', encoding='utf-8') as f:
        json.dump(words, f, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    asyncio.run(main())
"""
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(script)
            script_path = f.name
            
        try:
            subprocess.run([sys.executable, script_path], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Edge TTS Python API failed: {exc.stderr}") from exc
        finally:
            Path(script_path).unlink(missing_ok=True)
            
        return output_path
