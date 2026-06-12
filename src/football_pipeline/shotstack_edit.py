from __future__ import annotations

from .models import BrollAsset, TopicPackage


def estimate_voiceover_seconds(script: str, target_seconds: int) -> int:
    words = [word for word in script.split() if word.strip()]
    spoken_seconds = int(len(words) / 2.45) + 4
    return max(30, min(max(target_seconds + 8, 45), spoken_seconds))


def build_shotstack_edit(
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
    video_clips = []
    cursor = 0.0
    effects = ["zoomInSlow", "slideLeftSlow", "zoomOutSlow", "slideUpSlow"]

    for index, asset in enumerate(broll_assets):
        remaining = max(total_seconds - cursor, 0)
        length = min(clip_length, remaining) if remaining else clip_length
        if length <= 0:
            break
        video_clips.append(
            {
                "asset": {
                    "type": "video",
                    "src": asset.url,
                    "volume": 0,
                },
                "start": round(cursor, 2),
                "length": round(length, 2),
                "fit": "crop",
                "effect": effects[index % len(effects)],
                "transition": {"in": "fade", "out": "fade"},
            }
        )
        cursor += length
        if cursor >= total_seconds:
            break

    hook = topic.topic_title[:90]
    return {
        "timeline": {
            "background": "#071014",
            "tracks": [
                {
                    "clips": [
                        {
                            "asset": {
                                "type": "text",
                                "text": hook,
                                "width": 920,
                                "height": 230,
                                "font": {
                                    "family": "Montserrat",
                                    "color": "#FFFFFF",
                                    "size": 58,
                                    "weight": 800,
                                    "lineHeight": 0.95,
                                },
                                "background": {
                                    "color": "#071014",
                                    "opacity": 0.72,
                                    "padding": 22,
                                    "borderRadius": 8,
                                },
                                "alignment": {"horizontal": "center", "vertical": "center"},
                            },
                            "start": 0,
                            "length": min(5, total_seconds),
                            "position": "center",
                            "transition": {"in": "fade", "out": "fade"},
                        }
                    ]
                },
                {
                    "clips": [
                        {
                            "asset": {
                                "type": "rich-caption",
                                "src": "alias://voiceover",
                                "font": {
                                    "family": "Montserrat",
                                    "weight": "800",
                                    "color": "#FFFFFF",
                                    "size": 58,
                                },
                                "active": {
                                    "font": {
                                        "color": "#F7C948",
                                        "size": 64,
                                    }
                                },
                                "stroke": {
                                    "width": 3,
                                    "color": "#000000",
                                    "opacity": 0.85,
                                },
                                "background": {
                                    "color": "#000000",
                                    "opacity": 0.20,
                                    "borderRadius": 8,
                                    "wrap": True,
                                },
                                "padding": 18,
                                "align": {"horizontal": "center", "vertical": "middle"},
                                "animation": {"style": "pop"},
                            },
                            "start": 0,
                            "length": total_seconds,
                            "width": 980,
                            "height": 420,
                            "position": "bottom",
                            "offset": {"x": 0, "y": -0.06},
                        }
                    ]
                },
                {
                    "clips": [
                        {
                            "asset": {
                                "type": "audio",
                                "src": voiceover_url,
                                "volume": 1,
                                "effect": "fadeInFadeOut",
                            },
                            "start": 0,
                            "length": total_seconds,
                            "alias": "voiceover",
                        }
                    ]
                },
                {"clips": video_clips},
            ],
        },
        "output": {
            "format": "mp4",
            "aspectRatio": "9:16",
            "resolution": "1080",
            "fps": 30,
            "quality": "medium",
        },
    }
