import asyncio, os, sys, tempfile, shutil, subprocess
from pathlib import Path

# Add src to path
repo_root = Path(r"C:\Users\krish\Documents\fb")
sys.path.insert(0, str(repo_root / "src"))

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
else:
    print("  WARNING: 0 boundaries - fallback will be used")

# ── STEP 2: ASS generation ────────────────────────────────────────────────────
print("\nSTEP 2: ASS subtitle file")
from football_pipeline.moviepy_edit import _build_ass, _estimate_word_timings

if not words:
    words = _estimate_word_timings(SCRIPT, 8.0)
    print(f"  Fallback: {len(words)} estimated words")

ass_tmp = tempfile.NamedTemporaryFile(suffix=".ass", delete=False, mode="w", encoding="utf-8")
ass_path = Path(ass_tmp.name)
ass_tmp.close()

_build_ass(words, ass_path)
content = ass_path.read_text(encoding="utf-8")
lines = content.splitlines()
dialogue_lines = [l for l in lines if l.startswith("Dialogue")]
print(f"  ASS file: {len(lines)} lines total, {len(dialogue_lines)} Dialogue events")
print(f"  Header lines ok: {any('Script Info' in l for l in lines)}")
print(f"  Style line ok:   {any('DejaVu' in l for l in lines)}")
print(f"  Sample Dialogue: {dialogue_lines[0] if dialogue_lines else 'NONE'}")

# ── STEP 3: FFmpeg burn check ──────────────────────────────────────────────────
print("\nSTEP 3: FFmpeg subtitle burn")
ffmpeg = shutil.which("ffmpeg")
if not ffmpeg:
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        ffmpeg = get_ffmpeg_exe()
    except Exception:
        pass

if ffmpeg:
    print(f"  Using FFmpeg: {ffmpeg}")
    
    raw_tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    raw_path = raw_tmp.name
    raw_tmp.close()
    
    out_tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    out_path = out_tmp.name
    out_tmp.close()
    
    # Generate 1 sec black video
    subprocess.run([
        ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30",
        "-t", "1", "-c:v", "libx264", raw_path
    ], capture_output=True)
    
    ass_path_str = str(ass_path.resolve()).replace("\\", "/")
    
    cmd = [
        ffmpeg, "-y",
        "-i", raw_path,
        "-vf", f"ass='{ass_path_str}'",
        "-c:v", "libx264", "-preset", "fast",
        out_path
    ]
    print(f"  Command: {' '.join(cmd)}")
    
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        print("  PASS: FFmpeg burn succeeded!")
    else:
        print(f"  FAIL: FFmpeg returned {res.returncode}")
        print("  Stderr (last 10 lines):")
        for line in res.stderr.splitlines()[-10:]:
            print(f"    {line}")
            
    os.unlink(raw_path)
    os.unlink(out_path)
else:
    print("  SKIP: FFmpeg not available for test")

# Cleanup
os.unlink(mp3_path)
os.unlink(ass_path)
print("\nAll checks done.")
