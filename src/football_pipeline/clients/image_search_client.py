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
        
        # Load Google API Keys (will fail gracefully to Pexels if missing)
        google_api_key = self.settings.google_search_api_key
        google_cx = self.settings.google_search_engine_id
        
        for idx, query in enumerate(queries):
            asset = None
            
            if google_api_key and google_cx:
                try:
                    print(f"  Searching Google Images for: '{query}'...")
                    url = f"https://www.googleapis.com/customsearch/v1?q={urllib.parse.quote(query)}&key={google_api_key}&cx={google_cx}&searchType=image&num=3"
                    resp = requests.get(url, timeout=10)
                    resp.raise_for_status()
                    
                    results = resp.json().get("items", [])
                    if results:
                        best_img = results[0]["link"]
                        asset = BrollAsset(
                            id=f"google_img_{idx}",
                            url=best_img,
                            source="google"
                        )
                except Exception as e:
                    print(f"  Google Image error: {e}")
            else:
                print("  Google Search API keys missing. Skipping Google Search...")
                
            # Fallback to Pexels if Google fails, returns empty, or keys are missing
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
