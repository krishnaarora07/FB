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


def build_moviepy_edit(
    topic: TopicPackage,
    broll_paths: list[Path],
    voiceover_path: Path,
    output_path: Path,
) -> Path:
    """Renders the video locally using MoviePy.
    
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

        # Loop short clips or truncate long ones
        if clip.duration < length:
            import moviepy.video.fx.all as vfx
            clip = clip.fx(vfx.loop, duration=length)
        else:
            clip = clip.subclip(0, length)
        
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

    # 3. Add Title Hook
    hook = topic.topic_title[:90]
    
    # In MoviePy, TextClip requires ImageMagick
    try:
        txt_clip = TextClip(
            hook,
            fontsize=70,
            color='white',
            bg_color='black',
            font='Arial-Bold',
            method='caption',
            size=(900, None),
        )
        txt_clip = txt_clip.set_position('center').set_duration(min(5, total_seconds))
        txt_clip = txt_clip.crossfadein(0.5).crossfadeout(0.5)
        
        final_video = CompositeVideoClip([final_video, txt_clip])
    except Exception as e:
        print(f"  Warning: Failed to generate TextClip (ImageMagick might be missing): {e}")

    # 4. Export
    print(f"  Rendering video to {output_path}...")
    final_video.write_videofile(
        str(output_path),
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
    
    return output_path
