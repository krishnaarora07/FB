from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import json
import math


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class VideoSignal:
    video_id: str
    title: str
    channel_title: str
    channel_id: str
    published_at: str
    description: str
    tags: list[str]
    view_count: int
    like_count: int
    comment_count: int
    source: str
    url: str

    @classmethod
    def from_youtube_item(cls, item: dict, source: str) -> "VideoSignal":
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        video_id = item.get("id") or item.get("contentDetails", {}).get("videoId", "")
        return cls(
            video_id=video_id,
            title=snippet.get("title", ""),
            channel_title=snippet.get("channelTitle", ""),
            channel_id=snippet.get("channelId", ""),
            published_at=snippet.get("publishedAt", ""),
            description=snippet.get("description", ""),
            tags=list(snippet.get("tags", [])),
            view_count=_to_int(statistics.get("viewCount")),
            like_count=_to_int(statistics.get("likeCount")),
            comment_count=_to_int(statistics.get("commentCount")),
            source=source,
            url=f"https://www.youtube.com/watch?v={video_id}",
        )

    def prompt_dict(self) -> dict:
        description = self.description.replace("\n", " ")
        if len(description) > 500:
            description = f"{description[:500]}..."
        return {
            "video_id": self.video_id,
            "title": self.title,
            "channel": self.channel_title,
            "published_at": self.published_at,
            "views": self.view_count,
            "likes": self.like_count,
            "comments": self.comment_count,
            "source": self.source,
            "url": self.url,
            "tags": self.tags[:12],
            "description": description,
        }

    def score(self) -> float:
        source_bonus = 1.25 if self.source.startswith("fifa") else 1.0
        engagement = self.view_count + (self.like_count * 6) + (self.comment_count * 12)
        return math.log1p(max(engagement, 0)) * source_bonus


@dataclass(frozen=True)
class TopicPackage:
    topic_title: str
    angle: str
    script: str
    broll_queries: list[str]
    youtube_title: str
    youtube_description: str
    hashtags: list[str]
    source_video_ids: list[str]

    @classmethod
    def from_dict(cls, data: dict) -> "TopicPackage":
        return cls(
            topic_title=str(data.get("topic_title") or data.get("title") or "World Cup story"),
            angle=str(data.get("angle") or ""),
            script=str(data.get("script") or ""),
            broll_queries=[str(item) for item in data.get("broll_queries", [])][:10],
            youtube_title=str(data.get("youtube_title") or data.get("topic_title") or "Football trend update"),
            youtube_description=str(data.get("youtube_description") or ""),
            hashtags=[str(item) for item in data.get("hashtags", [])][:12],
            source_video_ids=[str(item) for item in data.get("source_video_ids", [])][:20],
        )


@dataclass(frozen=True)
class BrollAsset:
    keyword: str
    url: str
    duration: float
    width: int
    height: int
    pexels_id: int
    pexels_url: str
    credit: str


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(data, "__dataclass_fields__"):
        serializable = asdict(data)
    elif isinstance(data, list):
        serializable = [asdict(item) if hasattr(item, "__dataclass_fields__") else item for item in data]
    else:
        serializable = data
    path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

