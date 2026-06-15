from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .config import Settings
from .models import read_json, write_json
from .pipeline import FootballPipeline, load_broll, load_topic


def _print_path(label: str, path: Path) -> None:
    print(f"{label}: {path.resolve()}")


def collect_command(args: argparse.Namespace, settings: Settings) -> int:
    pipeline = FootballPipeline(settings)
    videos = pipeline.collect()
    write_json(Path(args.out), videos)
    print(f"Collected {len(videos)} football/FIFA signals.")
    _print_path("Signals", Path(args.out))
    return 0


def ideate_command(args: argparse.Namespace, settings: Settings) -> int:
    pipeline = FootballPipeline(settings)
    videos = [TopicSignalAdapter(item) for item in read_json(Path(args.signals))]
    topic = pipeline.ideate(videos)
    write_json(Path(args.out), topic)
    print(topic.topic_title)
    _print_path("Topic", Path(args.out))
    return 0


class TopicSignalAdapter:
    """Tiny adapter so saved signal JSON can be fed back to Gemini."""

    def __init__(self, data: dict) -> None:
        self.data = data

    def prompt_dict(self) -> dict:
        return self.data


def broll_command(args: argparse.Namespace, settings: Settings) -> int:
    pipeline = FootballPipeline(settings)
    topic = load_topic(Path(args.topic))
    broll = pipeline.fetch_broll(topic)
    write_json(Path(args.out), broll)
    print(f"Found {len(broll)} YouTube B-roll clips to download.")
    _print_path("B-roll", Path(args.out))
    return 0


def voiceover_command(args: argparse.Namespace, settings: Settings) -> int:
    pipeline = FootballPipeline(settings)
    topic = load_topic(Path(args.topic))
    output = pipeline.generate_voiceover(topic, Path(args.out).parent)
    if output != Path(args.out):
        Path(args.out).write_bytes(output.read_bytes())
    _print_path("Voiceover", Path(args.out))
    return 0


def render_command(args: argparse.Namespace, settings: Settings) -> int:
    pipeline = FootballPipeline(settings)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    topic = load_topic(Path(args.topic))
    broll = load_broll(Path(args.broll))
    voiceover_path = Path(args.voiceover)
    
    broll_paths = pipeline.download_broll(broll, out_dir)
    final = pipeline.render_video(topic, broll_paths, voiceover_path, out_dir)
    _print_path("Final video", final)
    return 0


def upload_command(args: argparse.Namespace, settings: Settings) -> int:
    pipeline = FootballPipeline(settings)
    topic = load_topic(Path(args.topic))
    url = pipeline.upload_to_youtube(Path(args.file), topic)
    print(url)
    return 0


def run_command(args: argparse.Namespace, settings: Settings) -> int:
    pipeline = FootballPipeline(settings)
    run_dir = Path(args.run_dir) if args.run_dir else pipeline.create_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)

    print("Collecting YouTube trend signals...")
    videos = pipeline.collect()
    write_json(run_dir / "signals.json", videos)

    print("Asking Gemini for the topic and script...")
    topic = pipeline.ideate(videos)
    write_json(run_dir / "topic.json", topic)
    (run_dir / "script.txt").write_text(topic.script, encoding="utf-8")

    print(f"Chosen topic: {topic.topic_title}")
    if args.dry_run:
        _print_path("Run directory", run_dir)
        return 0

    print("Fetching YouTube source video metadata for B-roll...")
    broll = pipeline.fetch_broll(topic)
    write_json(run_dir / "broll.json", broll)

    print("Generating voiceover...")
    voiceover_path = pipeline.generate_voiceover(topic, run_dir)

    if not args.render and not args.upload:
        print("Prepared assets. Pass --render to build the final video locally with MoviePy.")
        _print_path("Run directory", run_dir)
        return 0

    print("Downloading B-roll assets...")
    broll_paths = pipeline.download_broll(broll, run_dir)

    print("Rendering video locally with MoviePy...")
    final_path = pipeline.render_video(topic, broll_paths, voiceover_path, run_dir)
    _print_path("Final video", final_path)

    if args.upload:
        if not final_path:
            raise RuntimeError("Cannot upload because no final video file was downloaded.")
        print("Uploading to YouTube...")
        youtube_url = pipeline.upload_to_youtube(final_path, topic)
        print(youtube_url)

    _print_path("Run directory", run_dir)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Football trend video pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect")
    collect.add_argument("--out", required=True)
    collect.set_defaults(func=collect_command)

    ideate = subparsers.add_parser("ideate")
    ideate.add_argument("--signals", required=True)
    ideate.add_argument("--out", required=True)
    ideate.set_defaults(func=ideate_command)

    broll = subparsers.add_parser("broll")
    broll.add_argument("--topic", required=True)
    broll.add_argument("--out", required=True)
    broll.set_defaults(func=broll_command)

    voiceover = subparsers.add_parser("voiceover")
    voiceover.add_argument("--topic", required=True)
    voiceover.add_argument("--out", required=True)
    voiceover.set_defaults(func=voiceover_command)

    render = subparsers.add_parser("render")
    render.add_argument("--topic", required=True)
    render.add_argument("--broll", required=True)
    render.add_argument("--voiceover", required=True)
    render.add_argument("--out", required=True)
    render.set_defaults(func=render_command)

    upload = subparsers.add_parser("upload")
    upload.add_argument("--file", required=True)
    upload.add_argument("--topic", required=True)
    upload.set_defaults(func=upload_command)

    run = subparsers.add_parser("run")
    run.add_argument("--dry-run", action="store_true", help="Stop after topic/script generation.")
    run.add_argument("--render", action="store_true", help="Render the video locally.")
    run.add_argument("--upload", action="store_true", help="Upload the rendered video to YouTube.")
    run.add_argument("--run-dir")
    run.set_defaults(func=run_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    try:
        return args.func(args, settings)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
