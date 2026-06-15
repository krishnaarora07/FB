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
            # Clean query to avoid confusing Pexels API
            clean_query = query.lower().replace("portrait", "").replace("vertical", "").strip()
            
            # Re-added orientation=portrait as requested
            url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(clean_query)}&orientation=portrait&per_page=3"
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                videos = data.get("videos", [])
                
                # Fallback: If highly specific query yields 0 results, try a broader 2-word query
                if not videos and len(clean_query.split()) > 2:
                    simple_query = " ".join(clean_query.split()[:2])
                    print(f"  Pexels found 0 results for '{clean_query}'. Falling back to '{simple_query}'...")
                    url_fallback = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(simple_query)}&orientation=portrait&per_page=3"
                    resp_fallback = requests.get(url_fallback, headers=headers, timeout=10)
                    if resp_fallback.status_code == 200:
                        videos = resp_fallback.json().get("videos", [])

                if videos:
                    # Pick one of the top 2 most relevant results (don't randomize top 5)
                    video = random.choice(videos[:2])
                    files = video.get("video_files", [])
                    
                    if files:
                        # Grab the absolute highest resolution available
                        files.sort(key=lambda x: x.get("height", 0), reverse=True)
                        best_file = files[0]
                        
                        asset = BrollAsset(
                            id=str(video.get("id")),
                            url=best_file.get("link"),
                            source="pexels"
                        )
                        assets.append(asset)
            except Exception as e:
                print(f"  Warning: Pexels API failed for query '{query}': {e}")
                
        return assets
