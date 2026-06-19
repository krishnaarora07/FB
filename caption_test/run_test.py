"""
Full end-to-end caption test.
Run from the repo root: python caption_test/run_test.py
"""
import asyncio, json, sys, subprocess, shutil
from pathlib import Path

TEST_DIR = Path(__file__).parent
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

SCRIPT = "Incredible scenes at the World Cup. Nobody expected this. Watch what happens next."

# ─── 1. edge-tts ──────────────────────────────────────────────────────────────
print("=== STEP 1: edge-tts WordBoundary ===")
try:
    import edge_tts
except ImportError:
    print("FAIL: edge_tts not installed. Run: pip install edge-tts")
    sys.exit(1)

audio_path = TEST_DIR / "voice.mp3"

async def _tts():
    comm = edge_tts.Communicate(SCRIPT, "en-GB-RyanNeural", rate="+10%")
    words = []
    audio_chunks = []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append({
                "text": chunk["text"],
                "offset": chunk["offset"],
                "duration": chunk["duration"],
            })
    audio_path.write_bytes(b"".join(audio_chunks))
    return words

words = asyncio.run(_tts())
print(f"  Got {len(words)} word boundaries")
if words:
    for w in words[:4]:
        print(f"    {w}")
    print("  PASS: edge-tts WordBoundary works correctly")
else:
    print("  WARNING: 0 word boundaries — will use fallback timing")

(TEST_DIR / "voice.words.json").write_text(json.dumps(words, indent=2))
print()

# ─── 2. ASS file generation ───────────────────────────────────────────────────
print("=== STEP 2: ASS subtitle file ===")
from football_pipeline.moviepy_edit import _build_ass, _estimate_word_timings

if not words:
    words = _estimate_word_timings(SCRIPT, 8.0)
    print(f"  Using fallback: {len(words)} estimated word timings")

ass_path = TEST_DIR / "captions.ass"
_build_ass(words, ass_path)

content = ass_path.read_text(encoding="utf-8")
lines = content.splitlines()
print(f"  ASS file: {len(lines)} lines, {ass_path.stat().st_size} bytes")
print("  First 12 lines:")
for l in lines[:12]:
    print(f"    {l}")
print(f"  Last 3 lines:")
for l in lines[-3:]:
    print(f"    {l}")
print("  PASS: ASS file generated")
print()

# ─── 3. FFmpeg test ───────────────────────────────────────────────────────────
print("=== STEP 3: FFmpeg subtitle burn ===")
ffmpeg = shutil.which("ffmpeg")
if not ffmpeg:
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        ffmpeg = get_ffmpeg_exe()
    except Exception:
        pass

if not ffmpeg:
    print("  SKIP: ffmpeg not found on this system")
    sys.exit(0)

print(f"  Using: {ffmpeg}")

# Quick check: does ffmpeg have libass?
probe = subprocess.run([ffmpeg, "-filters"], capture_output=True, text=True)
if "ass" in probe.stdout:
    print("  PASS: FFmpeg has 'ass' filter (libass compiled in)")
else:
    print("  WARNING: 'ass' filter not found in FFmpeg — subtitles may not render")

# Generate a tiny 5-second black test video to burn captions onto
test_raw = TEST_DIR / "test_raw.mp4"
test_out = TEST_DIR / "test_captioned.mp4"
subprocess.run([
    ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30",
    "-i", str(audio_path),
    "-shortest", "-c:v", "libx264", "-c:a", "aac",
    str(test_raw)
], capture_output=True)
print(f"  Test video created: {test_raw.stat().st_size} bytes")

result = subprocess.run([
    ffmpeg, "-y",
    "-i", str(test_raw),
    "-vf", f"ass={ass_path.resolve()}",
    "-c:v", "libx264", "-preset", "fast",
    "-c:a", "copy",
    str(test_out)
], capture_output=True, text=True)

if result.returncode == 0:
    print(f"  PASS: Subtitle burn succeeded! Output: {test_out} ({test_out.stat().st_size} bytes)")
else:
    print(f"  FAIL: FFmpeg returned exit code {result.returncode}")
    print("  Last 20 lines of stderr:")
    for line in result.stderr.splitlines()[-20:]:
        print(f"    {line}")

print()
print("=== TEST COMPLETE ===")
