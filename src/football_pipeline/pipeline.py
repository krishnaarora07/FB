from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .clients.edge_tts_client import EdgeTtsClient
from .clients.gemini_client import GeminiTopicClient

from .clients.youtube_discovery import YouTubeDiscoveryClient
from .config import Settings
from .moviepy_edit import build_moviepy_edit
from .models import TopicPackage, VideoSignal, YouTubeClip, read_json, write_json
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

    def fetch_broll(self, topic: TopicPackage) -> list[YouTubeClip]:
        # Instead of searching Pexels, we just use the source videos the AI selected.
        return [
            YouTubeClip(video_id=vid, url=f"https://www.youtube.com/watch?v={vid}")
            for vid in topic.source_video_ids
        ]

    def generate_voiceover(self, topic: TopicPackage, run_dir: Path) -> Path:
        return EdgeTtsClient(self.settings).create_voiceover(topic.script, run_dir / "voiceover.mp3")

    def download_broll(self, broll_assets: list[YouTubeClip], run_dir: Path) -> list[Path]:
        import yt_dlp
        paths = []
        for i, asset in enumerate(broll_assets):
            output = run_dir / f"broll_{i}.mp4"
            print(f"  Downloading 15-second clip of YouTube video {asset.video_id} using yt-dlp...")
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]/bestvideo',
                'outtmpl': str(output),
                'download_ranges': yt_dlp.utils.download_range_func(None, [(0, 15)]),
                'force_keyframes_at_cuts': True,
                'quiet': True,
                'no_warnings': True,
            }
            if Path("cookies.txt").exists():
                ydl_opts['cookiefile'] = 'cookies.txt'
                
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([asset.url])
                if output.exists():
                    paths.append(output)
            except Exception as e:
                print(f"  Warning: Failed to download video {asset.video_id}: {e}")
                
        return paths

    def render_video(self, topic: TopicPackage, broll_paths: list[Path], voiceover_path: Path, run_dir: Path) -> Path:
        output_path = run_dir / "final.mp4"
        return build_moviepy_edit(topic, broll_paths, voiceover_path, output_path)

    def upload_to_youtube(self, video_path: Path, topic: TopicPackage) -> str:
        return YouTubeUploader(self.settings).upload(video_path, topic)


def load_topic(path: Path) -> TopicPackage:
    return TopicPackage.from_dict(read_json(path))


def load_broll(path: Path) -> list[YouTubeClip]:
    return [YouTubeClip(**item) for item in read_json(path)]

