"""Tests for the source-verified GitHub Actions Master Director job."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from create_master_director_plan import (  # noqa: E402
    DirectorJobError,
    create_master_director_plan,
)


def make_batch(path: Path, *, chosen_status: str = "ready") -> Path:
    plans = []
    for slot_id in (
        "music-secrets", "production-tech", "melody-stories", "real-performance"
    ):
        status = chosen_status if slot_id == "music-secrets" else "ready"
        item = {
            "production_date": "2026-11-23",
            "slot_id": slot_id,
            "slot_status": status,
            "title": f"Test story for {slot_id}",
            "narration_script": "A verified narration script with four clear sentences.",
        }
        if status == "blocked":
            item["blocked_reason"] = "No verified story for this slot."
        plans.append(item)
    path.write_text(
        json.dumps({"schema_version": 1, "production_date": "2026-11-23", "plans": plans}),
        encoding="utf-8",
    )
    return path


def fake_director_plan():
    shots = []
    for index in range(8):
        start = index * 4
        layers = []
        for layer_id, role, z_index, asset_mode, motion_type in (
            ("background", "background", 0, "opaque", "drift"),
            ("subject", "subject", 20, "transparent_png", "float"),
            ("foreground", "foreground", 40, "transparent_png", "parallax"),
        ):
            layers.append({
                "id": layer_id,
                "role": role,
                "description": f"{role} layer {index + 1}",
                "generation_prompt": f"Generate distinct {role} layer for shot {index + 1}",
                "z_index": z_index,
                "asset_mode": asset_mode,
                "motion": {
                    "type": motion_type,
                    "direction": "left",
                    "intensity": 0.25,
                    "start_offset_seconds": 0,
                    "rationale": f"Layer motion supports shot {index + 1}.",
                },
            })
        shots.append({
            "id": f"shot-{index + 1:02d}",
            "start_seconds": start,
            "end_seconds": start + 4,
            "visual_subject": f"Subject {index + 1}",
            "setting": f"Setting {index + 1}",
            "composition": f"Composition {index + 1}",
            "purpose": "hook" if index == 0 else "ending" if index == 7 else "reveal",
            "setting": f"Original setting for shot {index + 1}",
            "composition": f"Layered composition for shot {index + 1}",
            "visual_subject": f"Procedural subject {index + 1}",
            "camera": {"movement": "dolly_in", "shot_size": "medium", "angle": "front", "focus": "moving focal point"},
            "animation": {
                "subject_action": "The presenter gestures.",
                "environment_motion": "The environment breathes.",
                "graphic_action": "",
                "depth_motion": "Objects move at different depths.",
                "motion_rationale": "Motion explains the story beat.",
            },
            "procedural_scene": {
                "environment": ["concert_stage", "laboratory", "space", "forest_dusk"][index % 4],
                "objects": [
                    {"id": "moving-a", "kind": "orb", "x": .25, "y": .4, "size": 24, "color": "#DDAA55", "motion": "pulse", "period_seconds": 2.0},
                    {"id": "moving-b", "kind": "spark", "x": .75, "y": .6, "size": 18, "color": "#AABBCC", "motion": "float", "period_seconds": 2.4},
                ],
            },
            "character_action": {
                "visible": True,
                "gesture": "talking",
                "expression": "speaking",
                "loop": True,
                "cycle_duration_seconds": 1.8,
            },
            "transition_to_next": "match_cut" if index == 0 else "whip_pan" if index == 1 else "none" if index == 7 else "cut",
            "narration_cue": f"Narration cue {index + 1}",
            "music_cue": f"Music cue {index + 1}",
            "graphic_data": None,
        })
    return {
        "_director_provider": {"contract_version": "violin-prince-master-director-v3"},
        "render_mode": "procedural_2d",
        "visual_concept": {
            "concept_name": "Story-specific concept",
            "palette": {"dominant": "#112233", "secondary": "#AABBCC", "accent": "#DDAA55"},
        },
        "storyboard": {"duration_seconds": 32, "shots": shots},
    }


class MasterDirectorJobTests(unittest.TestCase):
    def test_generates_plan_and_layer_brief_from_verified_selected_story(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = make_batch(root / "batch.json")
            output = root / "artifacts"
            enriched = {
                "topic": "A verified music story",
                "title": "A Clear Music Fact",
                "hook": "Why does it sound this way?",
                "core_claim": "An evidence-backed claim.",
                "narration_script": "A verified narration script with four clear sentences.",
            }
            sources = [
                {"source_id": "S1", "publisher_domain": "publisher-one.example", "title": "Article One"},
                {"source_id": "S2", "publisher_domain": "publisher-two.example", "title": "Article Two"},
            ]
            plan = fake_director_plan()

            def fake_writer(generated, destination):
                Path(destination).parent.mkdir(parents=True, exist_ok=True)
                Path(destination).write_text(json.dumps(generated), encoding="utf-8")
                return Path(destination)

            with (
                patch("create_master_director_plan.validate_and_enrich_plan", return_value=(enriched, sources)),
                patch("create_master_director_plan.generate_director_plan", return_value=plan) as generate,
                patch("create_master_director_plan.write_director_plan", side_effect=fake_writer),
            ):
                summary = create_master_director_plan(batch, "music-secrets", output)

            self.assertEqual(summary["status"], "director_plan_created")
            self.assertEqual(summary["shot_count"], 8)
            self.assertFalse(summary["rendered"])
            self.assertFalse(summary["published"])
            self.assertEqual(generate.call_args.args[0]["verified_sources"], sources)
            self.assertIsNone(generate.call_args.kwargs["creator_preferences"])
            saved_plan = json.loads((output / "master-director-plan.json").read_text(encoding="utf-8"))
            self.assertEqual(saved_plan["production_context"]["slot_id"], "music-secrets")
            self.assertEqual(saved_plan["production_context"]["research_gate"], (
                "passed_existing_two_publisher_quote_narration_and_story_coherence_checks"
            ))
            brief = json.loads((output / "shot-layer-generation-brief.json").read_text(encoding="utf-8"))
            self.assertEqual(brief["shot_count"], 8)
            self.assertEqual(brief["render_mode"], "procedural_2d")
            self.assertEqual(len(brief["shots"][0]["environment"]["objects"]), 2)
            self.assertTrue(brief["shots"][0]["character_action"]["loop"])
            self.assertEqual(brief["asset_policy"]["generated_scene_images"], 0)
            self.assertEqual(brief["asset_policy"]["generated_transparent_cutouts"], 0)
            self.assertEqual(summary["procedural_stagecraft_brief"], str(output / "procedural-stagecraft-brief.json"))
            self.assertEqual(saved_plan["production_context"]["narration_script"], enriched["narration_script"])

    def test_procedural_brief_never_requests_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = make_batch(root / "batch.json")
            output = root / "artifacts"
            enriched = {
                "topic": "A verified music story",
                "title": "A Clear Music Fact",
                "hook": "Why does it sound this way?",
                "core_claim": "An evidence-backed claim.",
                "narration_script": "A verified narration script with four clear sentences.",
            }
            sources = [
                {"source_id": "S1", "publisher_domain": "publisher-one.example"},
                {"source_id": "S2", "publisher_domain": "publisher-two.example"},
            ]
            with (
                patch("create_master_director_plan.validate_and_enrich_plan", return_value=(enriched, sources)),
                patch("create_master_director_plan.generate_director_plan", return_value=fake_director_plan()),
                patch("create_master_director_plan.write_director_plan", side_effect=lambda plan, dest: (
                    Path(dest).parent.mkdir(parents=True, exist_ok=True) or Path(dest).write_text(json.dumps(plan)) or Path(dest)
                )),
            ):
                create_master_director_plan(batch, "music-secrets", output)
            brief = json.loads((output / "procedural-stagecraft-brief.json").read_text(encoding="utf-8"))
            serialized = json.dumps(brief).casefold()
            self.assertNotIn("generation_prompt", serialized)
            self.assertNotIn("transparent_png", serialized)
            self.assertNotIn("asset_mode", serialized)
            self.assertEqual(brief["asset_policy"]["mode"], "procedural_vectors_and_articulated_rig")

    def test_blocked_story_never_calls_research_or_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = make_batch(root / "batch.json", chosen_status="blocked")
            with (
                patch("create_master_director_plan.validate_and_enrich_plan") as validate,
                patch("create_master_director_plan.generate_director_plan") as generate,
            ):
                with self.assertRaisesRegex(DirectorJobError, "Selected story is blocked"):
                    create_master_director_plan(batch, "music-secrets", root / "out")
            validate.assert_not_called()
            generate.assert_not_called()

    def test_existing_source_and_narration_gates_run_before_copilot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = make_batch(root / "batch.json")
            with (
                patch(
                    "create_master_director_plan.validate_and_enrich_plan",
                    side_effect=RuntimeError("two-publisher evidence gate failed"),
                ),
                patch("create_master_director_plan.generate_director_plan") as generate,
            ):
                with self.assertRaisesRegex(DirectorJobError, "existing source, exact-quote"):
                    create_master_director_plan(batch, "music-secrets", root / "out")
            generate.assert_not_called()
            self.assertFalse((root / "out" / "master-director-plan.json").exists())

    def test_unknown_slot_and_invalid_batch_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = make_batch(root / "batch.json")
            with self.assertRaisesRegex(DirectorJobError, "Unknown canonical slot"):
                create_master_director_plan(batch, "not-a-slot", root / "out")
            with self.assertRaises(DirectorJobError):
                create_master_director_plan(root / "missing.json", "music-secrets", root / "out")


if __name__ == "__main__":
    unittest.main()
