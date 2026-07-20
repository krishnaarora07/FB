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
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=720x1280", "-frames:v", "1", str(photo_path)], capture_output=True)
        
    generate_avatar = modal.Function.from_name("avatar-pipeline", "generate_avatar")
    clip_paths = []
    
    # Read bytes for all chunks
    audio_bytes_list = [Path(ap).read_bytes() for ap in audio_paths]
    photo_bytes_list = [photo_path.read_bytes()] * len(audio_paths)
    
    print("Generating avatar clips in PARALLEL via Modal...")
    # Using .map() spins up multiple GPUs concurrently, turning a 30 min task into 5 mins
    for i, video_bytes in enumerate(generate_avatar.map(audio_bytes_list, photo_bytes_list)):
        cpath = out_dir / f"clip_{i:02d}.mp4"
        cpath.write_bytes(video_bytes)
        clip_paths.append(str(cpath))
        
    # 4. B-roll clips (Using RSS Image instead of AI Generation)
    print("Generating B-roll clips from RSS image...")
    broll_paths = []
    
    rss_img_path = out_dir / "rss_source_image.jpg"
    broll_video_path = out_dir / "broll_source.mp4"
    
    if getattr(topic, "source_image_url", ""):
        print(f"Downloading RSS image: {topic.source_image_url}")
        try:
            req = urllib.request.Request(topic.source_image_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                rss_img_path.write_bytes(response.read())
        except Exception as e:
            print(f"Failed to download RSS image: {e}")
            
    # Check if image exists and is valid (> 1KB to ensure it's not a 0-byte or error page)
    if rss_img_path.exists() and rss_img_path.stat().st_size > 1024:
        # Convert image to a 5-second video with a slow zoom (Ken Burns effect)
        try:
            print("Applying Ken Burns effect to image...")
            # We scale to 1440:2560 (2x 720p) preserving aspect ratio, crop exactly to 9:16, 
            # and then apply zoompan. This prevents ANY stretching or distortion of horizontal images!
            subprocess.run([
                "ffmpeg", "-y", "-loop", "1", "-i", str(rss_img_path),
                "-vf", "scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,zoompan=z='min(zoom+0.0015,1.5)':d=125:x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':s=720x1280",
                "-c:v", "libx264", "-t", "5", "-pix_fmt", "yuv420p", "-r", "25",
                str(broll_video_path)
            ], capture_output=True, check=True)
            
            # Use this same generated video for all 5 B-roll segments
            segments = topic.visual_segments[:5]
            for i, seg in enumerate(segments):
                broll_paths.append(str(broll_video_path))
        except subprocess.CalledProcessError as e:
            print(f"Failed to create B-roll video: {e}")
            broll_paths = []
    else:
        print("Missing or invalid RSS image. Falling back to full-screen avatar.")
        broll_paths = []
        
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
