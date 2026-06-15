from __future__ import annotations

import random
import urllib.parse

from ..config import Settings
from ..models import BrollAsset

class PexelsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def search_broll(self, queries: list[str]) -> list[BrollAsset]:
        import requests
        api_key = self.settings.require(self.settings.pexels_api_key, "PEXELS_API_KEY")
        headers = {"Authorization": api_key}
        
        assets = []
        for query in queries:
            url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(query)}&orientation=portrait&per_page=5"
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                videos = data.get("videos", [])
                if videos:
                    # Pick a random video from top 5
                    video = random.choice(videos)
                    files = video.get("video_files", [])
                    # Filter and sort files (e.g., HD under 1080p width)
                    hd_files = [f for f in files if f.get("quality") == "hd" and f.get("width", 2000) <= 1080]
                    if hd_files:
                        hd_files.sort(key=lambda x: x.get("width", 0), reverse=True)
                        best_file = hd_files[0]
                    elif files:
                        best_file = files[0]
                    else:
                        continue
                        
                    asset = BrollAsset(
                        id=str(video.get("id")),
                        url=best_file.get("link"),
                        source="pexels"
                    )
                    assets.append(asset)
            except Exception as e:
                print(f"  Warning: Pexels API failed for query '{query}': {e}")
                
        return assets
