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
    FEEDS = {
        "BBC Sport": "http://feeds.bbci.co.uk/sport/football/rss.xml",
        "ESPN Soccer": "https://www.espn.com/espn/rss/soccer/news",
        "Sky Sports": "https://www.skysports.com/rss/12040", 
    }

    def fetch_news(self, limit_per_feed: int = 15) -> List[NewsItem]:
        print("  Fetching real-time football news from BBC, ESPN, and Sky Sports...")
        all_news = []
        for source_name, url in self.FEEDS.items():
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
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
                    desc = desc_elem.text if desc_elem is not None else ""
                    
                    if title:
                        desc = re.sub(r'<[^>]+>', '', desc) # strip HTML if any
                        all_news.append(NewsItem(source=source_name, title=title.strip(), description=desc.strip()))
                        count += 1
            except Exception as e:
                print(f"  Warning: Failed to fetch RSS from {source_name}: {e}")
        
        return all_news
