import os
import json
import subprocess
import shutil
from pathlib import Path

def _build_ass(words: list[dict], ass_path: Path) -> None:
    # DejaVu Sans is pre-installed on ubuntu-latest
    ass_header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 720\n"
        "PlayResY: 1280\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,DejaVu Sans,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,3,1,2,10,10,200,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    def _ts(hundred_ns: int) -> str:
        s = hundred_ns / 10_000_000.0
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        cs = s % 60
        return f"{h}:{m:02d}:{cs:05.2f}"

    events = []
    pop = "{" + r"\t(0,80,\fscx130\fscy130)" + r"\t(80,150,\fscx100\fscy100)" + "}"

    for w in words:
        text = w["text"].strip()
        if not text: continue
        start = _ts(w["offset"])
        end = _ts(w["offset"] + w["duration"] + 600_000)
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{pop}{text}")

    content = ass_header + "\n".join(events) + "\n"
    ass_path.write_text(content, encoding="utf-8")

def normalize_video(src: str, dst: str, crop_to_fill: bool = False):
    w, h = 720, 1280
    
    if crop_to_fill:
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    else:
        vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"

    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-vf", vf,
        "-r", "25",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-an", dst
    ]
    subprocess.run(cmd, capture_output=True, check=True)

def assemble(clip_paths: list[str], broll_paths: list[str], output_path: str, base_audio_path: str = None):
    work_dir = os.path.dirname(output_path)
    if not clip_paths:
        raise ValueError("No clip paths provided.")
        
    print("Normalizing avatar clips...")
    norm_avatars = []
    for i, p in enumerate(clip_paths):
        dst = os.path.join(work_dir, f"norm_avatar_{i}.mp4")
        normalize_video(p, dst, crop_to_fill=False)
        norm_avatars.append(dst)
        
    print("Normalizing B-roll clips...")
    norm_brolls = []
    for i, p in enumerate(broll_paths):
        dst = os.path.join(work_dir, f"norm_broll_{i}.mp4")
        normalize_video(p, dst, crop_to_fill=True)
        norm_brolls.append(dst)

    print("Concatenating avatar clips...")
    list_file = os.path.join(work_dir, "concat_list.txt")
    with open(list_file, "w") as f:
        for p in norm_avatars:
            f.write(f"file '{os.path.abspath(p)}'\n")
            
    temp_avatar = os.path.join(work_dir, "temp_avatar.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file, "-c", "copy", temp_avatar
    ], check=True)

    # Calculate overlay timings for B-roll
    res = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", temp_avatar], capture_output=True, text=True)
    total_dur = float(res.stdout.strip()) if res.stdout.strip() else 60.0
    
    filter_chains = []
    last_v = "0:v"
    
    N = len(norm_brolls)
    if N > 0:
        spacing = total_dur / (N + 1)
        for i in range(N):
            start_t = spacing * (i + 1)
            end_t = start_t + 5.0
            
            # The PiP source for this B-roll is input i+1
            pip_in = f"{i+1}:v"
            # The B-roll source is input N+i+1
            broll_in = f"{N+i+1}:v"
            
            # 1. Scale and pad the PiP source (creates pip_ready)
            # Placed top-right to avoid subtitles at the bottom
            filter_chains.append(f"[{pip_in}]scale=240:426,pad=246:432:3:3:color=white@0.8[pip_ready_{i}]")
            
            # 2. Shift B-roll timestamps to its active window
            filter_chains.append(f"[{broll_in}]setpts=PTS-STARTPTS+{start_t}/TB[broll_shifted_{i}]")
            
            # 3. Overlay the PiP onto the B-roll (shortest=1 ensures the overlay stops when the 5s B-roll stops)
            filter_chains.append(f"[broll_shifted_{i}][pip_ready_{i}]overlay=x=W-w-30:y=30:shortest=1[broll_pip_{i}]")
            
            # 4. Add alpha crossfade to the combined PiP+Broll
            filter_chains.append(f"[broll_pip_{i}]format=rgba,fade=t=in:st={start_t}:d=0.5:alpha=1,fade=t=out:st={end_t-0.5}:d=0.5:alpha=1[broll_faded_{i}]")
            
            # 5. Overlay onto the main background
            out_v = f"v{i}"
            filter_chains.append(f"[{last_v}][broll_faded_{i}]overlay=enable='between(t,{start_t},{end_t})':format=auto[{out_v}]")
            last_v = out_v

    # Check for words.json for subtitles
    ass_path = None
    if base_audio_path:
        words_json = Path(base_audio_path).with_suffix(".words.json")
        if words_json.exists():
            ass_path = Path(work_dir) / "captions.ass"
            try:
                words = json.loads(words_json.read_text(encoding="utf-8"))
                _build_ass(words, ass_path)
            except Exception as e:
                print(f"Failed to build ASS subtitles: {e}")
                ass_path = None

    if ass_path:
        ass_str = str(ass_path.resolve()).replace("\\", "/")
        filter_chains.append(f"[{last_v}]ass={ass_str}:fontsdir=/usr/share/fonts[vfinal]")
        last_v = "vfinal"

    # Final FFmpeg command
    print("Compositing final video...")
    cmd = ["ffmpeg", "-y", "-i", temp_avatar]
    
    # Add temp_avatar N times for the PiP layers
    for _ in norm_brolls:
        cmd.extend(["-i", temp_avatar])
        
    for bp in norm_brolls:
        cmd.extend(["-i", bp])
        
    if base_audio_path:
        cmd.extend(["-i", base_audio_path])
        
    if filter_chains:
        cmd.extend(["-filter_complex", ";".join(filter_chains), "-map", f"[{last_v}]"])
    else:
        cmd.extend(["-map", "0:v"])
        
    if base_audio_path:
        cmd.extend(["-map", f"{2 * N + 1}:a", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest"])
        
    cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "23", output_path])
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Final composition failed:\n{result.stderr}")
        
    # Cleanup
    for p in norm_avatars + norm_brolls + [list_file, temp_avatar]:
        try: os.remove(p)
        except: pass
    if ass_path:
        try: os.remove(ass_path)
        except: pass

    print(f"Assembly complete -> {output_path}")
