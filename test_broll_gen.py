import subprocess
from pathlib import Path

# Create a dummy image
img_path = Path("dummy_image.jpg")
subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=1280x720", "-frames:v", "1", str(img_path)])

# Run the B-roll generation
broll_video_path = Path("test_broll.mp4")
cmd = [
    "ffmpeg", "-y", "-loop", "1", "-i", str(img_path),
    "-vf", "scale=-2:10*ih,zoompan=z='min(zoom+0.0015,1.5)':d=125:x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':s=720x1280",
    "-c:v", "libx264", "-t", "5", "-pix_fmt", "yuv420p", "-r", "25",
    str(broll_video_path)
]
print("Running:", " ".join(cmd))
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    print("FAILED!")
    print(res.stderr)
else:
    print("SUCCESS!")
