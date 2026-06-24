from __future__ import annotations

import json
import re
import time
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
        # Use best available model; falls back through verified chain on quota/errors
        model_name = getattr(self.settings, "gemini_model", None) or "gemini-2.5-pro"

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

        base_prompt = self._build_prompt(videos, history, analytics_str, trends, news, target_length, hook_pressure, search_terms, viral_seeds, proven_hashtags)
        # All verified models ordered best quality → most available (verified 2026-06-25)
        fallback_chain = [
            "gemini-2.5-pro",        # Best quality
            "gemini-3.5-flash",      # Latest flash gen
            "gemini-3.1-pro-preview",# Newer pro preview
            "gemini-2.5-flash",      # Stable, high quality flash
            "gemini-2.5-flash-lite", # Lighter 2.5, higher quota
            "gemini-2.0-flash",      # Reliable older gen
            "gemini-2.0-flash-lite", # High free-tier quota
            "gemini-flash-latest",   # Alias - ultimate fallback
        ]

        # Ensure starting model is in the chain; if not, prepend it
        if model_name not in fallback_chain:
            fallback_chain = [model_name] + fallback_chain

        # Outer loop: retry topic generation if virality score is too low
        for generation_attempt in range(1, 4):  # max 3 topic generations
            prompt = base_prompt
            if generation_attempt > 1:
                print(f"  Retrying topic generation (attempt {generation_attempt}/3)...", flush=True)

            # Inner loops: try each model with up to 5 retries each
            response = None
            used_model = model_name
            for candidate_model in fallback_chain:
                print(f"  Trying model: {candidate_model}", flush=True)
                for attempt in range(1, 6):  # 5 attempts per model
                    try:
                        from google.genai import types as genai_types
                        response = client.models.generate_content(
                            model=candidate_model,
                            contents=prompt,
                            config=genai_types.GenerateContentConfig(
                                temperature=0.2,  # Low = less hallucination
                                top_p=0.8,
                            )
                        )
                        used_model = candidate_model
                        break  # success — exit inner retry loop
                    except genai.errors.APIError as exc:
                        import time
                        err_code = getattr(exc, 'code', 500)

                        if err_code == 404:
                            print(f"  Model {candidate_model} not found (404), skipping.", flush=True)
                            break
                        elif err_code in (429, 503, 500, 502, 504):
                            wait_time = min(10, 5 * attempt)
                            print(f"  Gemini API error ({err_code}) on {candidate_model}. Waiting {wait_time}s... (attempt {attempt}/5)", flush=True)
                            time.sleep(wait_time)
                        else:
                            raise  # Unknown error — don't retry
                else:
                    print(f"  Model {candidate_model} exhausted all retries. Trying next fallback...", flush=True)
                    response = None
                    continue

                if response is not None:
                    break  # exit model loop on success

            if response is None:
                raise RuntimeError(
                    "All Gemini models exhausted after multiple retries. Check your API key and quota."
                )

            # Parse response
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

            if not topic_text:
                raise RuntimeError("Gemini returned an empty response — check your API key and model.")

            data = _parse_jsonish(topic_text)
            if "visual_segments" in data:
                data["script"] = " ".join([seg.get("text", "") for seg in data["visual_segments"]])
                bq = []
                for seg in data["visual_segments"]:
                    if "broll_queries" in seg:
                        bq.extend(seg["broll_queries"])
                    elif "broll_query" in seg:
                        bq.append(seg["broll_query"])
                data["broll_queries"] = bq

            # --- Citation Validation --- 
            # Check that the cited headline actually exists in the news feed
            cited_headline = data.get("source_headline", "")
            if cited_headline and news:
                news_titles_lower = [n.title.lower() for n in news]
                cited_words = cited_headline.lower().split()
                # Check if at least the first 4 words of the citation match any headline
                key_words = cited_words[:4]
                match_found = any(
                    all(w in title for w in key_words) for title in news_titles_lower
                ) if key_words else False
                if not match_found:
                    print(f"  ⚠️ Hallucination risk: cited headline not found in news feed. Sending to virality gate.", flush=True)
                else:
                    print(f"  ✅ Citation verified in news feed.", flush=True)
            elif not cited_headline:
                print(f"  ⚠️ No source_headline cited — Gemini did not anchor to a news story.", flush=True)

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

            score = 10  # default pass if scoring fails
            reason = ""
            try:
                from google.genai import types as genai_types
                score_response = client.models.generate_content(
                    model=used_model,
                    contents=score_prompt,
                    config=genai_types.GenerateContentConfig(
                        temperature=0.0,  # Fully deterministic for scoring
                    )
                )
                score_data = _parse_jsonish(getattr(score_response, "text", "{}"))
                score = int(score_data.get("score", 10))
                reason = score_data.get("reason", "")
                print(f"  Virality Predictor Score: {score}/10 (Reason: {reason})", flush=True)
            except Exception as e:
                print(f"  Warning: Virality Predictor failed ({e}), accepting script anyway.", flush=True)

            # ENFORCE the quality gate — reject fake news and low-scoring scripts
            if score < 7:
                if generation_attempt < 3:
                    print(f"  ❌ Script REJECTED (score {score}/10). Forcing a rewrite with feedback...", flush=True)
                    base_prompt += f"\n\nCRITICAL REJECTION FEEDBACK: Your previous script was scored {score}/10 and REJECTED because: {reason}. You MUST fix this. Write a completely different, 100% FACTUAL story from the news feed. Do NOT hallucinate or fabricate ANY details."
                    continue  # retry outer generation loop
                else:
                    print(f"  ⚠️ Score still {score}/10 after {generation_attempt} attempts — accepting best available script.", flush=True)

            self._save_history(history_path, history, topic.topic_title)
            return topic

        # Should never reach here, but safety net
        raise RuntimeError("Failed to generate a passing script after 3 attempts.")

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
            news_str = "\n═══════════════════════════════════════════\nLIVE FOOTBALL NEWS FEED\n═══════════════════════════════════════════\n"
            news_str += (
                "Sources are tagged [VERIFIED] or [RUMOUR].\n"
                "- [VERIFIED] = confirmed by reputable journalism (BBC, Guardian, Sky, Independent). "
                "You MAY state these as confirmed facts.\n"
                "- [RUMOUR] = tabloid/gossip speculation, not independently confirmed. "
                "You MUST frame these as 'reportedly', 'sources claim', or 'according to reports' — NEVER as confirmed fact.\n"
                "You MUST choose a story from this feed. DO NOT invent or hallucinate ANY details not present here.\n\n"
            )
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
Your task is to produce a complete, ready-to-publish YouTube Shorts video package based on ONE story from the news feed above.

