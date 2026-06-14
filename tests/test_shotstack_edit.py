import unittest

from football_pipeline.models import BrollAsset, TopicPackage
from football_pipeline.shotstack_edit import build_shotstack_edit


class ShotstackEditTests(unittest.TestCase):
    def test_build_shotstack_edit_uses_vertical_output_and_alias_captions(self) -> None:
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

        edit = build_shotstack_edit(topic, broll, "https://example.com/voice.mp3", target_seconds=60)

        self.assertEqual(edit["output"]["aspectRatio"], "9:16")
        self.assertEqual(edit["timeline"]["tracks"][1]["clips"][0]["asset"]["src"], "alias://voiceover")
        self.assertEqual(edit["timeline"]["tracks"][2]["clips"][0]["alias"], "voiceover")
        self.assertEqual(edit["timeline"]["tracks"][3]["clips"][0]["asset"]["volume"], 0)


if __name__ == "__main__":
    unittest.main()
