"""Regression tests for Google News RSS publisher metadata and research handoff."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

os.environ.setdefault("CF_ACCOUNT_ID", "test-account")
os.environ.setdefault("CF_AI_TOKEN", "test-ai-token")
ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run as pipeline


class GoogleNewsPublisherMetadataTests(unittest.TestCase):
    def setUp(self):
        self.item = ET.fromstring(
            "<item>"
            "<title>Space telescope finds a new signal - NASA</title>"
            "<link>https://news.google.com/rss/articles/example?oc=5</link>"
            "<pubDate>Thu, 12 Nov 2026 02:19:00 GMT</pubDate>"
            '<source url="https://www.nasa.gov">NASA</source>'
            "</item>"
        )

    def test_parser_keeps_publisher_from_rss_source_element(self):
        record = pipeline.google_news_item_record(self.item, "US", "Discovery")
        self.assertEqual(record["title"], "Space telescope finds a new signal")
        self.assertEqual(record["publisher_name"], "NASA")
        self.assertEqual(record["publisher_home"], "https://www.nasa.gov")
        self.assertEqual(record["publisher_domain"], "nasa.gov")
        self.assertEqual(record["url"], "https://news.google.com/rss/articles/example?oc=5")

    def test_planner_receives_headline_with_real_publisher_domain(self):
        record = pipeline.google_news_item_record(self.item, "US", "Discovery")
        compact = pipeline.planner_research_items([record])
        self.assertEqual(len(compact), 1)
        self.assertEqual(compact[0]["title"], "Space telescope finds a new signal")
        self.assertEqual(compact[0]["publisher_domain"], "nasa.gov")
        self.assertEqual(compact[0]["publisher_name"], "NASA")
        self.assertTrue(compact[0]["url"].startswith("https://news.google.com/"))

    def test_google_news_html_response_does_not_overwrite_publisher_domain(self):
        class FakeResponse:
            status_code = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}
            text = (
                "<html><body><p>This paragraph is deliberately longer than fifty "
                "characters so the evidence parser will retain this useful excerpt.</p></body></html>"
            )
            url = "https://news.google.com/rss/articles/example?oc=5"

        record = pipeline.google_news_item_record(self.item, "US", "Discovery")
        with patch.object(pipeline.requests, "get", return_value=FakeResponse()):
            enriched = pipeline.enrich_source_evidence([record])
        self.assertEqual(enriched[0]["publisher_domain"], "nasa.gov")
        self.assertEqual(enriched[0]["url"], record["url"])

    def test_missing_publisher_metadata_uses_explicit_headline_fallback(self):
        item = {
            "title": "A new instrument reaches the concert hall",
            "url": "https://news.google.com/rss/articles/unresolved",
            "publisher_domain": "",
        }
        compact = pipeline.planner_research_items([item])
        self.assertEqual(len(compact), 1)
        self.assertEqual(compact[0]["title"], item["title"])


if __name__ == "__main__":
    unittest.main()
