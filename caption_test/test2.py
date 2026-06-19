import asyncio, json, sys, os, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

SCRIPT = "Incredible scenes at the World Cup. Nobody expected this. Watch what happens next."

# ── STEP 1: edge-tts ──────────────────────────────────────────────────────────
print("STEP 1: edge-tts WordBoundary")
import edge_tts

async def tts():
    comm = edge_tts.Communicate(SCRIPT, "en-GB-RyanNeural", rate="+10%")
    words = []
    chunks = []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append({"text": chunk["text"], "offset": chunk["offset"], "duration": chunk["duration"]})
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.write(b"".join(chunks))
    tmp.close()
    return words, tmp.name

words, mp3_path = asyncio.run(tts())
print(f"  Got {len(words)} word boundaries from edge-tts")
if words:
    print(f"  First 3: {words[:3]}")
    print("  PASS")
else:
    print("  WARNING: 0 boundaries - fallback will be used")
os.unlink(mp3_path)

# ── STEP 2: ASS generation ────────────────────────────────────────────────────
print("\nSTEP 2: ASS subtitle file")
from football_pipeline.moviepy_edit import _build_ass, _estimate_word_timings

if not words:
    words = _estimate_word_timings(SCRIPT, 8.0)
    print(f"  Fallback: {len(words)} estimated words")

with tempfile.NamedTemporaryFile(suffix=".ass", delete=False, mode="w", encoding="utf-8") as f:
    ass_path = Path(f.name)

_build_ass(words, ass_path)
content = ass_path.read_text(encoding="utf-8")
lines = content.splitlines()
dialogue_lines = [l for l in lines if l.startswith("Dialogue")]
print(f"  ASS file: {len(lines)} lines total, {len(dialogue_lines)} Dialogue events")
print(f"  Header lines ok: {any('Script Info' in l for l in lines)}")
print(f"  Style line ok:   {any('DejaVu' in l for l in lines)}")
print(f"  Sample Dialogue: {dialogue_lines[0] if dialogue_lines else 'NONE'}")
os.unlink(ass_path)
print("  PASS" if dialogue_lines else "  FAIL: No Dialogue events!")

print("\nAll checks done")
