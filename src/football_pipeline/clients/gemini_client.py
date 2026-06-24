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

    def choose_topic(self, videos: list[VideoSignal], trends: list[str], news, insights=None) -> TopicPackage:
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
                            matching_item = next((item for item in last_3 if item.get("video_id") == sv.video_id), None)
                            title = matching_item.get("topic_title", sv.title) if matching_item else sv.title
                            analytics_str += f"- Topic: '{title}' -> Views: {sv.views if hasattr(sv, 'views') else sv.view_count}, Likes: {sv.likes if hasattr(sv, 'likes') else sv.like_count}, Comments: {sv.comments if hasattr(sv, 'comments') else sv.comment_count}\n"
                            
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
                if insights.avg_view_duration < 15:
                    hook_pressure = "red_alert"
                elif insights.avg_view_duration < 25:
                    hook_pressure = "high"
            search_terms = insights.search_terms
            viral_seeds = insights.viral_seeds
            
        # Ensure videos are at least 30 seconds as requested by the user
        target_length = max(30, self.settings.script_seconds)

        prompt = self._build_prompt(videos, history, analytics_str, trends, news, target_length, hook_pressure, search_terms, viral_seeds, proven_hashtags)
        # Retry up to three times if Gemini returns an empty response, 429 rate limit, or low virality score
        for attempt in range(1, 11):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                break
            except genai.errors.APIError as exc:
                if attempt < 10 and getattr(exc, 'code', 500) in (429, 503, 500, 502, 504):
                    import time
                    wait_time = min(30, 5 * attempt)
                    print(f"  Gemini API error ({getattr(exc, 'code', 'unknown')}) on {model_name}. Waiting {wait_time}s...", flush=True)
                    
                    # If it's a 429 Quota error, try falling back to older/lighter models
                    if getattr(exc, 'code', 500) == 429 and attempt >= 3:
                        if model_name == "gemini-3.5-flash":
                            model_name = "gemini-2.0-flash"
                            print(f"  Switching to fallback model: {model_name}", flush=True)
                        elif model_name == "gemini-2.0-flash":
                            model_name = "gemini-1.5-flash"
                            print(f"  Switching to fallback model: {model_name}", flush=True)

                    time.sleep(wait_time)
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
                    # Flatten the new broll_queries array format into the old list format for compatibility
                    bq = []
                    for seg in data["visual_segments"]:
                        if "broll_queries" in seg:
                            bq.extend(seg["broll_queries"])
                        elif "broll_query" in seg:
                            bq.append(seg["broll_query"])
                    data["broll_queries"] = bq
                topic = TopicPackage.from_dict(data)
                
                # --- Virality Predictor Quality Gate ---
                score_prompt = f"""You are a strict YouTube Shorts critic. Rate this script out of 10 for engagement, pacing, and factual integrity.
Script: "{topic.script}"
Title: "{topic.youtube_title}"

Respond in JSON only: {{"score": 7, "reason": "too slow to hook"}}

Score criteria:
- Automatically 0 if the story contains FAKE NEWS, fabricated drama, or hallucinated details.
- 9-10: Excellent hook, fast-paced, highly engaging, strong infinite loop, 100% FACTUAL.
- 7-8: Good, publishable, 100% FACTUAL.
- Below 7: REJECT — too boring, too slow, or weak hook"""
                
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

    def _build_prompt(self, videos: list[VideoSignal], history: list[str], analytics_str: str, trends: list[str], news, target_length: int, hook_pressure: str, search_terms: list[str], viral_seeds: list[str], proven_hashtags: list[str]) -> str:
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
                
        news_str = ""
        if news:
            news_str = "\n═══════════════════════════════════════════\nLIVE BREAKING NEWS (REAL SOURCE OF TRUTH)\n═══════════════════════════════════════════\n"
            news_str += "You MUST choose a story from these REAL live news items. DO NOT invent stories. DO NOT hallucinate events that aren't mentioned here.\n"
            for n in news[:30]:
                news_str += f"- [{n.source}] {n.title}\n  Summary: {n.description}\n"

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
You are an expert YouTube Shorts producer and editor specializing in highly-engaging, factual football (soccer) content.

Today is {date.today().isoformat()}.
{history_str}
{analytics_str}
{trends_str}
{news_str}
Your task is to analyze the provided LIVE BREAKING NEWS and produce a complete, ready-to-publish short-form video package based on ONE highly trending football topic.

═══════════════════════════════════════════
1. TOPIC SELECTION & FACTUAL ACCURACY
═══════════════════════════════════════════
- Select ONE highly trending football story EXCLUSIVELY from the LIVE BREAKING NEWS section above.
- Use the TREND SIGNALS and GOOGLE SEARCH TRENDS to decide *which* of the live news stories will go the most viral, but the facts of the story MUST come from the news feed.
- STRICT FACTUAL ACCURACY: You are a journalistic channel. You MUST NOT invent fake quotes, fake transfer rumors, or fake news. All statistics, event details, and stories must be 100% true based on the provided live news. Do NOT hallucinate.

═══════════════════════════════════════════
2. SCRIPT WRITING & PACING
═══════════════════════════════════════════
- MAXIMUM LENGTH: Under {word_limit} words (Target video length is {target_length}s). This is a strict hard limit.
- The script must be punchy, engaging, and fast-paced.
- THE INFINITE LOOP: The final sentence of your script MUST grammatically connect directly back into the very first sentence so the video seamlessly loops. (Example: End with "...and that explains why" if the video starts with "Lionel Messi is leaving his club...")
{hook_instructions}
- No filler words, introductions like "in this video", or outro requests like "like and subscribe". Get straight to the facts.

═══════════════════════════════════════════
3. VISUALS (GIPHY B-ROLL)
═══════════════════════════════════════════
Our visual engine strictly uses GIPHY to download short video clips.
- You MUST generate EXACTLY ONE visual segment for every single sentence in your script.
- For each sentence, provide an array of 2 to 3 `broll_queries`. These MUST be EXTREMELY short and broad (1-3 words max).
- Giphy's search is very literal and fails on complex phrases. Use basic nouns and simple actions.
- Instead of "Ronaldo celebrating a goal with his teammates", use just "Ronaldo goal" or "Ronaldo".
- Examples of good Giphy queries: "Messi sad", "Guardiola", "football fans", "referee", "red card".
- DO NOT write full sentences for queries. Keep them as broad, accurate, and short as possible.

═══════════════════════════════════════════
4. OUTPUT FORMAT (STRICT JSON)
═══════════════════════════════════════════
Return this exact JSON shape with NO extra text before or after:
{{
  "topic_title": "short descriptive topic name (max 8 words)",
  "angle": "one sentence explaining why this topic is currently trending",
  "visual_segments": [
    {{"text": "First sentence of the script...", "broll_queries": ["Ronaldo celebrating goal", "Portugal fans cheering"]}},
    {{"text": "Second sentence of the script...", "broll_queries": ["football fan crying", "sad soccer player"]}}
  ],
  "youtube_title": "viral upload title under 95 chars with a relevant emoji",
  "youtube_description": "2-3 engaging sentences naturally weaving in SEO keywords (player names, teams, 'Football Shorts').",
  "hashtags": {hashtag_instructions},
  "is_breaking_news": false // True ONLY if the event happened in the last 24-48 hours
}}

═══════════════════════════════════════════
TREND SIGNALS (YouTube metadata — use as topic inspiration)
═══════════════════════════════════════════
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
