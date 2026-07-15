from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import List
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Viral keyword scoring
# Each keyword that appears in the title adds the listed points.
# Higher = more likely to go viral on YouTube Shorts.
# Last refreshed: July 2026
# ---------------------------------------------------------------------------
_VIRAL_KEYWORDS: dict[str, int] = {
    # ── Transfer bombshells (highest virality) ──────────────────────────────
    "done deal":        10,
    "confirmed":         9,
    "medical":           9,   # "passes medical" = effectively done deal
    "signs":             8,
    "transfer":          7,
    "shock move":        9,
    "deadline":          8,
    "bid":               6,
    "offer":             6,
    "rejected":          8,
    "refuses":           8,
    "walks out":         9,
    "quit":              8,
    "quits":             8,
    "sacked":            9,
    "fired":             8,
    "axed":              8,   # Same energy as "sacked" — tabloid favourite
    "resign":            8,
    "exclusive":         7,
    "breaking":          8,
    "agreement":         7,   # "agreement reached" = nearly done deal
    "swap deal":         8,
    "release clause":    8,
    "buyout":            7,
    "snubs":             7,   # "snubs [club] to join [rival]" = drama
    "ghosted":           7,   # "club ghosted by star" = trending format
    "leaked contract":   9,
    # ── Drama / controversy ─────────────────────────────────────────────────
    "ban":               8,
    "banned":            8,
    "suspended":         7,
    "row":               6,
    "crisis":            7,
    "fury":              7,
    "furious":           7,
    "slams":             7,
    "blasts":            7,
    "war":               6,
    "feud":              6,
    "demands":           6,
    "leaked":            8,
    "reveals":           7,
    "admits":            6,
    "accused":           7,
    "arrest":            9,
    "scandal":           9,
    "betrayal":          8,
    "humiliated":        8,
    "embarrassed":       7,
    "dropped":           7,   # "dropped from squad" = controversy
    "benched":           6,
    "rift":              7,
    "fallout":           7,
    "fight":             7,
    "clash":             6,
    "argument":          6,
    "investigation":     8,
    "fraud":             9,
    # ── Career-defining moments ─────────────────────────────────────────────
    "retirement":        9,   # Huge emotional hook — always viral
    "comes out of retirement": 10,
    "comeback":          7,
    "returns":           6,
    "injury":            6,
    "ruled out":         7,   # "ruled out for season" = drama
    "surgery":           7,
    "career-ending":    10,
    # ── Records / stats ─────────────────────────────────────────────────────
    "record":            7,
    "million":           6,
    "billion":           7,
    "most expensive":    9,
    "all-time":          7,
    "historic":          6,
    "first ever":        7,
    "fastest":           6,
    "youngest":          7,
    "oldest":            6,
    "hat-trick":         7,
    "hat trick":         7,
    "brace":             5,
    "masterclass":       5,
    # ── World Cup 2026 — peak traffic event ─────────────────────────────────
    "world cup 2026":   10,   # Specific to current tournament — highest priority
    "world cup":         6,   # Bumped from 5 — tournament is live
    "wc2026":            9,
    "group stage":       5,
    "round of 16":       7,
    "quarter-final":     8,
    "semi-final":        9,
    "final":             8,   # Bumped from 5 — finals are massive now
    "knockout":          5,
    "penalty shootout":  9,
    "penalties":         7,
    "golden boot":       8,
    "golden glove":      7,
    "host nation":       5,
    # ── Champions League / major clubs ──────────────────────────────────────
    "champions league":  6,
    "europa league":     5,
    "premier league":    5,
    "la liga":           5,
    "serie a":           5,
    "bundesliga":        5,
    # ── 2026 Superstars (biggest guaranteed eyeballs) ───────────────────────
    "messi":             7,   # Bumped — still massive, WC context
    "ronaldo":           7,   # Bumped — retirement rumours circulating
    "mbappé":            7,
    "mbappe":            7,
    "haaland":           6,
    "bellingham":        6,
    "lamine yamal":      8,   # Breakout star — trending constantly
    "yamal":             7,
    "vinicius":          6,
    "vinicius jr":       6,
    "neymar":            5,
    "saka":              6,
    "salah":             6,
    "osimhen":           6,
    "gyokeres":          6,   # Top transfer target summer 2026
    "pedri":             5,
    "gavi":              5,
    "rodri":             6,
    "de bruyne":         6,
    "kane":              6,
}