⚠️ ANTI-HALLUCINATION CONTRACT — READ CAREFULLY ⚠️
You are bound to these rules. Breaking ANY of them = automatic score of 0 and rejection:
1. Base your script on ONE story explicitly present in the LIVE FOOTBALL NEWS FEED above.
2. Do NOT invent, extrapolate, or add ANY details not stated in the news item. No fabricated scores, quotes, bans, injuries, transfers or statistics.
3. Do NOT combine details from two different stories into one fictional narrative.
4. [RUMOUR] sources: use hedged language only: "reportedly", "sources claim", "according to reports". NEVER state as fact.
5. If unsure of a detail — leave it out. A shorter, factual script is better than a longer hallucinated one.

FORBIDDEN (score 0):
✗ Adding injuries/bans/scores not in the news item
✗ Inventing player quotes
✗ Mixing two players from different articles into one story
✗ Any statistic you cannot directly copy from the news text

═══════════════════════════════════════════
1. TOPIC SELECTION & FACTUAL ACCURACY
═══════════════════════════════════════════
- Select ONE story EXCLUSIVELY from the LIVE FOOTBALL NEWS FEED above.
- Pick the story most likely to go viral based on TREND SIGNALS, but ALL facts MUST come verbatim from that news item.
- If no exciting story exists, pick the most interesting factual one — do NOT add drama that isn't there.

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
Return ONLY this exact JSON with NO extra text before or after:
{{
  "source_headline": "EXACT headline copied word-for-word from the news feed this script is based on",
  "topic_title": "short descriptive topic name (max 8 words)",
  "angle": "one sentence explaining why this topic is currently trending",
  "visual_segments": [
    {{"text": "First sentence of the script...", "broll_queries": ["keyword1", "keyword2"]}},
    {{"text": "Second sentence...", "broll_queries": ["keyword1", "keyword2"]}}
  ],
  "youtube_title": "viral upload title under 95 chars with a relevant emoji",
  "youtube_description": "2-3 engaging sentences naturally weaving in SEO keywords (player names, teams, 'Football Shorts').",
  "hashtags": {hashtag_instructions},
  "is_breaking_news": false
}}

MANDATORY: The "source_headline" field must be the EXACT headline from the news feed. This is used to verify you did not hallucinate.

═══════════════════════════════════════════
TREND SIGNALS (YouTube metadata — use as topic inspiration)
═══════════════════════════════════════════
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
