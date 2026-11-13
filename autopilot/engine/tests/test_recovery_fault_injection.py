"""Controlled, offline fault-injection proof for Phase 2 targeted recovery.

All stage boundaries are exercised through build_prototype with deterministic
mocks. No Cloudflare requests, image generation, publishing or paid services
are invoked by these tests.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import motion_prototype as prototype
import run as pipeline
from quality_control import run_quality_gate as _real_quality_gate


def _valid_word_info():
    words = ["A", "violin", "phrase", "takes", "shape", "through", "careful", "bow", "and", "resonance"]
    cues = [
        {"start": round(0.10 + i * 0.30, 3), "end": round(0.26 + i * 0.30, 3), "text": word}
        for i, word in enumerate(words)
    ]
    return {
        "word_timing_method": "kokoro_predicted_phoneme_durations",
        "word_count": len(words),
        "word_cues": cues,
        "subtitle_cues": cues,
    }


class RecoveryFaultInjectionTests(unittest.TestCase):
    """Inject one defect per scenario and assert unaffected stages never rerun."""

    def _make_package(self, root):
        package = root / "package"
        output = root / "output"
        package.mkdir()
        output.mkdir()
        plan = {
            "title": "Controlled recovery test",
            "topic": "Synthetic offline recovery fixture",
            "visual_motif": "a single violin",
            "narration_script": "A violin phrase takes shape through careful bow and resonance.",
            "scenes": [
                {"caption": f"Scene {i}", "graphic_label": f"BEAT {i}",
                 "graphic_detail": "Controlled test detail"}
                for i in range(1, 4)
            ],
        }
        (package / "creative_plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (package / "stage.json").write_text(json.dumps({
            "stage": "visuals_ready",
            "visuals_run_id": "offline-fault-injection-fixture",
            "asset": {"audio_source": "generated_ambient_fallback"},
        }), encoding="utf-8")
        (package / "soundtrack.wav").write_bytes(b"synthetic-soundtrack-input")
        for index in range(1, 4):
            Image.new("RGB", (512, 512), (25 * index, 35 * index, 45 * index)).save(
                package / f"scene-{index}.jpg", "JPEG", quality=82
            )
        Image.new("RGB", (640, 480), (36, 42, 50)).save(
            package / "storyboard-preview.png", "PNG"
        )
        return package, output

    def _run_scenario(self, scenario):
        with tempfile.TemporaryDirectory(prefix=f"phase2-{scenario}-") as folder:
            package, output = self._make_package(Path(folder))
            calls = {"synth": 0, "baseline_render": 0, "html_render": 0, "mix": 0, "final_qc": 0}

            def synthesize(script, destination):
                calls["synth"] += 1
                destination = Path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"synthetic-kokoro-wav")
                info = _valid_word_info()
                if scenario == "narration_timing" and calls["synth"] == 1:
                    info = dict(info)
                    info["word_cues"] = []  # controlled timing defect on first take
                return destination, info

            def baseline_render(*args, **kwargs):
                calls["baseline_render"] += 1
                rendered = output / "mock-baseline-source.mp4"
                rendered.write_bytes(b"synthetic-baseline-video")
                return rendered, {"quality_gate_checks_passed": 1, "quality_gate_checks_total": 1}

            def validate_final(path, *args, **kwargs):
                path = Path(path)
                if path.name == "ffmpeg-baseline.mp4":
                    return {
                        "quality_gate_checks_passed": 1,
                        "quality_gate_checks_total": 1,
                    }
                calls["final_qc"] += 1
                if scenario == "audio_only" and calls["final_qc"] == 1:
                    error = pipeline.PipelineError("INJECTED_AUDIO_ONLY_DEFECT")
                    error.retry_stage = "audio_mix"
                    error.quality_report = {"failed_checks": ["true_peak"]}
                    raise error
                if scenario == "video_text" and calls["final_qc"] == 1:
                    error = pipeline.PipelineError("INJECTED_VIDEO_TEXT_DEFECT")
                    error.retry_stage = "video_render"
                    error.quality_report = {"failed_checks": ["encoded_frame_text_audit"]}
                    raise error
                return {
                    "quality_gate_checks_passed": 21,
                    "quality_gate_checks_total": 21,
                    "quality_gate_status": "passed",
                }

            def renderer_command(command):
                if command and command[0] == "node":
                    calls["html_render"] += 1
                    Path(command[-1]).write_bytes(b"synthetic-silent-video")
                    (output / "final-text-frame-audit.json").write_text(json.dumps({
                        "ok": True,
                        "frames": [
                            {"ok": True, "expected_text_nodes": 3, "actual_text_nodes": 3,
                             "missing_text": [], "invalid_text_nodes": [], "out_of_bounds_text": [],
                             "narration_word_count": 10, "timed_word_count": 10,
                             "narration_word_order_valid": True}
                            for _ in range(3)
                        ],
                    }), encoding="utf-8")

            def mix_audio(video_only, soundtrack, narration, target, audio_source):
                calls["mix"] += 1
                Path(target).write_bytes(b"synthetic-final-mux")

            def silent_gate(*args, **kwargs):
                return {"status": "passed", "passed": True, "checks": []}

            with (
                patch.object(prototype, "synthesize_voiceover", side_effect=synthesize),
                patch.object(prototype, "_music_energy_samples", return_value=[]),
                patch.object(prototype, "_run", side_effect=renderer_command),
                patch.object(prototype, "_mix_audio", side_effect=mix_audio),
                patch.object(prototype, "_extract_final_review_frames", return_value=[]),
                patch.object(prototype, "run_quality_gate", side_effect=silent_gate),
                patch.object(pipeline, "_valid_wav_checkpoint", return_value=True),
                patch.object(pipeline, "scene_durations_from_narration", return_value=[8.0, 8.0, 8.0]),
                patch.object(pipeline, "render", side_effect=baseline_render),
                patch.object(pipeline, "validate_final_video", side_effect=validate_final),
            ):
                report = prototype.build_prototype(package, output, fps=25)

            recovery = report["recovery"]
            result = {
                "scenario": scenario,
                "status": "passed",
                "injected_fault": {
                    "audio_only": "first final audio mix fails its audio QC",
                    "video_text": "first final render fails its encoded-text QC",
                    "narration_timing": "first narration take has missing native word cues",
                }[scenario],
                "calls": calls,
                "observed_recovery": {
                    "renderer_attempts": recovery["renderer_attempts"],
                    "audio_mix_attempts": recovery["audio_mix_attempts"],
                    "narration_reused": recovery["narration_reused"],
                },
            }

            if scenario == "audio_only":
                self.assertEqual(calls["html_render"], 1, result)
                self.assertEqual(calls["mix"], 2, result)
                self.assertEqual(calls["synth"], 1, result)
                self.assertEqual(recovery["renderer_attempts"], 1, result)
                self.assertEqual(recovery["audio_mix_attempts"], 2, result)
            elif scenario == "video_text":
                self.assertEqual(calls["html_render"], 2, result)
                self.assertEqual(calls["mix"], 2, result)
                self.assertEqual(calls["synth"], 1, result)
                self.assertEqual(recovery["renderer_attempts"], 2, result)
                self.assertEqual(recovery["audio_mix_attempts"], 2, result)
            else:
                self.assertEqual(calls["synth"], 2, result)
                self.assertEqual(calls["html_render"], 1, result)
                self.assertEqual(calls["mix"], 1, result)
                self.assertEqual(recovery["renderer_attempts"], 1, result)
                self.assertEqual(recovery["audio_mix_attempts"], 1, result)
            return result

    def test_all_three_faults_retry_only_the_affected_stage(self):
        results = [
            self._run_scenario("audio_only"),
            self._run_scenario("video_text"),
            self._run_scenario("narration_timing"),
        ]
        report = {
            "schema_version": 1,
            "status": "passed",
            "test_mode": "offline deterministic fault injection",
            "external_ai_calls": 0,
            "publishing_enabled": False,
            "scenarios": results,
        }
        destination = Path("work/output/motion-prototype/recovery-fault-injection-report.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.assertEqual(len(results), 3)
        self.assertTrue(all(item["status"] == "passed" for item in results))


if __name__ == "__main__":
    unittest.main()
