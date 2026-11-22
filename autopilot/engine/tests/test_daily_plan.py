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

    def test_production_identity_pins_plan_and_narration_hashes(self):
        import hashlib
        import json

        script = (
            "Could your room change your violin mix? "
            "Modern audio interfaces feature RoomTune monitor correction. "
            "It measures your room's acoustics and adjusts monitor response. "
            "Onboard DSP also runs input EQ, compression and reverb with no latency."
        )
        plan = {"production_date": "2026-11-21", "narration_script": script}
        plan_bytes = json.dumps(plan, ensure_ascii=False).encode("utf-8")
        plan_hash = hashlib.sha256(plan_bytes).hexdigest()
        script_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()

        identity = daily.build_production_identity(
            plan_bytes,
            plan,
            expected_plan_sha256=plan_hash,
            expected_narration_sha256=script_hash,
        )
        self.assertEqual(identity["plan_sha256"], plan_hash)
        self.assertEqual(identity["narration_script_sha256"], script_hash)
        self.assertEqual(identity["narration_word_count"], 35)
        self.assertEqual(identity["snapshot_lock"], "verified")

        with self.assertRaisesRegex(Exception, "checked-out plan"):
            daily.build_production_identity(
                plan_bytes,
                plan,
                expected_plan_sha256="0" * 64,
                expected_narration_sha256=script_hash,
            )
        with self.assertRaisesRegex(Exception, "both expected plan and narration hashes"):
            daily.build_production_identity(
                plan_bytes,
                plan,
                expected_plan_sha256=plan_hash,
            )


    def test_batch_materializes_one_slot_into_its_own_workspace(self):
        import hashlib
        import json
        import os
        import tempfile
        from datetime import datetime
        from unittest.mock import patch
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        plans = [
            {
                "production_date": today,
                "slot_id": slot_id,
                "title": "A separate slot story",
                "narration_script": "Could music reveal something new? Four sentences make a complete script. Evidence supports the second and third. This final sentence closes the story.",
            }
            for slot_id in ("music-secrets", "production-tech", "melody-stories", "real-performance")
        ]
        batch = {"schema_version": 1, "production_date": today, "plans": plans}

        with tempfile.TemporaryDirectory() as temporary:
            original_cwd = Path.cwd()
            try:
                os.chdir(temporary)
                batch_path = Path(".autopilot/daily-batches") / (today + ".json")
                batch_path.parent.mkdir(parents=True)
                batch_path.write_text(json.dumps(batch), encoding="utf-8")
                batch_hash = hashlib.sha256(batch_path.read_bytes()).hexdigest()
                workspace = Path("work/slots") / today / "melody-stories"
                with patch.dict(os.environ, {"EXPECTED_BATCH_SHA256": batch_hash}):
                    plan_path, returned_hash = daily._materialize_batch_slot(
                        batch_path, "melody-stories", workspace
                    )
                    self.assertEqual(
                        os.environ["EXPECTED_PLAN_SHA256"],
                        hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                    )
                materialized = json.loads(plan_path.read_text(encoding="utf-8"))
                self.assertEqual(returned_hash, batch_hash)
                self.assertEqual(materialized["slot_id"], "melody-stories")
                self.assertEqual(plan_path.parent.parent, workspace.resolve())
                self.assertEqual(
                    len({Path("work/slots") / today / slot for slot in (
                        "music-secrets", "production-tech", "melody-stories", "real-performance"
                    )}),
                    4,
                )
            finally:
                os.chdir(original_cwd)


    def test_batch_materialization_refuses_explicitly_blocked_slot(self):
        import hashlib
        import json
        import os
        import tempfile
        from datetime import datetime
        from unittest.mock import patch
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        plans = [
            {"production_date": today, "slot_id": slot, "title": "Slot",
             "narration_script": "A small test narration with enough tokens."}
            for slot in ("music-secrets", "production-tech", "melody-stories", "real-performance")
        ]
        plans[2] = {
            "production_date": today, "slot_id": "melody-stories",
            "slot_status": "blocked", "blocked_reason": "Independent sources not verified.",
        }
        with tempfile.TemporaryDirectory() as temporary:
            previous = Path.cwd()
            try:
                os.chdir(temporary)
                path = Path("batch.json")
                path.write_text(json.dumps({"production_date": today, "plans": plans}), encoding="utf-8")
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                workspace = Path("work/slots") / today / "melody-stories"
                with patch.dict(os.environ, {"EXPECTED_BATCH_SHA256": digest}):
                    with self.assertRaisesRegex(Exception, "Selected slot is blocked"):
                        daily._materialize_batch_slot(path, "melody-stories", workspace)
            finally:
                os.chdir(previous)

    def test_batch_materialization_rejects_a_changed_snapshot(self):
        import hashlib
        import json
        import os
        import tempfile
        from datetime import datetime
        from unittest.mock import patch
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        plans = [
            {"production_date": today, "slot_id": slot, "title": "Test slot",
             "narration_script": "One two three four five six seven eight nine ten."}
            for slot in ("music-secrets", "production-tech", "melody-stories", "real-performance")
        ]
        with tempfile.TemporaryDirectory() as temporary:
            original_cwd = Path.cwd()
            try:
                os.chdir(temporary)
                batch_path = Path("batch.json")
                batch_path.write_text(json.dumps({"production_date": today, "plans": plans}), encoding="utf-8")
                workspace = Path("work/slots") / today / "music-secrets"
                with patch.dict(os.environ, {"EXPECTED_BATCH_SHA256": "0" * 64}):
                    with self.assertRaisesRegex(Exception, "does not match"):
                        daily._materialize_batch_slot(batch_path, "music-secrets", workspace)
            finally:
                os.chdir(original_cwd)

    def test_workflow_exposes_four_non_cancelling_six_hour_slots(self):
        workflow_path = ENGINE_DIR.parents[1] / ".github" / "workflows" / "violin-prince-autopilot.yml"
        workflow = workflow_path.read_text(encoding="utf-8")
        for cron in ('"0 0 * * *"', '"0 6 * * *"', '"0 12 * * *"', '"0 18 * * *"'):
            self.assertIn(f"- cron: {cron}", workflow)
        self.assertIn("select_public_queue.py", workflow)
        self.assertIn("Select the next unused ready story from the scheduled date's batch", workflow)
        self.assertIn("group: violin-prince-private-preview-queue", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn('PUBLISH_ENABLED: "false"', workflow)

    def test_automatic_production_overrides_any_plan_visibility_to_private(self):
        plan = {
            "title": "Private preview test",
            "publish_metadata": {
                "title": "Private preview test",
                "privacy_status": "public",
                "description": "A test description.",
            },
        }
        result = daily.enforce_private_preview_visibility(plan)
        self.assertEqual(result["privacy_status"], "private")
        self.assertEqual(result["publish_metadata"]["privacy_status"], "private")
        self.assertEqual(result["publish_metadata"]["description"], "A test description.")

    def test_autopilot_trigger_watches_the_daily_plan_and_passes_snapshot_hashes(self):
        workflow_path = ENGINE_DIR.parents[1] / ".github" / "workflows" / "violin-prince-autopilot.yml"
        workflow = workflow_path.read_text(encoding="utf-8")
        self.assertIn('      - ".autopilot/daily-production-plan.json"', workflow)
        self.assertIn("plan_sha256=", workflow)
        self.assertIn("narration_sha256=", workflow)
        self.assertIn("EXPECTED_PLAN_SHA256:", workflow)
        self.assertIn("EXPECTED_NARRATION_SHA256:", workflow)

    def test_narration_contract_requires_exactly_35_words(self):
        script_35 = (
            "Could your room change your violin mix? "
            "Audient adds RoomTune correction to its iD interfaces. "
            "It measures the room and adjusts the signal reaching monitors. "
            "Its DSP runs EQ, compression and reverb with no latency."
        )
        script_36 = script_35 + " Today."
        self.assertEqual(daily.engine.narration_word_count(script_35), 35)
        self.assertEqual(daily.engine.narration_word_count(script_36), 36)
        self.assertEqual(daily.engine.narration_validation_error(script_35), "")
        self.assertIn("exactly 35 are required", daily.engine.narration_validation_error(script_36))

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

    def test_presenter_opt_in_copies_bundle_without_forcing_static_scene_poses(self):
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
            self.assertTrue(all("character_actions" not in scene for scene in result["scenes"]))
            self.assertEqual(
                result["presenter_integration"]["visibility_and_placement"],
                "narration-aware scene director",
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

    def test_checked_in_daily_plan_uses_valid_narration_and_evidence(self):
        import json

        project_root = ENGINE_DIR.parents[1]
        plan_path = project_root / ".autopilot" / "daily-production-plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        script = plan.get("narration_script", "")

        self.assertTrue(plan.get("title"))
        self.assertTrue(script)
        self.assertEqual(daily.engine.narration_word_count(script), 35)
        self.assertEqual(len(daily.engine.narration_sentences(script)), 4)
        self.assertEqual(daily.engine.narration_validation_error(script), "")

        sources = {
            str(item.get("source_id") or "")
            for item in plan.get("sources", [])
            if isinstance(item, dict)
        }
        evidence = plan.get("narration_evidence", [])
        self.assertEqual(
            {int(item.get("sentence_number") or 0) for item in evidence},
            {2, 3, 4},
        )
        self.assertTrue(sources)
        for item in evidence:
            self.assertIn(str(item.get("source_id") or ""), sources)
            self.assertGreaterEqual(len(str(item.get("quote") or "").strip()), 28)


if __name__ == "__main__":
    unittest.main()
