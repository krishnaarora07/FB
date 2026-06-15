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
            except genai.errors.APIError as exc:
                if attempt < 3 and getattr(exc, 'code', 500) in (429, 503, 500, 502, 504):
                    import time
                    print(f"  Gemini API error ({getattr(exc, 'code', 'unknown')}). Waiting 35 seconds... (Attempt {attempt}/3)")
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
            # If no text, wait and retry (exponential back-off)
            if attempt < 3:
                import time
                time.sleep(attempt * 5)
        # After three attempts, raise a clear error
        raise RuntimeError(
            "Gemini returned an empty response after 3 attempts - check your API key, model name, and network connectivity."
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
You are a world-class YouTube Shorts producer and editor with 10 years of experience creating viral football content. You have an obsessive eye for quality, perfect timing, and know exactly which raw footage will hook viewers in the first 0.5 seconds. Your videos regularly hit 1M+ views.

Today is {date.today().isoformat()}.
{history_str}
Your task is to pick ONE trending football topic connected to FIFA World Cup 2026 and produce a complete, ready-to-publish short-form video package. Think like the best football content creator on the internet.

═══════════════════════════════════════════
TOPIC SELECTION — Think like a journalist + hype-man
═══════════════════════════════════════════
- Choose the single most viral, debate-worthy, or emotionally charged World Cup 2026 topic in the metadata.
- Prioritize: surprise transfers, shocking squad snubs, underdog nations, tactical controversies, star player drama, record-breaking stats.
- Avoid boring "preview" or "recap" topics. Make people feel something.
- The topic MUST be directly connected to FIFA World Cup 2026 (national teams, qualifiers, squads, venues, fan culture, tactical stories).

═══════════════════════════════════════════
SCRIPT — Think like the best football narrator on YouTube
═══════════════════════════════════════════
- STRICT LIMIT: Under 95 words. Non-negotiable. Every word must earn its place.
- Hook in the first 5 words — make the viewer incapable of scrolling past.
- Use short punchy sentences. Vary rhythm. Build tension. End with a bang.
- Write like you are talking to a football-obsessed 18-year-old, not a journalist.
- NO filler words. NO "in this video". NO "don't forget to like and subscribe".
- Style: confident, passionate, slightly dramatic. Like a match day commentator at 90+3.
- NEVER invent facts, stats, or results not supported by the metadata.

═══════════════════════════════════════════
B-ROLL SELECTION — Think like a top video editor
═══════════════════════════════════════════
You must select exactly 4-5 YouTube video IDs for B-roll footage. These will be downloaded and cut. Think of yourself as the lead editor choosing the actual raw footage for each scene. Find clips that are visually explosive and perfectly match the story.

MANDATORY SCORING — only pick videos that score HIGH on ALL of these:
- VISUAL IMPACT: Is it cinematic? Dynamic camera work? Slow-mo? Close-up player emotion?
- RELEVANCE: Does it directly show what the script talks about? (players, stadiums, matches, goals)
- AUTHENTICITY: Is it raw match footage, fan cam, or player compilation? Not a talking head.
- DIVERSITY: Pick clips that show DIFFERENT scenes (stadium crowd, goal moment, player skill, fan reaction)

HARD BANS — automatically disqualify any video matching these:
- Official FIFA YouTube channel (copyright strike guaranteed)
- Any Hindi news channel (watermarks everywhere)
- Talking heads, podcasts, vlogging-to-camera, or panel shows
- Photo slideshows or static image compilations
- Videos with massive broadcaster watermarks (Sky Sports, beIN Sports, DAZN, ESPN, etc.)
- Any video from a major sports broadcaster or rights holder

IDEAL B-ROLL SOURCES:
- Independent football fan channels uploading raw match footage
- Player skills/compilation channels without heavy watermarks
- Amateur fan-cam stadium recordings
- Viral football moments reuploaded by fan accounts
- Tactical breakdown channels with clean footage

═══════════════════════════════════════════
OUTPUT FORMAT — JSON only, zero markdown
═══════════════════════════════════════════
Return this exact JSON shape with NO extra text before or after:
{{
  "topic_title": "short topic name (max 8 words)",
  "angle": "one electrifying sentence explaining why this topic is unmissable right now",
  "script": "voiceover script strictly under 95 words — punchy, dynamic, emotional",
  "broll_queries": ["portrait football stadium crowd", "soccer player goal celebration close up", "world cup fan reaction", "football skills dribble"],
  "youtube_title": "viral upload title under 95 chars with an emoji that creates FOMO",
  "youtube_description": "2-3 explosive sentences that hook readers, explain the topic, and end with a question to drive comments",
  "hashtags": ["#FIFAWorldCup2026", "#Football", "#WorldCup", "#Shorts"],
  "source_video_ids": ["exactly 4 or 5 youtube video IDs from the trend signals below that pass ALL B-roll scoring criteria — pure gameplay, player footage, or fan-cam ONLY. NO news channels, NO FIFA official, NO talking heads."]
}}

═══════════════════════════════════════════
TREND SIGNALS (YouTube metadata — use as topic inspiration, pick best IDs for B-roll)
═══════════════════════════════════════════
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
