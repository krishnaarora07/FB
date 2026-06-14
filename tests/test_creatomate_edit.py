import unittest

from football_pipeline.models import BrollAsset, TopicPackage
from football_pipeline.creatomate_edit import build_creatomate_edit


class CreatomateEditTests(unittest.TestCase):
    def test_build_creatomate_edit_uses_vertical_output_and_transcript(self) -> None:
        topic = TopicPackage(
            topic_title="Can this midfield survive the World Cup?",
            angle="A short angle.",
            script="This is a quick football script with enough words to estimate a compact duration.",
            broll_queries=["football stadium"],
            youtube_title="World Cup midfield watch",
            youtube_description="Description",
            hashtags=["#Football"],
            source_video_ids=["abc"],
        )
        broll = [
            BrollAsset(
                keyword="football stadium",
                url="https://example.com/video.mp4",
                duration=8,
                width=1080,
                height=1920,
                pexels_id=1,
                pexels_url="https://pexels.com/video/1",
                credit="Creator / Pexels",
            )
        ]

        edit = build_creatomate_edit(topic, broll, "https://example.com/voice.mp3", target_seconds=60)

        self.assertEqual(edit["output_format"], "mp4")
        self.assertEqual(edit["width"], 1080)
        self.assertEqual(edit["height"], 1920)
        
        # Check elements
        elements = edit["elements"]
        self.assertTrue(any(e["type"] == "video" for e in elements))
        self.assertTrue(any(e["type"] == "audio" for e in elements))
        self.assertTrue(any(e.get("transcript_source") for e in elements))


if __name__ == "__main__":
    unittest.main()
