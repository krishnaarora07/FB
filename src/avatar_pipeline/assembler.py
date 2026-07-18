import subprocess
import os

def assemble(clip_paths: list[str], broll_paths: list[str], output_path: str, base_audio_path: str = None):
    """
    Assemble avatar clips and b-roll clips into a final 720p H.264/AAC MP4.
    If base_audio_path is provided, it replaces the silent tracks with continuous voiceover.
    """
    if not clip_paths:
        raise ValueError("assemble() called with no clip_paths — nothing to assemble.")

    work_dir = os.path.dirname(output_path)
    normalized = []

    all_clips = []
    for i, clip in enumerate(clip_paths):
        all_clips.append(clip)
        if i < len(broll_paths):
            all_clips.append(broll_paths[i])
        elif broll_paths:
            all_clips.append(broll_paths[i % len(broll_paths)])

    # Re-encode every clip to 1280x720 @ 25fps, WITHOUT audio so concat is clean
    for idx, src in enumerate(all_clips):
        dst = os.path.join(work_dir, f"norm_{idx:03d}.mp4")
        cmd = [
            "ffmpeg", "-y", "-i", src,
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
            "-r", "25",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an", # Strip audio
            dst
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg re-encode failed for clip {src}:\n{result.stderr}"
            )
        normalized.append(dst)

    # Write concat list
    list_file = os.path.join(work_dir, "concat_list.txt")
    with open(list_file, "w") as f:
        for p in normalized:
            f.write(f"file '{os.path.abspath(p)}'\n")

    # Final concat (video only)
    temp_video = os.path.join(work_dir, "temp_video.mp4")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        temp_video
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg video assembly failed:\n{result.stderr}")
        
    # Mux audio
    if base_audio_path and os.path.exists(base_audio_path):
        cmd = [
            "ffmpeg", "-y",
            "-i", temp_video,
            "-i", base_audio_path,
            "-c:v", "copy",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-shortest",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg audio mux failed:\n{result.stderr}")
    else:
        # Just move temp to output if no audio provided
        import shutil
        shutil.move(temp_video, output_path)

    # Cleanup temp files
    for p in normalized:
        try: os.remove(p)
        except OSError: pass
    for p in (list_file, temp_video):
        try: os.remove(p)
        except OSError: pass

    print(f"Assembly complete → {output_path}")
