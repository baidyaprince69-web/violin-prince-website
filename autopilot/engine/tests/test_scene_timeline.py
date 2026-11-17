from __future__ import annotations

import unittest

from scene_timeline import (
    ScenePlanError,
    apply_scene_operations,
    build_scene_timeline,
    scene_asset_path,
)


class SceneTimelineTests(unittest.TestCase):
    def setUp(self):
        self.script = "First sentence. Second sentence. Third sentence. Fourth sentence."
        self.plan = {
            "narration_script": self.script,
            "scenes": [
                {"title": "Hook", "caption": "Hook", "image_prompt": "A violin detail"},
                {"title": "Detail", "caption": "Detail", "image_prompt": "A mechanism"},
                {"title": "Payoff", "caption": "Payoff", "image_prompt": "A performance"},
            ],
        }

    def test_legacy_plan_gets_stable_ids_and_complete_sentence_mapping(self):
        first = apply_scene_operations(self.plan)
        second = apply_scene_operations(self.plan)
        self.assertEqual([item["id"] for item in first["scenes"]], [item["id"] for item in second["scenes"]])
        mapped = [value for scene in first["scenes"] for value in scene["narration_sentence_indexes"]]
        self.assertEqual(sorted(mapped), [0, 1, 2, 3])

    def test_insert_music_only_scene_and_reorder_keep_ids_stable(self):
        prepared = apply_scene_operations(self.plan)
        ids = [scene["id"] for scene in prepared["scenes"]]
        prepared["scene_operations"] = [
            {
                "type": "insert",
                "after_scene_id": ids[0],
                "scene": {
                    "id": "visual-interlude",
                    "title": "Visual interlude",
                    "caption": "A short visual pause",
                    "image_prompt": "A string vibration visual",
                    "music_only": True,
                    "narration_sentence_indexes": [],
                },
            },
            {"type": "reorder", "order": [ids[2], ids[0], "visual-interlude", ids[1]]},
        ]
        edited = apply_scene_operations(prepared)
        self.assertEqual([scene["id"] for scene in edited["scenes"]], [ids[2], ids[0], "visual-interlude", ids[1]])
        self.assertEqual(len(edited["scene_operations_applied"]), 2)

    def test_delete_that_drops_narration_is_rejected(self):
        prepared = apply_scene_operations(self.plan)
        deleted_id = prepared["scenes"][1]["id"]
        prepared["scene_operations"] = [{"type": "delete", "scene_id": deleted_id}]
        with self.assertRaises(ScenePlanError):
            apply_scene_operations(prepared)

    def test_visual_update_cannot_rewrite_narration_script(self):
        prepared = apply_scene_operations(self.plan)
        prepared["scene_operations"] = [{
            "type": "update",
            "scene_id": prepared["scenes"][0]["id"],
            "changes": {"narration_script": "Unverified replacement."},
        }]
        with self.assertRaises(ScenePlanError):
            apply_scene_operations(prepared)

    def test_reorder_preserves_the_original_legacy_image_for_each_scene(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(1, 4):
                (root / f"scene-{index}.jpg").write_bytes(f"legacy-{index}".encode())
            prepared = apply_scene_operations(self.plan)
            ids = [scene["id"] for scene in prepared["scenes"]]
            prepared["scene_operations"] = [{
                "type": "reorder",
                "order": [ids[2], ids[0], ids[1]],
            }]
            reordered = apply_scene_operations(prepared)
            paths = [
                scene_asset_path(str(root), scene, index).name
                for index, scene in enumerate(reordered["scenes"])
            ]
        self.assertEqual(paths, ["scene-3.jpg", "scene-1.jpg", "scene-2.jpg"])

    def test_visual_prompt_update_invalidates_existing_legacy_art(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "scene-1.jpg").write_bytes(b"old-image")
            prepared = apply_scene_operations(self.plan)
            scene_id = prepared["scenes"][0]["id"]
            prepared["scene_operations"] = [{
                "type": "update",
                "scene_id": scene_id,
                "changes": {"image_prompt": "A revised close-up illustration"},
            }]
            edited = apply_scene_operations(prepared)
            scene = edited["scenes"][0]
            resolved = scene_asset_path(str(root), scene, 0)
        self.assertTrue(scene["_visual_asset_invalidated"])
        self.assertEqual(resolved.name, f"scene-{scene_id}.jpg")

    def test_four_scene_timeline_preserves_total_duration_and_transitions(self):
        plan = apply_scene_operations(self.plan)
        extra = {
            "id": "music-bridge",
            "title": "Bridge",
            "caption": "Instrument detail",
            "image_prompt": "Strings vibrate",
            "music_only": True,
            "narration_sentence_indexes": [],
        }
        plan["scenes"].insert(2, extra)
        timeline = build_scene_timeline(
            plan["scenes"],
            {"word_cues": [
                {"sentence_index": i, "start": i * 3.0, "end": i * 3.0 + 2.0}
                for i in range(4)
            ]},
            total_seconds=24.0,
            transition_seconds=0.3,
        )
        self.assertEqual(len(timeline["scenes"]), 4)
        self.assertAlmostEqual(timeline["scenes"][-1]["start"] + timeline["scenes"][-1]["clip_duration"], 24.0, places=3)
        self.assertAlmostEqual(sum(item["duration"] for item in timeline["scenes"]), 24.0, places=3)


if __name__ == "__main__":
    unittest.main()
