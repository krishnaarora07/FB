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
            results = []
            
            if giphy_api_key:
                try:
                    clean_query = query.replace("portrait", "").replace("vertical", "").strip()
                    
                    # Giphy limits queries to 50 chars, causing 414 URI Too Long errors
                    if len(clean_query) > 45:
                        clean_query = " ".join(clean_query[:45].split(" ")[:-1])
                        
                    print(f"  Searching Giphy for: '{clean_query}'...")
                    
                    url = f"https://api.giphy.com/v1/gifs/search?api_key={giphy_api_key}&q={urllib.parse.quote(clean_query)}&limit=5&rating=pg-13"
                    resp = requests.get(url, timeout=10)
                    if not resp.ok:
                        print(f"  Giphy API error body: {resp.text}")
                    resp.raise_for_status()
                    
                    results = resp.json().get("data", [])
                    for gif_idx, gif_data in enumerate(results):
                        mp4_url = gif_data.get("images", {}).get("original", {}).get("mp4")
                        if mp4_url:
                            asset = BrollAsset(
                                id=f"giphy_{gif_data.get('id', str(idx) + '_' + str(gif_idx))}",
                                url=mp4_url,
                                source="giphy"
                            )
                            assets.append(asset)
                            
                except Exception as e:
                    print(f"  Giphy API error: {e}")
            
            if not results:
                print(f"  Warning: No GIF found for '{query}'.")
                
        return assets
