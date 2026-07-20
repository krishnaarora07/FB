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
        tts.create_voiceover(topic.script, voice_path)
    except Exception as e:
        print(f"TTS failed: {e}. Falling back to 30s silent audio.")
        # Create silent fallback
        silent = AudioSegment.silent(duration=30000)
        silent.export(voice_path, format="wav")
        
    # 2b. Split Voiceover intelligently to preserve lip sync
    # LongCat lip sync drifts if audio chunks exceed ~15s. We split on silences and pack up to 12s.
    audio = AudioSegment.from_wav(voice_path)
    from pydub.silence import split_on_silence
    
    print("Splitting audio on silences to preserve lip sync...")
    chunks = split_on_silence(
        audio,
        min_silence_len=400,
        silence_thresh=audio.dBFS - 14,
        keep_silence=200
    )
    
    max_chunk_len = 12 * 1000 # 12 seconds
    if not chunks:
        # Fallback if silence splitting fails
        chunks = [audio[i:i+max_chunk_len] for i in range(0, len(audio), max_chunk_len)]
        
    audio_paths = []
    current_chunk = AudioSegment.empty()
    chunk_idx = 0
    
    for chunk in chunks:
        if len(current_chunk) + len(chunk) > max_chunk_len and len(current_chunk) > 0:
            cpath = out_dir / f"audio_{chunk_idx:02d}.wav"
            current_chunk.export(cpath, format="wav")
            audio_paths.append(str(cpath))
            chunk_idx += 1
            current_chunk = chunk
        else:
            current_chunk += chunk
            
    if len(current_chunk) > 0:
        cpath = out_dir / f"audio_{chunk_idx:02d}.wav"
        current_chunk.export(cpath, format="wav")
        audio_paths.append(str(cpath))
        
    print(f"Split voiceover into {len(audio_paths)} optimal chunks.")
        
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
    print("Generating B-roll clips from RSS news images...")
    broll_paths = []
    
    rss_img_path = out_dir / "rss_source_image.jpg"
    broll_video_path = out_dir / "broll_source.mp4"
    
    if getattr(topic, "source_image_url", ""):
        print(f"Downloading main RSS image: {topic.source_image_url}")
        try:
            req = urllib.request.Request(topic.source_image_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                rss_img_path.write_bytes(response.read())
        except Exception as e:
            print(f"Failed to download main RSS image: {e}")
            
    # First B-roll is the main RSS image Ken Burns effect
    if rss_img_path.exists() and rss_img_path.stat().st_size > 1024:
        try:
            print("Applying Ken Burns effect to main image...")
            subprocess.run([
                "ffmpeg", "-y", "-loop", "1", "-i", str(rss_img_path),
                "-vf", "scale=2560:1440:force_original_aspect_ratio=increase,crop=2560:1440,zoompan=z='min(zoom+0.0015,1.5)':d=125:x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':s=1280x720",
                "-c:v", "libx264", "-t", "5", "-pix_fmt", "yuv420p", "-r", "25",
                str(broll_video_path)
            ], capture_output=True, check=True)
            broll_paths.append(str(broll_video_path))
        except subprocess.CalledProcessError as e:
            print(f"Failed to create main B-roll video: {e}")

    # For remaining B-rolls, find relevant images from other news items!
    import random
    segments = topic.visual_segments or []
    used_image_urls = set()
    if getattr(topic, "source_image_url", ""):
        used_image_urls.add(topic.source_image_url)
        
    for i, seg in enumerate(segments):
        # Skip the first one if we already have the main RSS image
        if i == 0 and len(broll_paths) > 0:
            continue
            
        queries = seg.get("broll_queries", [])
        if not queries:
            query = seg.get("broll_query", "")
            if query: queries = [query]
            
        found_url = None
        # 1. Try to find a news item matching the broll query
        for query in queries:
            query_lower = query.lower()
            matching_news = [n for n in news if n.image_url and n.image_url not in used_image_urls and query_lower in n.title.lower()]
            if matching_news:
                found_url = matching_news[0].image_url
                break
                
        # 2. Fallback to any unused news image
        if not found_url:
            unused = [n for n in news if n.image_url and n.image_url not in used_image_urls]
            if unused:
                found_url = random.choice(unused).image_url
                
        # 3. Fallback to any valid news image
        if not found_url:
            valid_news = [n for n in news if n.image_url]
            if valid_news:
                found_url = random.choice(valid_news).image_url
                
        if found_url:
            used_image_urls.add(found_url)
            img_path = out_dir / f"rss_img_{i}.jpg"
            vid_path = out_dir / f"broll_rss_{i}.mp4"
            print(f"Downloading news image for segment {i}: {found_url}")
            try:
                req = urllib.request.Request(found_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as response:
                    img_path.write_bytes(response.read())
                    
                if img_path.exists() and img_path.stat().st_size > 1024:
                    subprocess.run([
                        "ffmpeg", "-y", "-loop", "1", "-i", str(img_path),
                        "-vf", "scale=2560:1440:force_original_aspect_ratio=increase,crop=2560:1440,zoompan=z='min(zoom+0.0015,1.5)':d=125:x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':s=1280x720",
                        "-c:v", "libx264", "-t", "5", "-pix_fmt", "yuv420p", "-r", "25",
                        str(vid_path)
                    ], capture_output=True, check=True)
                    broll_paths.append(str(vid_path))
                    continue # Success!
            except Exception as e:
                print(f"Failed to process news image for segment {i}: {e}")
                
        # If we failed to find or process an image for this segment, repeat the last available B-roll
        if broll_paths:
            broll_paths.append(broll_paths[-1])
        
    # 5. Assemble & Upload
    print("Assembling final video...")
    final_vid = out_dir / "final_avatar_video.mp4"
    assembler.assemble(clip_paths, broll_paths, str(final_vid), str(voice_path))
    
    print("Uploading to YouTube...")
    uploader = YouTubeUploader(settings)
    if final_vid.exists() and os.path.getsize(final_vid) > 0:
        uploader.upload(str(final_vid), topic)
        
    print("Pipeline complete!")

if __name__ == "__main__":
    run_pipeline()
