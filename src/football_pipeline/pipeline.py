from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .clients.chatterbox_tts_client import ChatterboxTtsClient
from .clients.gemini_client import GeminiTopicClient

from .clients.youtube_discovery import YouTubeDiscoveryClient
from .config import Settings
from .moviepy_edit import build_moviepy_edit
from .models import TopicPackage, VideoSignal, BrollAsset, read_json, write_json
from .youtube_upload import YouTubeUploader


class FootballPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_run_dir(self) -> Path:
        run_dir = Path(self.settings.output_dir).resolve() / datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def collect(self) -> list[VideoSignal]:
        return YouTubeDiscoveryClient(self.settings).collect()

    def get_insights(self):
        from .clients.analytics_client import YouTubeAnalyticsClient
        return YouTubeAnalyticsClient(self.settings).get_insights()

    def ideate(self, videos: list[VideoSignal], insights=None) -> TopicPackage:
        from .clients.trends_client import GoogleTrendsClient
        from .clients.rss_client import RSSClient
        trends = GoogleTrendsClient(self.settings).get_football_trends()
        news = RSSClient().fetch_news(limit_per_feed=15)
        return GeminiTopicClient(self.settings).choose_topic(videos, trends, news, insights)

    def fetch_broll(self, topic: TopicPackage) -> list[BrollAsset]:
        print("  Fetching dynamic B-roll strictly from Giphy...")
        from .clients.giphy_client import GiphyClient
        
        assets = []
        giphy_client = GiphyClient(self.settings)
        
        if hasattr(topic, "visual_segments") and topic.visual_segments:
            for idx, seg in enumerate(topic.visual_segments):
                queries = seg.get("broll_queries", [])
                if not queries:
                    query = seg.get("broll_query", "")
                    if query: queries = [query]
                
                for q_idx, query in enumerate(queries):
                    res = giphy_client.search_gifs(query, limit=1)
                    if res:
                        single_asset = res[0]
                        single_asset = BrollAsset(id=f"seg_{idx}_{single_asset.id}_{q_idx}", url=single_asset.url, source=single_asset.source)
                        assets.append(single_asset)
        else:
            # Fallback for old topics
            for idx, query in enumerate(topic.broll_queries):
                res = giphy_client.search_gifs(query, limit=1)
                if res:
                    for single_asset in res:
                        single_asset = BrollAsset(id=f"seg_{idx}_{single_asset.id}", url=single_asset.url, source=single_asset.source)
                        assets.append(single_asset)
            
        return assets

    def generate_voiceover(self, topic: TopicPackage, run_dir: Path) -> Path:
        return ChatterboxTtsClient(self.settings).create_voiceover(topic.script, run_dir / "voiceover.wav")

    def download_broll(self, broll_assets: list[BrollAsset], run_dir: Path) -> list[Path]:
        import requests
        paths = []
        for i, asset in enumerate(broll_assets):
            # Attempt to extract original extension, default to jpg
            ext = ".mp4" if asset.source in ["tenor", "giphy"] else ".jpg"
            if "." in asset.url.split("/")[-1]:
                parsed = asset.url.split("/")[-1].split("?")[0]
                if "." in parsed:
                    potential_ext = "." + parsed.split(".")[-1].lower()
                    if potential_ext in [".jpg", ".png", ".jpeg", ".webp", ".mp4"]:
                        ext = potential_ext
                    
            import re
            safe_id = re.sub(r'[^a-zA-Z0-9_]', '_', asset.id)
            output = run_dir / f"broll_{i}_{safe_id}{ext}"
            print(f"  Downloading asset {asset.id} -> {output.name}...")
            try:
                # Add User-Agent since some image hosts block default requests User-Agent
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                resp = requests.get(asset.url, stream=True, timeout=15, headers=headers)
                resp.raise_for_status()
                with open(output, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                paths.append(output)
            except Exception as e:
                print(f"  Warning: Failed to download image {asset.id}: {e}")
                
        return paths

    def render_video(self, topic: TopicPackage, broll_paths: list[Path], voiceover_path: Path, run_dir: Path, insights=None) -> Path:
        output_path = run_dir / "final.mp4"
        subtitles_path = voiceover_path.with_suffix('.words.json')
        return build_moviepy_edit(topic, broll_paths, voiceover_path, subtitles_path, output_path, insights)

    def upload_to_youtube(self, video_path: Path, topic: TopicPackage, insights=None) -> str:
        from .youtube_upload import YouTubeUploader
        video_id, scheduled_for = YouTubeUploader(self.settings).upload(video_path, topic, insights)
        
        # Save to upload_history.json for Analytics Feedback Loop
        history_path = Path("upload_history.json")
        import json
        history = []
        if history_path.exists():
            try:
                history = json.loads(history_path.read_text(encoding="utf-8"))
            except Exception:
                pass
                
        history.append({
            "video_id": video_id,
            "topic_title": topic.topic_title,
            "youtube_title": topic.youtube_title,
            "scheduled_for": scheduled_for,
            "hashtags": topic.hashtags,
            "viral_story_type": getattr(topic, "viral_story_type", ""),
            "debate_bait_comment": getattr(topic, "debate_bait_comment", ""),
        })
        history_path.write_text(json.dumps(history[-50:], indent=2, ensure_ascii=False), encoding="utf-8")
        
        return f"https://www.youtube.com/watch?v={video_id}"


def load_topic(path: Path) -> TopicPackage:
    return TopicPackage.from_dict(read_json(path))


def load_broll(path: Path) -> list[BrollAsset]:
    return [BrollAsset(**item) for item in read_json(path)]

