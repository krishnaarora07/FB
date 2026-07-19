from pathlib import Path
import subprocess

from src.avatar_pipeline.assembler import assemble

# Create a dummy audio file
Path("dummy_audio.wav").write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00")

# Create two dummy 2-second video clips
subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=720x1280", "-c:v", "libx264", "-t", "2", "clip_00.mp4"], capture_output=True)
subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=green:s=720x1280", "-c:v", "libx264", "-t", "2", "clip_01.mp4"], capture_output=True)

# Call assemble with empty broll_paths
try:
    assemble(["clip_00.mp4", "clip_01.mp4"], [], "final_test.mp4", "dummy_audio.wav")
    print("SUCCESS: Full-screen fallback worked!")
except Exception as e:
    print(f"FAILED: {e}")
