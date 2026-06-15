from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from ..config import Settings
from ..models import TopicPackage, VideoSignal, read_json, write_json


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
        # Retrieve API key, raise if missing
        api_key = self.settings.require(self.settings.gemini_api_key, "GEMINI_API_KEY or GOOGLE_API_KEY")
        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError("Install google-genai to use Gemini: pip install -e .") from exc

        client = genai.Client(api_key=api_key)
        # Use default Gemini model if not configured
        model_name = getattr(self.settings, "gemini_model", None) or "gemini-3.5-flash"
        
        history_path = Path("topic_history.json")
        history = []
        if history_path.exists():
            try:
                history = read_json(history_path)
            except Exception:
                pass

        prompt = self._build_prompt(videos, history)
        # Retry up to three times if Gemini returns an empty response or 429 rate limit
        for attempt in range(1, 4):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
            except genai.errors.ClientError as exc:
                if attempt < 3 and exc.code == 429:
                    import time
                    print(f"  Gemini rate limit exceeded. Waiting 35 seconds... (Attempt {attempt}/3)")
                    time.sleep(35)
                    continue
                raise

            # Prefer response.text if available
            if getattr(response, "text", None):
                topic = TopicPackage.from_dict(_parse_jsonish(response.text))
                self._save_history(history_path, history, topic.topic_title)
                return topic
            # Fallback: extract text from first candidate if present
            if hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0]
                # Different library versions may expose parts differently
                try:
                    part = candidate.content.parts[0]
                    candidate_text = getattr(part, "text", None) or getattr(part, "display_text", None)
                except Exception:
                    candidate_text = None
                if candidate_text:
                    topic = TopicPackage.from_dict(_parse_jsonish(candidate_text))
                    self._save_history(history_path, history, topic.topic_title)
                    return topic
            # If no text, wait and retry (exponential back‑off)
            if attempt < 3:
                import time
                time.sleep(attempt * 5)
        # After three attempts, raise a clear error
        raise RuntimeError(
            "Gemini returned an empty response after 3 attempts – check your API key, model name, and network connectivity."
        )

    def _save_history(self, path: Path, history: list[str], new_topic: str) -> None:
        history.append(new_topic)
        # Keep only the last 50 topics to avoid overflowing the prompt
        write_json(path, history[-50:])

    def _build_prompt(self, videos: list[VideoSignal], history: list[str]) -> str:
        signal_limit = self.settings.max_signals_for_gemini
        payload = [video.prompt_dict() for video in videos[:signal_limit]]
        
        history_str = ""
        if history:
            history_str = "\nCRITICAL: Do NOT repeat or use any of the following previously covered topics:\n"
            for t in history:
                history_str += f"- {t}\n"

        return f"""
You are a sharp football video producer making a short-form YouTube video for fans following the FIFA World Cup 2026 conversation.

Today is {date.today().isoformat()}. Use the YouTube metadata below as trend signals, not as footage to reuse.
{history_str}
Pick one timely, football-specific topic that is explicitly connected to the upcoming FIFA World Cup 2026. Then write a quirky, high-retention voiceover script.

Rules:
- CRITICAL: The script MUST be strictly under 95 words. If it is longer, the video will exceed the 60-second YouTube Shorts limit and be rejected.
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
  "source_video_ids": ["MUST include exactly 4 or 5 different youtube video ids from the signals to ensure we have diverse B-roll"]
}}

Trend signals:
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
