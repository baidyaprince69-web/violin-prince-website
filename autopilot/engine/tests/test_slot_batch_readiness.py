from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from daily_readiness import evaluate_daily_batch_readiness
from slot_registry import SLOT_CATALOG

class SlotBatchReadinessTests(unittest.TestCase):
    def _write(self, root: Path, relative: str, text: str) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _root(self, root: Path):
        self._write(root, "autopilot/engine/voiceover.py",
                    "def require_approved_own_voice():\n    return True\n")
        self._write(root, "autopilot/engine/run.py",
                    "def require_approved_illustration_provider():\n    return True\n")
        self._write(root, "autopilot/engine/voice-approval.json",
                    '{"schema_version":1,"status":"approved","provider":"private_qwen3","test_evidence":{"workflow_status":"success","exact_transcript_verified":true,"word_timestamps_verified":true}}')
        self._write(root, "autopilot/engine/illustration-approval.json", json.dumps({
            "schema_version": 1, "status": "approved_for_preview", "provider": "local_vector",
            "scope": "preview_video_only", "renderer_version": "violin-prince-vector-illustrator-v1",
            "publishing_enabled": False,
            "test_evidence": {
                "workflow_run_id": 44524124774, "workflow_status": "success",
                "all_six_modes_passed": True, "story_profile_scenes_passed": True,
                "network_calls": False, "output_width": 1024, "output_height": 1792,
                "output_format": "JPEG",
                "modes": ["comparison", "cover_performance", "macro_illustration",
                          "mechanism_illustration", "melody_map", "waveform"],
            },
        }))

    def _batch(self, date: str):
        return {"production_date": date, "plans": [
            {"production_date": date, "slot_id": slot, "title": SLOT_CATALOG[slot],
             "narration_script": "A sample four-sentence narration for readiness."}
            for slot in SLOT_CATALOG
        ]}

    def test_valid_four_slot_batch_passes_preview_readiness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._root(root)
            self._write(root, ".autopilot/daily-production-batch.json",
                        json.dumps(self._batch("2026-11-22")))
            result = evaluate_daily_batch_readiness(root, today="2026-11-22")
        self.assertTrue(result["ready"], result["blockers"])
        self.assertEqual(result["slot_count"], 4)

    def test_wrong_date_batch_is_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._root(root)
            self._write(root, ".autopilot/daily-production-batch.json",
                        json.dumps(self._batch("2026-11-21")))
            result = evaluate_daily_batch_readiness(root, today="2026-11-22")
        self.assertFalse(result["ready"])
        self.assertTrue(any("production_date" in item for item in result["blockers"]))

if __name__ == "__main__":
    unittest.main()
