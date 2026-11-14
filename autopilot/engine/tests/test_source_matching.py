"""Regression tests for robust source ID and URL resolution."""
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch
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
                "evidence_text": "MIT News explains how engineers developed the virtual violin and tested its realistic sound. The article describes the research team and its findings in detail.",
                "publisher_name": "MIT News",
                "publisher_domain": "news.mit.edu",
                "url": "https://news.mit.edu/2026/virtual-violin",
                "source": "MIT News",
            },
            {
                "title": "A new concert season begins in the city",
                "summary": "A local orchestra announced its concert schedule.",
                "evidence_text": "City Arts reviewed a virtual violin performance and reported how the instrument produced a realistic sound. The article explains the concert context and the instrument's role in the programme.",
                "publisher_name": "City Arts",
                "publisher_domain": "arts.example",
                "url": "https://arts.example/concert-season",
                "source": "City Arts",
            },
        ]
        self.compact = pipeline.planner_research_items(self.items)

    def test_planner_assigns_stable_source_ids(self):
        self.assertTrue(all(item["source_id"].startswith("SRC_") for item in self.compact))
        initial = {item["url"]: item["source_id"] for item in self.compact}
        reversed_results = {
            item["url"]: item["source_id"]
            for item in pipeline.planner_research_items(list(reversed(self.items)))
        }
        self.assertEqual(initial, reversed_results)

    def test_source_id_resolves_to_original_research_url(self):
        plan = {
            "topic": "A virtual violin with realistic sound",
            "title": "The virtual violin",
            "hook": "Can a virtual violin sound real?",
            "sources": [self.compact[0]["source_id"]],
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

    def test_verified_story_sources_require_two_independent_direct_publishers(self):
        plan = {
            "topic": "A virtual violin with realistic sound",
            "title": "The virtual violin",
            "hook": "Can a virtual violin sound real?",
            "sources": [],
        }
        selected = pipeline.select_verified_story_sources(plan, self.items, minimum_sources=2)
        self.assertEqual(len(selected), 2)
        self.assertEqual(
            {item["publisher_domain"] for item in selected},
            {"news.mit.edu", "arts.example"},
        )
        self.assertTrue(all(pipeline.is_direct_publisher_article(item) for item in selected))

    def test_verified_story_sources_fail_closed_when_only_one_publisher_exists(self):
        plan = {
            "topic": "A virtual violin with realistic sound",
            "title": "The virtual violin",
            "hook": "Can a virtual violin sound real?",
            "sources": [],
        }
        with self.assertRaisesRegex(pipeline.PipelineError, "at least 2 independent publishers"):
            pipeline.select_verified_story_sources(plan, self.items[:1], minimum_sources=2)

    def test_story_search_includes_relevant_seed_headline_variants(self):
        plan = {
            "topic": "MIT Virtual Violin Technology",
            "title": "The Digital Soul of the Violin",
            "hook": "Can a computer mimic a violin?",
        }
        phrases = pipeline.story_search_phrases(plan, self.items)
        self.assertIn("MIT engineers' virtual violin produces realistic sounds", phrases)
        self.assertIn("mit virtual violin technology digital soul", phrases)
        self.assertNotIn("A new concert season begins in the city", phrases)

    def test_bing_news_rss_record_preserves_publisher_and_article_url(self):
        item = ET.fromstring(
            "<item>"
            "<title>MIT virtual violin produces realistic sounds - MIT News</title>"
            "<link>https://news.mit.edu/2026/virtual-violin</link>"
            "<pubDate>Wed, 14 Nov 2026 10:00:00 GMT</pubDate>"
            '<source url="https://news.mit.edu">MIT News</source>'
            "</item>"
        )
        record = pipeline.bing_news_item_record(item)
        self.assertEqual(record["title"], "MIT virtual violin produces realistic sounds")
        self.assertEqual(record["publisher_name"], "MIT News")
        self.assertEqual(record["publisher_domain"], "news.mit.edu")
        self.assertEqual(record["url"], "https://news.mit.edu/2026/virtual-violin")
        self.assertEqual(record["summary"], "")
        self.assertEqual(record["link_type"], "discovery_lead")

    def test_research_continues_on_rss_after_first_gdelt_429(self):
        bing_xml = (
            b"<rss><channel><item>"
            b"<title>MIT virtual violin produces realistic sounds - MIT News</title>"
            b"<link>https://news.mit.edu/2026/virtual-violin</link>"
            b"<pubDate>Wed, 14 Nov 2026 10:00:00 GMT</pubDate>"
            b'<source url="https://news.mit.edu">MIT News</source>'
            b"</item></channel></rss>"
        )
        empty_rss = b"<rss><channel></channel></rss>"

        class FakeResponse:
            def __init__(self, content=b"", status_code=200):
                self.content = content
                self.status_code = status_code

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise pipeline.requests.HTTPError(
                        f"HTTP {self.status_code}", response=self
                    )

            def json(self):
                return {"articles": []}

        gdelt_calls = []
        bing_calls = []

        def fake_get(url, *args, **kwargs):
            if "api.gdeltproject.org" in url:
                gdelt_calls.append(url)
                return FakeResponse(status_code=429)
            if "news.google.com" in url:
                return FakeResponse(content=empty_rss)
            if "bing.com/news/search" in url:
                bing_calls.append(url)
                return FakeResponse(content=bing_xml)
            raise AssertionError("Unexpected story research URL: " + str(url))

        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with (
                    patch.object(pipeline, "story_search_phrases", return_value=["virtual violin", "MIT violin"]),
                    patch.object(pipeline.http, "get", side_effect=fake_get),
                    patch.object(pipeline, "enrich_source_evidence", side_effect=lambda items: items),
                ):
                    result = pipeline.research_story_sources(
                        {"topic": "MIT virtual violin", "title": "Digital violin"},
                        self.items[:1],
                    )
            finally:
                pipeline.WORK = original_work

        self.assertEqual(len(gdelt_calls), 1, "GDELT should pause after its first 429")
        self.assertEqual(len(bing_calls), 2, "Bing RSS should be attempted for each broad query")
        self.assertTrue(any(
            item.get("source_feed") == "Bing News story search"
            and item.get("url") == "https://news.mit.edu/2026/virtual-violin"
            for item in result
        ))

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
