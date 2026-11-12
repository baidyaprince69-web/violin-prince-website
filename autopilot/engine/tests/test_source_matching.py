"""Regression tests for robust source ID and URL resolution."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("CF_ACCOUNT_ID", "test-account")
os.environ.setdefault("CF_AI_TOKEN", "test-ai-token")
ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run as pipeline


class PlannerSourceMatchingTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            {
                "title": "MIT engineers' virtual violin produces realistic sounds",
                "summary": "Researchers developed a virtual violin with realistic sound.",
                "evidence_text": "",
                "publisher_name": "MIT News",
                "publisher_domain": "news.mit.edu",
                "url": "https://news.google.com/rss/articles/virtual-violin?oc=5",
                "source": "MIT News",
            },
            {
                "title": "A new concert season begins in the city",
                "summary": "A local orchestra announced its concert schedule.",
                "evidence_text": "",
                "publisher_name": "City Arts",
                "publisher_domain": "arts.example",
                "url": "https://arts.example/concert-season",
                "source": "City Arts",
            },
        ]
        self.compact = pipeline.planner_research_items(self.items)

    def test_planner_assigns_stable_source_ids(self):
        self.assertEqual([item["source_id"] for item in self.compact], ["S0001", "S0002"])

    def test_source_id_resolves_to_original_research_url(self):
        plan = {
            "topic": "A virtual violin with realistic sound",
            "title": "The virtual violin",
            "hook": "Can a virtual violin sound real?",
            "sources": ["S0001"],
        }
        selected = pipeline.resolve_plan_sources(plan, self.compact)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["url"], self.items[0]["url"])

    def test_publisher_name_resolves_without_rewriting_url(self):
        plan = {
            "topic": "A virtual violin with realistic sound",
            "title": "The virtual violin",
            "hook": "Can a virtual violin sound real?",
            "sources": ["MIT News"],
        }
        selected = pipeline.resolve_plan_sources(plan, self.compact)
        self.assertEqual([item["url"] for item in selected], [self.items[0]["url"]])

    def test_topic_fallback_uses_closest_supplied_headline(self):
        plan = {
            "topic": "A virtual violin produces realistic sound",
            "title": "How engineers recreated a violin virtually",
            "hook": "Can a virtual violin sound real?",
            "narration_script": "Engineers developed a virtual violin with realistic sound.",
            "sources": ["https://mit.edu/a-made-up-article"],
        }
        selected = pipeline.resolve_plan_sources(plan, self.compact)
        self.assertEqual([item["url"] for item in selected], [self.items[0]["url"]])

    def test_url_normalization_ignores_tracking_query_and_www(self):
        self.assertEqual(
            pipeline.source_key("https://www.example.com/article?utm_source=feed#top"),
            pipeline.source_key("https://example.com/article?oc=5"),
        )

    def test_unrelated_plan_does_not_get_random_source(self):
        plan = {
            "topic": "A deep ocean fossil discovery",
            "title": "Ancient fossils beneath the sea",
            "hook": "What is hidden under oceans?",
            "sources": [],
        }
        selected = pipeline.resolve_plan_sources(plan, self.compact)
        self.assertEqual(selected, [])


if __name__ == "__main__":
    unittest.main()
