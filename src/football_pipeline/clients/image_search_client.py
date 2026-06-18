from __future__ import annotations
import os
import requests
from pathlib import Path
from duckduckgo_search import DDGS
from ..config import Settings
from ..models import BrollAsset

class ImageSearchClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def search_images(self, queries: list[str]) -> list[BrollAsset]:
        """Search DuckDuckGo for images and return them as BrollAsset objects."""
        assets = []
        ddgs = DDGS()
        
        for idx, query in enumerate(queries):
            asset = None
            try:
                print(f"  Searching DuckDuckGo Image for: '{query}'...")
                results = ddgs.images(
                    keywords=query,
                    region="wt-wt",
                    safesearch="moderate",
                    size="Large",
                    max_results=3
                )
                
                if results:
                    best_img = results[0]
                    asset = BrollAsset(
                        id=f"ddg_img_{idx}",
                        url=best_img["image"],
                        source="duckduckgo"
                    )
            except Exception as e:
                print(f"  DuckDuckGo error: {e}")
                
            # Fallback to Pexels if DuckDuckGo fails or returns empty
            if not asset:
                print(f"  Falling back to Pexels Image for: '{query}'...")
                try:
                    import urllib.parse
                    api_key = self.settings.require(self.settings.pexels_api_key, "PEXELS_API_KEY")
                    headers = {"Authorization": api_key}
                    clean_query = query.lower().replace("portrait", "").replace("vertical", "").strip()
                    
                    url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(clean_query)}&orientation=portrait&per_page=3"
                    resp = requests.get(url, headers=headers, timeout=10)
                    resp.raise_for_status()
                    photos = resp.json().get("photos", [])
                    
                    if not photos and len(clean_query.split()) > 2:
                        simple_query = " ".join(clean_query.split()[:2])
                        url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(simple_query)}&orientation=portrait&per_page=3"
                        resp = requests.get(url, headers=headers, timeout=10)
                        photos = resp.json().get("photos", [])
                        
                    if photos:
                        photo = photos[0]
                        # Get highest quality portrait image
                        img_url = photo.get("src", {}).get("large2x", photo.get("src", {}).get("original"))
                        if img_url:
                            asset = BrollAsset(
                                id=f"pexels_img_{photo.get('id')}",
                                url=img_url,
                                source="pexels"
                            )
                except Exception as fallback_err:
                    print(f"  Pexels fallback error: {fallback_err}")
            
            if asset:
                assets.append(asset)
            else:
                print(f"  Warning: No image found for '{query}' anywhere.")
                
        return assets
