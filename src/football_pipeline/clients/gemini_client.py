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

        # --- Analytics Feedback Loop ---
        analytics_str = ""
        upload_history_path = Path("upload_history.json")
        if upload_history_path.exists():
            try:
                from .youtube_discovery import YouTubeDiscoveryClient
                yt_client = YouTubeDiscoveryClient(self.settings)
                upload_history = read_json(upload_history_path)
                
                # Get the last 3 video IDs
                last_3 = upload_history[-3:]
                video_ids = [item.get("video_id") for item in last_3 if item.get("video_id")]
                
                if video_ids:
                    stats_videos = yt_client.videos_by_ids(video_ids, "analytics_feedback")
                    if stats_videos:
                        analytics_str = "\n═══════════════════════════════════════════\nANALYTICS FEEDBACK — Learn from your past videos!\n═══════════════════════════════════════════\n"
                        analytics_str += "Here is how your recent videos performed. If a topic got high views/comments, DO MORE OF THAT. If it tanked, DO LESS.\n"
                        for sv in stats_videos:
                            matching_item = next((item for item in last_3 if item.get("video_id") == sv.id), None)
                            title = matching_item.get("topic_title", sv.title) if matching_item else sv.title
                            analytics_str += f"- Topic: '{title}' -> Views: {sv.views}, Likes: {sv.likes}, Comments: {sv.comments}\n"
            except Exception as exc:
                print(f"  Warning: Failed to fetch analytics feedback: {exc}")

        prompt = self._build_prompt(videos, history, analytics_str)
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

    def _build_prompt(self, videos: list[VideoSignal], history: list[str], analytics_str: str) -> str:
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
{analytics_str}
Your task is to pick ONE trending football topic connected to FIFA World Cup 2026 and produce a complete, ready-to-publish short-form video package. Think like the best football content creator on the internet.

═══════════════════════════════════════════
TOPIC SELECTION — Think like a 10M-subscriber YouTuber
═══════════════════════════════════════════
- Act as a master YouTube strategist. Your goal is MAXIMIZING VIEWS, RETENTION, and ENGAGEMENT.
- Analyze the provided Trend Signals. 
- Rule 1: If there is a MASSIVE breaking news story (a huge transfer, a World Cup upset, a massive injury), pick that.
- Rule 2: If it is a slow news day, IGNORE BORING STATS. Instead, explicitly hunt for "Micro-Drama" — referee mistakes, intense rivalries, savage press conference quotes, or locker-room fights. Drama triggers clicks.
- The topic MUST be directly connected to FIFA World Cup 2026.

═══════════════════════════════════════════
SCRIPT — The "Perfect Loop" & Mystery Hooks
═══════════════════════════════════════════
- STRICT LIMIT: Under 95 words. Non-negotiable. Every word must earn its place.
- THE PERFECT LOOP HACK: The final 5 words of your script MUST grammatically connect directly back into the first 5 words of the script so it forms an infinite looping sentence. Example: If the script starts with "Cristiano Ronaldo is finally breaking his silence...", it must end with "...and that is exactly why".
- THE OPEN LOOP HACK: Occasionally (about 50% of the time), start the script with a massive, controversial, unanswered question, and DO NOT answer it until the final 5 seconds.
- Use short punchy sentences. Vary rhythm. Build tension. End with a bang.
- NO filler words. NO "in this video". NO "don't forget to like and subscribe".

═══════════════════════════════════════════
B-ROLL SELECTION — Think like a stock video search engine
═══════════════════════════════════════════
You must generate 4-5 highly specific search queries to find the perfect B-roll on Google Images or Pexels.
Describe the VISUAL ACTION you want to see on screen (e.g. "angry football player shouting").

═══════════════════════════════════════════
OUTPUT FORMAT — JSON only, zero markdown
═══════════════════════════════════════════
Return this exact JSON shape with NO extra text before or after:
{{
  "topic_title": "short topic name (max 8 words)",
  "angle": "one electrifying sentence explaining why this topic is unmissable right now",
  "script": "voiceover script strictly under 95 words — punchy, dynamic, emotional",
  "broll_queries": ["sad soccer fan crying", "football player scoring goal slow motion", "angry football manager shouting", "stadium crowd cheering crazy"],
  "youtube_title": "viral upload title under 95 chars with an emoji that creates FOMO",
  "youtube_description": "2-3 explosive sentences that hook readers, naturally weave in highly-searched SEO keywords (like specific player names, teams, and 'Football Shorts'), and end with a controversial question.",
  "hashtags": ["#FIFAWorldCup2026", "#Football", "#Shorts", "... plus 10-15 highly optimized trending hashtags relevant to the topic to maximize algorithm discovery"]
}}

═══════════════════════════════════════════
TREND SIGNALS (YouTube metadata — use as topic inspiration)
═══════════════════════════════════════════
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
