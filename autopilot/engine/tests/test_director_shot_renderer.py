"""Tests for the shot-led Master Director -> HyperFrames project adapter."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import subprocess
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from PIL import Image

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import hyperframes_pipeline as pipeline  # noqa: E402

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
            "visual_layers": [
                {
                    "id": "background",
                    "role": "background",
                    "description": f"Full-frame environment without the subject {index + 1}",
                    "generation_prompt": f"Cinematic background plate, exclude subject, scene {index + 1}",
                    "z_index": 0,
                    "asset_mode": "opaque",
                    "motion": {
                        "type": "drift", "direction": "left", "intensity": 0.25,
                        "start_offset_seconds": 0,
                        "rationale": "Subtle environment drift adds depth."
                    }
                },
                {
                    "id": "subject",
                    "role": "subject",
                    "description": f"Isolated hero subject with transparent background {index + 1}",
                    "generation_prompt": f"Transparent cutout of the hero subject, scene {index + 1}",
                    "z_index": 20,
                    "asset_mode": "transparent_png",
                    "motion": {
                        "type": "float", "direction": "up", "intensity": 0.3,
                        "start_offset_seconds": 0.2,
                        "rationale": "A gentle subject movement gives the hero presence."
                    }
                },
                {
                    "id": "foreground",
                    "role": "foreground",
                    "description": f"Isolated foreground depth element {index + 1}",
                    "generation_prompt": f"Transparent foreground-only cinematic depth element, scene {index + 1}",
                    "z_index": 40,
                    "asset_mode": "transparent_png",
                    "motion": {
                        "type": "parallax", "direction": "right", "intensity": 0.45,
                        "start_offset_seconds": 0,
                        "rationale": "Independent foreground travel creates visual depth."
                    }
                }
            ],
            "transition_to_next": transitions[index],
            "narration_cue": f"Narration phrase {index + 1}",
            "music_cue": f"Music editorial target {index + 1}",
            "sound_effects": ["subtle impact"],
        })
    return {
        "schema_version": 2,
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


def make_layer_assets(root: Path, count: int = 8) -> dict[str, dict[str, Path]]:
    root.mkdir(parents=True, exist_ok=True)
    result = {}
    for index in range(count):
        shot_id = f"shot-{index + 1:02d}"
        shot_dir = root / shot_id
        shot_dir.mkdir(parents=True, exist_ok=True)
        from PIL import ImageDraw

        subject_path = shot_dir / "subject.png"
        subject = Image.new("RGBA", (360, 640), (0, 0, 0, 0))
        ImageDraw.Draw(subject).ellipse(
            (90 + index, 90, 265 + index, 540),
            fill=(160, 75 + index * 7, 55, 235),
            outline=(250, 245, 230, 220),
            width=5,
        )
        subject.save(subject_path, format="PNG")

        foreground_path = shot_dir / "foreground.png"
        foreground = Image.new("RGBA", (360, 640), (0, 0, 0, 0))
        ImageDraw.Draw(foreground).polygon(
            [(0, 470 + index), (95, 425), (180, 640), (0, 640)],
            fill=(15 + index * 9, 35, 55 + index * 8, 185),
        )
        foreground.save(foreground_path, format="PNG")
        result[shot_id] = {
            "subject": subject_path,
            "foreground": foreground_path,
        }
    return result


def build_project(plan, images, root):
    return build_director_hyperframes_project(
        plan,
        images,
        root / "project",
        layer_assets=make_layer_assets(root / "layers", len(plan["storyboard"]["shots"])),
    )


class DirectorShotRendererTests(unittest.TestCase):
    def test_builds_one_unique_render_scene_per_directed_shot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = make_images(root / "images")
            project = build_director_hyperframes_project(
                director_plan(), images, root / "project",
                layer_assets=make_layer_assets(root / "layers"),
                width=720, height=1280, fps=25
            )
            self.assertEqual(len(project["scenes"]), 8)
            self.assertEqual(len(project["shot_asset_manifest"]), 24)
            self.assertEqual(len({item["sha256"] for item in project["shot_asset_manifest"]}), 24)
            self.assertEqual(
                {layer["role"] for layer in project["scenes"][0]["visual_layers"]},
                {"background", "subject", "foreground"},
            )
            self.assertTrue(all(
                layer["asset_has_alpha"]
                for layer in project["scenes"][0]["visual_layers"]
                if layer["role"] != "background"
            ))
            self.assertEqual(project["scenes"][3]["director_camera"]["movement"], "pan")
            self.assertEqual(project["director_palette"]["accent"], "#D95D39")
            self.assertEqual(project["scenes"][1]["transition_in"], "match_cut")
            self.assertEqual(project["scenes"][1]["camera_motion_start_offset"], 0.0)
            self.assertEqual(project["scenes"][1]["camera_motion_duration"], 4.0)
            self.assertLess(project["scenes"][2]["start"], 8.0)
            self.assertEqual(project["duration_seconds"], 32)
            self.assertTrue((root / "project" / "project.json").is_file())

    def test_rejects_missing_per_shot_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = make_images(root / "images")
            with self.assertRaisesRegex(DirectorShotRenderError, "needs exactly these independently generated"):
                build_director_hyperframes_project(
                    director_plan(),
                    images,
                    root / "project",
                    layer_assets={f"shot-{index + 1:02d}": {} for index in range(8)},
                )

    def test_rejects_duplicate_image_content_even_when_filenames_differ(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = make_images(root / "images")
            images[1].write_bytes(images[0].read_bytes())
            with self.assertRaisesRegex(DirectorShotRenderError, "identical image content"):
                build_project(director_plan(), images, root)

    def test_rejects_unimplemented_morph_transition_instead_of_downgrading(self):
        plan = director_plan()
        plan["storyboard"]["shots"][0]["transition_to_next"] = "morph_cut"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = make_images(root / "images")
            with self.assertRaisesRegex(DirectorShotRenderError, "not supported by the current shot renderer"):
                build_project(plan, images, root)

    def test_invalid_director_contract_is_rejected_before_staging(self):
        plan = director_plan()
        del plan["visual_concept"]["palette"]["accent"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = make_images(root / "images")
            with self.assertRaisesRegex(DirectorShotRenderError, "failed validation"):
                build_project(plan, images, root)

    def test_rejects_nontransparent_png_disguised_as_a_subject_cutout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = make_images(root / "images")
            layers = make_layer_assets(root / "layers")
            bad_subject = root / "opaque-subject.png"
            Image.new("RGB", (360, 640), (120, 80, 40)).save(bad_subject, format="PNG")
            layers["shot-01"]["subject"] = bad_subject
            with self.assertRaisesRegex(DirectorShotRenderError, "real non-opaque alpha channel"):
                build_director_hyperframes_project(
                    director_plan(),
                    images,
                    root / "project",
                    layer_assets=layers,
                )

    def test_duplicate_transparent_layer_content_is_rejected_across_shots(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = make_images(root / "images")
            layers = make_layer_assets(root / "layers")
            layers["shot-02"]["subject"].write_bytes(
                layers["shot-01"]["subject"].read_bytes()
            )
            with self.assertRaisesRegex(DirectorShotRenderError, "identical image content"):
                build_director_hyperframes_project(
                    director_plan(),
                    images,
                    root / "project",
                    layer_assets=layers,
                )

    def test_render_project_keeps_action_and_music_sync_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = make_images(root / "images")
            project = build_project(director_plan(), images, root)
            self.assertEqual(
                project["scenes"][0]["director_animation"]["subject_action"],
                "Subject moves in a distinct way 1",
            )
            self.assertEqual(len(project["director_music_sync_cues"]), 2)
            self.assertEqual(
                project["scenes"][0]["animation_execution_status"],
                "separate_image_layers_staged_for_independent_motion",
            )

    def test_cut_does_not_create_an_overlap(self):
        plan = director_plan()
        plan["storyboard"]["shots"][0]["transition_to_next"] = "cut"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = make_images(root / "images")
            project = build_project(plan, images, root)
            self.assertEqual(project["scenes"][1]["start"], 4.0)
            self.assertEqual(project["scenes"][1]["transition_in"], "cut")
            self.assertEqual(project["scenes"][1]["transition_in_duration"], 0.0)


    def test_complete_director_video_path_renders_and_mixes_without_publishing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = make_images(root / "images")
            animation_dir = root / "animation2d"
            hyperframes_cli = animation_dir / "node_modules" / ".bin" / "hyperframes"
            hyperframes_cli.parent.mkdir(parents=True)
            hyperframes_cli.write_text("fixture", encoding="utf-8")
            font_path = root / "DMSerifDisplay-Regular.ttf"
            font_path.write_bytes(b"synthetic-font")
            audio = root / "music.wav"
            narration = root / "narration.wav"
            audio.write_bytes(b"music" * 2000)
            narration.write_bytes(b"voice" * 2000)
            output = root / "output" / "final.mp4"
            project_dir = root / "director-project"

            engine = SimpleNamespace(
                W=720,
                H=1280,
                FPS=25,
                _ensure_brand_fonts=lambda: {"serif": str(font_path)},
                write_kinetic_ass=lambda _cues, path, _words: (
                    Path(path).write_text("[Script Info]\n", encoding="utf-8")
                ),
            )

            def fake_run(command, *, cwd, timeout=900):
                name = Path(command[0]).name
                if name == "node" and len(command) > 1 and command[1] == "--version":
                    return subprocess.CompletedProcess(command, 0, stdout="v22.0.0", stderr="")
                if name == "hyperframes":
                    if command[1] == "render":
                        target = Path(command[command.index("--output") + 1])
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(b"V" * 8192)
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                if name == "ffprobe":
                    command_text = " ".join(command)
                    if "format=duration:stream=" in command_text:
                        result = {
                            "format": {"duration": "32.0"},
                            "streams": [
                                {"codec_type": "video", "codec_name": "h264",
                                 "width": 720, "height": 1280, "r_frame_rate": "25/1"},
                                {"codec_type": "audio", "codec_name": "aac",
                                 "sample_rate": "48000", "channels": 2},
                            ],
                        }
                    elif "format=duration" in command_text:
                        result = {"format": {"duration": "32.0"}}
                    else:
                        result = {"streams": [{
                            "codec_name": "h264", "width": 720,
                            "height": 1280, "r_frame_rate": "25/1"
                        }]}
                    return subprocess.CompletedProcess(
                        command, 0, stdout=json.dumps(result), stderr=""
                    )
                if name == "ffmpeg":
                    target = Path(command[-1])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"A" * (8192 if target.suffix == ".wav" else 200000))
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                raise AssertionError("Unexpected renderer command: " + repr(command))

            def fake_build(_node, scene_project, out_dir):
                self.assertTrue(Path(scene_project).is_file())
                project_data = json.loads(Path(scene_project).read_text(encoding="utf-8"))
                first_image = Path(project_data["scenes"][0]["image"])
                self.assertTrue((Path(scene_project).parent / first_image).is_file())
                Path(out_dir).mkdir(parents=True, exist_ok=True)
                render_scenes = project_data["scenes"]
                rendered_layers = sum(len(scene.get("visual_layers") or []) for scene in render_scenes)
                independent_tracks = sum(
                    1
                    for scene in render_scenes
                    for layer in scene.get("visual_layers") or []
                    if layer.get("role") != "background"
                    and (layer.get("motion") or {}).get("type") != "locked"
                )
                (Path(out_dir) / "motion-report.json").write_text(
                    json.dumps({
                        "status": "passed",
                        "independent_layer_motion_count": independent_tracks,
                        "rendered_layer_count": rendered_layers,
                        "scenes": []
                    }),
                    encoding="utf-8",
                )

            with (
                patch.object(pipeline, "ANIMATION2D_DIR", animation_dir),
                patch.object(pipeline, "_build_motion_project", side_effect=fake_build),
                patch.object(pipeline, "_run", side_effect=fake_run),
                patch.object(pipeline.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}"),
            ):
                report = pipeline.render_master_director_video(
                    engine,
                    director_plan(),
                    images,
                    audio,
                    narration,
                    {"subtitle_cues": [], "word_cues": []},
                    project_dir=project_dir,
                    output_video=output,
                    layer_assets=make_layer_assets(root / "layer-assets"),
                )

            self.assertTrue(output.is_file())
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["shot_count"], 8)
            self.assertEqual(report["duration_seconds"], 32)
            self.assertFalse(report["publish_ready"])
            self.assertIn("image-generation provider is not connected", report["publish_blocker"])
            self.assertEqual(report["rendered_layer_count"], 24)
            self.assertEqual(report["shot_count"], 8)
            self.assertTrue((output.parent / "master-director-render-report.json").is_file())


if __name__ == "__main__":
    unittest.main()
