from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file() -> None:
    """Load .env when python-dotenv is installed."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    load_dotenv()


def _csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    youtube_api_key: str | None
    gemini_api_key: str | None
    gemini_model: str
    pexels_api_key: str | None
    google_search_api_key: str | None
    google_search_engine_id: str | None
    x_consumer_key: str | None
    x_consumer_secret: str | None
    x_access_token: str | None
    x_access_token_secret: str | None
    youtube_client_secrets_file: Path
    youtube_token_file: Path
    youtube_upload_privacy_status: str
    youtube_upload_category_id: str
    fifa_channel_handle: str
    trend_regions: list[str]
    max_trending_per_region: int
    max_fifa_uploads: int
    football_keywords: list[str]
    output_dir: Path
    script_seconds: int
    max_signals_for_gemini: int

    @classmethod
    def from_env(cls) -> "Settings":
        load_env_file()
        return cls(
            youtube_api_key=os.getenv("YOUTUBE_API_KEY"),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
            pexels_api_key=os.getenv("PEXELS_API_KEY"),
            google_search_api_key=os.getenv("GOOGLE_SEARCH_API_KEY"),
            google_search_engine_id=os.getenv("GOOGLE_SEARCH_ENGINE_ID"),
            x_consumer_key=os.getenv("X_CONSUMER_KEY"),
            x_consumer_secret=os.getenv("X_CONSUMER_SECRET"),
            x_access_token=os.getenv("X_ACCESS_TOKEN"),
            x_access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
            youtube_client_secrets_file=Path(os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", "client_secret.json")),
            youtube_token_file=Path(os.getenv("YOUTUBE_TOKEN_FILE", "token.json")),
            youtube_upload_privacy_status=os.getenv("YOUTUBE_UPLOAD_PRIVACY_STATUS", "public"),
            youtube_upload_category_id=os.getenv("YOUTUBE_UPLOAD_CATEGORY_ID", "17"),
            fifa_channel_handle=os.getenv("FIFA_CHANNEL_HANDLE", "@FIFA"),
            trend_regions=_csv("YOUTUBE_TREND_REGIONS", "US,GB,IN"),
            max_trending_per_region=_int("MAX_TRENDING_PER_REGION", 25),
            max_fifa_uploads=_int("MAX_FIFA_UPLOADS", 25),
            football_keywords=_csv(
                "FOOTBALL_KEYWORDS",
                "football,soccer,fifa,world cup,worldcup,world cup 2026,2026 world cup,qualifier,qualifiers,fixture,squad,draw,goal,goals,striker,keeper,penalty",
            ),
            output_dir=Path(os.getenv("OUTPUT_DIR", "runs")),
            script_seconds=_int("SCRIPT_SECONDS", 45),
            max_signals_for_gemini=_int("MAX_SIGNALS_FOR_GEMINI", 35),
        )

    def require(self, value: str | None, label: str) -> str:
        if not value:
            raise RuntimeError(f"Missing {label}. Add it to .env or the environment.")
        return value

