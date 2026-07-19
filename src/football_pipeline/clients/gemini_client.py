from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path

from ..config import Settings
from ..models import TopicPackage, VideoSignal, read_json, write_json


def _parse_jsonish(text: str) -> dict:
    """Parse a JSON object from a Gemini response that may contain surrounding markdown
    fences or trailing conversational text after the JSON block.

    Strategy:
    1. Strip markdown fences (```json ... ```).
    2. Try a direct parse — fast path for well-formed responses.
    3. If the error is "Extra data", Gemini appended text *after* a valid JSON block.
       Slice the string at the reported error position and re-parse — this is precise.
    4. Last resort: extract the first {...} span with a non-greedy regex and re-parse.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Strategy 3: "Extra data" means valid JSON exists before e.pos — slice it off.
        if e.msg.startswith("Extra data"):
            try:
                return json.loads(cleaned[: e.pos].strip())
            except json.JSONDecodeError:
                pass  # fall through to regex strategy

        # Strategy 4: non-greedy regex to grab the first complete {...} block.
        match = re.search(r"\{.*?\}", cleaned, flags=re.DOTALL)
        if not match:
            raise e
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            raise e


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

        # (Hashtag recycling removed to prevent algorithm topic confusion)

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

        base_prompt = self._build_prompt(videos, history, analytics_str, trends, news, target_length, hook_pressure, search_terms, viral_seeds)

        # Free-tier Gemini models — ordered best quality → most quota available (July 2026)
        # Pro models (gemini-3.1-pro, gemini-2.5-pro) are PAID tier only — excluded.
        # Deprecated (removed): gemini-2.0-flash, gemini-2.0-flash-lite (June 2026)
        fallback_chain = [
            "gemini-3.5-flash",      # Best free-tier quality — agentic, 1M context, GA May 2026
            "gemini-2.5-flash",      # Proven workhorse — ~15 RPM / 1500 RPD free tier
            "gemini-2.5-flash-lite", # Higher quota, lighter — good middle safety net
            "gemini-3.1-flash-lite", # Ultra-low latency, highest free-tier RPM — last resort
        ]

        # Ensure starting model is in the chain; if not, prepend it
        if model_name not in fallback_chain:
            fallback_chain = [model_name] + fallback_chain

        # Track quota-exhausted models across ALL generation attempts so we never retry them
        quota_exhausted = set()

        # Outer loop: retry topic generation if virality score is too low
        for generation_attempt in range(1, 4):  # max 3 topic generations
            prompt = base_prompt
            if generation_attempt > 1:
                print(f"  Retrying topic generation (attempt {generation_attempt}/3)...", flush=True)

            # Build the effective chain for this attempt — skip exhausted models
            active_chain = [m for m in fallback_chain if m not in quota_exhausted]
            if not active_chain:
                raise RuntimeError("All Gemini models hit quota limits. Try again tomorrow or upgrade your plan.")

            response = None
            used_model = model_name
            for candidate_model in active_chain:
                print(f"  Trying model: {candidate_model}", flush=True)
                model_succeeded = False
                for attempt in range(1, 4):  # Max 3 attempts per model (not 5 — fail faster)
                    try:
                        from google.genai import types as genai_types
                        response = client.models.generate_content(
                            model=candidate_model,
                            contents=prompt,
                            config=genai_types.GenerateContentConfig(
                                temperature=0.5,  # Increased for more engaging scripts since sources are now verified
                                top_p=0.8,
                                response_mime_type="application/json"
                            )
                        )
                        used_model = candidate_model
                        model_succeeded = True
                        break  # success — exit inner retry loop
                    except genai.errors.APIError as exc:
                        err_code = getattr(exc, 'code', 500)

                        if err_code == 404:
                            print(f"  Model {candidate_model} not found (404), skipping permanently.", flush=True)
                            quota_exhausted.add(candidate_model)
                            break
                        elif err_code == 429:
                            # Quota exhausted — no point retrying, move on immediately
                            print(f"  Model {candidate_model} quota exhausted (429), skipping permanently.", flush=True)
                            quota_exhausted.add(candidate_model)
                            break
                        elif err_code in (503, 500, 502, 504):
                            # Transient server error — worth retrying with backoff
                            wait_time = min(10, 5 * attempt)
                            print(f"  Gemini API error ({err_code}) on {candidate_model}. Waiting {wait_time}s... (attempt {attempt}/3)", flush=True)
                            time.sleep(wait_time)
                        else:
                            raise  # Unknown error — don't retry

                if not model_succeeded:
                    response = None
                    continue

                if response is not None:
                    break  # exit model loop on success

            if response is None:
                exhausted_str = ", ".join(quota_exhausted) if quota_exhausted else "none logged"
                raise RuntimeError(
                    f"All Gemini models exhausted. Quota-hit models: [{exhausted_str}]. "
                    "Daily limits reset at midnight Pacific. Check https://aistudio.google.com/app/quotas"
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

            # --- Deterministic Infinite-Loop Connector Check ---
            # Validate that the script's last sentence echoes a word/phrase from the first.
            import re as _re
            sentences = [seg.get("text", "").strip() for seg in (data.get("visual_segments") or []) if seg.get("text", "").strip()]
            loop_ok = False
            loop_feedback = ""
            if len(sentences) >= 2:
                first_words = set(_re.findall(r'\b[a-zA-Z]{4,}\b', sentences[0].lower()))
                last_words  = set(_re.findall(r'\b[a-zA-Z]{4,}\b', sentences[-1].lower()))
                loop_ok = bool(first_words & last_words)  # at least one 4+ letter word shared
            else:
                loop_ok = False  # REJECT IF TOO SHORT TO FORM A LOOP

            if not loop_ok:
                print("  ⚠️ LOOP CHECK FAILED: last sentence shares no key words with first sentence.", flush=True)
                loop_feedback = (
                    "\n\nLOOP REJECTION: Your script has NO INFINITE LOOP. "
                    "The LAST sentence MUST echo a keyword from the FIRST sentence so the video "
                    "seamlessly repeats. Example connectors: 'And that's exactly why ...', "
                    "'Which brings us back to ...', 'So when you see ... again, now you know why.'"
                )
            else:
                print("  ✅ Infinite loop connector verified.", flush=True)

            # --- Virality Predictor Quality Gate ---
            score_prompt = f"""You are a strict YouTube Shorts critic. Rate this script out of 10.
