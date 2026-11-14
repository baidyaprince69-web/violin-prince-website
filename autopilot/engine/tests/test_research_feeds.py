"""Regression tests for Google News RSS publisher metadata and research handoff."""
import json
import os
import sys
import unittest
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

os.environ.setdefault("CF_ACCOUNT_ID", "test-account")
os.environ.setdefault("CF_AI_TOKEN", "test-ai-token")
ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run as pipeline


def datetime_for_test(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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

    def test_google_news_redirect_is_visible_only_as_a_discovery_lead(self):
        record = pipeline.google_news_item_record(self.item, "US", "Discovery")
        compact = pipeline.planner_research_items([record])
        self.assertEqual(len(compact), 1)
        self.assertEqual(compact[0]["source_eligibility"], "discovery_only")
        self.assertEqual(compact[0]["evidence_text"], "")
        self.assertEqual(pipeline.resolve_plan_sources({"sources": ["S0001"]}, compact), [])

    def test_planner_accepts_direct_publisher_article_links(self):
        record = pipeline.google_news_item_record(self.item, "US", "Discovery")
        record["url"] = "https://www.nasa.gov/news-release/example-article/"
        record["evidence_text"] = (
            "NASA published a detailed article about the discovery. "
            "The article explains the instrument, the research team, and the published findings."
        )
        compact = pipeline.planner_research_items([record])
        self.assertEqual(len(compact), 1)
        self.assertEqual(compact[0]["title"], "Space telescope finds a new signal")
        self.assertEqual(compact[0]["publisher_domain"], "nasa.gov")
        self.assertEqual(compact[0]["publisher_name"], "NASA")
        self.assertEqual(compact[0]["url"], "https://www.nasa.gov/news-release/example-article/")

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

    def test_unresolved_google_news_link_is_not_promoted_to_a_publisher_citation(self):
        item = {
            "title": "A new instrument reaches the concert hall",
            "url": "https://news.google.com/rss/articles/unresolved",
            "publisher_domain": "",
        }
        compact = pipeline.planner_research_items([item])
        self.assertEqual(len(compact), 1)
        self.assertEqual(compact[0]["source_eligibility"], "discovery_only")
        self.assertEqual(pipeline.resolve_plan_sources({"sources": ["S0001"]}, compact), [])


    def test_google_news_article_id_is_parsed_from_rss_and_read_urls(self):
        self.assertEqual(
            pipeline._google_news_article_id(
                "https://news.google.com/rss/articles/CBMiExample_token-123?oc=5&ceid=US:en"
            ),
            "CBMiExample_token-123",
        )
        self.assertEqual(
            pipeline._google_news_article_id("https://news.google.com/articles/ArticleToken"),
            "ArticleToken",
        )
        self.assertEqual(pipeline._google_news_article_id("https://example.com/articles/not-google"), "")

    def test_google_news_batchexecute_resolver_returns_matching_publisher_url(self):
        publisher_url = "https://www.nasa.gov/news-release/space-telescope-signal/"
        inner = json.dumps([None, publisher_url], separators=(",", ":"))
        response_body = ")]}'\n" + json.dumps([["wrb.fr", "Fbv4je", inner, None, "generic"]])

        class FakeResponse:
            text = response_body

            def raise_for_status(self):
                return None

        with patch.object(pipeline.requests, "post", return_value=FakeResponse()) as post:
            resolved = pipeline.resolve_google_news_article_url(
                "https://news.google.com/rss/articles/CBMiExample_token?oc=5&ceid=US:en",
                '<div data-n-a-sg="signed-value" data-n-a-ts="1794564000"></div>',
                expected_domain="nasa.gov",
            )
        self.assertEqual(resolved, publisher_url)
        self.assertEqual(post.call_count, 1)
        self.assertIn("batchexecute", post.call_args.args[0])
        self.assertIn("Fbv4je", post.call_args.kwargs["data"])
        self.assertIn("signed-value", post.call_args.kwargs["data"])

    def test_google_news_resolver_rejects_wrong_publisher_domain(self):
        publisher_url = "https://unrelated.example/story/"
        inner = json.dumps([None, publisher_url], separators=(",", ":"))
        response_body = json.dumps([["wrb.fr", "Fbv4je", inner, None, "generic"]])

        class FakeResponse:
            text = response_body

            def raise_for_status(self):
                return None

        with patch.object(pipeline.requests, "post", return_value=FakeResponse()):
            with self.assertRaisesRegex(ValueError, "did not match"):
                pipeline.resolve_google_news_article_url(
                    "https://news.google.com/rss/articles/CBMiExample_token",
                    '<div data-n-a-sg="sig" data-n-a-ts="1794564000"></div>',
                    expected_domain="nasa.gov",
                )

    def test_google_news_wrapper_is_promoted_only_after_real_article_resolution(self):
        publisher_url = "https://www.nasa.gov/news-release/space-telescope-signal/"
        inner = json.dumps([None, publisher_url], separators=(",", ":"))
        rpc_text = ")]}'\n" + json.dumps([["wrb.fr", "Fbv4je", inner, None, "generic"]])

        class FakeResponse:
            def __init__(self, url, text):
                self.status_code = 200
                self.headers = {"Content-Type": "text/html; charset=utf-8"}
                self.url = url
                self.text = text

        google_page = (
            '<html><body><div data-n-a-sg="signed-value" '
            'data-n-a-ts="1794564000"></div></body></html>'
        )
        publisher_page = (
            '<html><head>'
            '<meta property="og:type" content="article">'
            '<meta property="article:published_time" content="2026-11-12T02:19:00Z">'
            '<meta property="og:title" content="Space telescope finds a new signal">'
            '</head><body>'
            '<p>NASA scientists reported a new signal from the space telescope instrument. '
            'The team described the observation and its implications for the mission.</p>'
            '<p>The article explains how the instrument collected the data and how the '
            'researchers will examine the signal in follow-up observations.</p>'
            '</body></html>'
        )
        record = pipeline.google_news_item_record(self.item, "US", "Discovery")
        with patch.object(
            pipeline.requests,
            "get",
            side_effect=[
                FakeResponse(record["url"], google_page),
                FakeResponse(publisher_url, publisher_page),
            ],
        ), patch.object(
            pipeline.requests,
            "post",
            return_value=type("RPCResponse", (), {
                "text": rpc_text,
                "raise_for_status": lambda self: None,
            })(),
        ):
            enriched = pipeline.enrich_source_evidence([record])[0]

        self.assertTrue(enriched["article_page_verified"])
        self.assertEqual(enriched["url"], publisher_url)
        self.assertEqual(enriched["publisher_domain"], "nasa.gov")
        self.assertEqual(enriched["publisher_resolution_status"], "resolved_via_google_news_batchexecute")
        self.assertEqual(enriched["published_at_utc"], "2026-11-12T02:19:00Z")
        self.assertEqual(enriched["source_url_original"], record["url"])
        self.assertGreaterEqual(len(enriched["evidence_text"]), 90)

    def test_publisher_publication_date_can_be_extracted_from_time_element(self):
        html = (
            '<html><head><meta property="og:title" content="A violin discovery"></head>'
            '<body><time itemprop="datePublished" datetime="2026-11-13T09:30:00Z">'
            'November 13</time></body></html>'
        )
        metadata = pipeline.extract_article_page_metadata(html)
        self.assertEqual(metadata["published_at_utc"], "2026-11-13T09:30:00Z")
        self.assertTrue(metadata["has_publication_metadata"])

    def test_og_article_tag_does_not_make_a_category_or_wrong_story_an_article(self):
        category_html = (
            '<html><head><meta property="og:type" content="article">'
            '<meta property="og:title" content="Music News"></head>'
            '<body><p>A section page containing many music headlines and links to other pages.</p></body></html>'
        )
        category_meta = pipeline.extract_article_page_metadata(category_html)
        self.assertFalse(pipeline._article_page_verified(
            {"title": "A new violin research discovery"},
            "https://hollywoodreporter.com/c/music/film-tv-music-news/",
            category_html,
            category_meta,
        ))
        wrong_title_html = (
            '<html><head><meta property="og:type" content="article">'
            '<meta property="og:title" content="Music News"></head>'
            '<body><p>A real article body with enough words but a different subject from the supplied headline.</p></body></html>'
        )
        wrong_meta = pipeline.extract_article_page_metadata(wrong_title_html)
        self.assertFalse(pipeline._article_page_verified(
            {"title": "NASA discovers a new space telescope signal"},
            "https://example.com/2026/new-article/",
            wrong_title_html,
            wrong_meta,
        ))

    def test_targeted_records_after_first_hundred_are_not_dropped(self):
        records = [
            {
                "title": f"Publisher report number {index}",
                "url": f"https://publisher{index}.example/articles/report-{index}",
                "publisher_domain": f"publisher{index}.example",
            }
            for index in range(135)
        ]
        compact = pipeline.planner_research_items(records)
        self.assertEqual(len(compact), 135)
        self.assertEqual(compact[-1]["url"], records[-1]["url"])

    def test_google_news_interstitial_can_expose_a_matching_article_url(self):
        page = (
            '<html><body><a href="https://www.nasa.gov/news-release/example-article/">'
            "Read the article</a></body></html>"
        )
        resolved = pipeline._publisher_article_url_from_html(page, "nasa.gov")
        self.assertEqual(resolved, "https://www.nasa.gov/news-release/example-article/")


    def test_modern_google_news_url_id_and_signed_rpc_resolution(self):
        article_url = (
            "https://news.google.com/rss/articles/"
            "CBMiQ0VJbVdIY2x1d2RZcF9hZ2VudF9pZA?oc=5&ceid=US:en"
        )
        self.assertEqual(
            pipeline._google_news_article_id(article_url),
            "CBMiQ0VJbVdIY2x1d2RZcF9hZ2VudF9pZA",
        )
        self.assertEqual(pipeline._google_news_article_id("https://example.com/story"), "")

        class FakeResponse:
            status_code = 200
            text = (
                ")]}'\n"
                + __import__("json").dumps([[
                    "wrb.fr",
                    "Fbv4je",
                    __import__("json").dumps([
                        "garturlres",
                        "https://news.mit.edu/2026/virtual-violin-model",
                    ]),
                    None, None, None, "generic",
                ]])
                + "\n"
            )

            def raise_for_status(self):
                return None

        page = '<div data-n-a-sg="signed-value" data-n-a-ts="1794660000"></div>'
        with patch.object(pipeline.requests, "post", return_value=FakeResponse()) as post:
            resolved = pipeline.resolve_google_news_article_url(
                article_url, page, expected_domain="news.mit.edu"
            )
        self.assertEqual(resolved, "https://news.mit.edu/2026/virtual-violin-model")
        args, kwargs = post.call_args
        self.assertIn("batchexecute", args[0])
        self.assertIn("f.req=", kwargs["data"])
        self.assertIn("CBMiQ0VJbVdIY2x1d2RZcF9hZ2VudF9pZA", kwargs["data"])

    def test_google_news_resolver_rejects_destination_outside_rss_publisher(self):
        article_url = "https://news.google.com/rss/articles/CBMiQ0VJbVdIY2x1d2RZcF9hZ2VudF9pZA"
        class FakeResponse:
            text = (
                "[["
                '"wrb.fr","Fbv4je","'
                + __import__("json").dumps([
                    "garturlres", "https://unrelated.example/story"
                ]).replace('"', '\\"')
                + '",null,null,null,"generic"]]'
            )
            def raise_for_status(self):
                return None
        page = '<div data-n-a-sg="sig" data-n-a-ts="1794660000"></div>'
        with patch.object(pipeline.requests, "post", return_value=FakeResponse()):
            with self.assertRaisesRegex(ValueError, "did not match its RSS publisher"):
                pipeline.resolve_google_news_article_url(
                    article_url, page, expected_domain="news.mit.edu"
                )

    def test_google_news_enrichment_resolves_article_and_uses_publisher_evidence(self):
        article_url = (
            "https://news.google.com/rss/articles/"
            "CBMiQ0VJbVdIY2x1d2RZcF9hZ2VudF9pZA?oc=5&ceid=US:en"
        )
        publisher_url = "https://news.mit.edu/2026/virtual-violin-model"
        class FakeResponse:
            status_code = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}
            def __init__(self, url, text):
                self.url = url
                self.text = text

        google_page = (
            '<html><head><title>Google News</title></head>'
            '<body><div data-n-a-sg="signed-value" data-n-a-ts="1794660000"></div></body></html>'
        )
        publisher_page = (
            '<html><head><meta property="og:type" content="article">'
            '<meta property="article:published_time" content="2026-11-13T08:00:00Z">'
            '<meta property="og:title" content="MIT engineers develop a physics based virtual violin model">'
            '<script type="application/ld+json">'
            '{"@type":"NewsArticle","headline":"MIT engineers develop a physics based virtual violin model",'
            '"datePublished":"2026-11-13T08:00:00Z"}'
            '</script></head><body><article><p>'
            'MIT engineers developed a physics based virtual violin model that simulates string vibration, '
            'the interaction between the instrument structure and surrounding air, and the effects of '
            'different wood types and body thicknesses on acoustic properties. The research team describes '
            'how the model can predict instrument behavior before a physical violin is built.'
            '</p></article></body></html>'
        )
        record = {
            "title": "MIT engineers develop a physics based virtual violin model",
            "url": article_url,
            "date": "Fri, 13 Nov 2026 08:00:00 GMT",
            "publisher_name": "MIT News",
            "publisher_domain": "news.mit.edu",
        }
        with patch.object(
            pipeline.requests,
            "get",
            side_effect=[
                FakeResponse(article_url, google_page),
                FakeResponse(publisher_url, publisher_page),
            ],
        ) as get, patch.object(
            pipeline.requests,
            "post",
            return_value=type(
                "RpcResponse",
                (),
                {
                    "text": "[[" + '"wrb.fr","Fbv4je","'
                    + __import__("json").dumps(["garturlres", publisher_url]).replace('"', '\\"')
                    + '",null,null,null,"generic"]]',
                    "raise_for_status": lambda self: None,
                },
            )(),
        ):
            enriched = pipeline.enrich_source_evidence([record])
        self.assertEqual(get.call_count, 2)
        self.assertEqual(enriched[0]["url"], publisher_url)
        self.assertEqual(enriched[0]["source_url_original"], article_url)
        self.assertEqual(enriched[0]["publisher_domain"], "news.mit.edu")
        self.assertTrue(enriched[0]["article_page_verified"])
        self.assertEqual(
            enriched[0]["publisher_resolution_status"],
            "resolved_via_google_news_batchexecute",
        )
        self.assertIn("MIT engineers developed", enriched[0]["evidence_text"])
        self.assertEqual(
            pipeline.article_freshness(
                enriched[0],
                as_of=datetime_for_test("2026-11-14T08:00:00Z"),
            )["freshness_status"],
            "preferred",
        )

    def test_article_verification_does_not_trust_og_type_on_a_section_page(self):
        url = "https://culture.org/art-and-culture/"
        html = (
            '<meta property="og:type" content="article">'
            '<meta property="og:title" content="Art & Culture - Art news and Cultural Trends">'
        )
        metadata = pipeline.extract_article_page_metadata(html)
        item = {"title": "Art & Culture - Art news and Cultural Trends"}
        self.assertTrue(metadata["og_type_article"])
        self.assertFalse(metadata["structured_article"])
        self.assertFalse(metadata["has_publication_metadata"])
        self.assertFalse(pipeline._article_page_verified(item, url, html, metadata))


if __name__ == "__main__":
    unittest.main()
