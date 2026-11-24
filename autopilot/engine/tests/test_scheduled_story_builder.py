"""Offline tests for per-cron live research commissioning and no-repeat claims."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run as engine  # noqa: E402
from scheduled_story_builder import (  # noqa: E402
    SLOT_STORY_TYPES,
    _empty_batch,
    build_scheduled_batch,
)


class ScheduledStoryBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.now = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
        self.saved_work = engine.WORK
        self.saved_out = engine.OUT
        self.saved_images = engine.IMAGES

    def tearDown(self):
        engine.WORK = self.saved_work
        engine.OUT = self.saved_out
        engine.IMAGES = self.saved_images
        self.temporary.cleanup()

    def _write_batch(self, production_date="2026-11-24"):
        path = self.root / ".autopilot" / "daily-batches" / f"{production_date}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_empty_batch(production_date), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def test_empty_batch_has_exactly_the_four_canonical_blocked_slots(self):
        batch = _empty_batch("2026-11-24")
        self.assertEqual(
            [plan["slot_id"] for plan in batch["plans"]],
            ["music-secrets", "production-tech", "melody-stories", "real-performance"],
        )
        self.assertEqual(len(batch["plans"]), 4)
        self.assertTrue(all(plan["slot_status"] == "blocked" for plan in batch["plans"]))
        self.assertEqual(
            SLOT_STORY_TYPES["production-tech"],
            ("music_production", "music_technology"),
        )

    def test_existing_attempt_is_terminal_and_does_not_repeat_research(self):
        attempt = self.root / ".autopilot" / "public-youtube-attempts" / "2026-11-24-melody-stories.json"
        attempt.parent.mkdir(parents=True)
        attempt.write_text(json.dumps({"status": "attempting"}), encoding="utf-8")
        with patch.object(engine, "research") as research:
            result = build_scheduled_batch(
                self.root,
                production_date="2026-11-24",
                slot_id="melody-stories",
                now=self.now,
                dry_run=True,
            )
        self.assertEqual(result["status"], "terminal")
        research.assert_not_called()

    def test_existing_ready_plan_is_reused_without_research(self):
        path = self._write_batch()
        payload = json.loads(path.read_text(encoding="utf-8"))
        plan = next(item for item in payload["plans"] if item["slot_id"] == "melody-stories")
        plan.update({
            "slot_status": "ready",
            "title": "A distinct melody story",
            "narration_script": "Four sentence placeholder for a previously prepared story.",
        })
        path.write_text(json.dumps(payload), encoding="utf-8")
        with patch.object(engine, "research") as research:
            result = build_scheduled_batch(
                self.root,
                production_date="2026-11-24",
                slot_id="melody-stories",
                now=self.now,
                dry_run=True,
            )
        self.assertEqual(result["status"], "reused_existing_ready_plan")
        research.assert_not_called()

    def test_existing_research_claim_requires_reconciliation_not_research(self):
        self._write_batch()
        history = self.root / ".autopilot" / "research-history" / "2026-11-24-production-tech.json"
        history.parent.mkdir(parents=True)
        history.write_text(
            json.dumps({"status": "researching", "research_identity": "2026-11-24-production-tech"}),
            encoding="utf-8",
        )
        with patch.object(engine, "research") as research:
            result = build_scheduled_batch(
                self.root,
                production_date="2026-11-24",
                slot_id="production-tech",
                now=self.now,
                dry_run=True,
            )
        self.assertEqual(result["status"], "reconciliation_required")
        research.assert_not_called()

    def test_failed_research_is_saved_as_a_blocked_slot_and_history(self):
        with patch.object(engine, "all_researched_topics", return_value=[]),              patch.object(engine, "research", return_value=[]),              patch.object(engine, "discover_source_first_story_groups", return_value=[]):
            result = build_scheduled_batch(
                self.root,
                production_date="2026-11-24",
                slot_id="music-secrets",
                now=self.now,
                dry_run=True,
            )

        self.assertEqual(result["status"], "blocked")
        batch = json.loads(
            (self.root / ".autopilot" / "daily-batches" / "2026-11-24.json").read_text(encoding="utf-8")
        )
        selected = next(plan for plan in batch["plans"] if plan["slot_id"] == "music-secrets")
        self.assertEqual(selected["slot_status"], "blocked")
        self.assertIn("two independent", selected["blocked_reason"])
        history = json.loads(
            (self.root / ".autopilot" / "research-history" / "2026-11-24-music-secrets.json").read_text(encoding="utf-8")
        )
        self.assertEqual(history["status"], "blocked")
        self.assertIn("research_identity", history)


    def test_previously_researched_article_headlines_are_skipped_and_recorded(self):
        with patch.object(engine, "all_researched_topics", return_value=["Violin bridge resonance and tone"]), \\
             patch.object(engine, "research", return_value=[{
                 "title": "Violin bridge resonance and tone explained",
                 "url": "https://example.org/bridge",
                 "publisher_domain": "example.org",
             }]), \\
             patch.object(engine, "discover_source_first_story_groups", return_value=[]) as discover:
            result = build_scheduled_batch(
                self.root,
                production_date="2026-11-24",
                slot_id="music-secrets",
                now=self.now,
                dry_run=True,
            )

        self.assertEqual(result["status"], "blocked")
        discover.assert_called_once_with([], max_seed_queries=3, max_phrases=4, as_of=self.now)
        history = json.loads(
            (self.root / ".autopilot" / "research-history" / "2026-11-24-music-secrets.json").read_text(encoding="utf-8")
        )
        self.assertEqual(history["skipped_repeat_research_items"], ["Violin bridge resonance and tone explained"])
        self.assertEqual(history["eligible_research_record_count"], 0)
    def test_real_performance_refuses_to_substitute_sampled_audio_for_missing_creator_recording(self):
        self._write_batch()
        missing_recording = self.root / "not-present.wav"
        with patch.dict(os.environ, {"VIOLIN_RECORDING_PATH": str(missing_recording)}),              patch.object(engine, "all_researched_topics", return_value=[]),              patch.object(engine, "research", return_value=[{"title": "A violin performance technique"}]),              patch.object(engine, "discover_source_first_story_groups", return_value=[{
                 "group_id": "PERFORMANCE-TEST",
                 "topic_hint": "A violin performance technique",
                 "source_ids": ["S001", "S002"],
                 "publisher_families": ["publisher-one", "publisher-two"],
                 "sources": [],
             }]):
            result = build_scheduled_batch(
                self.root,
                production_date="2026-11-24",
                slot_id="real-performance",
                now=self.now,
                dry_run=True,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertIn("actual creator-recorded violin WAV", result["blocked_reason"])
        batch = json.loads(
            (self.root / ".autopilot" / "daily-batches" / "2026-11-24.json").read_text(encoding="utf-8")
        )
        selected = next(plan for plan in batch["plans"] if plan["slot_id"] == "real-performance")
        self.assertEqual(selected["slot_status"], "blocked")


if __name__ == "__main__":
    unittest.main()
