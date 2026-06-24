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
    # Ordered by viral potential — spicy transfers, drama, controversies first
    FEEDS = {
        # 🔥 Transfer gossip & breaking drama
        "GOAL.com":           "https://www.goal.com/feeds/en/news",
        "90min":              "https://www.90min.com/feeds/latest.rss",
        "Football365":        "https://www.football365.com/feed",
        "FourFourTwo":        "https://www.fourfourtwo.com/rss/news",
        "The Athletic":       "https://theathletic.com/rss-feeds/",

        # 🔥 Transfer rumours — most viral content on YouTube
        "Transfermarkt News": "https://www.transfermarkt.co.uk/news/rss",
        "TeamTalk":           "https://www.teamtalk.com/feed",

        # 📰 Broader football news as fallback
        "Sky Sports Football": "https://www.skysports.com/rss/12040",
        "BBC Sport Football":  "http://feeds.bbci.co.uk/sport/football/rss.xml",
        "Mirror Football":     "https://www.mirror.co.uk/sport/football/rss.xml",
        "The Sun Football":    "https://www.thesun.co.uk/sport/football/feed/",
        "Daily Mail Football": "https://www.dailymail.co.uk/sport/football/index.rss",
        "TalkSPORT":           "https://talksport.com/feed/",
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
