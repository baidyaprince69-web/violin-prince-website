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

    def test_preferred_model_urls_are_parsed_and_deduplicated(self):
        first = "https://sketchfab.com/3d-models/violin-0162dea1b1044cd281c57af5e5fc2046"
        second = "https://sketchfab.com/3d-models/violin-b45bce730d8a489c83ecc944f3725475"
        entries = resolver._preferred_model_entries({
            "preferred_model_urls": [first, second, first],
        })
        self.assertEqual(
            entries,
            [
                (first, "0162dea1b1044cd281c57af5e5fc2046"),
                (second, "b45bce730d8a489c83ecc944f3725475"),
            ],
        )

    def test_bow_url_field_can_be_loaded_separately(self):
        source = "https://sketchfab.com/3d-models/violin-bow-af332828a42f4f8cbbe81bea3de0b00d"
        with patch.object(resolver, "fetch_model_metadata", return_value={
            "name": "Violin Bow",
            "faceCount": 4300,
            "isDownloadable": True,
            "license": {"slug": "cc-by"},
        }) as fetch:
            models, failures = resolver.load_preferred_story_models(
                {"preferred_bow_model_urls": [source]},
                field_name="preferred_bow_model_urls",
            )
        self.assertEqual(failures, [])
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["name"], "Violin Bow")
        self.assertEqual(models[0]["_violin_prince_source_url"], source)
        fetch.assert_called_once()

    def test_explicit_models_are_loaded_before_search_and_keep_source_url(self):
        source = "https://sketchfab.com/3d-models/violin-0162dea1b1044cd281c57af5e5fc2046"
        with patch.object(resolver, "fetch_model_metadata", return_value={
            "name": "Violin",
            "faceCount": 120000,
            "isDownloadable": True,
            "license": {"slug": "cc-by"},
        }) as fetch:
            models, failures = resolver.load_preferred_story_models({
                "preferred_model_urls": [source],
            })
        self.assertEqual(failures, [])
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["uid"], "0162dea1b1044cd281c57af5e5fc2046")
        self.assertEqual(models[0]["_violin_prince_source_url"], source)
        fetch.assert_called_once()

    def test_violin_story_query_requires_bow_and_strings(self):
        query = resolver.derive_story_query({
            "topic": "How a violin bridge transfers vibration",
            "title": "The violin's sound",
        })
        self.assertIn("violin", query)
        self.assertIn("bow", query)
        self.assertIn("strings", query)

    def test_gltf_package_size_includes_external_geometry_and_textures(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            descriptor = root / "scene.gltf"
            descriptor.write_text(json.dumps({
                "buffers": [{"uri": "scene.bin", "byteLength": 8192}],
                "images": [{"uri": "textures/albedo.png"}],
            }), encoding="utf-8")
            (root / "scene.bin").write_bytes(b"g" * 8192)
            (root / "textures").mkdir()
            (root / "textures" / "albedo.png").write_bytes(b"t" * 2048)
            self.assertGreaterEqual(resolver._model_package_size(descriptor), 8192 + 2048)

    def test_gltf_package_rejects_missing_or_escaping_external_assets(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            descriptor = root / "scene.gltf"
            descriptor.write_text(json.dumps({
                "buffers": [{"uri": "../outside.bin", "byteLength": 4096}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(resolver.StoryAssetError, "outside"):
                resolver._model_package_size(descriptor)
            descriptor.write_text(json.dumps({
                "buffers": [{"uri": "missing.bin", "byteLength": 4096}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(resolver.StoryAssetError, "missing"):
                resolver._model_package_size(descriptor)

    def test_imported_gltf_must_expose_named_bow_and_string_meshes(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "violin.gltf"
            path.write_text(json.dumps({
                "scene": 0,
                "scenes": [{"nodes": [0]}],
                "nodes": [
                    {"name": "Violin", "children": [1, 2]},
                    {"name": "violin_bow", "mesh": 0},
                    {"name": "violin_strings", "mesh": 1},
                ],
                "meshes": [{"name": "Bow"}, {"name": "Strings"}],
            }), encoding="utf-8")
            parts = resolver.inspect_named_model_parts(path)
            self.assertEqual(parts["bow"], ["Violin / violin_bow"])
            self.assertEqual(parts["strings"], ["Violin / violin_strings"])
            self.assertEqual(
                parts["mesh_nodes"],
                ["Violin / violin_bow", "Violin / violin_strings"],
            )

    def test_gltf_part_inspection_inherits_parent_names(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "violin.gltf"
            path.write_text(json.dumps({
                "scene": 0,
                "scenes": [{"nodes": [0]}],
                "nodes": [
                    {"name": "Bow Assembly", "children": [1]},
                    {"name": "Maple Stick", "mesh": 0},
                ],
                "meshes": [{"name": "Stick"}],
            }), encoding="utf-8")
            parts = resolver.inspect_named_model_parts(path)
            self.assertEqual(parts["bow"], ["Bow Assembly / Maple Stick"])
            self.assertEqual(parts["strings"], [])

    def test_missing_physical_subject_fails_closed(self):
        with self.assertRaises(resolver.StoryAssetError):
            resolver.derive_story_query({"title": "A and the of"})

    def test_noncommercial_and_unknown_licenses_are_rejected(self):
        self.assertFalse(resolver._license_allowed({"license": {"slug": "cc-by-nc"}}))
        self.assertFalse(resolver._license_allowed({"license": {"slug": "custom"}}))
        self.assertTrue(resolver._license_allowed({"license": {"slug": "cc-by"}}))
        self.assertTrue(resolver._license_allowed({"license": {"slug": "cc0"}}))

    def test_explicit_preferred_model_can_pass_70k_face_floor(self):
        preferred = {
            "uid": "c" * 32,
            "name": "Violin",
            "license": {"slug": "cc-by"},
            "isDownloadable": True,
            "faceCount": 74878,
            "vertexCount": 37669,
            "pbrType": "metalness",
            "tags": [{"name": "violin"}],
        }
        self.assertEqual(
            resolver.score_candidate(preferred, "violin bow strings"),
            float("-inf"),
        )
        self.assertGreater(
            resolver.score_candidate(
                preferred,
                "violin bow strings",
                min_face_count=resolver.PREFERRED_MIN_FACE_COUNT,
            ),
            0,
        )

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
        args, kwargs = session.get.call_args_list[0]
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
