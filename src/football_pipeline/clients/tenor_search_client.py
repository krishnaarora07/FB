from __future__ import annotations
import os
import requests
import urllib.parse
from pathlib import Path
from ..config import Settings
from ..models import BrollAsset

class TenorSearchClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def search_videos(self, queries: list[str]) -> list[BrollAsset]:
        """Search Tenor API for MP4 GIFs and return them as BrollAsset objects."""
        assets = []
        
        google_api_key = self.settings.google_search_api_key
        
        for idx, query in enumerate(queries):
            asset = None
            
            if google_api_key:
                try:
                    print(f"  Searching Tenor for MP4 video: '{query}'...")
                    url = f"https://tenor.googleapis.com/v2/search?q={urllib.parse.quote(query)}&key={google_api_key}&limit=1&media_filter=mp4"
                    resp = requests.get(url, timeout=10)
                    resp.raise_for_status()
                    
                    results = resp.json().get("results", [])
                    if results:
                        # Extract the mp4 url
                        media_formats = results[0].get("media_formats", {})
                        best_vid = media_formats.get("mp4", {}).get("url")
                        
                        if best_vid:
                            asset = BrollAsset(
                                id=f"tenor_vid_{idx}",
                                url=best_vid,
                                source="tenor"
                            )
                except Exception as e:
                    print(f"  Tenor API error (Ensure Tenor API is enabled in GCP Console): {e}")
            else:
                print("  Google Search API keys missing. Skipping Tenor Search...")
                
            # Fallback to Pexels Images if Tenor fails or is not enabled
            if not asset:
                print(f"  Falling back to Pexels Image for: '{query}'...")
                try:
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
                print(f"  Warning: No video/image found for '{query}' anywhere.")
                
        return assets
