"""Offline tests for the shared Discover → Optimize → Learn SEO engine."""
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autopilot.engine.seo_intelligence import (
    build_queries, build_topic_queries, discover, learn, load_profile, optimize,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeYouTubeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, dict(params)))
        if url.endswith("/search"):
            language = params["relevanceLanguage"]
            query = params["q"]
            video_id = language + "_" + str(len([x for x in self.calls if x[0].endswith("/search")]))
            published = (datetime(2026, 11, 14, tzinfo=timezone.utc) - timedelta(days=4)).isoformat().replace("+00:00", "Z")
            return FakeResponse({
                "items": [{
                    "id": {"videoId": video_id},
                    "snippet": {
                        "title": query + " | violin performance",
                        "channelTitle": "Sample Music Channel",
                        "publishedAt": published,
                        "description": "A public search result sample.",
                    },
                }],
            })
        if url.endswith("/videos"):
            ids = params["id"].split(",")
            return FakeResponse({
                "items": [{
                    "id": video_id,
                    "statistics": {"viewCount": str((index + 1) * 1200), "likeCount": "32", "commentCount": "4"},
                } for index, video_id in enumerate(ids)],
            })
        raise AssertionError("Unexpected YouTube API URL: " + url)


class SEOIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile()

    def test_profile_covers_english_hindi_and_bengali(self):
        codes = {item["code"] for item in self.profile["search_languages"]}
        self.assertEqual(codes, {"en", "hi", "bn"})
        self.assertEqual(self.profile["region_code"], "IN")
        self.assertEqual(self.profile["brand_name"], "Violin Prince")

    def test_query_budget_keeps_each_language_in_the_mix(self):
        queries = build_queries(self.profile, max_queries=6)
        self.assertEqual(len(queries), 6)
        self.assertEqual({item["language"] for item in queries}, {"en", "hi", "bn"})

    def test_query_rotation_tests_new_phrases_without_losing_language_coverage(self):
        first = build_queries(self.profile, max_queries=3, rotation_index=0)
        second = build_queries(self.profile, max_queries=3, rotation_index=1)
        self.assertEqual([item["language"] for item in first], ["en", "hi", "bn"])
        self.assertEqual([item["language"] for item in second], ["en", "hi", "bn"])
        self.assertNotEqual([item["query"] for item in first], [item["query"] for item in second])

    def test_topic_queries_cover_english_hindi_and_bengali(self):
        queries = build_topic_queries("A violin cover of a Bengali melody")
        self.assertEqual([item["language"] for item in queries], ["en", "hi", "bn"])
        self.assertIn("violin cover", queries[0]["query"])
        self.assertIn("वायलिन कवर", queries[1]["query"])
        self.assertIn("বেহালা কভার", queries[2]["query"])

    def test_discover_accepts_a_video_specific_query_plan(self):
        session = FakeYouTubeSession()
        custom = build_topic_queries("Violin rendition of a film melody")
        result = discover(
            profile=self.profile,
            api_key="test-key",
            session=session,
            query_plan_override=custom,
            now=datetime(2026, 11, 14, tzinfo=timezone.utc),
        )
        self.assertEqual(result["queries_sampled"], 3)
        self.assertEqual([item["query"] for item in result["query_plan"]], [item["query"] for item in custom])
        self.assertEqual({item["language"] for item in result["query_results"]}, {"en", "hi", "bn"})

    def test_real_channel_search_terms_feed_the_next_discover_run(self):
        learned = {
            "search_term_signals": [
                {
                    "language": "en",
                    "search_term": "emotional violin cover",
                    "views": 24,
                    "video_sample_count": 4,
                },
                {
                    "language": "hi",
                    "search_term": "हिंदी गाने वायलिन कवर",
                    "views": 18,
                    "video_sample_count": 3,
                },
                {
                    "language": "bn",
                    "search_term": "বাংলা বেহালা গান",
                    "views": 12,
                    "video_sample_count": 3,
                },
            ],
        }
        result = discover(profile=self.profile, api_key="", learned_signals=learned)
        by_language = {}
        for item in result["query_plan"]:
            by_language.setdefault(item["language"], []).append(item["query"])
        self.assertIn("emotional violin cover", by_language["en"])
        self.assertIn("हिंदी गाने वायलिन कवर", by_language["hi"])
        self.assertIn("বাংলা বেহালা গান", by_language["bn"])
        self.assertEqual(len(result["learned_search_terms_used"]), 3)
        self.assertEqual(result["queries_sampled"], 0)
        self.assertIsNone(result["search_volume"])

    def test_learn_preserves_actual_youtube_search_terms_as_first_party_evidence(self):
        videos = [
            {
                "video_id": "en-" + str(index),
                "title": "English violin cover " + str(index),
                "language": "en",
                "views": 50 + index,
                "average_view_percentage": 45 + index,
            }
            for index in range(3)
        ]
        result = learn({
            "videos": videos,
            "search_terms": [
                {
                    "language": "en",
                    "search_term": "emotional violin cover",
                    "views": 28,
                    "video_sample_count": 3,
                },
                {
                    "language": "en",
                    "search_term": "random phrase",
                    "views": 2,
                    "video_sample_count": 1,
                },
            ],
        })
        self.assertTrue(result["search_term_learning_ready"])
        self.assertEqual(len(result["search_term_signals"]), 1)
        self.assertEqual(result["search_term_signals"][0]["search_term"], "emotional violin cover")
        self.assertEqual(result["search_term_signals"][0]["evidence"], "actual_youtube_search_traffic")

    def test_no_api_key_prepares_queries_without_fabricating_metrics(self):
        result = discover(profile=self.profile, api_key="")
        self.assertEqual(result["status"], "search_authorization_missing")
        self.assertEqual(result["queries_sampled"], 0)
        self.assertEqual(result["search_volume"], None)
        self.assertEqual(len(result["query_plan"]), 9)
        self.assertFalse(result["available"])

    def test_discover_uses_oauth_without_a_separate_api_key(self):
        session = FakeYouTubeSession()
        result = discover(
            profile=self.profile,
            api_key="",
            access_token="oauth-access-token",
            session=session,
            max_queries=3,
            now=datetime(2026, 11, 14, tzinfo=timezone.utc),
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["queries_sampled"], 3)
        self.assertEqual(
            session.headers.get("Authorization"),
            "Bearer oauth-access-token",
        )
        search_calls = [call for call in session.calls if call[0].endswith("/search")]
        self.assertEqual(len(search_calls), 3)
        self.assertTrue(all("key" not in params for _url, params in search_calls))

    def test_discover_samples_each_language_and_observed_video_statistics(self):
        session = FakeYouTubeSession()
        result = discover(
            profile=self.profile,
            api_key="test-key",
            session=session,
            now=datetime(2026, 11, 14, tzinfo=timezone.utc),
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["queries_sampled"], 9)
        self.assertEqual({item["language"] for item in result["query_results"]}, {"en", "hi", "bn"})
        self.assertTrue(all(item["median_views"] is not None for item in result["query_results"]))
        self.assertTrue(all(item["median_views_per_day_observed"] is not None for item in result["query_results"]))
        self.assertIsNone(result["search_volume"])
        search_calls = [call for call in session.calls if call[0].endswith("/search")]
        self.assertEqual(len(search_calls), 9)
        self.assertEqual({call[1]["relevanceLanguage"] for call in search_calls}, {"en", "hi", "bn"})

    def test_optimize_preserves_content_and_never_auto_approves(self):
        plan = {
            "title": "A violin story worth hearing",
            "topic": "A short violin story",
            "hook": "Listen closely.",
            "description": "An original short made for Violin Prince.",
            "language": "hi",
            "seo_metadata_approved": False,
        }
        discovery = {
            "recommended_opportunities": [
                {"language": "en", "query": "emotional violin instrumental"},
                {"language": "hi", "query": "बॉलीवुड वायलिन कवर"},
            ],
        }
        result = optimize(plan, discovery=discovery, profile=self.profile)
        self.assertEqual(result["seo_title"], plan["title"])
        self.assertEqual(result["primary_keyword"], "बॉलीवुड वायलिन कवर")
        self.assertFalse(result["seo_metadata_approved"])
        self.assertTrue(result["seo_optimization"]["metadata_review_required"])
        self.assertLessEqual(len(result["seo_hashtags"]), 3)
        self.assertLessEqual(len(result["seo_title"]), 100)

    def test_owner_approval_alias_is_preserved_but_not_created(self):
        approved = optimize({
            "title": "বাংলা গানের বেহালা কভার",
            "metadata_approved": True,
        }, profile=self.profile)
        pending = optimize({
            "title": "বাংলা গানের বেহালা কভার",
            "metadata_approved": False,
        }, profile=self.profile)
        self.assertTrue(approved["seo_metadata_approved"])
        self.assertFalse(pending["seo_metadata_approved"])

    def test_learn_uses_real_video_report_rows_and_requires_minimum_samples(self):
        videos = []
        for index, percentage in enumerate([24, 28, 32], start=1):
            videos.append({
                "video_id": "en_" + str(index),
                "title": "English violin cover " + str(index),
                "language": "en",
                "views": 100 + index,
                "average_view_percentage": percentage,
                "average_view_duration_seconds": 21,
                "seo_context": {"primary_keyword": "violin cover"},
            })
        for index, percentage in enumerate([48, 55, 62], start=1):
            videos.append({
                "video_id": "hi_" + str(index),
                "title": "हिंदी वायलिन कवर " + str(index),
                "language": "hi",
                "views": 200 + index,
                "average_view_percentage": percentage,
                "average_view_duration_seconds": 32,
                "seo_context": {"primary_keyword": "बॉलीवुड वायलिन कवर"},
            })
        result = learn({"videos": videos, "period": {"days": 28}}, minimum_group_size=3)
        by_language = {item["language"]: item for item in result["language_signals"]}
        self.assertEqual(result["stage"], "learn")
        self.assertTrue(result["learning_ready"])
        self.assertEqual(by_language["en"]["relative_performance"], "below_channel_median")
        self.assertEqual(by_language["hi"]["relative_performance"], "above_channel_median")
        self.assertEqual(len(result["keyword_signals"]), 2)
        self.assertIn("thumbnail_impressions_ctr", result["metrics_not_available"])

    def test_learn_does_not_overreact_to_small_groups_or_claim_missing_ctr(self):
        result = learn({
            "videos": [
                {"video_id": "one", "title": "বাংলা বেহালা কভার", "views": 500, "average_view_percentage": 80},
                {"video_id": "two", "title": "বাংলা বেহালা কভার", "views": 900, "average_view_percentage": 90},
            ],
        }, minimum_group_size=3)
        signal = result["language_signals"][0]
        self.assertEqual(signal["language"], "bn")
        self.assertEqual(signal["relative_performance"], "insufficient_data")
        self.assertFalse(result["learning_ready"])
        self.assertIn("thumbnail_impressions_ctr", result["metrics_not_available"])

    
    def test_discover_ignores_unknown_language_learning_signal(self):
        result = discover(
            profile=self.profile,
            api_key="",
            learned_signals={
                "language_signals": [
                    {
                        "language": "unknown",
                        "sample_count": 15,
                        "relative_performance": "above_channel_median",
                    }
                ]
            },
        )
        self.assertEqual(result["learned_language_signals_used"], [])
        self.assertEqual(
            {item["language"] for item in result["query_plan"]},
            {"en", "hi", "bn"},
        )

if __name__ == "__main__":
    unittest.main()
