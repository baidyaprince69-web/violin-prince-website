"""Offline tests for ChatGPT-prepared daily production evidence gates."""
import sys
import unittest
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

import run_daily_plan as daily  # noqa: E402


class DailyPlanEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.sources = [
            {
                "source_id": "S001",
                "publisher_domain": "publisher-one.example",
                "evidence_text": "Researchers measured the violin string vibration at several frequencies in a controlled acoustic experiment. This exact passage supports the claim.",
            },
            {
                "source_id": "S002",
                "publisher_domain": "publisher-two.example",
                "evidence_text": "The bridge transfers the string motion into the instrument body, producing resonant sound. This exact passage supports a second claim.",
            },
        ]
        self.sentences = [
            "Why does a violin sound so alive?",
            "Researchers measured the violin string vibration at several frequencies.",
            "The bridge transfers the string motion into the instrument body.",
            "That resonance shapes the sound heard in the room.",
        ]

    def test_narration_contract_uses_37_to_38_words_as_the_duration_estimate(self):
        script_37 = (
            "Could your room change your violin mix? "
            "Audient adds RoomTune monitor correction to its iD interfaces. "
            "It measures the room and adjusts the signal reaching monitors. "
            "Its onboard DSP runs EQ, compression and reverb with no latency."
        )
        script_38 = (
            "Could your room change your violin mix? "
            "Audient adds RoomTune monitor correction to its new iD interfaces. "
            "It measures the room and adjusts the signal reaching monitors. "
            "Its onboard DSP runs EQ, compression and reverb with no latency."
        )
        self.assertEqual(daily.engine.narration_word_count(script_37), 37)
        self.assertEqual(daily.engine.narration_word_count(script_38), 38)
        self.assertEqual(daily.engine.narration_validation_error(script_37), "")
        self.assertEqual(daily.engine.narration_validation_error(script_38), "")
        self.assertIn("37–38", daily.engine.narration_validation_error(script_38 + " Today."))


    def test_presenter_workflow_flag_enables_daily_plans(self):
        plan = {"scenes": []}
        result = daily.enable_presenter_from_environment(plan, "true")
        self.assertIs(result["use_violin_prince_presenter"], True)

    def test_presenter_workflow_flag_stays_off_when_not_enabled(self):
        plan = {"scenes": []}
        result = daily.enable_presenter_from_environment(plan, "false")
        self.assertNotIn("use_violin_prince_presenter", result)

    def test_exact_article_quotes_cover_each_body_sentence(self):
        evidence = [
            {"sentence_number": 2, "source_id": "S001", "quote": "Researchers measured the violin string vibration at several frequencies in a controlled acoustic experiment."},
            {"sentence_number": 3, "source_id": "S002", "quote": "The bridge transfers the string motion into the instrument body, producing resonant sound."},
            {"sentence_number": 4, "source_id": "S001", "quote": "This exact passage supports the claim."},
        ]
        checked = daily.validate_claim_evidence(evidence, self.sources, self.sentences)
        self.assertEqual([item["sentence_number"] for item in checked], [2, 3, 4])

    def test_rejects_quote_not_present_in_article_body(self):
        evidence = [
            {"sentence_number": 2, "source_id": "S001", "quote": "The violin bridge creates an entirely different sound with this mechanism."},
            {"sentence_number": 3, "source_id": "S002", "quote": "The bridge transfers the string motion into the instrument body, producing resonant sound."},
            {"sentence_number": 4, "source_id": "S001", "quote": "This exact passage supports the claim."},
        ]
        with self.assertRaisesRegex(Exception, "does not appear"):
            daily.validate_claim_evidence(evidence, self.sources, self.sentences)

    def test_rejects_missing_sentence_evidence(self):
        evidence = [
            {"sentence_number": 2, "source_id": "S001", "quote": "Researchers measured the violin string vibration at several frequencies in a controlled acoustic experiment."},
            {"sentence_number": 3, "source_id": "S002", "quote": "The bridge transfers the string motion into the instrument body, producing resonant sound."},
        ]
        with self.assertRaisesRegex(Exception, "Missing exact publisher evidence"):
            daily.validate_claim_evidence(evidence, self.sources, self.sentences)

    def test_presenter_opt_in_copies_bundle_and_assigns_scene_poses(self):
        import json
        import tempfile
        from PIL import Image

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle = root / "rig"
            package = root / "package"
            bundle.mkdir()
            package.mkdir()
            character = {
                "id": "violin-prince",
                "layers": [{"id": "torso", "role": "torso", "src": "torso.png"}],
                "expressions": {
                    "neutral": {"src": "expression-neutral.png"},
                    "speaking": {"src": "expression-speaking.png"},
                },
                "pose_assets": {
                    "resting_hands": {"src": "pose-resting_hands.png"},
                    "explaining_two_hands": {"src": "pose-explaining_two_hands.png"},
                    "open_palms": {"src": "pose-open_palms.png"},
                },
            }
            (bundle / "character.json").write_text(json.dumps(character), encoding="utf-8")
            for name in (
                "torso.png", "expression-neutral.png", "expression-speaking.png",
                "pose-resting_hands.png", "pose-explaining_two_hands.png", "pose-open_palms.png",
            ):
                Image.new("RGBA", (24, 24), (100, 120, 140, 255)).save(bundle / name)

            plan = {
                "use_violin_prince_presenter": True,
                "scenes": [{}, {}, {}],
            }
            result = daily.attach_violin_prince_presenter(
                plan, package_dir=package, rig_bundle_dir=bundle
            )
            self.assertEqual(len(result["characters"]), 1)
            self.assertTrue(result["presenter_integration"]["enabled"])
            self.assertEqual(
                [scene["character_actions"]["violin-prince"]["pose_asset"] for scene in result["scenes"]],
                ["resting_hands", "explaining_two_hands", "open_palms"],
            )
            copied = result["characters"][0]
            self.assertTrue(Path(copied["layers"][0]["src"]).is_file())
            self.assertTrue(Path(copied["expressions"]["speaking"]["src"]).is_file())
            self.assertTrue(Path(copied["pose_assets"]["open_palms"]["src"]).is_file())

    def test_presenter_opt_in_preserves_explicit_scene_action(self):
        import json
        import tempfile
        from PIL import Image

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle = root / "rig"
            package = root / "package"
            bundle.mkdir()
            package.mkdir()
            character = {
                "id": "violin-prince",
                "layers": [{"id": "torso", "role": "torso", "src": "torso.png"}],
                "expressions": {"neutral": {"src": "expression-neutral.png"}},
                "pose_assets": {"point_left": {"src": "pose-point_left.png"}},
            }
            (bundle / "character.json").write_text(json.dumps(character), encoding="utf-8")
            for name in ("torso.png", "expression-neutral.png", "pose-point_left.png"):
                Image.new("RGBA", (24, 24), (100, 120, 140, 255)).save(bundle / name)

            custom = {"pose_asset": "point_left", "expression": "neutral"}
            plan = {
                "use_violin_prince_presenter": True,
                "scenes": [{"character_actions": {"violin-prince": custom}}],
            }
            result = daily.attach_violin_prince_presenter(
                plan, package_dir=package, rig_bundle_dir=bundle
            )
            self.assertEqual(result["scenes"][0]["character_actions"]["violin-prince"], custom)

    def test_presenter_opt_in_fails_when_saved_bundle_is_missing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(Exception, "tested rig bundle is missing"):
                daily.attach_violin_prince_presenter(
                    {"use_violin_prince_presenter": True, "scenes": []},
                    package_dir=Path(folder) / "package",
                    rig_bundle_dir=Path(folder) / "missing-rig",
                )

    def test_rejects_unselected_source(self):
        evidence = [
            {"sentence_number": 2, "source_id": "S999", "quote": "Researchers measured the violin string vibration at several frequencies in a controlled acoustic experiment."},
            {"sentence_number": 3, "source_id": "S002", "quote": "The bridge transfers the string motion into the instrument body, producing resonant sound."},
            {"sentence_number": 4, "source_id": "S001", "quote": "This exact passage supports the claim."},
        ]
        with self.assertRaisesRegex(Exception, "unselected source"):
            daily.validate_claim_evidence(evidence, self.sources, self.sentences)


if __name__ == "__main__":
    unittest.main()
