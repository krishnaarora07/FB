import os
import sys
from pathlib import Path
import requests

# Add src to path
repo_root = Path(r"C:\Users\krish\Documents\fb")
sys.path.insert(0, str(repo_root / "src"))

from football_pipeline.clients.image_search_client import ImageSearchClient
from football_pipeline.config import Settings
from football_pipeline.moviepy_edit import build_moviepy_edit
from football_pipeline.models import TopicPackage

def test_parallax():
    from dotenv import load_dotenv
    load_dotenv(repo_root / ".env")
    
    class MockSettings:
        pexels_api_key = os.environ.get("PEXELS_API_KEY", "")
        def require(self, val, name):
            return val
            
    settings = MockSettings()
    client = ImageSearchClient(settings)
    
    # 1. Search for an image
    queries = ["Lionel Messi holding world cup trophy"]
    assets = client.search_images(queries)
    if not assets:
        print("No assets found.")
        return
        
    asset = assets[0]
    print(f"Found image: {asset.url}")
    
    # 2. Download it
    run_dir = repo_root / "caption_test"
    run_dir.mkdir(exist_ok=True)
    img_path = run_dir / "test_parallax.jpg"
    
    resp = requests.get(asset.url, stream=True, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    with open(img_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
            
    print(f"Downloaded image to {img_path}")
    
    # 3. Process it using the internal moviepy_edit logic
    sys.path.insert(0, str(repo_root / "src"))
    
    # We can just extract _create_parallax_clip from moviepy_edit.py
    # But since it's nested inside build_moviepy_edit, let's copy it here just for testing
    import numpy as np
    from PIL import Image, ImageFilter
    from moviepy.editor import ImageClip, CompositeVideoClip
    from rembg import remove

    print("Running rembg...")
    input_img = Image.open(img_path).convert("RGBA")
    fg_img = remove(input_img)
    print("Background removed.")
    
    target_ratio = 1080 / 1920.0
    w, h = input_img.size
    img_ratio = w / h
    
    if img_ratio > target_ratio:
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        bg_crop = input_img.crop((left, 0, left + new_w, h))
        fg_crop = fg_img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        bg_crop = input_img.crop((0, top, w, top + new_h))
        fg_crop = fg_img.crop((0, top, w, top + new_h))
        
    bg_img = bg_crop.resize((1080, 1920), Image.Resampling.LANCZOS)
    bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=15))
    fg_img = fg_crop.resize((1080, 1920), Image.Resampling.LANCZOS)
    
    length = 4.0
    
    def resize_bg(t):
        return 1.1 - 0.05 * (t / length)
        
    def resize_fg(t):
        return 1.0 + 0.05 * (t / length)

    bg_clip = ImageClip(np.array(bg_img.convert("RGB"))).set_duration(length)
    bg_clip = bg_clip.resize(resize_bg).set_position("center")
    
    fg_clip = ImageClip(np.array(fg_img)).set_duration(length)
    fg_clip = fg_clip.resize(resize_fg).set_position("center")
    
    comp = CompositeVideoClip([bg_clip, fg_clip], size=(1080, 1920)).set_duration(length)
    
    out_vid = run_dir / "parallax_out.mp4"
    print(f"Writing parallax video to {out_vid}")
    comp.write_videofile(str(out_vid), fps=30, codec="libx264")
    print("Done!")

if __name__ == "__main__":
    test_parallax()
