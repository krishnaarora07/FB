from __future__ import annotations

from ..config import Settings
from ..http import ApiError, request_json
from ..models import BrollAsset


class PexelsClient:
    BASE_URL = "https://api.pexels.com/v1"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.api_key = settings.require(settings.pexels_api_key, "PEXELS_API_KEY")

    def search_broll(self, queries: list[str], per_query: int = 2) -> list[BrollAsset]:
        assets: list[BrollAsset] = []
        seen_ids: set[int] = set()
        for query in queries:
            try:
                response = request_json(
                    "GET",
                    f"{self.BASE_URL}/videos/search",
                    params={
                        "query": query,
                        "orientation": "portrait",
                        "per_page": per_query,
                    },
                    headers={
                        "Authorization": self.api_key,
                        "Accept": "application/json",
                        "User-Agent": "football-trend-pipeline/0.1",
                    },
                )
            except ApiError as exc:
                raise RuntimeError(
                    "Pexels video search failed. Check that PEXELS_API_KEY is valid and enabled for API access."
                ) from exc
            for video in response.get("videos", []):
                pexels_id = int(video.get("id", 0))
                if pexels_id in seen_ids:
                    continue
                file = self._best_video_file(video.get("video_files", []))
                if not file:
                    continue
                seen_ids.add(pexels_id)
                user = video.get("user", {})
                credit_name = user.get("name") or "Pexels creator"
                assets.append(
                    BrollAsset(
                        keyword=query,
                        url=file["link"],
                        duration=float(video.get("duration") or 6),
                        width=int(file.get("width") or 0),
                        height=int(file.get("height") or 0),
                        pexels_id=pexels_id,
                        pexels_url=video.get("url", ""),
                        credit=f"{credit_name} / Pexels",
                    )
                )
        return assets

    @staticmethod
    def _best_video_file(files: list[dict]) -> dict | None:
        if not files:
            return None

        def score(file: dict) -> tuple[int, int, int]:
            width = int(file.get("width") or 0)
            height = int(file.get("height") or 0)
            is_vertical = 1 if height >= width else 0
            quality = 1 if file.get("quality") == "hd" else 0
            pixels = width * height
            return (is_vertical, quality, pixels)

        return sorted(files, key=score, reverse=True)[0]
