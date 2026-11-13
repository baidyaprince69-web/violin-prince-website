"""Offline regression tests for resolving a valid, non-expired V2 artifact source."""
import importlib.util
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
SCRIPT = ENGINE.parent / "scripts" / "resolve_v2_source.py"
SPEC = importlib.util.spec_from_file_location("resolve_v2_source", SCRIPT)
resolver = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(resolver)


def run_record(run_id, *, conclusion="success", status="completed", path=None):
    return {
        "id": run_id,
        "status": status,
        "conclusion": conclusion,
        "path": path or resolver.V2_WORKFLOW_PATH,
    }


def artifact(name, expired=False):
    return {"name": name, "expired": expired}


class SourceArtifactSelectionTests(unittest.TestCase):
    def test_auto_selection_paginates_past_recent_runs_without_valid_packages(self):
        first_page = [
            run_record(run_id, conclusion="failure")
            for run_id in range(500, 550)
        ]
        data = {
            "actions/workflows/violin-prince-autopilot.yml/runs?status=completed&per_page=50&page=1": {
                "workflow_runs": first_page
            },
            "actions/workflows/violin-prince-autopilot.yml/runs?status=completed&per_page=50&page=2": {
                "workflow_runs": [run_record(499)]
            },
            "actions/runs/499/artifacts?per_page=100": {
                "artifacts": [
                    artifact("violin-prince-run-499"),
                    artifact("visual-package"),
                ]
            },
        }
        self.assertEqual(
            resolver.resolve_source_run_id(
                "owner/repo", "token", api_get=lambda path: data[path]
            ),
            "499",
        )

    def test_auto_selection_skips_prepare_only_run_and_uses_latest_visual_package(self):
        data = {
            "actions/workflows/violin-prince-autopilot.yml/runs?status=completed&per_page=50&page=1": {
                "workflow_runs": [run_record(300), run_record(299)]
            },
            "actions/runs/300/artifacts?per_page=100": {
                "artifacts": [artifact("violin-prince-run-300")]
            },
            "actions/runs/299/artifacts?per_page=100": {
                "artifacts": [
                    artifact("violin-prince-run-299"),
                    artifact("visual-package"),
                ]
            },
        }
        selected = resolver.resolve_source_run_id(
            "owner/repo", "token", api_get=lambda path: data[path]
        )
        self.assertEqual(selected, "299")

    def test_expired_artifacts_are_not_selected(self):
        data = {
            "actions/workflows/violin-prince-autopilot.yml/runs?status=completed&per_page=50&page=1": {
                "workflow_runs": [run_record(200)]
            },
            "actions/runs/200/artifacts?per_page=100": {
                "artifacts": [
                    artifact("violin-prince-run-200"),
                    artifact("visual-package", expired=True),
                ]
            },
        }
        with self.assertRaisesRegex(RuntimeError, "No recent successful V2 run"):
            resolver.resolve_source_run_id(
                "owner/repo", "token", api_get=lambda path: data[path]
            )

    def test_manual_run_id_is_accepted_only_with_both_unexpired_artifacts(self):
        data = {
            "actions/runs/123": run_record(123),
            "actions/runs/123/artifacts?per_page=100": {
                "artifacts": [
                    artifact("violin-prince-run-123"),
                    artifact("visual-package"),
                ]
            },
        }
        self.assertEqual(
            resolver.resolve_source_run_id(
                "owner/repo", "token", "123", api_get=lambda path: data[path]
            ),
            "123",
        )

    def test_manual_run_id_rejects_failed_or_wrong_workflow_runs(self):
        for record in (
            run_record(123, conclusion="failure"),
            run_record(123, path=".github/workflows/other.yml"),
        ):
            with self.subTest(record=record):
                with self.assertRaisesRegex(RuntimeError, "Requested V2 run 123"):
                    resolver.resolve_source_run_id(
                        "owner/repo", "token", "123", api_get=lambda _path: record
                    )

    def test_manual_run_id_rejects_non_numeric_input_without_api_call(self):
        with self.assertRaisesRegex(RuntimeError, "digits only"):
            resolver.resolve_source_run_id(
                "owner/repo", "token", "../main",
                api_get=lambda _path: self.fail("API must not be called")
            )


if __name__ == "__main__":
    unittest.main()
