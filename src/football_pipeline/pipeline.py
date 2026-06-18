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

    def ideate(self, videos: list[VideoSignal]) -> TopicPackage:
        return GeminiTopicClient(self.settings).choose_topic(videos)

    def fetch_broll(self, topic: TopicPackage) -> list[BrollAsset]:
        print("  Fetching high-quality images from DuckDuckGo for Parallax...")
        from .clients.image_search_client import ImageSearchClient
        return ImageSearchClient(self.settings).search_images(topic.broll_queries)

    def generate_voiceover(self, topic: TopicPackage, run_dir: Path) -> Path:
        return ChatterboxTtsClient(self.settings).create_voiceover(topic.script, run_dir / "voiceover.wav")

    def download_broll(self, broll_assets: list[BrollAsset], run_dir: Path) -> list[Path]:
        import requests
        paths = []
        for i, asset in enumerate(broll_assets):
            # Attempt to extract original extension, default to jpg
            ext = ".jpg"
            if "." in asset.url.split("/")[-1]:
                potential_ext = "." + asset.url.split("/")[-1].split(".")[1][:3]
                if potential_ext.lower() in [".jpg", ".png", ".jpeg", ".webp"]:
                    ext = potential_ext.lower()
                    
            output = run_dir / f"broll_{i}{ext}"
            print(f"  Downloading image {asset.id}...")
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

    def render_video(self, topic: TopicPackage, broll_paths: list[Path], voiceover_path: Path, run_dir: Path) -> Path:
        output_path = run_dir / "final.mp4"
        subtitles_path = voiceover_path.with_suffix('.words.json')
        return build_moviepy_edit(topic, broll_paths, voiceover_path, subtitles_path, output_path)

    def upload_to_youtube(self, video_path: Path, topic: TopicPackage) -> str:
        return YouTubeUploader(self.settings).upload(video_path, topic)


def load_topic(path: Path) -> TopicPackage:
    return TopicPackage.from_dict(read_json(path))


def load_broll(path: Path) -> list[BrollAsset]:
    return [BrollAsset(**item) for item in read_json(path)]

