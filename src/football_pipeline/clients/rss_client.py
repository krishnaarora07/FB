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
    # VERIFIED = confirmed journalism from reputable outlets
    # RUMOUR   = transfer gossip / tabloid speculation, may be unconfirmed

    # Tier 1 — most reliable, journalistic sources (Gemini can state these as facts)
    VERIFIED_FEEDS = {
        # English-language heavyweights
        "BBC Sport":          "http://feeds.bbci.co.uk/sport/football/rss.xml",
        "The Guardian":       "https://www.theguardian.com/football/rss",
        "Sky Sports":         "https://www.skysports.com/rss/12040",
        "The Independent":    "https://www.independent.co.uk/sport/football/rss",
        # Global & continental
        "ESPN FC":            "https://www.espn.com/espn/rss/soccer/news",
        "UEFA Official":      "https://www.uefa.com/rssfeed/uefachampionsleague/rss.xml",
        "Goal.com":           "https://www.goal.com/feeds/en/news",
        "90min":              "https://www.90min.com/posts.rss",
        "Football Italia":    "https://www.football-italia.net/feed/",
        # Spanish press (English editions — packed with La Liga / Champions League scoops)
        "AS English":         "https://en.as.com/rss/soccer.xml",
        "Marca English":      "https://www.marca.com/en/rss/soccer/",
        # French & Italian press
        "L'Equipe":           "https://www.lequipe.fr/rss/actu_rss_Football.xml",
        # Brazilian / South American football
        "Globo Esporte":      "https://ge.globo.com/rss/",
        # World Cup & FIFA
        "FIFA News":          "https://www.fifa.com/en/articles/rss",
    }

    # Tier 2 — transfer gossip / tabloid; Gemini must hedge these with "reportedly" etc.
    RUMOUR_FEEDS = {
        "TalkSPORT":          "https://talksport.com/feed/",
        "Mirror Football":    "https://www.mirror.co.uk/sport/football/rss.xml",
        "Calciomercato":      "https://www.calciomercato.com/en/rss",
        "Football Transfers": "https://www.footballtransfers.com/en/transfer-news/rss",
    }

    def fetch_news(self, limit_per_feed: int = 10) -> List[NewsItem]:
        total_sources = len(self.VERIFIED_FEEDS) + len(self.RUMOUR_FEEDS)
        print(
            f"  Fetching real-time football news from {total_sources} sources "
            f"({len(self.VERIFIED_FEEDS)} verified + {len(self.RUMOUR_FEEDS)} rumour)...",
            flush=True,
        )
        all_news: List[NewsItem] = []
        successful = 0

        for tier_label, feeds in [
            ("VERIFIED", self.VERIFIED_FEEDS),
            ("RUMOUR",   self.RUMOUR_FEEDS),
        ]:
            for source_name, url in feeds.items():
                try:
                    req = urllib.request.Request(
                        url,
                        headers={
                            'User-Agent': (
                                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                'AppleWebKit/537.36 (KHTML, like Gecko) '
                                'Chrome/124.0.0.0 Safari/537.36'
                            ),
                            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
                        }
                    )
                    with urllib.request.urlopen(req, timeout=12) as response:
                        xml_data = response.read()

                    root = ET.fromstring(xml_data)
                    count = 0
                    for item in root.findall('.//item'):
                        if count >= limit_per_feed:
                            break
                        title_elem = item.find('title')
                        desc_elem  = item.find('description')

                        title = title_elem.text if title_elem is not None else ""
                        desc  = (desc_elem.text or "") if desc_elem is not None else ""
                        desc  = re.sub(r'<[^>]+>', '', desc)  # strip HTML

                        if title:
                            tagged_source = f"{source_name} [{tier_label}]"
                            all_news.append(NewsItem(
                                source=tagged_source,
                                title=title.strip(),
                                description=desc.strip(),
                            ))
                            count += 1
                    successful += 1
                except Exception as e:
                    print(f"  Warning: Failed to fetch RSS from {source_name}: {e}", flush=True)

        print(
            f"  Fetched {len(all_news)} news items from {successful}/{total_sources} sources.",
            flush=True,
        )
        return all_news
