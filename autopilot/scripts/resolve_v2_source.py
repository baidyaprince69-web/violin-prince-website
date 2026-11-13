#!/usr/bin/env python3
"""Select a recent successful V2 run whose package artifacts have not expired."""
from __future__ import annotations

import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_ROOT = "https://api.github.com/repos"
V2_WORKFLOW_PATH = ".github/workflows/violin-prince-autopilot.yml"


def github_get_json(repository: str, token: str, resource: str) -> dict:
    """Fetch GitHub REST JSON with one bounded retry for transient API/network errors."""
    url = f"{API_ROOT}/{repository}/{resource.lstrip('/')}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ViolinPrinceV3SourceResolver/1.0",
    }
    for attempt in range(2):
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError("GitHub returned an unexpected non-object JSON response.")
            return payload
        except HTTPError as exc:
            if attempt == 0 and exc.code in (500, 502, 503, 504):
                time.sleep(1)
                continue
            raise RuntimeError(
                f"GitHub API returned HTTP {exc.code} while checking source artifacts."
            ) from exc
        except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            if attempt == 0:
                time.sleep(1)
                continue
            raise RuntimeError(
                "Could not reach GitHub to resolve a valid V2 source package: " + str(exc)[:240]
            ) from exc
    raise RuntimeError("GitHub source lookup did not return a response.")


def _has_required_artifacts(run_id: str, api_get) -> bool:
    payload = api_get(f"actions/runs/{run_id}/artifacts?per_page=100")
    available = {
        str(item.get("name", ""))
        for item in payload.get("artifacts", [])
        if isinstance(item, dict) and item.get("expired") is False
    }
    required = {f"violin-prince-run-{run_id}", "visual-package"}
    return required.issubset(available)


def resolve_source_run_id(
    repository: str,
    token: str,
    requested_run_id: str = "",
    api_get=None,
) -> str:
    """Find a successful V2 run with a complete, unexpired visual package."""
    if api_get is None:
        api_get = lambda resource: github_get_json(repository, token, resource)

    requested = str(requested_run_id or "").strip()
    if requested:
        if not re.fullmatch(r"[0-9]+", requested):
            raise RuntimeError("source_run_id must contain digits only.")
        candidates = [api_get(f"actions/runs/{requested}")]
    else:
        listing = api_get(
            "actions/workflows/violin-prince-autopilot.yml/runs?status=completed&per_page=30"
        )
        candidates = listing.get("workflow_runs", [])

    for run in candidates:
        if not isinstance(run, dict):
            continue
        if run.get("path") != V2_WORKFLOW_PATH:
            continue
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            continue
        run_id = str(run.get("id", ""))
        if not re.fullmatch(r"[0-9]+", run_id):
            continue
        if _has_required_artifacts(run_id, api_get):
            return run_id

    if requested:
        raise RuntimeError(
            f"Requested V2 run {requested} is not a successful run with both "
            "unexpired 'visual-package' and 'violin-prince-run' artifacts."
        )
    raise RuntimeError(
        "No recent successful V2 run with both required, unexpired artifacts was found. "
        "Run the V2 workflow through its Visuals or Full stage, then retry."
    )


def main() -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    token = os.environ.get("GH_TOKEN", "").strip()
    requested = os.environ.get("REQUESTED_SOURCE_RUN_ID", "").strip()
    if not repository or not token:
        raise RuntimeError("GITHUB_REPOSITORY and GH_TOKEN are required for source selection.")

    selected = resolve_source_run_id(repository, token, requested)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"source_run_id={selected}\n")
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as environment:
        environment.write(f"SOURCE_RUN_ID={selected}\n")
    print(
        f"Selected successful V2 source run {selected}; its visual and diagnostic "
        "artifacts are present and have not expired."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"::error::{exc}")
        raise SystemExit(1)
