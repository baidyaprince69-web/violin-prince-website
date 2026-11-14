"""Tests for evidence-first article discovery and story grouping."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("CF_ACCOUNT_ID", "test-account")
os.environ.setdefault("CF_AI_TOKEN", "test-ai-token")
ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run as pipeline


def article(title, domain, path, body):
    return {
        "title": title,
        "publisher_name": domain,
        "publisher_domain": domain,
        "url": f"https://{domain}/{path}",
        "date": "2026-11-14",
        "published_at_utc": "2026-11-14T00:00:00Z",
        "publication_date_source": "test publisher metadata",
        "article_page_verified": True,
        "article_page_kind": "article_metadata",
        "source_feed": "test direct article",
        "link_type": "publisher_article",
        "evidence_text": body,
    }


MIT_ARTICLE = article(
    "MIT engineers develop a physics based virtual violin model",
    "news.mit.edu",
    "2026/virtual-violin-model",
    (
        "MIT engineers developed a physics based computational violin model. "
        "The model simulates string vibration and the interaction between the "
        "instrument structure and surrounding air. Researchers can change wood "
        "type and body thickness to compare predicted acoustic properties before "
        "building a physical instrument. The current model handles plucked strings "
        "more completely than the complex interaction involved in bowing."
    ),
)

SECOND_ARTICLE = article(
    "MIT's virtual violin model explains realistic instrument sounds",
    "physicsworld.com",
    "features/mit-virtual-violin-sound-model",
    (
        "Researchers at MIT developed a virtual violin model that simulates string "
        "vibrations and explains how the instrument body interacts with surrounding "
        "air. The computational design produces realistic sounds when strings are "
        "plucked. The team can adjust digital wood properties and body dimensions "
        "to examine predicted acoustic results. Reproducing the interaction of a "
        "bow with the strings remains a more difficult modelling problem."
    ),
)

UNRELATED_ARTICLE = article(
    "MIT museum opens a new exhibition about modern architecture",
    "museumreview.example",
    "arts/mit-architecture-exhibition",
    (
        "The museum announced a new architecture exhibition featuring buildings "
        "from several cities. Curators assembled drawings, models, photographs, "
        "and design notes to explain how urban spaces have changed. The public "
        "display includes historical materials and interviews with architects."
    ),
)


class EvidenceFirstGroupingTests(unittest.TestCase):
    def test_same_subject_articles_form_a_group_before_story_selection(self):
        groups = pipeline.build_verified_story_groups([MIT_ARTICLE, SECOND_ARTICLE])
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group["independent_publisher_count"], 2)
        self.assertEqual(set(group["publisher_families"]), {"mit.edu", "physicsworld.com"})
        self.assertEqual(len(group["source_ids"]), 2)
        self.assertTrue(all(len(item["evidence_text"]) >= 90 for item in group["sources"]))

    def test_subdomains_of_one_publisher_do_not_count_as_independent(self):
        same_family = dict(SECOND_ARTICLE)
        same_family["publisher_domain"] = "lab.mit.edu"
        same_family["publisher_name"] = "MIT Laboratory News"
        same_family["url"] = "https://lab.mit.edu/2026/virtual-violin-model"
        groups = pipeline.build_verified_story_groups([MIT_ARTICLE, same_family])
        self.assertEqual(groups, [])

    def test_near_identical_syndicated_article_bodies_are_not_corroboration(self):
        copied = dict(SECOND_ARTICLE)
        copied["evidence_text"] = MIT_ARTICLE["evidence_text"]
        groups = pipeline.build_verified_story_groups([MIT_ARTICLE, copied])
        self.assertEqual(groups, [])

    def test_general_topic_overlap_does_not_join_unrelated_articles(self):
        groups = pipeline.build_verified_story_groups([MIT_ARTICLE, UNRELATED_ARTICLE])
        self.assertEqual(groups, [])

    def test_aggregator_links_and_short_excerpts_never_count_as_articles(self):
        aggregator = dict(SECOND_ARTICLE)
        aggregator["url"] = "https://news.google.com/rss/articles/example"
        short = dict(MIT_ARTICLE)
        short["evidence_text"] = "A short result snippet."
        self.assertEqual(
            pipeline.build_verified_story_groups([aggregator, short]),
            [],
        )

    def test_category_tag_archive_and_event_pages_are_not_article_pages(self):
        for url in (
            "https://soundtrackworld.com/category/news/",
            "https://example.com/tag/violin/",
            "https://example.com/archive/2026/",
            "https://example.com/events/world-soundtrack-awards/",
            "https://en.wikipedia.org/wiki/World_Soundtrack_Awards",
        ):
            with self.subTest(url=url):
                self.assertFalse(pipeline.is_direct_publisher_article(url))

    def test_publication_date_policy_prefers_fifty_hours_but_accepts_up_to_seven_days(self):
        as_of = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
        cases = [
            (49, "preferred", True),
            (50, "preferred", True),
            (51, "acceptable", True),
            (120, "acceptable", True),
            (168, "acceptable", True),
            (169, "stale", False),
        ]
        for age, expected_status, expected_eligible in cases:
            with self.subTest(age_hours=age):
                record = {
                    "published_at_utc": (as_of - timedelta(hours=age)).isoformat(),
                }
                result = pipeline.article_freshness(record, as_of=as_of)
                self.assertEqual(result["freshness_status"], expected_status)
                self.assertEqual(result["freshness_eligible"], expected_eligible)

    def test_recent_but_undated_or_future_articles_do_not_qualify(self):
        as_of = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
        undated = dict(MIT_ARTICLE)
        undated.pop("date", None)
        undated.pop("published_at_utc", None)
        future = dict(SECOND_ARTICLE)
        future["published_at_utc"] = (as_of + timedelta(hours=2)).isoformat()
        self.assertFalse(pipeline._story_article_eligibility(undated, as_of)[0])
        self.assertEqual(pipeline._story_article_eligibility(undated, as_of)[1], "publication_date_missing")
        self.assertFalse(pipeline._story_article_eligibility(future, as_of)[0])
        self.assertEqual(pipeline._story_article_eligibility(future, as_of)[1], "publication_date_is_in_the_future")

    def test_two_independent_articles_six_days_old_remain_eligible(self):
        as_of = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
        older_first = dict(MIT_ARTICLE)
        older_second = dict(SECOND_ARTICLE)
        published = (as_of - timedelta(days=6)).isoformat()
        older_first["published_at_utc"] = published
        older_second["published_at_utc"] = published
        groups = pipeline.build_verified_story_groups([older_first, older_second], as_of=as_of)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["preferred_source_count"], 0)
        self.assertEqual(groups[0]["oldest_source_age_hours"], 144)

    def test_articles_older_than_seven_days_do_not_form_a_group(self):
        as_of = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
        old_first = dict(MIT_ARTICLE)
        old_second = dict(SECOND_ARTICLE)
        published = (as_of - timedelta(days=7, hours=1)).isoformat()
        old_first["published_at_utc"] = published
        old_second["published_at_utc"] = published
        self.assertEqual(
            pipeline.build_verified_story_groups([old_first, old_second], as_of=as_of),
            [],
        )

    def test_article_metadata_extraction_reads_published_time_and_jsonld(self):
        html = (
            '<html><head><meta property="og:type" content="article">'
            '<meta property="article:published_time" content="2026-11-12T17:46:00Z">'
            '<meta property="og:title" content="A virtual violin model">'
            '</head><body><p>Article evidence.</p></body></html>'
        )
        meta = pipeline.extract_article_page_metadata(html)
        self.assertTrue(meta["is_article"])
        self.assertEqual(meta["published_at_utc"], "2026-11-12T17:46:00Z")
        self.assertEqual(meta["page_title"], "A virtual violin model")

        jsonld = (
            '<script type="application/ld+json">'
            '{"@type":"NewsArticle","headline":"A new violin discovery",'
            '"datePublished":"2026-11-13T08:00:00Z"}'
            '</script>'
        )
        structured = pipeline.extract_article_page_metadata(jsonld)
        self.assertTrue(structured["is_article"])
        self.assertEqual(structured["published_at_utc"], "2026-11-13T08:00:00Z")

    def test_source_first_expansion_finds_corroboration_before_planner_runs(self):
        lead = {
            "title": "MIT engineers develop a virtual violin model",
            "url": "https://news.google.com/rss/articles/seed",
            "publisher_domain": "news.mit.edu",
        }
        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with patch.object(
                    pipeline,
                    "research_story_sources",
                    return_value=[MIT_ARTICLE, SECOND_ARTICLE],
                ) as targeted_search:
                    groups = pipeline.discover_source_first_story_groups(
                        [lead], max_seed_queries=1, max_phrases=3
                    )
                self.assertEqual(len(groups), 1)
                self.assertEqual(groups[0]["independent_publisher_count"], 2)
                self.assertEqual(targeted_search.call_count, 1)
                self.assertEqual(targeted_search.call_args.kwargs["max_phrases"], 3)
                diagnostics = Path(folder) / "story_candidates.json"
                self.assertTrue(diagnostics.is_file())
            finally:
                pipeline.WORK = original_work

    def test_planner_cannot_select_a_story_group_that_was_not_supplied(self):
        groups = pipeline.build_verified_story_groups([MIT_ARTICLE, SECOND_ARTICLE])
        self.assertEqual(len(groups), 1)
        response = {
            "response": {
                "story_group_id": "STORY_NOT_ELIGIBLE",
                "sources": groups[0]["source_ids"],
            }
        }
        with patch.object(pipeline, "ai", return_value=response):
            with self.assertRaisesRegex(
                pipeline.PipelineError, "did not select an eligible source-first story_group_id"
            ):
                pipeline.make_plan(
                    [MIT_ARTICLE, SECOND_ARTICLE],
                    story_groups=groups,
                )


if __name__ == "__main__":
    unittest.main()
