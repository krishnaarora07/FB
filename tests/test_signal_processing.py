import unittest

from football_pipeline.models import VideoSignal
from football_pipeline.signal_processing import dedupe_videos, is_football_related, rank_videos


def video(video_id: str, title: str, views: int, source: str = "trending:US") -> VideoSignal:
    return VideoSignal(
        video_id=video_id,
        title=title,
        channel_title="Channel",
        channel_id="channel",
        published_at="2026-06-11T00:00:00Z",
        description="",
        tags=[],
        view_count=views,
        like_count=0,
        comment_count=0,
        source=source,
        url=f"https://www.youtube.com/watch?v={video_id}",
    )


class SignalProcessingTests(unittest.TestCase):
    def test_football_keyword_filter(self) -> None:
        self.assertTrue(is_football_related(video("1", "World Cup squad shock", 10), ["world cup"]))
        self.assertFalse(is_football_related(video("2", "Basketball highlights", 10), ["world cup"]))

    def test_dedupe_keeps_higher_score(self) -> None:
        lower = video("1", "World Cup", 10)
        higher = video("1", "World Cup", 1000)
        self.assertEqual(dedupe_videos([lower, higher]), [higher])

    def test_rank_videos_by_score(self) -> None:
        ranked = rank_videos([video("a", "World Cup", 10), video("b", "World Cup", 1000)])
        self.assertEqual([item.video_id for item in ranked], ["b", "a"])


if __name__ == "__main__":
    unittest.main()
