from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
import re
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import List
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Viral keyword scoring
# Each keyword that appears in the title adds the listed points.
# Higher = more likely to go viral on YouTube Shorts.
# ---------------------------------------------------------------------------
_VIRAL_KEYWORDS: dict[str, int] = {
    # Transfer bombshells (highest virality)
    "done deal":      10,
    "confirmed":       9,
    "signs":           8,
    "transfer":        7,
    "shock move":      9,
    "deadline":        8,
    "bid":             6,
    "offer":           6,
    "rejected":        8,
    "refuses":         8,
    "walks out":       9,
    "quit":            8,
    "quits":           8,
    "sacked":          9,
    "fired":           8,
    "resign":          8,
    "exclusive":       7,
    "breaking":        8,
    # Drama / controversy
    "ban":             8,
    "banned":          8,
    "suspended":       7,
    "row":             6,
    "crisis":          7,
    "fury":            7,
    "furious":         7,
    "slams":           7,
    "blasts":          7,
    "war":             6,
    "feud":            6,
    "demands":         6,
    "leaked":          8,
    "reveals":         7,
    "admits":          6,
    "accused":         7,
    "arrest":          9,
    "scandal":         9,
    # Records / stats
    "record":          7,
    "million":         6,
    "billion":         7,
    "most expensive":  9,
    "all-time":        7,
    "historic":        6,
    "first ever":      7,
    "fastest":         6,
    # World Cup / major events
    "world cup":       5,
    "champions league":5,
    "final":           5,
    "knockout":        4,
    # Superstars (guaranteed eyeballs)
    "messi":           6,
    "ronaldo":         6,
    "mbappé":          6,
    "mbappe":          6,
    "haaland":         5,
    "bellingham":      5,
    "neymar":          5,
    "vinicius":        5,
}


def _viral_score(title: str) -> int:
    """Score a headline 0–100 based on viral keyword matches."""
    lower = title.lower()
    return sum(pts for kw, pts in _VIRAL_KEYWORDS.items() if kw in lower)


@dataclass
class NewsItem:
    source: str
    title: str
    description: str
    pub_date: datetime = field(default_factory=lambda: datetime.min.replace(tzinfo=timezone.utc))
    viral_score: int = 0


class RSSClient:
    # VERIFIED = confirmed journalism — Gemini may state as facts
    # RUMOUR   = transfer gossip / tabloid — Gemini must hedge with "reportedly" etc.

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
        # Spanish press (La Liga / Champions League scoops)
        "AS English":         "https://en.as.com/rss/soccer.xml",
        "Marca English":      "https://www.marca.com/en/rss/soccer/",
        # French press
        "L'Equipe":           "https://www.lequipe.fr/rss/actu_rss_Football.xml",
        # South American football
        "Globo Esporte":      "https://ge.globo.com/rss/",
        # World Cup & FIFA
        "FIFA News":          "https://www.fifa.com/en/articles/rss",
    }

    # Transfer gossip / tabloid — always hedged in the prompt
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
                            "User-Agent": (
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0.0.0 Safari/537.36"
                            ),
                            "Accept": "application/rss+xml, application/xml, text/xml, */*",
                        },
                    )
                    with urllib.request.urlopen(req, timeout=12) as response:
                        xml_data = response.read()

                    root = ET.fromstring(xml_data)
                    count = 0
                    for item in root.findall(".//item"):
                        if count >= limit_per_feed:
                            break
                        title_elem   = item.find("title")
                        desc_elem    = item.find("description")
                        pubdate_elem = item.find("pubDate")

                        title = title_elem.text if title_elem is not None else ""
                        desc  = (desc_elem.text or "") if desc_elem is not None else ""
                        desc  = re.sub(r"<[^>]+>", "", desc)  # strip HTML tags

                        # Parse publication date for recency ranking
                        pub_date = datetime.min.replace(tzinfo=timezone.utc)
                        if pubdate_elem is not None and pubdate_elem.text:
                            try:
                                pub_date = parsedate_to_datetime(pubdate_elem.text.strip())
                                if pub_date.tzinfo is None:
                                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                            except Exception:
                                pass

                        if title:
                            score = _viral_score(title)
                            tagged_source = f"{source_name} [{tier_label}]"
                            all_news.append(NewsItem(
                                source=tagged_source,
                                title=title.strip(),
                                description=desc.strip(),
                                pub_date=pub_date,
                                viral_score=score,
                            ))
                            count += 1
                    successful += 1
                except Exception as e:
                    print(f"  Warning: Failed to fetch RSS from {source_name}: {e}", flush=True)

        # ── Sort: viral score descending, then recency descending ──────────
        # This means the most sensational AND most recent stories float to the
        # top of the feed before being passed to Gemini.
        all_news.sort(key=lambda n: (n.viral_score, n.pub_date), reverse=True)

        top_score = all_news[0].viral_score if all_news else 0
        print(
            f"  Fetched {len(all_news)} items from {successful}/{total_sources} sources. "
            f"Top viral score: {top_score}",
            flush=True,
        )
        return all_news
