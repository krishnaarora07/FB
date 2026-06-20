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

    def choose_topic(self, videos: list[VideoSignal], trends: list[str], insights=None) -> TopicPackage:
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

        proven_hashtags = []
        if upload_history_path.exists():
            try:
                upload_history = read_json(upload_history_path)
                last_3 = upload_history[-3:]
                for item in last_3:
                    if "hashtags" in item:
                        proven_hashtags.extend(item["hashtags"])
            except Exception:
                pass
        proven_hashtags = list(dict.fromkeys(proven_hashtags))[:10]

        target_length = self.settings.script_seconds
        hook_pressure = "normal"
        search_terms = []
        viral_seeds = []
        if insights:
            if insights.avg_view_duration:
                target_length = min(insights.avg_view_duration, 20) # FORCE micro-scripts to pass seed audience
                if target_length < 10:
                    hook_pressure = "red_alert"
                elif target_length < 20:
                    hook_pressure = "high"
            search_terms = insights.search_terms
            viral_seeds = insights.viral_seeds
        else:
            target_length = 20 # Default to 20s if no analytics available

        prompt = self._build_prompt(videos, history, analytics_str, trends, target_length, hook_pressure, search_terms, viral_seeds, proven_hashtags)
        # Retry up to three times if Gemini returns an empty response, 429 rate limit, or low virality score
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

            topic_text = None
            if getattr(response, "text", None):
                topic_text = response.text
            elif hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0]
                try:
                    part = candidate.content.parts[0]
                    topic_text = getattr(part, "text", None) or getattr(part, "display_text", None)
                except Exception:
                    pass

            if topic_text:
                data = _parse_jsonish(topic_text)
                if "visual_segments" in data:
                    data["script"] = " ".join([seg.get("text", "") for seg in data["visual_segments"]])
                    data["broll_queries"] = [seg.get("broll_query", "") for seg in data["visual_segments"]]
                topic = TopicPackage.from_dict(data)
                
                # --- Virality Predictor Quality Gate ---
                score_prompt = f"""You are a brutal YouTube shorts critic. Rate this script out of 10 for virality.
Script: "{topic.script}"
Title: "{topic.youtube_title}"

Respond in JSON only: {{"score": 7, "reason": "too slow to hook"}}

Score criteria:
- 9-10: Explosive hook, high drama, strong loop
- 7-8: Good, publishable
- Below 7: REJECT — too boring, too slow, or no hook"""
                
                try:
                    score_response = client.models.generate_content(
                        model=model_name,
                        contents=score_prompt,
                    )
                    score_data = _parse_jsonish(getattr(score_response, "text", "{}"))
                    score = int(score_data.get("score", 10))
                    reason = score_data.get("reason", "")
                    print(f"  Virality Predictor Score: {score}/10 (Reason: {reason})")
                    
                    if score < 7 and attempt < 3:
                        print("  Script rejected for low virality score. Forcing Gemini to rewrite...")
                        prompt += f"\nCRITICAL FEEDBACK FROM PREVIOUS ATTEMPT: Your last script was rejected because: {reason}. Make it much more explosive and dramatic."
                        import time
                        time.sleep(2)
                        continue
                except Exception as e:
                    print(f"  Warning: Virality Predictor failed ({e}), accepting script anyway.")
                    
                self._save_history(history_path, history, topic.topic_title)
                return topic

            if attempt < 3:
                import time
                time.sleep(attempt * 5)
                
        raise RuntimeError(
            "Gemini returned an empty response after 3 attempts - check your API key, model name, and network connectivity."
        )

    def _save_history(self, path: Path, history: list[str], new_topic: str) -> None:
        history.append(new_topic)
        # Keep only the last 50 topics to avoid overflowing the prompt
        write_json(path, history[-50:])

    def _build_prompt(self, videos: list[VideoSignal], history: list[str], analytics_str: str, trends: list[str], target_length: int, hook_pressure: str, search_terms: list[str], viral_seeds: list[str], proven_hashtags: list[str]) -> str:
        signal_limit = self.settings.max_signals_for_gemini
        payload = [video.prompt_dict() for video in videos[:signal_limit]]

        history_str = ""
        if history:
            history_str = "\nCRITICAL: Do NOT repeat or use any of the following previously covered topics:\n"
            for t in history:
                history_str += f"- {t}\n"

        trends_str = ""
        if trends:
            trends_str = "═══════════════════════════════════════════\nGOOGLE SEARCH TRENDS (Real-time Spikes)\n═══════════════════════════════════════════\n"
            trends_str += "The following topics are actively spiking on Google right now. IF one of these overlaps with a YouTube trend, prioritize it highly:\n"
            for tr in trends:
                trends_str += f"- {tr}\n"

        if search_terms:
            trends_str += "\n═══════════════════════════════════════════\nPROVEN YOUTUBE SEARCH TERMS\n═══════════════════════════════════════════\n"
            trends_str += "These are the exact search terms viewers typed to find this channel. PRIORITIZE these heavily:\n"
            for term in search_terms:
                trends_str += f"- {term}\n"

        if viral_seeds:
            trends_str += "\n═══════════════════════════════════════════\nVIRAL SEEDS (DOUBLE DOWN!)\n═══════════════════════════════════════════\n"
            trends_str += "The following topics PREVIOUSLY WENT VIRAL (>1000 views) on your channel. Explore adjacent angles, sequels, or related controversies on these themes. Double down on what works!\n"
            for seed in viral_seeds:
                trends_str += f"- {seed}\n"
                
        hook_instructions = "- Use short punchy sentences. Vary rhythm. Build tension. End with a bang."
        if hook_pressure == "high":
            hook_instructions = "🚨 HIGH PRESSURE: Your opening hook is failing. Viewers are swiping away. Your first sentence MUST be a single explosive statement that creates instant shock."
        elif hook_pressure == "red_alert":
            hook_instructions = "🚨 RED ALERT EMERGENCY: Viewers are swiping away in 3 seconds. Write the most aggressive, controversial opening sentence possible. Make it a question nobody can resist answering."

        hashtag_instructions = '["#FIFAWorldCup2026", "#Football", "#Shorts", "... plus 10-15 highly optimized trending hashtags relevant to the topic"]'
        if proven_hashtags:
            hashtag_instructions = f'["#FIFAWorldCup2026", "#Football", "#Shorts", ... plus these proven high-performing tags: {", ".join(proven_hashtags)}]'

        # Approximate words = target_length * 2.1 (avg speaking rate of 2.1 words/sec)
        word_limit = int(target_length * 2.1)

        return f"""
You are a world-class YouTube Shorts producer and editor with 10 years of experience creating viral football content. You have an obsessive eye for quality, perfect timing, and know exactly which raw footage will hook viewers in the first 0.5 seconds. Your videos regularly hit 1M+ views.

Today is {date.today().isoformat()}.
{history_str}
{analytics_str}
{trends_str}
Your task is to pick ONE trending football topic connected to FIFA World Cup 2026 and produce a complete, ready-to-publish short-form video package. Think like the best football content creator on the internet.

═══════════════════════════════════════════
TOPIC SELECTION — The "Mega-Star" Mandate
═══════════════════════════════════════════
- Act as a master YouTube strategist. Your goal is MAXIMIZING VIEWS, RETENTION, and ENGAGEMENT.
- Analyze the provided Trend Signals. 
- Rule 1: STRICT MEGA-STAR BIAS. Videos about abstract concepts or stadiums get ZERO views. You MUST pick topics revolving around mega-stars (Messi, Ronaldo, Yamal, Mbappe, Zlatan, Neymar).
- Rule 2: Hunt for "Micro-Drama" — referee mistakes, intense rivalries, savage press conference quotes, or locker-room fights. Drama triggers clicks.
- The topic MUST be directly connected to FIFA World Cup 2026.

═══════════════════════════════════════════
SCRIPT — The "Perfect Loop" & Mystery Hooks
═══════════════════════════════════════════
- STRICT LIMIT: Under {word_limit} words (Target video length is {target_length}s). Non-negotiable. Every word must earn its place.
- THE PERFECT LOOP HACK: The final 5 words of your script MUST grammatically connect directly back into the first 5 words of the script so it forms an infinite looping sentence. Example: If the script starts with "Cristiano Ronaldo is finally breaking his silence...", it must end with "...and that is exactly why".
- THE OPEN LOOP HACK: Occasionally (about 50% of the time), start the script with a massive, controversial, unanswered question, and DO NOT answer it until the final 5 seconds.
{hook_instructions}
- NO filler words. NO "in this video". NO "don't forget to like and subscribe".

═══════════════════════════════════════════
B-ROLL SELECTION — Think like a stock video search engine
═══════════════════════════════════════════
You MUST generate EXACTLY ONE visual segment for every single sentence in your script.
For each sentence, describe the VISUAL ACTION you want to see on screen (e.g. "angry football player shouting").
Also specify the `asset_type`: Use "image" for high-quality player shots (Google), and use "gif" for funny memes, intense reactions, or specific short video loops (Tenor). KEEP "gif" LIMITED (mostly use "image").
This 1-to-1 mapping is critical for perfectly synchronizing the images to the TTS audio.

═══════════════════════════════════════════
OUTPUT FORMAT — JSON only, zero markdown
═══════════════════════════════════════════
Return this exact JSON shape with NO extra text before or after:
{{
  "topic_title": "short topic name (max 8 words)",
  "angle": "one electrifying sentence explaining why this topic is unmissable right now",
  "visual_segments": [
    {"text": "First sentence of the script...", "broll_query": "angry football manager shouting", "asset_type": "image"},
    {"text": "Second sentence of the script...", "broll_query": "sad soccer fan crying", "asset_type": "gif"}
  ],
  "youtube_title": "viral upload title under 95 chars with an emoji that creates FOMO",
  "youtube_description": "2-3 explosive sentences that hook readers, naturally weave in highly-searched SEO keywords (like specific player names, teams, and 'Football Shorts'), and end with a controversial question.",
  "hashtags": {hashtag_instructions},
  "is_breaking_news": false // Set to true ONLY if the topic is a massive, breaking event from the last 24 hours (e.g., major injury, massive transfer, live controversy). Otherwise false.
}}

═══════════════════════════════════════════
TREND SIGNALS (YouTube metadata — use as topic inspiration)
═══════════════════════════════════════════
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
