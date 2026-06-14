from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .clients.edge_tts_client import EdgeTtsClient
from .clients.gemini_client import GeminiTopicClient
from .clients.pexels_client import PexelsClient
from .clients.youtube_discovery import YouTubeDiscoveryClient
from .config import Settings
from .moviepy_edit import build_moviepy_edit
from .models import BrollAsset, TopicPackage, VideoSignal, read_json, write_json
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
        queries = topic.broll_queries or ["portrait soccer stadium", "football fans cheering", "soccer ball close up"]
        return PexelsClient(self.settings).search_broll(queries)

    def generate_voiceover(self, topic: TopicPackage, run_dir: Path) -> Path:
        return EdgeTtsClient(self.settings).create_voiceover(topic.script, run_dir / "voiceover.mp3")

    def download_broll(self, broll_assets: list[BrollAsset], run_dir: Path) -> list[Path]:
        import urllib.request
        paths = []
        for i, asset in enumerate(broll_assets):
            output = run_dir / f"broll_{i}.mp4"
            print(f"  Downloading B-roll {i} from Pexels...")
            req = urllib.request.Request(
                asset.url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            )
            with urllib.request.urlopen(req) as response, open(output, 'wb') as out_file:
                out_file.write(response.read())
            paths.append(output)
        return paths

    def render_video(self, topic: TopicPackage, broll_paths: list[Path], voiceover_path: Path, run_dir: Path) -> Path:
        output_path = run_dir / "final.mp4"
        return build_moviepy_edit(topic, broll_paths, voiceover_path, output_path)

    def upload_to_youtube(self, video_path: Path, topic: TopicPackage) -> str:
        return YouTubeUploader(self.settings).upload(video_path, topic)


def load_topic(path: Path) -> TopicPackage:
    return TopicPackage.from_dict(read_json(path))


def load_broll(path: Path) -> list[BrollAsset]:
    return [BrollAsset(**item) for item in read_json(path)]

