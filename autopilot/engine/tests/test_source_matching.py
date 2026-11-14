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
            if "html.duckduckgo.com" in url:
                return FakeResponse(content=empty_rss)
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

    def test_news_aggregator_urls_never_count_as_publisher_articles(self):
        for url in (
            "https://www.bing.com/news/apiclick.aspx?ref=feed",
            "https://www.msn.com/en-us/news/science/story",
            "https://news.google.com/rss/articles/example",
            "https://duckduckgo.com/?q=violin",
        ):
            with self.subTest(url=url):
                self.assertFalse(pipeline.is_direct_publisher_article(url))

    def test_bing_namespaced_source_metadata_preserves_publisher_domain(self):
        item = ET.fromstring(
            '<item xmlns:News="https://schemas.microsoft.com/News/2010/10">'
            "<title>MIT virtual violin produces realistic sounds - MIT News</title>"
            "<link>https://www.bing.com/news/apiclick.aspx?ref=feed</link>"
            "<pubDate>Sat, 14 Nov 2026 10:00:00 GMT</pubDate>"
            '<News:Source Url="https://news.mit.edu">MIT News</News:Source>'
            "</item>"
        )
        record = pipeline.bing_news_item_record(item)
        self.assertEqual(record["publisher_name"], "MIT News")
        self.assertEqual(record["publisher_home"], "https://news.mit.edu")
        self.assertEqual(record["publisher_domain"], "news.mit.edu")
        self.assertTrue(record["url"].startswith("https://www.bing.com/"))
        self.assertEqual(record["link_type"], "discovery_lead")
        self.assertFalse(pipeline.is_direct_publisher_article(record))

    def test_bing_interstitial_is_replaced_only_after_publisher_article_fetch(self):
        article_url = "https://news.mit.edu/2026/virtual-violin"
        aggregator_html = (
            '<html><head><link rel="canonical" href="' + article_url +
            '"></head><body><p>This is only a search results page and not article evidence.</p></body></html>'
        )
        article_text = (
            "MIT engineers describe a computational virtual violin and explain how "
            "the model reproduces the resonance and timbre of acoustic instruments. "
            "The article outlines the research approach, the instrument's sound model, "
            "and the technical details that distinguish the work from a simple recording."
        )
        article_html = "<html><body><p>" + article_text + "</p></body></html>"

        class FakeResponse:
            def __init__(self, url, body):
                self.url = url
                self.status_code = 200
                self.headers = {"Content-Type": "text/html; charset=utf-8"}
                self.text = body

        responses = {
            "https://www.bing.com/news/apiclick.aspx?ref=feed": FakeResponse(
                "https://www.bing.com/news/apiclick.aspx?ref=feed", aggregator_html
            ),
            article_url: FakeResponse(article_url, article_html),
        }

        with patch.object(pipeline.requests, "get", side_effect=lambda url, **kwargs: responses[url]):
            result = pipeline.enrich_source_evidence([{
                "title": "MIT virtual violin",
                "url": "https://www.bing.com/news/apiclick.aspx?ref=feed",
                "publisher_name": "MIT News",
                "publisher_domain": "news.mit.edu",
                "source_feed": "Bing News story search",
                "link_type": "discovery_lead",
            }])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"], article_url)
        self.assertEqual(result[0]["publisher_domain"], "news.mit.edu")
        self.assertEqual(result[0]["link_type"], "publisher_article")
        self.assertGreaterEqual(len(result[0]["evidence_text"]), 90)

    def test_bing_interstitial_without_publisher_target_remains_discovery_only(self):
        class FakeResponse:
            def __init__(self):
                self.url = "https://www.bing.com/news/apiclick.aspx?ref=feed"
                self.status_code = 200
                self.headers = {"Content-Type": "text/html; charset=utf-8"}
                self.text = "<html><body><p>Search results page only, not publisher evidence.</p></body></html>"

        with patch.object(pipeline.requests, "get", return_value=FakeResponse()):
            result = pipeline.enrich_source_evidence([{
                "title": "A news headline",
                "url": "https://www.bing.com/news/apiclick.aspx?ref=feed",
                "publisher_name": "Unknown publisher",
                "publisher_domain": "",
                "source_feed": "Bing News story search",
                "link_type": "discovery_lead",
            }])

        self.assertEqual(result[0]["link_type"], "discovery_lead")
        self.assertNotIn("publisher_url", result[0])
        self.assertNotIn("evidence_text", result[0])
        self.assertFalse(pipeline.is_direct_publisher_article(result[0]))

    def test_duckduckgo_search_extracts_final_publisher_urls_from_redirects(self):
        page = (
            '<html><body>'
            '<a class="result__a" href="//duckduckgo.com/l/?uddg='
            'https%3A%2F%2Fspaceandsky.com%2Froman-space-telescope-instruments-aligned-commissioning%2F">'
            '<span>Roman telescope instruments now line up</span></a>'
            '<a data-testid="result-title-a" href="https://orbital-wire.com/astronomy-astrophysics/roman-space-telescope-completes-instrument-alignment/">'
            'Roman Space Telescope completes instrument alignment</a>'
            '</body></html>'
        )
        records = pipeline.duckduckgo_search_records(page)
        self.assertEqual(len(records), 2)
        self.assertEqual(
            records[0]["url"],
            "https://spaceandsky.com/roman-space-telescope-instruments-aligned-commissioning/",
        )
        self.assertEqual(records[0]["publisher_domain"], "spaceandsky.com")
        self.assertEqual(records[1]["publisher_domain"], "orbital-wire.com")
        self.assertTrue(all(item["link_type"] == "discovery_lead" for item in records))
        self.assertTrue(all(pipeline.is_direct_publisher_article(item) for item in records))

    def test_direct_link_search_results_can_supply_two_readable_publishers(self):
        space_url = "https://spaceandsky.com/roman-space-telescope-instruments-aligned-commissioning/"
        orbital_url = "https://orbital-wire.com/astronomy-astrophysics/roman-space-telescope-completes-instrument-alignment/"
        search_html = (
            '<html><body>'
            '<a class="result__a" href="//duckduckgo.com/l/?uddg='
            'https%3A%2F%2Fspaceandsky.com%2Froman-space-telescope-instruments-aligned-commissioning%2F">'
            'Roman telescope instruments now line up to a hair’s breadth</a>'
            '<a class="result__a" href="https://orbital-wire.com/astronomy-astrophysics/roman-space-telescope-completes-instrument-alignment/">'
            'Roman Space Telescope completes key instrument alignment</a>'
            '</body></html>'
        )
        empty_rss = b"<rss><channel></channel></rss>"

        class FakeResponse:
            def __init__(self, url="", text="", content=b"", status_code=200):
                self.url = url
                self.text = text
                self.content = content or text.encode("utf-8")
                self.status_code = status_code
                self.headers = {"Content-Type": "text/html; charset=utf-8"}

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise pipeline.requests.HTTPError(
                        f"HTTP {self.status_code}", response=self
                    )

            def json(self):
                return {"articles": []}

        def fake_search_get(url, *args, **kwargs):
            if "api.gdeltproject.org" in url:
                return FakeResponse(url, status_code=429)
            if "news.google.com" in url or "bing.com/news/search" in url:
                return FakeResponse(url, content=empty_rss)
            if "html.duckduckgo.com" in url:
                return FakeResponse(url, text=search_html)
            raise AssertionError("Unexpected discovery provider: " + str(url))

        article_paragraphs = {
            space_url: (
                "NASA’s Nancy Grace Roman Space Telescope has finished aligning its instruments in space. "
                "Engineers compared observed star positions with expected positions, then updated the telescope’s internal map. "
                "The Wide Field Instrument guides the telescope while the Coronagraph searches nearby stars."
            ),
            orbital_url: (
                "NASA’s Nancy Grace Roman Space Telescope completed instrument alignment work on November 13, 2026. "
                "The Wide Field Instrument’s detectors work together when Roman locks onto guide stars. "
                "The observatory’s instruments are now prepared for the next commissioning tests."
            ),
        }

        def fake_article_get(url, **kwargs):
            body = "<html><body><p>" + article_paragraphs[url] + "</p></body></html>"
            return FakeResponse(url, text=body)

        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with (
                    patch.object(pipeline, "story_search_phrases", return_value=["roman telescope instruments aligned"]),
                    patch.object(pipeline.http, "get", side_effect=fake_search_get),
                    patch.object(pipeline.requests, "get", side_effect=fake_article_get),
                ):
                    research = pipeline.research_story_sources(
                        {
                            "topic": "NASA Roman Space Telescope instrument alignment",
                            "title": "Roman Telescope Instruments Aligned",
                            "hook": "How do space instruments align?",
                        },
                        [],
                    )

                selected = pipeline.select_verified_story_sources(
                    {
                        "topic": "NASA Roman Space Telescope instrument alignment",
                        "title": "Roman Telescope Instruments Aligned",
                        "hook": "How do space instruments align?",
                    },
                    research,
                    minimum_sources=2,
                )
            finally:
                pipeline.WORK = original_work

        self.assertEqual(
            {item["publisher_domain"] for item in selected},
            {"spaceandsky.com", "orbital-wire.com"},
        )
        self.assertTrue(all(len(item["evidence_text"]) >= 90 for item in selected))
        self.assertTrue(all(pipeline.is_direct_publisher_article(item) for item in selected))

    def test_run28_generic_virtual_violin_sites_do_not_support_mit_research_claim(self):
        plan = {
            "topic": "Virtual Violin Technology",
            "title": "The Future of the Violin",
            "hook": "Can a computer play a violin?",
            "description": (
                "MIT engineers have developed a new and highly advanced virtual string instrument. "
                "This technology replicates the complex sounds of a real acoustic violin."
            ),
            "narration_script": (
                "Can a computer play a violin? MIT engineers have developed a new and highly advanced "
                "virtual string instrument. This technology replicates the complex sounds of a real "
                "acoustic violin. Digital innovation now achieves the precision of traditional classical "
                "musical performance."
            ),
        }
        sources = [
            {
                "title": "MIT engineers' virtual violin produces realistic sounds",
                "url": "https://news.mit.edu/2026/mit-engineers-virtual-violin-produces-realistic-sounds-0429",
                "publisher_domain": "news.mit.edu",
                "publisher_name": "MIT News",
                "evidence_text": (
                    "MIT engineers developed a computational violin model that reproduces realistic "
                    "sounds. The article explains the research team's methods for modelling resonance, "
                    "timbre, and expressive acoustic properties of a violin."
                ),
            },
            {
                "title": "Virtual Violin — Play Violin Online Free",
                "url": "https://raugen.com/toolbox/virtual-violin",
                "publisher_domain": "raugen.com",
                "publisher_name": "RauGen",
                "evidence_text": (
                    "Play a virtual violin online using your keyboard. This browser-based tool lets "
                    "you explore notes and practice melodies with an interactive instrument."
                ),
            },
            {
                "title": "Virtual violin",
                "url": "https://www.musicca.com/violin",
                "publisher_domain": "musicca.com",
                "publisher_name": "Musicca",
                "evidence_text": (
                    "Play the violin online with this virtual instrument. Select notes and play melodies "
                    "using your computer keyboard in a simple interactive music tool."
                ),
            },
            {
                "title": "Online Virtual Violin Sheet Music",
                "url": "https://iplaymusic.com/strings/online-virtual-violin-sheet-music/",
                "publisher_domain": "iplaymusic.com",
                "publisher_name": "iPlayMusic",
                "evidence_text": (
                    "Use online virtual violin sheet music to practice songs. The web player offers "
                    "notes and melodies for people learning how to play a violin."
                ),
            },
        ]
        for source in sources[1:]:
            self.assertFalse(
                pipeline.source_supports_story(plan, source),
                source["publisher_domain"] + " should not corroborate the MIT research claim",
            )
        self.assertTrue(pipeline.source_supports_story(plan, sources[0]))

        with self.assertRaisesRegex(
            pipeline.PipelineError,
            "only 1 relevant direct publisher source",
        ):
            pipeline.select_verified_story_sources(plan, sources, minimum_sources=2)

    def test_two_publishers_must_both_support_the_named_mit_claim(self):
        plan = {
            "topic": "Virtual Violin Technology",
            "title": "The Future of the Violin",
            "hook": "Can a computer play a violin?",
            "description": (
                "MIT engineers developed a computational virtual violin model that reproduces "
                "the resonance and timbre of acoustic instruments."
            ),
        }
        sources = [
            {
                "title": "MIT engineers' virtual violin produces realistic sounds",
                "url": "https://news.mit.edu/2026/mit-engineers-virtual-violin-produces-realistic-sounds-0429",
                "publisher_domain": "news.mit.edu",
                "publisher_name": "MIT News",
                "evidence_text": (
                    "MIT engineers developed a computational violin model that reproduces realistic "
                    "sounds. The article explains their research methods and how the model recreates "
                    "the resonance and timbre of an acoustic violin."
                ),
            },
            {
                "title": "MIT engineers build a computational virtual violin",
                "url": "https://arstechnica.com/science/2026/11/mit-computational-virtual-violin",
                "publisher_domain": "arstechnica.com",
                "publisher_name": "Ars Technica",
                "evidence_text": (
                    "MIT engineers have developed a computational virtual violin. Their model recreates "
                    "the resonance, timbre, and nuanced sounds of a physical violin by modelling how "
                    "strings and acoustic components respond."
                ),
            },
            {
                "title": "Virtual violin simulator for music practice",
                "url": "https://music-tool.example/virtual-violin",
                "publisher_domain": "music-tool.example",
                "publisher_name": "Music Tool",
                "evidence_text": (
                    "Play an online virtual violin in your browser. Use the keyboard to select notes "
                    "and practice simple melodies with an interactive instrument."
                ),
            },
        ]
        selected = pipeline.select_verified_story_sources(plan, sources, minimum_sources=2)
        self.assertEqual(
            {item["publisher_domain"] for item in selected},
            {"news.mit.edu", "arstechnica.com"},
        )

    def test_identical_article_text_from_two_domains_counts_as_one_source(self):
        plan = {
            "topic": "MIT computational virtual violin",
            "title": "MIT engineers create a virtual violin",
            "description": "MIT engineers developed a physics-based computational violin model.",
        }
        shared_body = (
            "MIT engineers developed a computational violin model that reproduces realistic sounds. "
            "The article explains how the research team models the resonance and timbre of acoustic "
            "instruments before a physical violin is built. Their work gives instrument makers a way "
            "to evaluate design changes using a computational model and detailed acoustic measurements."
        )
        sources = [
            {
                "title": "MIT engineers create a computational virtual violin",
                "url": "https://publisher-one.example/mit-virtual-violin",
                "publisher_domain": "publisher-one.example",
                "publisher_name": "Publisher One",
                "evidence_text": shared_body,
            },
            {
                "title": "MIT engineers create a computational virtual violin",
                "url": "https://publisher-two.example/mit-virtual-violin",
                "publisher_domain": "publisher-two.example",
                "publisher_name": "Publisher Two",
                "evidence_text": shared_body.replace(".", ";"),
            },
        ]

        self.assertGreaterEqual(
            pipeline.source_content_similarity(sources[0], sources[1]),
            0.88,
        )
        with self.assertRaisesRegex(
            pipeline.PipelineError,
            "only 1 relevant direct publisher source",
        ):
            pipeline.select_verified_story_sources(plan, sources, minimum_sources=2)

    def test_distinct_article_body_text_from_second_publisher_counts_independently(self):
        plan = {
            "topic": "MIT computational virtual violin",
            "title": "MIT engineers create a virtual violin",
            "description": "MIT engineers developed a physics-based computational violin model.",
        }
        first_body = (
            "MIT engineers developed a computational violin model that reproduces realistic sounds. "
            "The model recreates resonance and timbre using the physical properties of the instrument."
        )
        second_body = (
            "Researchers at MIT describe a digital violin design environment that predicts acoustic "
            "responses before a maker constructs the instrument. The work combines physical modelling "
            "with measurements of violin structure and surrounding air."
        )
        sources = [
            {
                "title": "MIT engineers create a computational virtual violin",
                "url": "https://publisher-one.example/mit-virtual-violin",
                "publisher_domain": "publisher-one.example",
                "publisher_name": "Publisher One",
                "evidence_text": first_body,
            },
            {
                "title": "MIT researchers model violin acoustics digitally",
                "url": "https://publisher-two.example/mit-acoustic-model",
                "publisher_domain": "publisher-two.example",
                "publisher_name": "Publisher Two",
                "evidence_text": second_body,
            },
        ]
        self.assertLess(
            pipeline.source_content_similarity(sources[0], sources[1]),
            0.88,
        )
        selected = pipeline.select_verified_story_sources(plan, sources, minimum_sources=2)
        self.assertEqual(
            {item["publisher_domain"] for item in selected},
            {"publisher-one.example", "publisher-two.example"},
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
