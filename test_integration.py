import os
import subprocess
from src.avatar_pipeline.assembler import assemble

# Make sure we have the dummy files
if not os.path.exists("dummy_avatar.mp4"):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=720x1280:d=10", "-c:v", "libx264", "dummy_avatar.mp4"])
if not os.path.exists("dummy_broll.mp4"):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=720x1280:d=4", "-c:v", "libx264", "dummy_broll.mp4"])
if not os.path.exists("dummy_audio.wav"):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "10", "dummy_audio.wav"])

clip_paths = ["dummy_avatar.mp4"]
broll_paths = ["dummy_broll.mp4", "dummy_broll.mp4"]
out_path = "final_pip_test.mp4"

try:
    assemble(clip_paths, broll_paths, out_path, "dummy_audio.wav")
    print("Integration test passed!")
except Exception as e:
    print(f"Integration test failed: {e}")
