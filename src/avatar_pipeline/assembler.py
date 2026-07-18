import subprocess
import os

def assemble(clip_paths: list[str], broll_paths: list[str], output_path: str):
    """
    Assemble avatar clips and b-roll clips into a final 720p H.264/AAC MP4.
    Clips are re-encoded to a common format before concatenation to prevent
    codec/resolution mismatch errors.
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

    # Re-encode every clip to 1280x720 @ 25fps, AAC audio so concat is safe
    for idx, src in enumerate(all_clips):
        dst = os.path.join(work_dir, f"norm_{idx:03d}.mp4")
        cmd = [
            "ffmpeg", "-y", "-i", src,
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
            "-r", "25",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-shortest",
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

    # Final concat (stream copy — all inputs already match)
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg final assembly failed:\n{result.stderr}")

    # Cleanup temp files
    for p in normalized:
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        os.remove(list_file)
    except OSError:
        pass

    print(f"Assembly complete → {output_path}")
