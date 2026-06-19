from __future__ import annotations

from pathlib import Path

from .config import Settings
from .models import TopicPackage


SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]


class YouTubeUploader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def upload(self, video_path: Path, topic: TopicPackage) -> str:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:
            raise RuntimeError("Install Google upload dependencies with: pip install -e .") from exc

        creds = None
        token_file = self.settings.youtube_token_file
        if token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.settings.youtube_client_secrets_file.exists():
                    raise RuntimeError(
                        f"Missing OAuth client secrets file: {self.settings.youtube_client_secrets_file}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.settings.youtube_client_secrets_file),
                    SCOPES,
                )
                creds = flow.run_local_server(port=0)
            token_file.write_text(creds.to_json(), encoding="utf-8")

        youtube = build("youtube", "v3", credentials=creds)
        from datetime import datetime, timezone, timedelta
        publish_dt = datetime.now(timezone.utc).replace(hour=18, minute=0, second=0, microsecond=0)
        if datetime.now(timezone.utc) > publish_dt:
            publish_dt += timedelta(days=1)
        publish_at_str = publish_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        body = {
            "snippet": {
                "title": topic.youtube_title[:100],
                "description": self._description(topic),
                "tags": [tag.lstrip("#") for tag in topic.hashtags],
                "categoryId": self.settings.youtube_upload_category_id,
            },
            "status": {
                "privacyStatus": "private",
                "publishAt": publish_at_str,
                "selfDeclaredMadeForKids": False,
            },
        }
        media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            _, response = request.next_chunk()
        
        video_id = response['id']
        
        # Automatically post affiliate links as a pinned/top-level comment
        comment_parts = []
        if self.settings.affiliate_link_amazon:
            comment_parts.append(f"🛒 Grab the official match ball & gear here: {self.settings.affiliate_link_amazon}")
        if self.settings.affiliate_link_amazon_2:
            comment_parts.append(f"⚡ Upgrade your football kit here: {self.settings.affiliate_link_amazon_2}")
        if self.settings.affiliate_link_fanatics:
            comment_parts.append(f"👕 Get your favorite player's jersey here: {self.settings.affiliate_link_fanatics}")
            
        if comment_parts:
            comment_text = "\n".join(comment_parts)
            try:
                print(f"  Adding affiliate comment to video {video_id}...")
                youtube.commentThreads().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "videoId": video_id,
                            "topLevelComment": {
                                "snippet": {
                                    "textOriginal": comment_text
                                }
                            }
                        }
                    }
                ).execute()
            except Exception as e:
                print(f"  Warning: Failed to post affiliate comment: {e}")
                
        return video_id

    def _description(self, topic: TopicPackage) -> str:
        hashtags = " ".join(topic.hashtags)
        parts = [topic.youtube_description.strip(), ""]
        
        if self.settings.affiliate_link_amazon:
            parts.append(f"🛒 Grab the official match ball & gear: {self.settings.affiliate_link_amazon}")
        if self.settings.affiliate_link_amazon_2:
            parts.append(f"⚡ Upgrade your football kit here: {self.settings.affiliate_link_amazon_2}")
        if self.settings.affiliate_link_fanatics:
            parts.append(f"👕 Get your favorite player's jersey: {self.settings.affiliate_link_fanatics}")
            
        if self.settings.affiliate_link_amazon or self.settings.affiliate_link_amazon_2 or self.settings.affiliate_link_fanatics:
            parts.append("")
            
        parts.append(hashtags.strip())
        return "\n".join(part for part in parts if part)

