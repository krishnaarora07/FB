from __future__ import annotations

import time
from pathlib import Path
import tweepy
from ..config import Settings
from ..models import TopicPackage


class TwitterClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = all([
            settings.x_consumer_key,
            settings.x_consumer_secret,
            settings.x_access_token,
            settings.x_access_token_secret
        ])
        
        if self.enabled:
            # v1.1 API (Required for Media Upload)
            auth = tweepy.OAuth1UserHandler(
                settings.x_consumer_key, settings.x_consumer_secret,
                settings.x_access_token, settings.x_access_token_secret
            )
            self.api_v1 = tweepy.API(auth)
            
            # v2 API (Required for creating the Tweet)
            self.client_v2 = tweepy.Client(
                consumer_key=settings.x_consumer_key,
                consumer_secret=settings.x_consumer_secret,
                access_token=settings.x_access_token,
                access_token_secret=settings.x_access_token_secret
            )

    def upload_to_twitter(self, video_path: Path, topic: TopicPackage) -> str | None:
        """Uploads a video to Twitter and creates a tweet."""
        if not self.enabled:
            print("  Skipping Twitter upload: API keys missing.")
            return None
            
        print("  Uploading video to X (Twitter)...")
        try:
            # 1. Upload Video using chunked upload via v1.1 API
            media = self.api_v1.media_upload(filename=str(video_path), media_category="tweet_video")
            media_id = media.media_id
            
            # 2. Wait for processing to finish
            processing_info = media.processing_info
            while processing_info:
                state = processing_info.get("state")
                if state == "succeeded":
                    break
                if state == "failed":
                    error = processing_info.get("error", {})
                    raise RuntimeError(f"Twitter media processing failed: {error}")
                    
                check_after_secs = processing_info.get("check_after_secs", 5)
                print(f"    Twitter is processing video... waiting {check_after_secs} seconds.")
                time.sleep(check_after_secs)
                
                # Check status again
                status = self.api_v1.get_media_upload_status(media_id)
                processing_info = status.processing_info

            # 3. Create Tweet text
            hashtags = " ".join([tag if tag.startswith("#") else f"#{tag}" for tag in topic.hashtags])
            tweet_text = f"{topic.topic_title}\n\n{hashtags}"
            
            # 4. Post the Tweet using v2 API
            print("  Publishing tweet...")
            response = self.client_v2.create_tweet(text=tweet_text, media_ids=[media_id])
            tweet_id = response.data['id']
            print(f"  Successfully posted to X: https://x.com/user/status/{tweet_id}")
            return str(tweet_id)
            
        except Exception as e:
            print(f"  Error uploading to Twitter: {e}")
            return None
