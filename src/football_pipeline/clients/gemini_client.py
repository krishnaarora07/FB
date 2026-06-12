from __future__ import annotations

import json
import re
from datetime import date

from ..config import Settings
from ..models import TopicPackage, VideoSignal


def _parse_jsonish(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


class GeminiTopicClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def choose_topic(self, videos: list[VideoSignal]) -> TopicPackage:
        api_key = self.settings.require(self.settings.gemini_api_key, "GEMINI_API_KEY or GOOGLE_API_KEY")
        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError("Install google-genai to use Gemini: pip install -e .") from exc

        client = genai.Client(api_key=api_key)
        prompt = self._build_prompt(videos)
        response = client.models.generate_content(
            model=self.settings.gemini_model,
            contents=prompt,
        )
        return TopicPackage.from_dict(_parse_jsonish(response.text or ""))

    def _build_prompt(self, videos: list[VideoSignal]) -> str:
        signal_limit = self.settings.max_signals_for_gemini
        payload = [video.prompt_dict() for video in videos[:signal_limit]]
        return f"""
You are a sharp football video producer making a short-form YouTube video for fans following the FIFA World Cup 2026 conversation.

Today is {date.today().isoformat()}. Use the YouTube metadata below as trend signals, not as footage to reuse.

Pick one timely, football-specific topic that is explicitly connected to the upcoming FIFA World Cup 2026. Then write a quirky, high-retention voiceover script for about {self.settings.script_seconds} seconds.

Rules:
- Do not invent match results, injuries, transfers, or fixtures that are not supported by the metadata.
- The chosen topic must connect to FIFA World Cup 2026, national teams, squads, qualifiers, fixtures, venues, stars, tactical storylines, or fan debates.
- Avoid pure club-football topics unless the angle clearly explains why they matter for World Cup 2026.
- Make the script punchy and playful, but not cringe.
- Include concrete B-roll search queries for Pexels. Use visual search terms, not abstract terms.
- Output JSON only. No markdown.

Return this exact JSON shape:
{{
  "topic_title": "short topic name",
  "angle": "one sentence explaining the chosen angle",
  "script": "voiceover script",
  "broll_queries": ["portrait football stadium", "soccer fans cheering"],
  "youtube_title": "upload title under 95 chars",
  "youtube_description": "2-4 sentence upload description with source context and Pexels credit reminder",
  "hashtags": ["#FIFAWorldCup", "#Football"],
  "source_video_ids": ["youtube ids that informed the choice"]
}}

Trend signals:
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
