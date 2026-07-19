import cv2
import numpy as np
import imageio
import subprocess
import os

width, height = 704, 480
fps = 24
frames = [np.random.randint(0, 256, (height, width, 3), dtype=np.uint8) for _ in range(24)]

# Old way: OpenCV mp4v
out_cv2 = "test_cv2.mp4"
fourcc = cv2.VideoWriter_fourcc(*"mp4v")
writer = cv2.VideoWriter(out_cv2, fourcc, fps, (width, height))
for f in frames:
    writer.write(f)
writer.release()

# New way: imageio libx264
out_io = "test_io.mp4"
imageio.mimwrite(out_io, frames, fps=fps, codec="libx264", pixelformat="yuv420p", quality=8)

def test_ffmpeg(input_file):
    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
        "-c:v", "libx264", "-preset", "fast",
        f"out_{input_file}"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res

print("Testing OpenCV mp4v...")
res_cv2 = test_ffmpeg(out_cv2)
print("OpenCV exit code:", res_cv2.returncode)

print("Testing imageio libx264...")
res_io = test_ffmpeg(out_io)
print("ImageIO exit code:", res_io.returncode)

# Check pixel formats detected by ffmpeg
def check_pix_fmt(f):
    res = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt", "-of", "default=noprint_wrappers=1:nokey=1", f], capture_output=True, text=True)
    return res.stdout.strip()

print("OpenCV generated pix_fmt:", check_pix_fmt(out_cv2))
print("ImageIO generated pix_fmt:", check_pix_fmt(out_io))
