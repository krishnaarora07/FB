from __future__ import annotations

from .models import BrollAsset, TopicPackage


def estimate_voiceover_seconds(script: str, target_seconds: int) -> int:
    words = [word for word in script.split() if word.strip()]
    spoken_seconds = int(len(words) / 2.45) + 4
    return max(30, min(max(target_seconds + 8, 45), spoken_seconds))


def build_creatomate_edit(
    topic: TopicPackage,
    broll_assets: list[BrollAsset],
    voiceover_url: str,
    *,
    target_seconds: int = 60,
) -> dict:
    if not broll_assets:
        raise ValueError("At least one B-roll asset is required.")

    total_seconds = estimate_voiceover_seconds(topic.script, target_seconds)
    clip_length = max(4.0, total_seconds / len(broll_assets))
    
    elements = []
    
    # 1. Add background B-roll videos
    cursor = 0.0
    for asset in broll_assets:
        remaining = max(total_seconds - cursor, 0)
        length = min(clip_length, remaining) if remaining else clip_length
        if length <= 0:
            break
            
        elements.append({
            "type": "video",
            "track": 1,
            "source": asset.url,
            "time": round(cursor, 2),
            "duration": round(length, 2),
            "audio_volume": "0%",
            "fit": "cover",
            "transition": {"type": "fade", "duration": 0.5}
        })
        cursor += length
        if cursor >= total_seconds:
            break

    # 2. Add Voiceover
    elements.append({
        "type": "audio",
        "track": 2,
        "source": voiceover_url,
        "time": 0,
        "duration": total_seconds
    })

    # 3. Add Title Hook
    hook = topic.topic_title[:90]
    elements.append({
        "type": "text",
        "track": 3,
        "text": hook,
        "time": 0,
        "duration": min(5, total_seconds),
        "x": "50%",
        "y": "50%",
        "width": "80%",
        "height": "20%",
        "font_family": "Montserrat",
        "font_weight": "800",
        "fill_color": "#FFFFFF",
        "background_color": "rgba(7, 16, 20, 0.72)",
        "background_border_radius": "2%",
        "padding": "5%",
        "y_alignment": "50%",
        "x_alignment": "50%",
        "animations": [
            {"time": "start", "duration": 0.5, "type": "fade", "transition": True},
            {"time": "end", "duration": 0.5, "type": "fade", "transition": True}
        ]
    })

    # 4. Add Auto-Captions (linked to voiceover track)
    elements.append({
        "type": "text",
        "track": 4,
        "transcript_source": voiceover_url,
        "time": 0,
        "duration": total_seconds,
        "y": "85%",
        "x": "50%",
        "width": "90%",
        "height": "20%",
        "y_alignment": "50%",
        "x_alignment": "50%",
        "font_family": "Montserrat",
        "font_weight": "800",
        "fill_color": "#FFFFFF",
        "stroke_color": "#000000",
        "stroke_width": "0.5%",
        "background_color": "rgba(0, 0, 0, 0.2)",
        "background_border_radius": "2%",
        "padding": "4%",
        "transcript_effect": "pop",
        "transcript_color": "#F7C948"
    })

    return {
        "output_format": "mp4",
        "width": 1080,
        "height": 1920,
        "frame_rate": 30,
        "duration": total_seconds,
        "elements": elements
    }
