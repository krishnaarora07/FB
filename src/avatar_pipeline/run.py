import os
import json
import urllib.request
import subprocess
import re
from pathlib import Path
from pydub import AudioSegment

from src.football_pipeline.clients.rss_client import RSSClient
from src.football_pipeline.clients.gemini_client import GeminiTopicClient
from src.avatar_pipeline.fish_speech_client import FishSpeechClient
from src.football_pipeline.youtube_upload import YouTubeUploader
from src.football_pipeline.config import Settings
from src.avatar_pipeline import assembler
import modal

def run_pipeline():
    settings = Settings.from_env()
    
    # 1. Script
    print("Fetching news...")
    news = RSSClient().fetch_news()
    
    print("Choosing topic...")
    gemini = GeminiTopicClient(settings)
    topic = gemini.choose_topic([], [], news)
    if not topic:
        print("No topic selected. Exiting.")
        return
        
    # Match article URL and Image URL
    def get_words(text):
        return set(re.findall(r'\w+', str(text).lower()))
        
    topic_headline_words = get_words(getattr(topic, "source_headline", ""))
    best_match = None
    best_score = -1.0
    
    for n in news:
        n_title_words = get_words(n.title)
        
        # Exact match logic (fast path)
        if getattr(topic, "source_headline", "") and topic.source_headline.strip().lower() == n.title.strip().lower():
            best_match = n
            best_score = 1.0
            break
            
        # Jaccard similarity fallback
        if topic_headline_words and n_title_words:
            intersection = topic_headline_words.intersection(n_title_words)
            union = topic_headline_words.union(n_title_words)
            score = len(intersection) / len(union) if union else 0
            if score > best_score:
                best_score = score
                best_match = n

        # Topic title substring fallback
        elif n.title in topic.topic_title or topic.topic_title in n.title:
            if best_score < 0.1: # Only override if we haven't found a decent match yet
                best_score = 0.1
                best_match = n

    if best_match and best_score >= 0.0:
        object.__setattr__(topic, "source_article_url", best_match.article_url)
        object.__setattr__(topic, "source_image_url", best_match.image_url)
            
    # 2. Voiceover
    print("Generating voiceover...")
    tts = FishSpeechClient(settings)
    out_dir = Path(settings.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    voice_path = out_dir / "voiceover.wav"
    
    # 2a. Call Modal TTS
    try:
        ref_audio_path = Path("assets/reference_audio.wav")
        ref_audio_bytes = ref_audio_path.read_bytes() if ref_audio_path.exists() else None
        ref_text = "Welcome to the daily football update. Let us get right into the news on the pitch." if ref_audio_bytes else None
        
        tts.create_voiceover(topic.script, voice_path, ref_audio_bytes, ref_text)
    except Exception as e:
        print(f"TTS failed: {e}.")
        raise RuntimeError(f"Voiceover generation failed: {e}")
        
    # 2b. Pass the full voiceover as a single audio file.
    # LongCat's generate_avc continuation runs all segments within ONE GPU call,
    # which is the only way to preserve lip sync across the full video.
    # VRAM headroom comes from --use_int8 + offload_kv_cache in modal_avatar.py / longcat_script.py.
    audio_paths = [str(voice_path)]
    total_s = len(AudioSegment.from_wav(str(voice_path))) / 1000
    print(f"  Full voiceover: {total_s:.1f}s -> 1 GPU call (INT8 + KV-offload handles up to ~90s)")

    # 2c. Compute per-segment spoken timestamps from Whisper word alignment.
    # This is what drives B-roll timing later — each broll shows exactly when
    # the avatar is speaking the sentence it was selected for.
    seg_timings = []  # list of (start_s, spoken_duration_s) per visual_segment
    _segments_list = topic.visual_segments or []
    _words_path = voice_path.with_suffix('.words.json')
    if _words_path.exists() and _segments_list:
        _words_data = json.loads(_words_path.read_text(encoding='utf-8'))
        _word_pos = 0
        for _seg in _segments_list:
            _seg_word_count = len(_seg.get('text', '').split())
            if _word_pos < len(_words_data):
                _start_s = _words_data[_word_pos]['offset'] / 10_000_000
                _end_idx = min(_word_pos + max(_seg_word_count - 1, 0), len(_words_data) - 1)
                _end_s = (_words_data[_end_idx]['offset'] + _words_data[_end_idx]['duration']) / 10_000_000
                _dur_s = max(3.0, _end_s - _start_s)
            else:
                _start_s = seg_timings[-1][0] + seg_timings[-1][1] if seg_timings else 0.0
                _dur_s = 4.0
            seg_timings.append((_start_s, _dur_s))
            _word_pos += _seg_word_count
        print(f"  Computed {len(seg_timings)} segment timings from Whisper alignment.")
    else:
        # Fallback: distribute evenly if words.json is missing
        _n = len(_segments_list) or 1
        for _i in range(_n):
            seg_timings.append((_i * (total_s / _n), total_s / _n))
        print("  Warning: words.json not found, falling back to even B-roll spacing.")

    # 3. Avatar clips
    print("Generating avatar clips via Modal...")
    photo_path = Path("assets/avatar_photo.jpg")
    if not photo_path.exists():
        # Make a dummy black image if missing
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=1024x1024", "-frames:v", "1", str(photo_path)], capture_output=True)
        
    generate_avatar = modal.Function.from_name("avatar-pipeline", "generate_avatar")
    clip_paths = []
    
    print("Generating avatar clips SEQUENTIALLY via Modal (keeps 1 GPU warm to save massive costs)...")
    photo_bytes = photo_path.read_bytes()
    for i, ap in enumerate(audio_paths):
        print(f"  Generating clip {i+1}/{len(audio_paths)}...")
        audio_bytes = Path(ap).read_bytes()
        video_bytes = generate_avatar.remote(audio_bytes, photo_bytes)
        cpath = out_dir / f"clip_{i:02d}.mp4"
        cpath.write_bytes(video_bytes)
        clip_paths.append(str(cpath))
        
    # 4. B-roll clips (Using RSS News Images)
    # ─────────────────────────────────────────────────────────────────────
    # Strategy
    #   BROLL_EVERY   – group this many visual segments under ONE B-roll
    #                   image so each image stays on screen 8-12 s instead
    #                   of flashing every 3-4 s.
    #   MIN_BROLL_DUR – never show a B-roll for less than this many seconds.
    #   Word-overlap scoring replaces the broken substring match so a query
    #   like "Rodri Ballon d'Or" finds "Man City's Rodri wins Ballon d'Or".
    # ─────────────────────────────────────────────────────────────────────
    print("Generating B-roll clips from RSS news images...")

    BROLL_EVERY   = 3      # 1 new image per N visual segments
    MIN_BROLL_DUR = 8.0    # seconds each image stays on screen

    def _word_overlap(query: str, title: str) -> float:
        """Fraction of query words that appear in the news title (0–1)."""
        q = set(re.findall(r'\w+', query.lower()))
        t = set(re.findall(r'\w+', title.lower()))
        return len(q & t) / len(q) if q else 0.0

    def _group_timing(start_idx: int, n_segs: int) -> tuple:
        """(start_s, duration_s) spanning n_segs segments from start_idx."""
        if not seg_timings or start_idx >= len(seg_timings):
            fallback = start_idx * (total_s / max(len(_segments_list), 1))
            return (fallback, MIN_BROLL_DUR)
        g_start = seg_timings[start_idx][0]
        end_idx = min(start_idx + n_segs - 1, len(seg_timings) - 1)
        g_end   = seg_timings[end_idx][0] + seg_timings[end_idx][1]
        return (g_start, max(MIN_BROLL_DUR, g_end - g_start))

    def _make_kenburns(src: Path, dst: Path, dur_s: float) -> bool:
        d = max(int(round(dur_s)), int(MIN_BROLL_DUR))
        try:
            subprocess.run([
                "ffmpeg", "-y", "-loop", "1", "-i", str(src),
                "-vf", (
                    f"scale=2560:1440:force_original_aspect_ratio=increase,"
                    f"crop=2560:1440,"
                    f"zoompan=z='min(zoom+0.0015,1.5)':d={d*25}:"
                    f"x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':s=1280x720"
                ),
                "-c:v", "libx264", "-t", str(d), "-pix_fmt", "yuv420p", "-r", "25",
                str(dst)
            ], capture_output=True, check=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"  Ken Burns failed: {e}")
            return False

    def _download_img(url: str, dst: Path) -> bool:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                dst.write_bytes(r.read())
            return dst.exists() and dst.stat().st_size > 1024
        except Exception as e:
            print(f"  Image download failed: {e}")
            return False

    def _best_url(queries: list, used: set) -> str | None:
        """Score every RSS image against all queries; return the best match."""
        best_url, best_score = None, 0.0
        for query in queries:
            for n in news:
                if not n.image_url or n.image_url in used:
                    continue
                score = _word_overlap(query, n.title)
                if score > best_score:
                    best_score, best_url = score, n.image_url
        # Accept if at least 25 % of query words matched a title
        if best_score >= 0.25 and best_url:
            return best_url
        # Fallback: first unused image (most recent, not random)
        for n in news:
            if n.image_url and n.image_url not in used:
                return n.image_url
        return None

    rss_img_path     = out_dir / "rss_source_image.jpg"
    broll_video_path = out_dir / "broll_source.mp4"
    segments         = topic.visual_segments or []
    used_image_urls: set = set()
    if getattr(topic, "source_image_url", ""):
        used_image_urls.add(topic.source_image_url)

    # Download the topic's primary RSS image
    if getattr(topic, "source_image_url", ""):
        print(f"Downloading main RSS image: {topic.source_image_url}")
        _download_img(topic.source_image_url, rss_img_path)

    broll_paths: list   = []
    broll_timings: list = []

    # ── First B-roll: main RSS image covering the first BROLL_EVERY segments ──
    if rss_img_path.exists() and rss_img_path.stat().st_size > 1024:
        t0_start, t0_dur = _group_timing(0, BROLL_EVERY)
        print(f"Applying Ken Burns effect to main image ({t0_dur:.1f}s)...")
        if _make_kenburns(rss_img_path, broll_video_path, t0_dur):
            broll_paths.append(str(broll_video_path))
            broll_timings.append((t0_start, t0_dur))

    # ── Remaining B-rolls: one per group of BROLL_EVERY segments ──────────────
    seg_start = BROLL_EVERY   # first group already covered by main RSS image
    grp_idx   = 1

    while seg_start < len(segments):
        group = segments[seg_start : seg_start + BROLL_EVERY]
        g_start, g_dur = _group_timing(seg_start, len(group))

        # Collect all broll_queries from every segment in this group
        all_queries: list = []
        for seg in group:
            qs = seg.get("broll_queries", [])
            if not qs and seg.get("broll_query"):
                qs = [seg["broll_query"]]
            all_queries.extend(qs)

        found_url = _best_url(all_queries, used_image_urls)

        if found_url:
            used_image_urls.add(found_url)
            img_path = out_dir / f"rss_img_grp{grp_idx}.jpg"
            vid_path = out_dir / f"broll_grp{grp_idx}.mp4"
            n_end = seg_start + len(group) - 1
            print(f"  B-roll {grp_idx} (segs {seg_start}–{n_end}, {g_dur:.1f}s): {found_url}")
            if _download_img(found_url, img_path) and _make_kenburns(img_path, vid_path, g_dur):
                broll_paths.append(str(vid_path))
                broll_timings.append((g_start, g_dur))
            elif broll_paths:
                broll_paths.append(broll_paths[-1])
                broll_timings.append((g_start, g_dur))
        elif broll_paths:
            print(f"  No image found for B-roll group {grp_idx}; reusing previous clip.")
            broll_paths.append(broll_paths[-1])
            broll_timings.append((g_start, g_dur))

        seg_start += BROLL_EVERY
        grp_idx   += 1

    # 5. Assemble & Upload
    print("Assembling final video...")
    final_vid = out_dir / "final_avatar_video.mp4"
    assembler.assemble(clip_paths, broll_paths, str(final_vid), str(voice_path), broll_timings)
    
    print("Uploading to YouTube...")
    uploader = YouTubeUploader(settings)
    if final_vid.exists() and os.path.getsize(final_vid) > 0:
        uploader.upload(str(final_vid), topic)
        
    print("Pipeline complete!")

if __name__ == "__main__":
    run_pipeline()
