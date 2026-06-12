from __future__ import annotations

from pathlib import Path

from .config import Settings
from .models import TopicPackage


SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


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
        body = {
            "snippet": {
                "title": topic.youtube_title[:100],
                "description": self._description(topic),
                "tags": [tag.lstrip("#") for tag in topic.hashtags],
                "categoryId": self.settings.youtube_upload_category_id,
            },
            "status": {
                "privacyStatus": self.settings.youtube_upload_privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }
        media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            _, response = request.next_chunk()
        return f"https://www.youtube.com/watch?v={response['id']}"

    @staticmethod
    def _description(topic: TopicPackage) -> str:
        hashtags = " ".join(topic.hashtags)
        parts = [topic.youtube_description.strip(), "", hashtags.strip()]
        return "\n".join(part for part in parts if part)

