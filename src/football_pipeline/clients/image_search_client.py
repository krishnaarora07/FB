from __future__ import annotations
import os
import requests
from pathlib import Path
import urllib.parse
from ..config import Settings
from ..models import BrollAsset

class ImageSearchClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def search_images(self, queries: list[str]) -> list[BrollAsset]:
        """Search Google Images and return them as BrollAsset objects."""
        assets = []
        
        giphy_api_key = self.settings.giphy_api_key
        if giphy_api_key:
            giphy_api_key = giphy_api_key.strip(' "\'\r\n\t')
        else:
            print("  WARNING: GIPHY_API_KEY is missing from environment. B-roll generation will fail.")
            
        for idx, query in enumerate(queries):
            asset = None
            
            if giphy_api_key:
                try:
                    clean_query = query.replace("portrait", "").replace("vertical", "").strip()
                    print(f"  Searching Giphy for: '{clean_query}'...")
                    
                    url = f"https://api.giphy.com/v1/gifs/search?api_key={giphy_api_key}&q={urllib.parse.quote(clean_query)}&limit=1&rating=pg-13"
                    resp = requests.get(url, timeout=10)
                    if not resp.ok:
                        print(f"  Giphy API error body: {resp.text}")
                    resp.raise_for_status()
                    
                    results = resp.json().get("data", [])
                    if results:
                        # Grab the high-quality mp4 variant of the GIF
                        gif_data = results[0]
                        mp4_url = gif_data.get("images", {}).get("original", {}).get("mp4")
                        if mp4_url:
                            asset = BrollAsset(
                                id=f"giphy_{gif_data.get('id', idx)}",
                                url=mp4_url,
                                source="giphy"
                            )
                except Exception as e:
                    print(f"  Giphy API error: {e}")
            
            if asset:
                assets.append(asset)
            else:
                print(f"  Warning: No GIF found for '{query}'.")
                
        return assets
