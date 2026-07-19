import subprocess
import os

# Create dummy videos
if not os.path.exists("dummy_avatar.mp4"):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=720x1280:d=10", "-c:v", "libx264", "dummy_avatar.mp4"])
if not os.path.exists("dummy_broll.mp4"):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=720x1280:d=4", "-c:v", "libx264", "dummy_broll.mp4"])

broll_paths = ["dummy_broll.mp4", "dummy_broll.mp4"]

cmd = ["ffmpeg", "-y"]
cmd.extend(["-i", "dummy_avatar.mp4"])

for _ in broll_paths:
    cmd.extend(["-i", "dummy_avatar.mp4"])
    
for bp in broll_paths:
    cmd.extend(["-i", bp])

filter_chains = []
last_v = "0:v"
N = len(broll_paths)

for i in range(N):
    start_t = 1.0 + i * 4.0
    end_t = start_t + 4.0
    
    pip_in = f"{i+1}:v"
    broll_in = f"{N+i+1}:v"
    
    filter_chains.append(f"[{pip_in}]scale=240:426,pad=246:432:3:3:color=white@0.8[pip_ready_{i}]")
    filter_chains.append(f"[{broll_in}]setpts=PTS-STARTPTS+{start_t}/TB[broll_shifted_{i}]")
    filter_chains.append(f"[broll_shifted_{i}][pip_ready_{i}]overlay=x=W-w-30:y=30:shortest=1[broll_pip_{i}]")
    filter_chains.append(f"[broll_pip_{i}]format=rgba,fade=t=in:st={start_t}:d=0.5:alpha=1,fade=t=out:st={end_t-0.5}:d=0.5:alpha=1[broll_faded_{i}]")
    
    out_v = f"v{i}"
    filter_chains.append(f"[{last_v}][broll_faded_{i}]overlay=enable='between(t,{start_t},{end_t})':format=auto[{out_v}]")
    last_v = out_v

cmd.extend(["-filter_complex", ";".join(filter_chains), "-map", f"[{last_v}]", "-c:v", "libx264", "test_out2.mp4"])

print("Running command:", " ".join(cmd))
res = subprocess.run(cmd, capture_output=True, text=True)
print("Exit code:", res.returncode)
if res.returncode != 0:
    print(res.stderr)