Script: "{topic.script}"
Title: "{topic.youtube_title}"

Respond in JSON only: {{"score": 7, "reason": "short explanation", "loop_present": true}}

Score criteria (ALL must pass for 9-10):
- Automatically 0 if FAKE NEWS, fabricated drama, or hallucinated details are detected. 
  CRITICAL RULE: "Fake News" ONLY means information that contradicts or adds to the provided LIVE NEWS FEED. 
  DO NOT fact-check the script against your internal historical knowledge (e.g., stating "this match hasn't happened recently"), because your training data is outdated. If it matches the news feed, it is FACT.
- Automatically 0 if the final sentence does NOT connect back to the opening (missing infinite loop).
- 9-10: Explosive hook, punchy pacing, verified facts, AND a clear infinite loop connector.
- 7-8: Solid, publishable, factual, has a loop connector.
- Below 7: REJECT — too boring, slow hook, weak pacing, or missing infinite loop.

Infinite loop means: the last sentence must grammatically and thematically lead back into the first 
sentence so a viewer watching on repeat feels the video never ends."""

            score = 10  # default pass if scoring fails
            reason = ""
            try:
                from google.genai import types as genai_types
                score_response = client.models.generate_content(
                    model=used_model,
                    contents=score_prompt,
                    config=genai_types.GenerateContentConfig(
                        temperature=0.0,  # Fully deterministic for scoring
                        response_mime_type="application/json"
                    )
                )
                score_data = _parse_jsonish(getattr(score_response, "text", "{}"))
                score = int(score_data.get("score", 10))
                reason = score_data.get("reason", "")
                loop_present = score_data.get("loop_present", True)
                print(f"  Virality Predictor Score: {score}/10 (Reason: {reason}, Loop: {loop_present})", flush=True)
            except Exception as e:
                print(f"  Warning: Virality Predictor failed ({e}), accepting script anyway.", flush=True)

            # ENFORCE the quality gate — reject fake news, weak scripts, and missing loops
            if score < 7 or not loop_ok:
                if generation_attempt < 3:
                    rejection_reason = reason if score < 7 else "missing infinite loop connector"
                    print(f"  ❌ Script REJECTED (score {score}/10, loop_ok={loop_ok}). Forcing a rewrite...", flush=True)
                    base_prompt += (
                        f"\n\nCRITICAL REJECTION FEEDBACK: Your previous script was scored {score}/10 "
                        f"and REJECTED because: {rejection_reason}. "
                        "Write a completely different, 100% FACTUAL story from the news feed. "
                        "Do NOT hallucinate ANY details."
                        + loop_feedback
                    )
                    continue  # retry outer generation loop
                else:
                    print(f"  ⚠️ Score {score}/10 / loop_ok={loop_ok} after {generation_attempt} attempts — accepting best available script.", flush=True)

            self._save_history(history_path, history, topic.topic_title)
            return topic

        # Should never reach here, but safety net
        raise RuntimeError("Failed to generate a passing script after 3 attempts.")

    def _save_history(self, path: Path, history: list[str], new_topic: str) -> None:
        history.append(new_topic)
        # Keep only the last 50 topics to avoid overflowing the prompt
        write_json(path, history[-50:])

    def _build_prompt(self, videos: list[VideoSignal], history: list[str], analytics_str: str, trends: list[str], news, target_length: int, hook_pressure: str, search_terms: list[str], viral_seeds: list[str]) -> str:
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
            news_str = "\n\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\nLIVE FOOTBALL NEWS FEED\n\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\n"
            news_str += (
                "Sources are tagged [VERIFIED] or [RUMOUR].\n"
                "- [VERIFIED] = confirmed by reputable journalism. You MAY state as confirmed fact.\n"
                "- [RUMOUR] = unconfirmed speculation. MUST use 'reportedly', 'sources claim' etc.\n"
                "You MUST choose a story from this feed. DO NOT hallucinate any detail not present here.\n\n"
            )
            # Stories are pre-sorted by viral_score desc then recency desc.
            # Split into HOT (score >= 6) and regular so Gemini sees priority clearly.
            hot    = [n for n in news if getattr(n, "viral_score", 0) >= 6][:15]
            normal = [n for n in news if getattr(n, "viral_score", 0) <  6][:30]

            if hot:
                news_str += (
                    "\ud83d\udd25 HOT STORIES (highest viral potential \u2014 STRONGLY PREFER one of these):\n\n"
                )
                for n in hot:
                    vs = getattr(n, "viral_score", 0)
                    news_str += f"- [{n.source}] [score={vs}] {n.title}\n  Summary: {n.description}\n"

            if normal:
                news_str += "\n\ud83d\udcf0 OTHER STORIES (use only if no HOT story suits a viral angle):\n\n"
                for n in normal:
                    news_str += f"- [{n.source}] {n.title}\n  Summary: {n.description}\n"


        hook_instructions = "- Use short punchy sentences. Vary rhythm. Build tension. End with a bang."
        if hook_pressure == "high":
            hook_instructions = "🚨 HIGH PRESSURE: Your opening hook is failing. Viewers are swiping away. Your first sentence MUST be a single explosive statement that creates instant shock."
        elif hook_pressure == "red_alert":
            hook_instructions = "🚨 RED ALERT EMERGENCY: Viewers are swiping away in 3 seconds. Write the most aggressive, controversial opening sentence possible. Make it a question nobody can resist answering."

        hashtag_instructions = '["#FIFAWorldCup2026", "#Football", "#Shorts", "... plus 10-15 highly optimized 100% fresh hashtags specific ONLY to this exact story"]'

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

╔══════════════════════════════════════════════════╗
║   ⚠️  ANTI-HALLUCINATION CONTRACT  ⚠️            ║
╚══════════════════════════════════════════════════╝
Breaking ANY rule below = automatic score of 0 and rejection:
1. Base your script on ONE story explicitly present in the LIVE FOOTBALL NEWS FEED above.
2. Do NOT invent, extrapolate, or add ANY details not stated in the news item.
   → No fabricated scores, quotes, bans, injuries, transfers, or statistics.
3. Do NOT combine details from two different stories into one fictional narrative.
4. [RUMOUR] sources: use hedged language ONLY — "reportedly", "sources claim",
   "according to reports". NEVER state as confirmed fact.
5. If unsure of any detail — leave it out entirely.
   A shorter, factual script beats a longer hallucinated one every time.

FORBIDDEN (instant score 0):
  ✗ Injuries / bans / scores not explicitly in the news item
  ✗ Inventing or paraphrasing player quotes
  ✗ Mixing two players from different articles into one story
  ✗ Any statistic you cannot copy verbatim from the news text
  ✗ Dramatic embellishment beyond what is stated in the source

═══════════════════════════════════════════
STEP 1 — VIRAL STORY TYPE SELECTION
═══════════════════════════════════════════
Before writing a single word of the script, you MUST:
  a) Choose the ONE story from the news feed with the highest viral potential.
  b) Classify it into exactly ONE of these 6 viral emotion types:

  TYPE 1 — SHOCK
     Trigger: A fact that is genuinely surprising and counter-intuitive.
     Example hook style: "[Player] just did something nobody saw coming."
     Anti-hallucination rule: The shocking fact MUST be stated in the news item. Do NOT invent shock.

  TYPE 2 — OUTRAGE
     Trigger: A decision, action, or ruling that a large audience will feel is unfair or absurd.
     Example hook style: "This decision has left football fans furious."
     Anti-hallucination rule: State only what happened — do NOT editorialize beyond the source.

  TYPE 3 — DISBELIEF
     Trigger: A stat, fee, or record that sounds impossible but is real.
     Example hook style: "€300 million. That's the actual number."
     Anti-hallucination rule: The number or record MUST appear verbatim in the news item.

  TYPE 4 — PRIDE / INSPIRATION
     Trigger: A human achievement story — underdog, comeback, cultural milestone.
     Example hook style: "Two years ago he was released. Today he's at the World Cup."
     Anti-hallucination rule: Do NOT embellish the backstory beyond what the source states.

  TYPE 5 — URGENCY
     Trigger: A time-sensitive event — deadline, imminent announcement, window closing.
     Example hook style: "The transfer window closes in 48 hours and [Club] just made their move."
     Anti-hallucination rule: Do NOT state a deadline unless the source explicitly mentions timing.

  TYPE 6 — HUMOUR / ABSURDITY
     Trigger: A genuinely funny or bizarre football moment.
     Example hook style: "Only in football does this happen."
     Anti-hallucination rule: The funny detail MUST be from the source. Do NOT exaggerate.

  Prioritise this order when equally viral: SHOCK > DISBELIEF > URGENCY > OUTRAGE > PRIDE > HUMOUR.
  Output your chosen type in the JSON as "viral_story_type".

═══════════════════════════════════════════
STEP 2 — SCRIPT: VIRAL FORMULA + INVISIBLE LOOP
═══════════════════════════════════════════
MAXIMUM LENGTH: Under {word_limit} words ({target_length}s target). Hard limit — do NOT exceed.

You MUST structure the script using this exact 5-beat formula:

  BEAT 1 — HOOK (1–2 sentences)
    • The very first sentence must create INSTANT intrigue or shock.
    • 3–8 words max for the opening line. No preamble, no context.
    • Start mid-action. "Messi refused." not "In today's video, we look at Messi's contract."
    • Only use facts present in the news item.

  BEAT 2 — TWIST (1–2 sentences)
    • Immediately subvert or deepen the expectation set by the hook.
    • Add the detail that makes the hook make sense — but keep it sharp.
    • Still only facts from the source.

  BEAT 3 — PROOF (1 sentence)
    • One concrete, specific fact — a number, a name, a quote, a source — that makes it real.
    • This is the credibility beat. ONLY use details verbatim from the news item.
    • Format: "According to [source], ..." or just state the fact directly if VERIFIED.

  BEAT 4 — STAKES (1–2 sentences)
    • Why does this matter? Who wins, who loses, what changes?
    • Keep it grounded — extrapolate only what the source implies, not what you invent.

  BEAT 5 — INVISIBLE LOOP (1 sentence)
    ⚠️ THIS IS MACHINE-CHECKED. Missing or generic loops = automatic rejection.
    • The loop sentence must feel like a NATURAL CONTINUATION of the story, NOT a labelled ending.
    • It must echo the exact subject (player name / club / event) from BEAT 1.
    • The viewer should feel the video is still going, not that it just ended.
    • BAD: "What a story. Drop your thoughts below."  ← generic, no echo, rejected.
    • BAD: "And that's why football is amazing."       ← no subject echo, rejected.
    • GOOD (if Beat 1 = "Messi refused €300 million"):
        "And that €300 million refusal? It's the reason Messi's next move will define his legacy."
    • GOOD (if Beat 1 = "The referee missed a clear penalty"):
        "Which is exactly why that referee's name is still trending worldwide."
    • The loop sentence must share at least one 4+ letter keyword with Beat 1. Non-negotiable.

{hook_instructions}
- No filler words, "in this video", "like and subscribe", or meta-commentary. Facts only.

═══════════════════════════════════════════
STEP 3 — VISUALS (GIPHY B-ROLL)
═══════════════════════════════════════════
Our visual engine strictly uses GIPHY to download short video clips.
- You MUST generate EXACTLY ONE visual segment for every single sentence in your script.
- For each sentence, provide an array of 2 to 3 `broll_queries`. EXTREMELY short and broad (1-3 words max).
- Giphy search is very literal. Use basic nouns and simple actions only.
- GOOD examples: "Messi sad", "Guardiola", "football fans", "referee", "red card", "stadium".
- BAD examples: "Ronaldo celebrating a goal with his teammates after a controversial penalty".
- Map each beat visually:
    HOOK   → dramatic action clip (goal, tackle, red card, crowd roar)
    TWIST  → reaction clip (manager shock, player face, fans stunned)
    PROOF  → generic authority visual (press conference, trophy, scoreboard)
    STAKES → wide/epic visual (stadium, flag, crowd celebration or protest)
    LOOP   → echo the Hook clip or a wide stadium shot — completing the visual circle

═══════════════════════════════════════════
STEP 4 — OUTPUT FORMAT (STRICT JSON)
═══════════════════════════════════════════
Return ONLY this exact JSON. NO extra text before or after. NO markdown fences:
{{
  "source_headline": "EXACT headline copied word-for-word from the news feed",
  "viral_story_type": "SHOCK | OUTRAGE | DISBELIEF | PRIDE | URGENCY | HUMOUR",
  "topic_title": "short descriptive topic name (max 8 words)",
  "angle": "one sentence: why this story is viral right now",
  "visual_segments": [
    {{"beat": "HOOK",   "text": "First sentence...",  "broll_queries": ["keyword1", "keyword2"]}},
    {{"beat": "TWIST",  "text": "Second sentence...", "broll_queries": ["keyword1", "keyword2"]}},
    {{"beat": "PROOF",  "text": "Third sentence...",  "broll_queries": ["keyword1", "keyword2"]}},
    {{"beat": "STAKES", "text": "Fourth sentence...", "broll_queries": ["keyword1", "keyword2"]}},
    {{"beat": "LOOP",   "text": "Final sentence — echoes Beat 1 subject.", "broll_queries": ["keyword1", "keyword2"]}}
  ],
  "youtube_title": "Viral title under 95 chars with relevant emoji — must match viral_story_type tone",
  "youtube_description": "2-3 punchy sentences with SEO keywords. MUST end with a binary debate question e.g. 'Right call or massive mistake? Comment below.'",
  "hashtags": {hashtag_instructions},
  "debate_bait_comment": "A single polarising binary question (max 15 words) to pin as first comment",
  "is_breaking_news": false
}}

MANDATORY: "source_headline" must be the EXACT headline from the news feed — used to verify no hallucination.
MANDATORY: "viral_story_type" must be one of the 6 types. Do NOT invent a new type.
MANDATORY: "debate_bait_comment" must be a binary choice question, not open-ended.

═══════════════════════════════════════════
TREND SIGNALS (YouTube metadata — topic inspiration only)
═══════════════════════════════════════════
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
