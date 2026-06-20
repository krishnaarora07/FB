from __future__ import annotations

from pathlib import Path

# Patch Pillow >= 10.0.0 for moviepy 1.0.3 compatibility
import PIL.Image
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

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
        # White bold text, black outline (size 3), small drop-shadow (1), bottom-third (MarginV=250)
        "Style: Default,DejaVu Sans,68,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,3,1,2,10,10,250,1\n"
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
    insights=None
) -> Path:
    """Combine voiceover, subtitles, and B-roll into a final vertical video."""
    
    # --- Dynamic B-Roll Pacing ---
    target_duration = 1.8 # Lower baseline from 2.5 to 1.8
    if insights and insights.avg_view_duration:
        if insights.avg_view_duration < 15:
            target_duration = 1.0 # Hyper-fast pacing for low retention
        elif insights.avg_view_duration <= 25:
            target_duration = 1.4 # Fast pacing

    if not broll_paths:
        raise ValueError("At least one B-roll asset is required.")

    # ── 1. Load Voiceover ──────────────────────────────────────────────────────
    audio = AudioFileClip(str(voiceover_path))
    total_seconds = audio.duration

    # ── 2. Prepare B-roll videos (or Parallax Images) ─────────────────────────
    clip_length = max(target_duration, total_seconds / len(broll_paths))
    video_clips = []
    cursor = 0.0

    def _create_parallax_clip(img_path: Path, length: float):
        import numpy as np
        from PIL import Image, ImageFilter
        from moviepy.editor import ImageClip, CompositeVideoClip
        from rembg import remove

        # 1. Load image and remove background
        input_img = Image.open(img_path).convert("RGBA")
        fg_img = remove(input_img)

        # 2. Crop to 9:16 aspect ratio (Full Vertical)
        target_ratio = 1080 / 1920.0
        w, h = input_img.size
        img_ratio = w / h
        
        if img_ratio > target_ratio:
            new_w = int(h * target_ratio)
            left = (w - new_w) // 2
            bg_crop = input_img.crop((left, 0, left + new_w, h))
            fg_crop = fg_img.crop((left, 0, left + new_w, h))
        else:
            new_h = int(w / target_ratio)
            top = (h - new_h) // 2
            bg_crop = input_img.crop((0, top, w, top + new_h))
            fg_crop = fg_img.crop((0, top, w, top + new_h))
            
        bg_img = bg_crop.resize((1080, 1920), Image.Resampling.LANCZOS)
        bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=15))
        fg_img = fg_crop.resize((1080, 1920), Image.Resampling.LANCZOS)
        
        # 3. Animate with MoviePy
        # Zoom out slowly for background
        def resize_bg(t):
            return 1.1 - 0.05 * (t / length)
            
        # Zoom in slowly for foreground
        def resize_fg(t):
            return 1.0 + 0.05 * (t / length)

        bg_clip = ImageClip(np.array(bg_img.convert("RGB"))).set_duration(length)
        bg_clip = bg_clip.resize(resize_bg).set_position("center")
        
        fg_clip = ImageClip(np.array(fg_img)).set_duration(length)
        fg_clip = fg_clip.resize(resize_fg)
        # Force exact dimension with transparent padding to bypass CompositeVideoClip positioning bugs
        fg_clip = fg_clip.on_color(size=(1080, 1920), color=(0,0,0), col_opacity=0, pos="center")
        
        return CompositeVideoClip([bg_clip, fg_clip], size=(1080, 1920)).set_duration(length)

    for broll_path in broll_paths:
        remaining = max(total_seconds - cursor, 0)
        length = min(clip_length, remaining) if remaining else clip_length
        if length <= 0:
            break

        if broll_path.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
            print(f"  Generating Parallax clip for {broll_path.name}...")
            clip = _create_parallax_clip(broll_path, length)
        else:
            raw_fg = VideoFileClip(str(broll_path)).without_audio()
            raw_bg = VideoFileClip(str(broll_path)).without_audio()

            # Loop short clips; smartly extract from middle of long ones
            if raw_fg.duration < length:
                import moviepy.video.fx.all as vfx
                raw_fg = raw_fg.fx(vfx.loop, duration=length)
                raw_bg = raw_bg.fx(vfx.loop, duration=length)
            else:
                import random
                buffer = raw_fg.duration * 0.15
                if raw_fg.duration - (2 * buffer) >= length:
                    start_t = random.uniform(buffer, raw_fg.duration - buffer - length)
                else:
                    start_t = random.uniform(0, max(0, raw_fg.duration - length))
                raw_fg = raw_fg.subclip(start_t, start_t + length)
                raw_bg = raw_bg.subclip(start_t, start_t + length)
                
            # Create Foreground (original ratio, fit inside 1080x1920)
            fg_clip = raw_fg.resize(width=1080)
            if fg_clip.h > 1920:
                fg_clip = fg_clip.resize(height=1920)
                
            # Create Background (blown up and blurred fast)
            bg_clip = raw_bg.resize(height=1920)
            if bg_clip.w < 1080:
                bg_clip = bg_clip.resize(width=1080)
            
            x_center = bg_clip.w / 2
            y_center = bg_clip.h / 2
            bg_clip = bg_clip.crop(x1=x_center - 540, y1=y_center - 960, x2=x_center + 540, y2=y_center + 960)
            
            def blur_frame(image):
                from PIL import Image, ImageFilter
                import numpy as np
                img = Image.fromarray(image).convert("RGB")
                img.thumbnail((270, 480))
                img = img.filter(ImageFilter.GaussianBlur(radius=5))
                img = img.resize((1080, 1920), Image.Resampling.BILINEAR)
                return np.array(img)
                
            bg_clip = bg_clip.fl_image(blur_frame)
            
            # Force exact dimension with transparent padding to bypass CompositeVideoClip positioning bugs
            fg_clip = fg_clip.on_color(size=(1080, 1920), color=(0,0,0), col_opacity=0, pos="center")
            
            from moviepy.editor import CompositeVideoClip
            clip = CompositeVideoClip([bg_clip, fg_clip], size=(1080, 1920)).set_duration(length)

        if cursor > 0:
            import random
            from moviepy.editor import CompositeVideoClip, ColorClip
            
            t_type = random.choice(["crossfade", "dip_to_black", "flash_white", "hard_cut"])
            
            if t_type == "crossfade":
                clip = clip.crossfadein(0.3)
            elif t_type == "dip_to_black":
                clip = clip.fadein(0.3)
            elif t_type == "flash_white":
                flash = ColorClip(size=(1080, 1920), color=(255,255,255)).set_duration(0.15)
                flash = flash.crossfadeout(0.15)
                clip = CompositeVideoClip([clip, flash.set_position("center")])

        video_clips.append(clip)
        cursor += clip.duration
        if cursor >= total_seconds:
            break

    top_video = concatenate_videoclips(video_clips, method="compose")
    top_video = top_video.set_duration(total_seconds).set_position("center")
    
    # ── 2.6. Build 1-Frame Thumbnail Injection ───────────────────────────────
    # We create a 0.1s super-saturated frame of the very first frame to trick the algorithm thumbnail
    thumb_clip = None
    if video_clips:
        first_frame = video_clips[0].get_frame(0)
        from PIL import Image, ImageEnhance
        import numpy as np
        img = Image.fromarray(first_frame)
        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(2.5) # Hyper-saturate
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.2) # Brighten
        
        from moviepy.editor import ImageClip
        thumb_clip = ImageClip(np.array(img)).set_duration(0.1).set_start(0.1).set_position(("center", "top"))

    # Compose layers
    layers = [top_video]
    if thumb_clip:
        layers.append(thumb_clip)
        
    final_video = CompositeVideoClip(layers, size=(1080, 1920)).set_duration(total_seconds)
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
