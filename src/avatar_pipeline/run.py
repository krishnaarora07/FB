import os
import json
from pathlib import Path
from pydub import AudioSegment

from src.football_pipeline.clients.rss_client import RSSClient
from src.football_pipeline.clients.gemini_client import GeminiTopicClient
from src.football_pipeline.clients.chatterbox_tts_client import ChatterboxTtsClient
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
        
    # Match article URL
    for n in news:
        if n.title in topic.topic_title or topic.topic_title in n.title:
            topic.source_article_url = n.article_url
            break
            
    # 2. Voiceover
    print("Generating voiceover...")
    tts = ChatterboxTtsClient(settings)
    out_dir = Path(settings.output_dir)
    out_dir.mkdir(exist_ok=True, parents=True)
    base_audio_path = out_dir / "full_audio.wav"
    
    # In a real run, this generates the TTS
    tts.create_voiceover(topic.script, base_audio_path)
    
    if not base_audio_path.exists():
        # Fallback dummy for testing
        with open(base_audio_path, "wb") as f:
            f.write(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00")
            
    # Split audio into 6 chunks
    audio = AudioSegment.from_wav(str(base_audio_path))
    chunk_length = len(audio) // 6 if len(audio) > 0 else 1000
    
    audio_chunks = []
    for i in range(6):
        chunk = audio[i*chunk_length : (i+1)*chunk_length]
        chunk_path = out_dir / f"audio_{i:02d}.wav"
        chunk.export(chunk_path, format="wav")
        audio_chunks.append(chunk_path)
        
    # 3. Avatar clips
    print("Generating avatar clips via Modal...")
    photo_path = Path("assets/avatar_photo.jpg")
    if not photo_path.exists():
        raise FileNotFoundError(
            "assets/avatar_photo.jpg not found! "
            "Place the avatar face photo in the assets/ directory before running."
        )
    photo_bytes = photo_path.read_bytes()
    
    clip_paths = []
    generate_avatar = modal.Function.from_name("avatar-pipeline", "generate_avatar")
    for i, achunk in enumerate(audio_chunks):
        audio_bytes = achunk.read_bytes()
        print(f"Generating avatar clip {i}...")
        video_bytes = generate_avatar.remote(audio_bytes, photo_bytes)
        cpath = out_dir / f"clip_{i:02d}.mp4"
        cpath.write_bytes(video_bytes)
        clip_paths.append(str(cpath))
        
    # 4. B-roll clips
    print("Generating B-roll clips via Modal...")
    broll_paths = []
    segments = topic.visual_segments[:5]
    generate_broll = modal.Function.from_name("avatar-pipeline", "generate_broll")
    for i, seg in enumerate(segments):
        desc = seg.get("broll_query", "football match scene")
        print(f"Generating broll {i}: {desc}...")
        vbytes = generate_broll.remote(desc, 8)
        bpath = out_dir / f"broll_{i:02d}.mp4"
        bpath.write_bytes(vbytes)
        broll_paths.append(str(bpath))
        
    # 5. Assemble & Upload
    print("Assembling final video...")
    final_vid = out_dir / "final_avatar_video.mp4"
    assembler.assemble(clip_paths, broll_paths, str(final_vid), str(base_audio_path))
    
    print("Uploading to YouTube...")
    uploader = YouTubeUploader(settings)
    if final_vid.exists() and os.path.getsize(final_vid) > 0:
        uploader.upload(str(final_vid), topic)
        
    print("Pipeline complete!")

if __name__ == "__main__":
    run_pipeline()
