from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scene_checkpoints import (
    load_valid_checkpoint,
    retry_transient,
    save_checkpoint,
    scene_fingerprint,
)


class SceneCheckpointTests(unittest.TestCase):
    def test_checkpoint_is_reused_only_when_fingerprint_and_output_hash_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "scene.png"
            image.write_bytes(b"source-image")
            render = root / "render.mp4"
            render.write_bytes(b"x" * 5000)
            fingerprint = scene_fingerprint(
                {"id": "scene-a", "caption": "A"},
                image,
                renderer_version="motion-hf-v1",
                render_settings={"fps": 25},
            )
            checkpoint = save_checkpoint(root / "cache", "scene-a", fingerprint, render)
            self.assertEqual(
                load_valid_checkpoint(root / "cache", "scene-a", fingerprint),
                checkpoint,
            )
            self.assertIsNone(load_valid_checkpoint(root / "cache", "scene-a", "changed"))
            checkpoint.write_bytes(b"corrupted")
            self.assertIsNone(load_valid_checkpoint(root / "cache", "scene-a", fingerprint))

    def test_changed_source_image_changes_scene_fingerprint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "scene.png"
            image.write_bytes(b"source-one")
            first = scene_fingerprint(
                {"id": "scene-a"}, image, renderer_version="v1"
            )
            image.write_bytes(b"source-two")
            second = scene_fingerprint(
                {"id": "scene-a"}, image, renderer_version="v1"
            )
        self.assertNotEqual(first, second)

    def test_scene_position_and_total_count_invalidate_position_dependent_rendering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "scene.png"
            image.write_bytes(b"source-image")
            scene = {"id": "scene-a", "caption": "A"}
            first = scene_fingerprint(
                scene,
                image,
                renderer_version="legacy-v1",
                render_settings={"scene_index": 0, "total_scene_count": 3, "plan_title": "Title"},
            )
            reordered = scene_fingerprint(
                scene,
                image,
                renderer_version="legacy-v1",
                render_settings={"scene_index": 2, "total_scene_count": 3, "plan_title": "Title"},
            )
            inserted = scene_fingerprint(
                scene,
                image,
                renderer_version="legacy-v1",
                render_settings={"scene_index": 0, "total_scene_count": 4, "plan_title": "Title"},
            )
        self.assertNotEqual(first, reordered)
        self.assertNotEqual(first, inserted)

    def test_retry_retries_only_transient_failures_with_bounded_backoff(self):
        calls = {"count": 0}
        sleeps = []

        def transient():
            calls["count"] += 1
            if calls["count"] < 3:
                raise TimeoutError("renderer timed out")
            return "done"

        self.assertEqual(
            retry_transient(transient, attempts=3, sleep=sleeps.append),
            "done",
        )
        self.assertEqual(calls["count"], 3)
        self.assertEqual(sleeps, [1.0, 2.0])

        with self.assertRaisesRegex(ValueError, "invalid filter"):
            retry_transient(
                lambda: (_ for _ in ()).throw(ValueError("invalid filter")),
                sleep=sleeps.append,
            )

    def test_retry_attempts_are_capped(self):
        calls = {"count": 0}

        def always_timeout():
            calls["count"] += 1
            raise TimeoutError("renderer timed out")

        with self.assertRaises(TimeoutError):
            retry_transient(always_timeout, attempts=99, sleep=lambda _seconds: None)
        self.assertEqual(calls["count"], 4)


if __name__ == "__main__":
    unittest.main()
