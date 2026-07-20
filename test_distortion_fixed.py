import subprocess
from pathlib import Path

# The image is horiz_image.jpg from earlier
img_path = Path("horiz_image.jpg")

# Run the B-roll generation with fixed crop
broll_video_path = Path("test_horiz_broll_fixed.mp4")
cmd = [
    "ffmpeg", "-y", "-loop", "1", "-i", str(img_path),
    "-vf", "scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840,zoompan=z='min(zoom+0.0015,1.5)':d=125:x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':s=720x1280",
    "-c:v", "libx264", "-t", "5", "-pix_fmt", "yuv420p", "-r", "25",
    str(broll_video_path)
]
print("Running:", " ".join(cmd))
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    print("FAILED!")
    print(res.stderr)
else:
    print("SUCCESS! Video created at", str(broll_video_path))
