from __future__ import annotations

from pathlib import Path

from moviepy.editor import (
    AudioFileClip,
    VideoFileClip,
    concatenate_videoclips,
)

from .models import TopicPackage


def _build_ass(words: list[dict], ass_path: Path) -> None:
    """Convert a list of word-boundary dicts into a .ass subtitle file with pop animation."""

    # DejaVu Sans is pre-installed on ubuntu-latest with NO extra apt packages needed.
    # This avoids font-lookup failures that plagued Liberation Sans / Arial.
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
        # White bold text, black outline (size 3), small drop-shadow (1), centred low (MarginV=800)
        "Style: Default,DejaVu Sans,58,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,3,1,2,10,10,800,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    def _ts(hundred_ns: int) -> str:
        """100-nanosecond offset → ASS timestamp H:MM:SS.cs"""
        s = hundred_ns / 10_000_000.0
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        cs = s % 60
        return f"{h}:{m:02d}:{cs:05.2f}"

    events: list[str] = []
    # Pop animation: {\t(0,80,\fscx130\fscy130)\t(80,150,\fscx100\fscy100)}
    pop = "{" + r"\t(0,80,\fscx130\fscy130)" + r"\t(80,150,\fscx100\fscy100)" + "}"

    for w in words:
        text = w["text"].strip()
        if not text:
            continue
        start = _ts(w["offset"])
        # Extend duration slightly so rapid words don't flash too fast
        end = _ts(w["offset"] + w["duration"] + 600_000)
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{pop}{text}")

    content = ass_header + "\n".join(events) + "\n"
    ass_path.write_text(content, encoding="utf-8")
    print(f"  ASS subtitle file written: {len(events)} events, {ass_path.stat().st_size} bytes")


def _estimate_word_timings(script: str, audio_duration_s: float) -> list[dict]:
    """
    Fallback: if edge-tts returned no WordBoundary events, distribute words
    evenly across the audio duration in 100-nanosecond units.
    """
    tokens = [t for t in script.split() if t.strip()]
    if not tokens:
        return []
    ns_total = int(audio_duration_s * 10_000_000)
    ns_per_word = ns_total // len(tokens)
    return [
        {
            "text": tok,
            "offset": i * ns_per_word,
            "duration": int(ns_per_word * 0.80),
        }
        for i, tok in enumerate(tokens)
    ]


def build_moviepy_edit(
    topic: TopicPackage,
    broll_paths: list[Path],
    voiceover_path: Path,
    subtitles_path: Path,
    output_path: Path,
) -> Path:
    """Renders the video locally using MoviePy, then burns subtitles using FFmpeg."""
    if not broll_paths:
        raise ValueError("At least one B-roll asset is required.")

    # ── 1. Load Voiceover ──────────────────────────────────────────────────────
    audio = AudioFileClip(str(voiceover_path))
    total_seconds = audio.duration

    # ── 2. Prepare B-roll videos ───────────────────────────────────────────────
    clip_length = max(4.0, total_seconds / len(broll_paths))
    video_clips = []
    cursor = 0.0

    for broll_path in broll_paths:
        remaining = max(total_seconds - cursor, 0)
        length = min(clip_length, remaining) if remaining else clip_length
        if length <= 0:
            break

        clip = VideoFileClip(str(broll_path))

        # Crop to 9:16 (1080×1920)
        clip = clip.resize(height=1920)
        if clip.w > 1080:
            x_center = clip.w / 2
            clip = clip.crop(x1=x_center - 540, y1=0, x2=x_center + 540, y2=1920)
        else:
            clip = clip.resize(width=1080, height=1920)

        # Loop short clips; smartly extract from middle of long ones
        if clip.duration < length:
            import moviepy.video.fx.all as vfx
            clip = clip.fx(vfx.loop, duration=length)
        else:
            import random
            buffer = clip.duration * 0.15
            if clip.duration - (2 * buffer) >= length:
                start_t = random.uniform(buffer, clip.duration - buffer - length)
            else:
                start_t = random.uniform(0, max(0, clip.duration - length))
            clip = clip.subclip(start_t, start_t + length)

        if cursor > 0:
            clip = clip.crossfadein(0.5)

        video_clips.append(clip)
        cursor += clip.duration
        if cursor >= total_seconds:
            break

    final_video = concatenate_videoclips(video_clips, method="compose")
    final_video = final_video.set_duration(total_seconds)
    final_video = final_video.set_audio(audio)

    # ── 3. Export raw video (no captions yet) ─────────────────────────────────
    temp_output = output_path.with_name(output_path.stem + "_raw.mp4")
    print(f"  Rendering raw video → {temp_output}...")
    final_video.write_videofile(
        str(temp_output),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        preset="fast",
    )
    audio.close()
    for c in video_clips:
        c.close()
    final_video.close()

    # ── 4. Build subtitle file ─────────────────────────────────────────────────
    import json
    words: list[dict] = []
    if subtitles_path.exists():
        try:
            words = json.loads(subtitles_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  WARNING: Could not read words.json: {exc}")

    if words:
        print(f"  Using {len(words)} edge-tts word-boundary events for captions.")
    else:
        print("  No word-boundary events found — generating estimated word timings from script.")
        words = _estimate_word_timings(topic.script, total_seconds)
        print(f"  Estimated {len(words)} word timings from script text.")

    ass_path = output_path.with_name("captions.ass")
    _build_ass(words, ass_path)

    # ── 5. Burn subtitles via FFmpeg ───────────────────────────────────────────
    print("  Burning subtitles into video via FFmpeg...")
    import subprocess, shutil

    ffmpeg_exe = shutil.which("ffmpeg")
    if not ffmpeg_exe:
        from imageio_ffmpeg import get_ffmpeg_exe
        ffmpeg_exe = get_ffmpeg_exe()
    print(f"  Using FFmpeg: {ffmpeg_exe}")

    # Use absolute paths to avoid any working-directory ambiguity.
    # On Linux the ass filter path must have backslashes-in-colons escaped; keep it simple
    # by using the absolute posix path and wrapping in single quotes via the list form.
    # We also specify fontsdir=/usr/share/fonts so libass explicitly knows where to look.
    ass_path_str = str(ass_path.resolve()).replace("\\", "/") # Ensure forward slashes for filter parsing
    
    # On Linux (GitHub Actions), the path is like /home/runner/..., so no drive-letter colons to worry about.
    # We omit single quotes as FFmpeg can sometimes treat them as literal characters in the filename.
    command = [
        ffmpeg_exe, "-y",
        "-i", str(temp_output.resolve()),
        "-vf", f"ass={ass_path_str}:fontsdir=/usr/share/fonts",
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "copy",
        str(output_path.resolve()),
    ]
    print(f"  FFmpeg command: {' '.join(command)}")

    result = subprocess.run(command, capture_output=True, text=True)
    print(f"  FFmpeg exit code: {result.returncode}")
    if result.returncode != 0:
        print(f"  FFmpeg stderr (last 40 lines):\n" +
              "\n".join(result.stderr.splitlines()[-40:]))
        raise RuntimeError(
            f"FFmpeg subtitle burning failed (exit {result.returncode}). "
            "Check stderr above for font/libass errors."
        )

    temp_output.unlink(missing_ok=True)
    print("  Subtitle burn complete.")
    return output_path
