import json
from pathlib import Path
from ..config import Settings

class CommentBotClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def reply_to_comments(self) -> None:
        history_path = Path("upload_history.json")
        if not history_path.exists():
            print("No upload history found. Cannot reply to comments.")
            return

        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Failed to read upload history: {e}")
            return
            
        last_3 = history[-3:]
        video_ids = [item.get("video_id") for item in last_3 if item.get("video_id")]
        
        if not video_ids:
            print("No video IDs found in history.")
            return

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("Install Google upload dependencies with: pip install -e .") from exc
            
        # Authenticate with YouTube
        SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]
        creds = None
        token_file = self.settings.youtube_token_file
        if token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                from google_auth_oauthlib.flow import InstalledAppFlow
                if not self.settings.youtube_client_secrets_file.exists():
                    raise RuntimeError(f"Missing OAuth client secrets file: {self.settings.youtube_client_secrets_file}")
                flow = InstalledAppFlow.from_client_secrets_file(str(self.settings.youtube_client_secrets_file), SCOPES)
                creds = flow.run_local_server(port=0)
            token_file.write_text(creds.to_json(), encoding="utf-8")
            
        youtube = build("youtube", "v3", credentials=creds)
        
        # Connect to Gemini
        api_key = self.settings.require(self.settings.gemini_api_key, "GEMINI_API_KEY")
        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError("Install google-genai to use Gemini") from exc
        gemini_client = genai.Client(api_key=api_key)
        model_name = getattr(self.settings, "gemini_model", None) or "gemini-3.5-flash"
        
        for video_id in video_ids:
            print(f"Scanning comments for video {video_id}...")
            try:
                response = youtube.commentThreads().list(
                    part="snippet",
                    videoId=video_id,
                    maxResults=5,
                    order="relevance"
                ).execute()
                
                for item in response.get("items", []):
                    top_comment = item["snippet"]["topLevelComment"]["snippet"]
                    comment_text = top_comment["textDisplay"]
                    comment_id = item["snippet"]["topLevelComment"]["id"]
                    reply_count = item["snippet"]["totalReplyCount"]
                    
                    if reply_count == 0:
                        print(f"  Found unanswered comment: '{comment_text}'")
                        prompt = f"""You are the creator of a highly viral YouTube football channel. 
A fan just commented on your latest video: "{comment_text}"
Write a witty, engaging, 1-sentence reply to this fan. Keep it enthusiastic but cool. Do not use emojis excessively. Respond with ONLY the reply text."""
                        
                        try:
                            gemini_resp = gemini_client.models.generate_content(
                                model=model_name,
                                contents=prompt
                            )
                            reply_text = getattr(gemini_resp, "text", "").strip()
                            if reply_text:
                                youtube.comments().insert(
                                    part="snippet",
                                    body={
                                        "snippet": {
                                            "parentId": comment_id,
                                            "textOriginal": reply_text
                                        }
                                    }
                                ).execute()
                                print(f"  -> Replied: '{reply_text}'")
                        except Exception as e:
                            print(f"  -> Failed to reply: {e}")
                            
            except Exception as e:
                print(f"  Error fetching comments for video {video_id}: {e}")
