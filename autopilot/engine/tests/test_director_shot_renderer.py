"""Tests for the shot-led Master Director -> HyperFrames project adapter."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from director_shot_renderer import (  # noqa: E402
    DirectorShotRenderError,
    build_director_hyperframes_project,
)


def director_plan():
    purposes = ["hook", "context", "reveal", "explanation", "contrast", "reveal", "payoff", "ending"]
    sizes = ["extreme_wide", "wide", "medium", "close_up", "macro", "overhead", "point_of_view", "close_up"]
    movements = ["dolly_in", "truck_left", "orbit", "pan", "crane_up", "tracking", "whip_pan", "dolly_out"]
    transitions = ["match_cut", "whip_pan", "dissolve", "cut", "foreground_wipe", "speed_ramp", "light_transition", "none"]
    shots = []
    for index in range(8):
        start = index * 4
        shots.append({
            "id": f"shot-{index + 1:02d}",
            "start_seconds": start,
            "end_seconds": start + 4,
            "purpose": purposes[index],
            "visual_subject": f"Unique visual subject {index + 1}",
            "setting": f"Distinct setting {index + 1}",
            "visual_description": f"Original shot description with unique subject detail {index + 1}",
            "composition": f"Layered visual composition {index + 1}",
            "camera": {
                "shot_size": sizes[index],
                "angle": f"Angle {index + 1}",
                "movement": movements[index],
                "focus": f"Focus detail {index + 1}",
            },
            "animation": {
                "subject_action": f"Subject moves in a distinct way {index + 1}",
                "environment_motion": f"Environment responds {index + 1}",
                "graphic_action": "",
                "depth_motion": f"Depth planes separate {index + 1}",
                "motion_rationale": f"Motion meaning {index + 1}",
            },
            "transition_to_next": transitions[index],
            "narration_cue": f"Narration phrase {index + 1}",
            "music_cue": f"Music editorial target {index + 1}",
            "sound_effects": ["subtle impact"],
        })
    return {
        "schema_version": 1,
        "story_understanding": {
            "central_truth": "A concise supported music fact.",
            "viewer_question": "What causes this sound?",
            "emotional_arc": ["curiosity", "discovery", "understanding"],
            "key_revelations": ["The first supported reveal.", "The second supported reveal."],
        },
        "visual_concept": {
            "concept_name": "Resonance in motion",
            "visual_metaphor": "A pulse visibly travelling through an instrument.",
            "creative_rationale": "The metaphor makes a sound process visible.",
            "art_direction": "Tactile cinematic close-up imagery and dimensional lighting.",
            "palette": {
                "dominant": "#19324A",
                "secondary": "#D6E0E8",
                "accent": "#D95D39",
                "harmony": "temperature_contrast",
                "reasoning": "Cool structural colour contrasts with a warm event accent.",
                "contrast_strategy": "Use the dark dominant behind light text and reserve the accent for focal reveals.",
            },
            "lighting_plan": "Directional edge lighting reveals surface detail.",
            "composition_language": "Foreground, subject and background have distinct depth.",
        },
        "storyboard": {"duration_seconds": 32, "shots": shots},
        "edit_direction": {
            "pacing": "Build into the reveal and settle on a resolved ending.",
            "transition_language": "Cuts and motivated animated transitions.",
            "typography": "Readable phone-sized typography with no subject obstruction.",
            "sound_design": "Restrained accents on factual reveals.",
            "music_mood": "Curiosity moving toward resolution.",
            "music_sync_cues": [
                {"time_seconds": 4, "event": "First reveal", "reason": "Land on the first musical accent."},
                {"time_seconds": 20, "event": "Musical payoff", "reason": "Allow the final phrase to resolve."},
            ],
            "final_payoff": "The visual metaphor resolves into the instrument's musical result.",
        },
    }


def make_images(root: Path, count: int = 8) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(count):
        path = root / f"shot-{index + 1:02d}.png"
        image = Image.new("RGB", (360, 640))
        pixels = image.load()
        for y in range(640):
            for x in range(360):
                pixels[x, y] = (
                    (x * 3 + index * 27) % 256,
                    (y * 2 + index * 43) % 256,
                    (x + y + index * 59) % 256,
                )
        image.save(path, format="PNG")
        paths.append(path)
    return paths


class DirectorShotRendererTests(unittest.TestCase):
    def test_builds_one_unique_render_scene_per_directed_shot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = make_images(root / "images")
            project = build_director_hyperframes_project(
                director_plan(), images, root / "project", width=720, height=1280, fps=25
            )
            self.assertEqual(len(project["scenes"]), 8)
            self.assertEqual(len(project["shot_asset_manifest"]), 8)
            self.assertEqual(len({item["sha256"] for item in project["shot_asset_manifest"]}), 8)
            self.assertEqual(project["scenes"][3]["director_camera"]["movement"], "pan")
            self.assertEqual(project["director_palette"]["accent"], "#D95D39")
            self.assertEqual(project["scenes"][1]["transition_in"], "whip_pan")
            self.assertLess(project["scenes"][1]["start"], 4.0)
            self.assertEqual(project["duration_seconds"], 32)
            self.assertTrue((root / "project" / "project.json").is_file())

    def test_rejects_missing_per_shot_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(DirectorShotRenderError, "needs its own image asset"):
                build_director_hyperframes_project(director_plan(), [], root / "project")

    def test_rejects_duplicate_image_content_even_when_filenames_differ(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = make_images(root / "images")
            images[1].write_bytes(images[0].read_bytes())
            with self.assertRaisesRegex(DirectorShotRenderError, "identical image content"):
                build_director_hyperframes_project(director_plan(), images, root / "project")

    def test_rejects_unimplemented_morph_transition_instead_of_downgrading(self):
        plan = director_plan()
        plan["storyboard"]["shots"][0]["transition_to_next"] = "morph_cut"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = make_images(root / "images")
            with self.assertRaisesRegex(DirectorShotRenderError, "not supported by the current shot renderer"):
                build_director_hyperframes_project(plan, images, root / "project")

    def test_invalid_director_contract_is_rejected_before_staging(self):
        plan = director_plan()
        del plan["visual_concept"]["palette"]["accent"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = make_images(root / "images")
            with self.assertRaisesRegex(DirectorShotRenderError, "failed validation"):
                build_director_hyperframes_project(plan, images, root / "project")

    def test_render_project_keeps_action_and_music_sync_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = make_images(root / "images")
            project = build_director_hyperframes_project(director_plan(), images, root / "project")
            self.assertEqual(
                project["scenes"][0]["director_animation"]["subject_action"],
                "Subject moves in a distinct way 1",
            )
            self.assertEqual(len(project["director_music_sync_cues"]), 2)
            self.assertIn("requires_separated_assets", project["scenes"][0]["animation_execution_status"])

    def test_cut_does_not_create_an_overlap(self):
        plan = director_plan()
        plan["storyboard"]["shots"][0]["transition_to_next"] = "cut"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = make_images(root / "images")
            project = build_director_hyperframes_project(plan, images, root / "project")
            self.assertEqual(project["scenes"][1]["start"], 4.0)
            self.assertEqual(project["scenes"][1]["transition_in"], "cut")
            self.assertEqual(project["scenes"][1]["transition_in_duration"], 0.0)


if __name__ == "__main__":
    unittest.main()
