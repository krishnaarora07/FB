from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
import re
from dataclasses import dataclass
from typing import List

@dataclass
class NewsItem:
    source: str
    title: str
    description: str

class RSSClient:
    # All URLs live-tested and verified working on 2026-06-25
    # Ordered by viral/drama potential — spiciest first
    FEEDS = {
        # 🔥 Dramatic & viral football stories
        "Caught Offside":          "https://www.caughtoffside.com/feed/",        # transfer gossip
        "The Independent Football": "https://www.independent.co.uk/sport/football/rss",  # exclusives
        "Mirror Football":         "https://www.mirror.co.uk/sport/football/rss.xml",    # tabloid drama
        "90min":                   "https://www.90min.com/posts.rss",                    # viral news
        "Planet Football":         "https://www.planetfootball.com/feed/",              # controversies
        "Football Italia":         "https://www.football-italia.net/feed/",             # Serie A drama

        # 📰 High-quality broader football coverage
        "The Guardian Football":   "https://www.theguardian.com/football/rss",
        "Sky Sports Football":     "https://www.skysports.com/rss/12040",
        "BBC Sport Football":      "http://feeds.bbci.co.uk/sport/football/rss.xml",
        "TalkSPORT":               "https://talksport.com/feed/",
    }

    def fetch_news(self, limit_per_feed: int = 15) -> List[NewsItem]:
        source_names = ", ".join(list(self.FEEDS.keys())[:5]) + "..."
        print(f"  Fetching real-time football news from {len(self.FEEDS)} sources ({source_names})", flush=True)
        all_news = []
        successful = 0
        for source_name, url in self.FEEDS.items():
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                        'Accept': 'application/rss+xml, application/xml, text/xml, */*',
                    }
                )
                with urllib.request.urlopen(req, timeout=10) as response:
                    xml_data = response.read()

                root = ET.fromstring(xml_data)
                count = 0
                for item in root.findall('.//item'):
                    if count >= limit_per_feed:
                        break
                    title_elem = item.find('title')
                    desc_elem = item.find('description')

                    title = title_elem.text if title_elem is not None else ""
                    desc = (desc_elem.text or "") if desc_elem is not None else ""
                    desc = re.sub(r'<[^>]+>', '', desc)  # strip HTML

                    if title:
                        all_news.append(NewsItem(source=source_name, title=title.strip(), description=desc.strip()))
                        count += 1
                successful += 1
            except Exception as e:
                print(f"  Warning: Failed to fetch RSS from {source_name}: {e}", flush=True)

        print(f"  Fetched {len(all_news)} news items from {successful}/{len(self.FEEDS)} sources.", flush=True)
        return all_news
