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
    # Fixed-interval strategy (eliminates the "flashing" bug):
    #   BROLL_DUR      – every image is visible for EXACTLY this many seconds
    #   BROLL_INTERVAL – a new image starts every N seconds
    #
    # The previous group-based approach produced overlapping timing windows
    # (group N's start_t < group N-1's end_t), so FFmpeg layered the new
    # image on top of the old one after only 1-2 s.  Fixed intervals mean
    # no overlap is ever possible.
    #
    # Word-overlap scoring is kept so images actually relate to the topic.
    # ─────────────────────────────────────────────────────────────────────
    print("Generating B-roll clips from RSS news images...")

    BROLL_DUR      = 5.0   # seconds each image is visible (user wants 4-5 s)
    BROLL_INTERVAL = 9.0   # seconds between the START of successive images

    def _word_overlap(query: str, title: str) -> float:
        """Fraction of query words that appear in the news title (0–1)."""
        q = set(re.findall(r'\w+', query.lower()))
        t = set(re.findall(r'\w+', title.lower()))
        return len(q & t) / len(q) if q else 0.0

    def _make_kenburns(src: Path, dst: Path, dur_s: float) -> bool:
        d = max(int(round(dur_s)), 4)
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
        if best_score >= 0.25 and best_url:
            return best_url
        # Fallback: first unused image (most recent, not random)
        for n in news:
            if n.image_url and n.image_url not in used:
                return n.image_url
        return None

    segments         = topic.visual_segments or []
    rss_img_path     = out_dir / "rss_source_image.jpg"
    broll_video_path = out_dir / "broll_source.mp4"
    used_image_urls: set = set()
    if getattr(topic, "source_image_url", ""):
        used_image_urls.add(topic.source_image_url)

    if getattr(topic, "source_image_url", ""):
        print(f"Downloading main RSS image: {topic.source_image_url}")
        _download_img(topic.source_image_url, rss_img_path)

    broll_paths: list   = []
    broll_timings: list = []

    # Place B-rolls at fixed intervals through the full audio duration.
    # Image for each slot: the visual segment(s) whose spoken window overlaps
    # that timestamp, scored by word-overlap against news titles.
    b_start  = 0.0
    slot_idx = 0

    while b_start + BROLL_DUR <= total_s:
        b_end = b_start + BROLL_DUR

        # 1. Find visual segments whose spoken window overlaps [b_start, b_end]
        all_queries: list = []
        for s_idx, (s_st, s_dur) in enumerate(seg_timings):
            s_end = s_st + s_dur
            if s_st < b_end and s_end > b_start and s_idx < len(segments):
                seg = segments[s_idx]
                qs  = seg.get("broll_queries", [])
                if not qs and seg.get("broll_query"):
                    qs = [seg["broll_query"]]
                all_queries.extend(qs)

        # 2. If no queries, fall back to the topic title
        if not all_queries:
            all_queries = [topic.topic_title] if getattr(topic, "topic_title", "") else []

        # 3. Use the main RSS image for the very first slot (most relevant)
        if slot_idx == 0 and rss_img_path.exists() and rss_img_path.stat().st_size > 1024:
            print(f"  B-roll slot 0 (t={b_start:.1f}s): main RSS image ({BROLL_DUR}s)")
            if _make_kenburns(rss_img_path, broll_video_path, BROLL_DUR):
                broll_paths.append(str(broll_video_path))
                broll_timings.append((b_start, BROLL_DUR))
        else:
            found_url = _best_url(all_queries, used_image_urls)
            if found_url:
                used_image_urls.add(found_url)
                img_path = out_dir / f"rss_img_b{slot_idx}.jpg"
                vid_path = out_dir / f"broll_b{slot_idx}.mp4"
                print(f"  B-roll slot {slot_idx} (t={b_start:.1f}s, {BROLL_DUR}s): {found_url}")
                if _download_img(found_url, img_path) and _make_kenburns(img_path, vid_path, BROLL_DUR):
                    broll_paths.append(str(vid_path))
                    broll_timings.append((b_start, BROLL_DUR))
                elif broll_paths:
                    broll_paths.append(broll_paths[-1])
                    broll_timings.append((b_start, BROLL_DUR))
            elif broll_paths:
                print(f"  B-roll slot {slot_idx}: no image found, reusing previous.")
                broll_paths.append(broll_paths[-1])
                broll_timings.append((b_start, BROLL_DUR))

        b_start  += BROLL_INTERVAL
        slot_idx += 1

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
