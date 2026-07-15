from __future__ import annotations

from ..config import Settings

# Map standard region codes to pytrends `pn` names
REGION_MAP = {
    "US": "united_states",
    "GB": "united_kingdom",
    "IN": "india",
    "CA": "canada",
    "AU": "australia",
    "ZA": "south_africa",
    "NG": "nigeria",
    "FR": "france",
    "DE": "germany",
    "IT": "italy",
    "ES": "spain",
    "BR": "brazil",
    "AR": "argentina",
    "MX": "mexico",
}

class GoogleTrendsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get_football_trends(self) -> list[str]:
        """Fetches daily trending searches and filters for football keywords.

        NOTE: pytrends is no longer maintained (repo archived) and Google's
        backend now returns 404 for its endpoints.  We skip gracefully so the
        pipeline continues with RSS news alone.  If a working alternative
        (e.g. SerpApi) is added later, implement it here.
        """
        print("  Skipping Google Trends (pytrends is deprecated / Google endpoint returns 404).")
        print("  Found 0 football-related Google Search trends.")
        return []
