from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .clients.gtts_client import GTTSClient
from .clients.gemini_client import GeminiTopicClient
from .clients.pexels_client import PexelsClient
from .clients.shotstack_client import ShotstackClient
from .clients.creatomate_client import CreatomateClient
from .clients.youtube_discovery import YouTubeDiscoveryClient
from .config import Settings
from .creatomate_edit import build_creatomate_edit
from .http import request_bytes
from .models import BrollAsset, TopicPackage, VideoSignal, read_json, write_json
from .shotstack_edit import build_shotstack_edit
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
        return GTTSClient(self.settings).create_voiceover(topic.script, run_dir / "voiceover.mp3")

    def build_edit_json(self, topic: TopicPackage, broll: list[BrollAsset], voiceover_url: str) -> dict:
        return build_creatomate_edit(
            topic=topic,
            broll_assets=broll,
            voiceover_url=voiceover_url,
            target_seconds=self.settings.script_seconds,
        )

    def render(self, edit: dict) -> tuple[str, dict, str | None]:
        client = CreatomateClient(self.settings)
        render_id = client.render(edit)
        print(f"  Started Creatomate render: {render_id}")
        response = client.wait_for_render(render_id)
        return render_id, response, client.find_output_url(response)

    def upload_voiceover_to_shotstack(self, voiceover_path: Path) -> str:
        return ShotstackClient(self.settings).upload_file(voiceover_path, content_type="audio/mpeg")

    def download_render(self, render_url: str, run_dir: Path) -> Path:
        output = run_dir / "final.mp4"
        import urllib.request
        print("  Downloading rendered video from Shotstack...")
        urllib.request.urlretrieve(render_url, str(output))
        return output

    def upload_to_youtube(self, video_path: Path, topic: TopicPackage) -> str:
        return YouTubeUploader(self.settings).upload(video_path, topic)


def load_topic(path: Path) -> TopicPackage:
    return TopicPackage.from_dict(read_json(path))


def load_broll(path: Path) -> list[BrollAsset]:
    return [BrollAsset(**item) for item in read_json(path)]

