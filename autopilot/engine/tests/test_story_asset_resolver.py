"""Offline tests for story-aware 3D asset discovery and licensing."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import story_asset_resolver as resolver


class StoryAssetResolverTests(unittest.TestCase):
    def test_query_is_derived_from_topic_and_changes_by_story(self):
        violin = resolver.derive_story_query({
            "topic": "Violin bridge vibration and sound",
            "title": "How a violin produces resonance",
            "scenes": [{"caption": "The bridge transfers string vibration"}],
        })
        train = resolver.derive_story_query({
            "topic": "Steam locomotive valve mechanism",
            "title": "How a steam engine moves",
            "scenes": [{"caption": "Pistons convert steam pressure into motion"}],
        })
        self.assertIn("violin", violin)
        self.assertIn("bridge", violin)
        self.assertIn("steam", train)
        self.assertIn("locomotive", train)
        self.assertNotEqual(violin, train)

    def test_explicit_model_query_takes_priority(self):
        query = resolver.derive_story_query({
            "model_query": "grand piano realistic concert instrument",
            "topic": "Unrelated topic",
        })
        self.assertIn("grand", query)
        self.assertIn("piano", query)
        self.assertNotIn("unrelated", query)

    def test_missing_physical_subject_fails_closed(self):
        with self.assertRaises(resolver.StoryAssetError):
            resolver.derive_story_query({"title": "A and the of"})

    def test_noncommercial_and_unknown_licenses_are_rejected(self):
        self.assertFalse(resolver._license_allowed({"license": {"slug": "cc-by-nc"}}))
        self.assertFalse(resolver._license_allowed({"license": {"slug": "custom"}}))
        self.assertTrue(resolver._license_allowed({"license": {"slug": "cc-by"}}))
        self.assertTrue(resolver._license_allowed({"license": {"slug": "cc0"}}))

    def test_candidate_quality_gate_requires_download_and_geometry(self):
        good = {
            "uid": "a" * 32,
            "name": "Detailed violin body",
            "license": {"slug": "cc-by"},
            "isDownloadable": True,
            "faceCount": 180000,
            "vertexCount": 90000,
            "pbr_type": "metalness",
            "likeCount": 80,
            "tags": [{"name": "violin"}],
        }
        self.assertGreater(resolver.score_candidate(good, "violin body"), 0)
        self.assertEqual(
            resolver.score_candidate({**good, "faceCount": 1000}, "violin body"),
            float("-inf"),
        )
        self.assertEqual(
            resolver.score_candidate({**good, "isDownloadable": False}, "violin body"),
            float("-inf"),
        )

    def test_ranker_returns_best_relevant_candidate_first(self):
        generic = {
            "uid": "a" * 32, "name": "Generic object",
            "license": {"slug": "cc0"}, "isDownloadable": True,
            "faceCount": 40000, "likeCount": 5,
        }
        relevant = {
            "uid": "b" * 32, "name": "Realistic violin model",
            "license": {"slug": "cc-by"}, "isDownloadable": True,
            "faceCount": 180000, "pbr_type": "metalness", "likeCount": 80,
            "tags": [{"name": "violin"}, {"name": "instrument"}],
        }
        result = resolver.rank_story_models([generic, relevant], "violin instrument")
        self.assertEqual(result[0]["uid"], relevant["uid"])

    def test_search_uses_topic_query_and_downloadable_filter(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {"results": [{"uid": "b" * 32}]}
        response.raise_for_status.return_value = None
        session.get.return_value = response
        rows = resolver.search_story_models(
            "violin bridge realistic detailed PBR 3D model",
            session=session,
        )
        self.assertEqual(len(rows), 1)
        args, kwargs = session.get.call_args
        self.assertTrue(args[0].endswith("/search"))
        self.assertEqual(kwargs["params"]["type"], "models")
        self.assertEqual(kwargs["params"]["downloadable"], "true")
        self.assertIn("violin", kwargs["params"]["q"])

    def test_missing_download_token_stops_without_reference_fallback(self):
        with patch.dict(resolver.os.environ, {}, clear=True):
            with tempfile.TemporaryDirectory() as temp:
                with self.assertRaisesRegex(resolver.StoryAssetError, "SKETCHFAB_ACCESS_TOKEN"):
                    resolver.resolve_story_asset(
                        {"model_query": "violin PBR"},
                        temp,
                        session=Mock(),
                    )


if __name__ == "__main__":
    unittest.main()
