"""Tests for the authorised Sketchfab-to-Blender asset resolver."""
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import asset_resolver


class SketchfabAssetResolverTests(unittest.TestCase):
    def test_extracts_uid_from_exact_sketchfab_model_url(self):
        self.assertEqual(
            asset_resolver.model_uid_from_url(asset_resolver.DEFAULT_MODEL_URL),
            "0162dea1b1044cd281c57af5e5fc2046",
        )

    def test_rejects_non_sketchfab_urls_and_invalid_uids(self):
        for value in ("https://example.com/model-0162dea1b1044cd281c57af5e5fc2046",
                      "https://sketchfab.com/3d-models/violin-not-a-uid"):
            with self.subTest(value=value), self.assertRaises(asset_resolver.AssetResolutionError):
                asset_resolver.model_uid_from_url(value)

    def test_commercial_licence_allowlist_and_rejections(self):
        allowed = {"license": "cc-by"}
        blocked = {"license": "by-nc"}
        unknown = {"license": "custom"}
        self.assertTrue(asset_resolver._license_details(allowed)[0] in asset_resolver.COMMERCIAL_LICENSES)
        self.assertFalse(asset_resolver._license_details(blocked)[0] in asset_resolver.COMMERCIAL_LICENSES)
        self.assertFalse(asset_resolver._license_details(unknown)[0] in asset_resolver.COMMERCIAL_LICENSES)

    def test_reference_only_when_no_download_token(self):
        model = {
            "name": "Violin",
            "isDownloadable": True,
            "license": "cc-by",
            "user": {"username": "example-creator"},
            "viewerUrl": asset_resolver.DEFAULT_MODEL_URL,
            "thumbnails": {"images": []},
        }
        session = Mock()
        response = Mock()
        response.json.return_value = model
        response.raise_for_status.return_value = None
        session.get.return_value = response
        with tempfile.TemporaryDirectory() as tmp:
            result = asset_resolver.resolve_sketchfab_asset(
                asset_resolver.DEFAULT_MODEL_URL, tmp, session=session
            )
            self.assertEqual(result["resolution"], "reference_only")
            self.assertIn("authenticated", result["reason"])
            self.assertTrue(Path(result["manifest_path"]).is_file())
            saved = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["creator"], "example-creator")

    def test_license_block_prevents_download_endpoint(self):
        model = {
            "name": "Violin",
            "isDownloadable": True,
            "license": "by-nc",
            "user": {"username": "example-creator"},
            "thumbnails": {"images": []},
        }
        session = Mock()
        response = Mock()
        response.json.return_value = model
        response.raise_for_status.return_value = None
        session.get.return_value = response
        with tempfile.TemporaryDirectory() as tmp:
            result = asset_resolver.resolve_sketchfab_asset(
                asset_resolver.DEFAULT_MODEL_URL, tmp,
                access_token="test-token", session=session
            )
            self.assertEqual(result["resolution"], "reference_only")
            self.assertEqual(session.get.call_count, 1)

    def test_safe_extract_returns_gltf_and_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "safe.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("scene.gltf", '{"asset":{"version":"2.0"}}')
            extracted = asset_resolver._safe_extract_glb_or_gltf(archive, root / "out")
            self.assertTrue(extracted.is_file())
            self.assertEqual(extracted.suffix, ".gltf")

            unsafe = root / "unsafe.zip"
            with zipfile.ZipFile(unsafe, "w") as package:
                package.writestr("../escape.gltf", '{"asset":{"version":"2.0"}}')
            with self.assertRaises(asset_resolver.AssetResolutionError):
                asset_resolver._safe_extract_glb_or_gltf(unsafe, root / "unsafe-out")


if __name__ == "__main__":
    unittest.main()
