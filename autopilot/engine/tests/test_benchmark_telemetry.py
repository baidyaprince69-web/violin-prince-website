"""Tests for privacy-safe benchmark telemetry helpers."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from benchmark_telemetry import capture_host_diagnostics, process_snapshot, write_json_atomic


class BenchmarkTelemetryTests(unittest.TestCase):
    def test_json_writer_atomically_creates_readable_json(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "nested" / "report.json"
            write_json_atomic(path, {"status": "ok", "frames": [1, 2]})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {
                "status": "ok",
                "frames": [1, 2],
            })
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_host_capture_includes_hardware_but_excludes_unlisted_secrets(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "host-diagnostics.json"
            with patch.dict(os.environ, {
                "SKETCHFAB_ACCESS_TOKEN": "do-not-write-this",
                "BLENDER_RENDER_WORKERS": "3",
                "LP_NUM_THREADS": "1",
            }, clear=False):
                payload = capture_host_diagnostics(target)
            self.assertIn("cpu_count_os", payload["hardware"])
            self.assertIn("memory_total", payload["hardware"])
            self.assertIn("cgroup", payload["hardware"])
            self.assertEqual(payload["environment"]["BLENDER_RENDER_WORKERS"], "3")
            self.assertNotIn("SKETCHFAB_ACCESS_TOKEN", payload["environment"])
            saved = target.read_text(encoding="utf-8")
            self.assertNotIn("do-not-write-this", saved)

    def test_process_snapshot_returns_non_secret_runtime_resource_fields(self):
        result = process_snapshot()
        self.assertIn("pid", result)
        self.assertIn("cpu_count_os", result)
        self.assertIsInstance(result["pid"], int)


if __name__ == "__main__":
    unittest.main()