def _viral_score(title: str, pub_date: datetime) -> int:
    """Score a headline based on viral keyword matches + recency bonus.

    Recency bonus:
      < 2 hours old  → +5  (breaking news)
      < 6 hours old  → +3  (very fresh)
      >= 6 hours old →  +0
    """
    lower = title.lower()
    base = sum(pts for kw, pts in _VIRAL_KEYWORDS.items() if kw in lower)

    # Recency bonus — older stories penalised implicitly via sort,
    # but fresh breaking news gets an explicit bump to surface faster.
    try:
        age_hours = (datetime.now(timezone.utc) - pub_date).total_seconds() / 3600
        if age_hours < 2:
            recency_bonus = 5
        elif age_hours < 6:
            recency_bonus = 3
        else:
            recency_bonus = 0
    except Exception:
        recency_bonus = 0

    return base + recency_bonus


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
        # Premium journalism
        "FourFourTwo":        "https://www.fourfourtwo.com/rss",
    }

    # Transfer gossip / tabloid — always hedged in the prompt
    RUMOUR_FEEDS = {
        "TalkSPORT":          "https://talksport.com/feed/",
        "Mirror Football":    "https://www.mirror.co.uk/sport/football/rss.xml",
        "Calciomercato":      "https://www.calciomercato.com/en/rss",
        "Football Transfers": "https://www.footballtransfers.com/en/transfer-news/rss",
    }

    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }

    def _fetch_one_feed(
        self,
        source_name: str,
        url: str,
        tier_label: str,
        limit: int,
    ) -> tuple[list[NewsItem], bool]:
        """Fetch and parse a single RSS feed. Returns (items, success_flag)."""
        items: list[NewsItem] = []
        try:
            req = urllib.request.Request(url, headers=self._HEADERS)
            with urllib.request.urlopen(req, timeout=12) as response:
                xml_data = response.read()

            root = ET.fromstring(xml_data)
            count = 0
            tagged_source = f"{source_name} [{tier_label}]"

            for item in root.findall(".//item"):
                if count >= limit:
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
                    score = _viral_score(title, pub_date)
                    items.append(NewsItem(
                        source=tagged_source,
                        title=title.strip(),
                        description=desc.strip(),
                        pub_date=pub_date,
                        viral_score=score,
                    ))
                    count += 1

            return items, True

        except Exception as e:
            print(f"  Warning: Failed to fetch RSS from {source_name}: {e}", flush=True)
            return [], False

    def fetch_news(self, limit_per_feed: int = 15) -> List[NewsItem]:
        """Fetch all RSS feeds in parallel and return scored, sorted news items."""
        all_feeds: list[tuple[str, str, str]] = []
        for tier_label, feeds in [
            ("VERIFIED", self.VERIFIED_FEEDS),
            ("RUMOUR",   self.RUMOUR_FEEDS),
        ]:
            for source_name, url in feeds.items():
                all_feeds.append((source_name, url, tier_label))

        total_sources = len(all_feeds)
        print(
            f"  Fetching real-time football news from {total_sources} sources in parallel "
            f"({len(self.VERIFIED_FEEDS)} verified + {len(self.RUMOUR_FEEDS)} rumour)...",
            flush=True,
        )

        all_news: list[NewsItem] = []
        successful = 0

        # ── Parallel fetch — all feeds concurrently ─────────────────────────
        # max_workers=16 is safe: these are pure I/O (network) tasks, not CPU.
        with ThreadPoolExecutor(max_workers=16) as executor:
            future_to_source = {
                executor.submit(self._fetch_one_feed, name, url, tier, limit_per_feed): name
                for name, url, tier in all_feeds
            }
            for future in as_completed(future_to_source):
                items, ok = future.result()
                all_news.extend(items)
                if ok:
                    successful += 1

        # ── Sort: viral score descending, then recency descending ────────────
        # The most sensational AND most recent stories float to the top
        # before being passed to Gemini.
        all_news.sort(key=lambda n: (n.viral_score, n.pub_date), reverse=True)

        top_score = all_news[0].viral_score if all_news else 0
        print(
            f"  Fetched {len(all_news)} items from {successful}/{total_sources} sources. "
            f"Top viral score: {top_score}",
            flush=True,
        )
        return all_news
