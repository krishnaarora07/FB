from __future__ import annotations

from .models import VideoSignal


def is_football_related(video: VideoSignal, keywords: list[str]) -> bool:
    haystack = " ".join(
        [
            video.title,
            video.description,
            video.channel_title,
            " ".join(video.tags),
        ]
    ).lower()
    return any(keyword.lower() in haystack for keyword in keywords)


def dedupe_videos(videos: list[VideoSignal]) -> list[VideoSignal]:
    by_id: dict[str, VideoSignal] = {}
    for video in videos:
        if not video.video_id:
            continue
        existing = by_id.get(video.video_id)
        if existing is None or video.score() > existing.score():
            by_id[video.video_id] = video
    return list(by_id.values())


def rank_videos(videos: list[VideoSignal]) -> list[VideoSignal]:
    return sorted(videos, key=lambda item: item.score(), reverse=True)

