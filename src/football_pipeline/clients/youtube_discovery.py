from __future__ import annotations

from .youtube_util import chunked
from ..config import Settings
from ..http import request_json
from ..models import VideoSignal
from ..signal_processing import dedupe_videos, is_football_related, rank_videos


class YouTubeDiscoveryClient:
    BASE_URL = "https://www.googleapis.com/youtube/v3"
    SPORTS_CATEGORY_ID = "17"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.api_key = settings.require(settings.youtube_api_key, "YOUTUBE_API_KEY")

    def _get(self, resource: str, params: dict) -> dict:
        params = dict(params)
        params["key"] = self.api_key
        return request_json("GET", f"{self.BASE_URL}/{resource}", params=params)

    def most_popular_sports(self, region_code: str, max_results: int) -> list[VideoSignal]:
        response = self._get(
            "videos",
            {
                "part": "snippet,statistics,contentDetails",
                "chart": "mostPopular",
                "regionCode": region_code,
                "videoCategoryId": self.SPORTS_CATEGORY_ID,
                "maxResults": min(max_results, 50),
            },
        )
        return [VideoSignal.from_youtube_item(item, f"trending:{region_code}") for item in response.get("items", [])]

    def channel_upload_playlist_id(self, handle: str) -> str:
        response = self._get(
            "channels",
            {
                "part": "snippet,contentDetails",
                "forHandle": handle,
                "maxResults": 1,
            },
        )
        items = response.get("items", [])
        if not items:
            raise RuntimeError(f"No YouTube channel found for handle {handle}")
        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    def playlist_video_ids(self, playlist_id: str, max_results: int) -> list[str]:
        ids: list[str] = []
        page_token: str | None = None
        while len(ids) < max_results:
            response = self._get(
                "playlistItems",
                {
                    "part": "contentDetails",
                    "playlistId": playlist_id,
                    "maxResults": min(50, max_results - len(ids)),
                    **({"pageToken": page_token} if page_token else {}),
                },
            )
            ids.extend(item["contentDetails"]["videoId"] for item in response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return ids

    def videos_by_ids(self, video_ids: list[str], source: str) -> list[VideoSignal]:
        videos: list[VideoSignal] = []
        for batch in chunked(video_ids, 50):
            response = self._get(
                "videos",
                {
                    "part": "snippet,statistics,contentDetails",
                    "id": ",".join(batch),
                    "maxResults": len(batch),
                },
            )
            videos.extend(VideoSignal.from_youtube_item(item, source) for item in response.get("items", []))
        return videos

    def recent_channel_videos(self, handle: str, max_results: int) -> list[VideoSignal]:
        playlist_id = self.channel_upload_playlist_id(handle)
        ids = self.playlist_video_ids(playlist_id, max_results)
        return self.videos_by_ids(ids, f"fifa:{handle}")

    def collect(self) -> list[VideoSignal]:
        videos: list[VideoSignal] = []
        for region in self.settings.trend_regions:
            videos.extend(self.most_popular_sports(region, self.settings.max_trending_per_region))
        videos.extend(self.recent_channel_videos(self.settings.fifa_channel_handle, self.settings.max_fifa_uploads))

        filtered = [
            video
            for video in dedupe_videos(videos)
            if video.source.startswith("fifa") or is_football_related(video, self.settings.football_keywords)
        ]
        return rank_videos(filtered)

