from __future__ import annotations

from pathlib import Path

from moviepy.editor import (
    AudioFileClip,
    CompositeVideoClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
)

from .models import TopicPackage


def _words_to_ass(words_json_path: Path, ass_path: Path) -> None:
    import json
    words = json.loads(words_json_path.read_text(encoding="utf-8"))
    
    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,10,10,850,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ass_events = []
    
    def convert_time(hundred_ns: int) -> str:
        # 100-nanoseconds to ASS time format: H:MM:SS.cs
        seconds = hundred_ns / 10_000_000.0
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    for word in words:
        start = convert_time(word['offset'])
        # Add a tiny buffer to duration to make transitions smoother
        end = convert_time(word['offset'] + word['duration'] + 500_000)
        
        text = word['text'].strip()
        if not text:
            continue
            
        ass_events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
            
    ass_path.write_text(ass_header + "\\n".join(ass_events), encoding="utf-8")


def build_moviepy_edit(
    topic: TopicPackage,
    broll_paths: list[Path],
    voiceover_path: Path,
    subtitles_path: Path,
    output_path: Path,
) -> Path:
    """Renders the video locally using MoviePy, then burns subtitles using FFmpeg.
    
    Returns the output_path.
    """
    if not broll_paths:
        raise ValueError("At least one B-roll asset is required.")

    # 1. Load Voiceover
    audio = AudioFileClip(str(voiceover_path))
    total_seconds = audio.duration
    
    # 2. Prepare B-roll videos
    clip_length = max(4.0, total_seconds / len(broll_paths))
    video_clips = []
    cursor = 0.0
    
    for broll_path in broll_paths:
        remaining = max(total_seconds - cursor, 0)
        length = min(clip_length, remaining) if remaining else clip_length
        if length <= 0:
            break
            
        clip = VideoFileClip(str(broll_path))
        
        # Crop to 9:16 (1080x1920)
        # We assume 1080x1920 target. Scale height to 1920, then crop width to 1080.
        clip = clip.resize(height=1920)
        if clip.w > 1080:
            x_center = clip.w / 2
            clip = clip.crop(x1=x_center - 540, y1=0, x2=x_center + 540, y2=1920)
        else:
            clip = clip.resize(width=1080, height=1920)

        # Loop short clips or smartly extract from the middle of long ones
        if clip.duration < length:
            import moviepy.video.fx.all as vfx
            clip = clip.fx(vfx.loop, duration=length)
        else:
            import random
            # Skip first 15% and last 15% of video to avoid channel intros/outros
            buffer = clip.duration * 0.15
            
            # Ensure we have enough space to randomly sample
            if clip.duration - (2 * buffer) >= length:
                start_t = random.uniform(buffer, clip.duration - buffer - length)
            else:
                start_t = random.uniform(0, clip.duration - length)
                
            clip = clip.subclip(start_t, start_t + length)
        
        # Add fadein transition between clips
        if cursor > 0:
            clip = clip.crossfadein(0.5)

        video_clips.append(clip)
        cursor += clip.duration
        
        if cursor >= total_seconds:
            break

    # Concatenate all B-roll clips
    final_video = concatenate_videoclips(video_clips, method="compose")
    
    # Ensure final duration exactly matches audio
    final_video = final_video.set_duration(total_seconds)
    final_video = final_video.set_audio(audio)

    # 3. Export raw video without captions
    temp_output = output_path.with_name(output_path.stem + "_raw.mp4")
    print(f"  Rendering raw video to {temp_output}...")
    final_video.write_videofile(
        str(temp_output),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        preset="fast"
    )
    
    # Close clips to free memory
    audio.close()
    for c in video_clips:
        c.close()
    final_video.close()
    
    # 4. Burn Subtitles using FFmpeg
    print("  Burning captions via FFmpeg using hardcoded ASS format...")
    import subprocess
    from imageio_ffmpeg import get_ffmpeg_exe
    ffmpeg_exe = get_ffmpeg_exe()
    
    run_dir = output_path.parent
    ass_path = subtitles_path.with_suffix(".ass")
    _words_to_ass(subtitles_path, ass_path)
    
    in_name = temp_output.name
    out_name = output_path.name
    ass_name = ass_path.name
    
    command = [
        ffmpeg_exe, "-y", 
        "-i", in_name, 
        "-vf", f"ass={ass_name}", 
        "-c:a", "copy", 
        out_name
    ]
    
    try:
        subprocess.run(command, cwd=str(run_dir), check=True, capture_output=True, text=True)
        # Cleanup the temp file if successful
        temp_output.unlink(missing_ok=True)
    except subprocess.CalledProcessError as e:
        print(f"  Warning: FFmpeg subtitle burning failed: {e.stderr}")
        # If subtitles fail, just use the raw video as final
        temp_output.rename(output_path)
    
    return output_path
