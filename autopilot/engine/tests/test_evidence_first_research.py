"""Tests for evidence-first article discovery and story grouping."""
import os
import sys
import tempfile
import unittest
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
