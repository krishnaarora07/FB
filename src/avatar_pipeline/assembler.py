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
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,DejaVu Sans,64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,3,1,2,10,10,320,1\n"
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

def normalize_video(src: str, dst: str, crop_to_fill: bool = False, keep_audio: bool = False):
    # Output is 1080x1920 portrait (9:16) — mandatory for YouTube Shorts.
    # Avatar (480x832) fills naturally; landscape B-roll images get center-cropped.
    w, h = 1080, 1920

    if crop_to_fill:
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    else:
        vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"

    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-vf", vf,
        "-r", "25",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23"
    ]
    
    if keep_audio:
        cmd.extend(["-c:a", "aac", "-ar", "44100", "-ac", "2", dst])
    else:
        cmd.extend(["-an", dst])
        
    subprocess.run(cmd, capture_output=True, check=True)

def assemble(clip_paths: list[str], broll_paths: list[str], output_path: str, base_audio_path: str = None, broll_timings: list[tuple] = None):
    work_dir = os.path.dirname(output_path)
    if not clip_paths:
        raise ValueError("No clip paths provided.")
        
    print("Normalizing avatar clips and preserving native audio...")
    norm_avatars = []
    for i, p in enumerate(clip_paths):
        dst = os.path.join(work_dir, f"norm_avatar_{i}.mp4")
        # crop_to_fill=True: LongCat outputs 480x832 (ratio 0.577, not exact 9:16).
        # With False it pads to 1080x1920 leaving 24px black bars top/bottom.
        # With True it crops 14px from each side — no black bars, face stays intact.
        normalize_video(p, dst, crop_to_fill=True, keep_audio=True)
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

    # Get avatar video duration
    res = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", temp_avatar], capture_output=True, text=True)
    total_dur = float(res.stdout.strip()) if res.stdout.strip() else 60.0

    # ──────────────────────────────────────────────────────────────────────────
    # B-ROLL OVERLAY  (portrait 9:16 — 1080×1920)
    # ──────────────────────────────────────────────────────────────────────────
    # Design: B-roll fills the full 1080×1920 portrait frame; avatar is a
    # small portrait PiP (240×426, 9:16) at bottom-center with a white border.
    #
    # Input layout:
    #   0      = temp_avatar  (portrait 1080×1920, full duration)
    #   1..N   = norm_brolls  (portrait 1080×1920 Ken-Burns clips)
    #   N+1    = TTS WAV
    #
    # Per B-roll slot i:
    #   1. Trim avatar window → scale to 252×448 PiP (maintains 9:16) → [pip_i]
    #   2. Trim B-roll to d seconds → [br_i]
    #   3. [br_i][pip_i] → overlay PiP at bottom-center → [comp_i]
    #   4. Clock-shift comp_i, overlay onto master avatar stream → [v_i]
    # ──────────────────────────────────────────────────────────────────────────
    N = len(norm_brolls)
    filter_chains = []
    last_v = "0:v"

    if N > 0:
        if broll_timings and len(broll_timings) == N:
            timings = broll_timings
        else:
            spacing = total_dur / (N + 1)
            timings = [(spacing * (i + 1), 5.0) for i in range(N)]

        for i in range(N):
            start_t, broll_dur = timings[i]
            start_t = min(float(start_t), max(0.0, total_dur - float(broll_dur) - 0.5))
            end_t   = min(start_t + float(broll_dur), total_dur)
            d       = end_t - start_t

            broll_in = f"{i+1}:v"

            # Step 1: Avatar PiP — trim window, scale to 380x676 portrait (9:16),
            # add 6px white border → 392x688. Avatar already fills 1080x1920 cleanly
            # (crop_to_fill=True removes the 24px black bars from normalization).
            filter_chains.append(
                f"[0:v]trim=start={start_t:.3f}:end={end_t:.3f},setpts=PTS-STARTPTS,"
                f"scale=380:676,pad=392:688:6:6:color=white[pip_{i}]"
            )

            # Step 2: Trim B-roll to exact display duration.
            filter_chains.append(
                f"[{broll_in}]trim=duration={d:.3f},setpts=PTS-STARTPTS[br_{i}]"
            )

            # Step 3: Composite — B-roll portrait background + avatar PiP
            # placed at bottom-center of the 1080×1920 frame.
            filter_chains.append(
                f"[br_{i}][pip_{i}]overlay=x=(W-w)/2:y=H-h-40:shortest=1[comp_{i}]"
            )

            # Step 4: Clock-shift composite to start_t, overlay on master stream.
            out_v = f"v_{i}"
            filter_chains.append(
                f"[comp_{i}]setpts=PTS+{start_t:.3f}/TB[comp_clk_{i}]"
            )
            filter_chains.append(
                f"[{last_v}][comp_clk_{i}]overlay="
                f"enable='between(t,{start_t:.3f},{end_t:.3f})':format=auto[{out_v}]"
            )
            last_v = out_v

    # ── Subtitles ─────────────────────────────────────────────────────────────
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

    # ── Final FFmpeg command ───────────────────────────────────────────────────
    # Input layout:
    #   0          = temp_avatar
    #   1..N       = norm_brolls (one per slot)
    #   N+1        = base_audio_path (TTS WAV)
    audio_input_idx = 1 + N  # one avatar + N brolls

    print("Compositing final video...")
    cmd = ["ffmpeg", "-y", "-i", temp_avatar]
    for bp in norm_brolls:
        cmd.extend(["-i", bp])
    if base_audio_path:
        cmd.extend(["-i", base_audio_path])

    if filter_chains:
        cmd.extend(["-filter_complex", ";".join(filter_chains), "-map", f"[{last_v}]"])
    else:
        cmd.extend(["-map", "0:v"])

    # Always pin audio to the original TTS WAV — LongCat's embedded audio can
    # be silently truncated inside Modal's container.
    if base_audio_path:
        cmd.extend(["-map", f"{audio_input_idx}:a", "-c:a", "aac", "-ar", "44100", "-ac", "2"])
    else:
        cmd.extend(["-map", "0:a", "-c:a", "aac", "-ar", "44100", "-ac", "2"])

    # Pin output duration to exactly the TTS audio length.
    # Without this, if avatar video < audio, FFmpeg stops at video EOF and
    # silently drops the final sentences.
    if base_audio_path:
        audio_dur_res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", base_audio_path],
            capture_output=True, text=True
        )
        try:
            audio_dur = float(audio_dur_res.stdout.strip())
            cmd.extend(["-t", f"{audio_dur:.3f}"])
            print(f"  Output duration pinned to audio: {audio_dur:.2f}s")
        except ValueError:
            pass  # ffprobe failed; let FFmpeg decide naturally

    cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "23", output_path])
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Final composition failed:\n{result.stderr[-4000:]}")
        
    # Cleanup
    for p in norm_avatars + norm_brolls + [list_file, temp_avatar]:
        try: os.remove(p)
        except: pass
    if ass_path:
        try: os.remove(ass_path)
        except: pass

    print(f"Assembly complete -> {output_path}")
