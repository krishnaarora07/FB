from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timedelta, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from ..config import Settings


@dataclass
class AnalyticsInsights:
    avg_view_duration: int | None
    search_terms: list[str]
    viral_seeds: list[str]
    best_days: list[int]


class YouTubeAnalyticsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.scopes = [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.force-ssl",
            "https://www.googleapis.com/auth/yt-analytics.readonly"
        ]

    def _get_creds(self) -> Credentials | None:
        token_file = self.settings.youtube_token_file
        if not token_file.exists():
            return None
        creds = Credentials.from_authorized_user_file(str(token_file), self.scopes)
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                return None
        if creds and creds.valid:
            return creds
        return None

    def get_insights(self) -> AnalyticsInsights:
        creds = self._get_creds()
        avg_view_duration = None
        search_terms = []
        viral_seeds = []
        best_days = []
        
        # 1. Fetch Viral Seeds using Data API (real-time views)
        try:
            history_path = Path("upload_history.json")
            if history_path.exists():
                history = json.loads(history_path.read_text(encoding="utf-8"))
                last_50 = history[-50:]
                video_ids = [item["video_id"] for item in last_50 if "video_id" in item]
                
                if video_ids and creds:
                    yt = build("youtube", "v3", credentials=creds)
                    for i in range(0, len(video_ids), 50):
                        chunk = video_ids[i:i+50]
                        res = yt.videos().list(part="statistics", id=",".join(chunk)).execute()
                        for item in res.get("items", []):
                            views = int(item.get("statistics", {}).get("viewCount", 0))
                            if views >= 1000:
                                topic_title = next((h.get("topic_title", "") for h in last_50 if h.get("video_id") == item["id"]), "")
                                if topic_title:
                                    viral_seeds.append(topic_title)
        except Exception as e:
            print(f"  Warning: Failed to fetch viral seeds: {e}")

        # 2. Fetch Deep Analytics (requires yt-analytics.readonly scope)
        if creds:
            try:
                yta = build("youtubeAnalytics", "v2", credentials=creds)
                
                # YouTube Analytics data is typically delayed by ~2 days
                end_date = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
                start_date = (datetime.now(timezone.utc) - timedelta(days=32)).strftime("%Y-%m-%d")
                
                # AVD
                res = yta.reports().query(
                    ids="channel==MINE",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="averageViewDuration"
                ).execute()
                
                if res.get("rows") and len(res["rows"]) > 0:
                    avg_view_duration = int(res["rows"][0][0])
                    
                # Best Days Calculation
                try:
                    res_days = yta.reports().query(
                        ids="channel==MINE",
                        startDate=start_date,
                        endDate=end_date,
                        metrics="views",
                        dimensions="day"
                    ).execute()
                    
                    if res_days.get("rows"):
                        day_views = {i: 0 for i in range(7)}
                        for row in res_days["rows"]:
                            dt = datetime.strptime(row[0], "%Y-%m-%d")
                            day_views[dt.weekday()] += int(row[1])
                        
                        sorted_days = sorted(day_views.items(), key=lambda x: x[1], reverse=True)
                        best_days = [day for day, views in sorted_days[:2]]
                except Exception as e:
                    print(f"  Warning: Failed to calculate best days: {e}")
                    
                # Search Terms
                res_search = yta.reports().query(
                    ids="channel==MINE",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views",
                    dimensions="insightTrafficSourceDetail",
                    filters="insightTrafficSourceType==YT_SEARCH",
                    sort="-views",
                    maxResults=10
                ).execute()
                
                if res_search.get("rows"):
                    search_terms = [row[0] for row in res_search["rows"]]
                    
            except Exception as e:
                print(f"  Warning: Analytics API skipped or failed (needs yt-analytics.readonly scope). Run 'football-pipeline authenticate'. Error: {e}")

        return AnalyticsInsights(
            avg_view_duration=avg_view_duration,
            search_terms=search_terms,
            viral_seeds=list(set(viral_seeds)),
            best_days=best_days
        )
