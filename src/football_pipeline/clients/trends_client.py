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
        """Fetches daily trending searches and filters for football keywords."""
        try:
            from pytrends.request import TrendReq
        except ImportError as exc:
            print("  Warning: pytrends not installed. Skipping Google Trends.")
            return []

        print("  Fetching Google Trends data...")
        
        # Initialize pytrends with a generic English locale and a strict timeout
        try:
            pytrends = TrendReq(hl='en-US', tz=360, timeout=(10, 25))
        except Exception as e:
            print(f"  Warning: Failed to initialize pytrends: {e}")
            return []

        football_keywords = [kw.lower().strip() for kw in self.settings.football_keywords]
        trending_queries = []

        for region in self.settings.trend_regions:
            pn_name = REGION_MAP.get(region.upper())
            if not pn_name:
                continue

            try:
                # Returns a pandas DataFrame with one column '0' containing the queries
                df = pytrends.trending_searches(pn=pn_name)
                
                # Check if it's empty
                if df.empty:
                    continue
                    
                # Extract the first column as a list
                queries = df[df.columns[0]].tolist()
                
                # Filter for football keywords
                for query in queries:
                    q_lower = str(query).lower()
                    if any(kw in q_lower for kw in football_keywords):
                        trending_queries.append(query)
                        
            except Exception as e:
                print(f"  Warning: Could not fetch trends for {pn_name}: {e}")

        # Deduplicate while preserving order
        seen = set()
        clean_trends = []
        for q in trending_queries:
            if q not in seen:
                seen.add(q)
                clean_trends.append(q)

        print(f"  Found {len(clean_trends)} football-related Google Search trends.")
        return clean_trends
