"""GitHub Copilot CLI adapter for the Master Creative Director.

The adapter accepts a verified story context, requests a shot-led JSON plan
from Copilot CLI, and validates the result before returning it. It deliberately
runs with no usable tools: the model can make creative decisions, but cannot
read or modify the repository, execute shell commands, fetch URLs, or call MCPs.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from master_creative_director import (
    DIRECTOR_CONTRACT_VERSION,
    DirectorPlanError,
    build_director_request,
    require_valid_director_plan,
)


class CopilotDirectorError(RuntimeError):
    """Raised when Copilot cannot produce a valid Master Director plan."""


DEFAULT_TIMEOUT_SECONDS = 600
MAX_PROMPT_CHARACTERS = 60000
MAX_RESPONSE_CHARACTERS = 60000
MAX_AI_CREDITS_PER_RESPONSE = 8


def _decode_director_json(response: str) -> dict[str, Any]:
    """Accept strict JSON or one JSON fenced block; reject prose and extra data."""
    value = str(response or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if len(lines) < 3 or not lines[0].startswith("```") or lines[-1].strip() != "```":
            raise CopilotDirectorError("Copilot returned an incomplete JSON code fence.")
        value = "\n".join(lines[1:-1]).strip()
        if lines[0].strip().casefold() not in {"```", "```json"}:
            raise CopilotDirectorError("Copilot returned an unsupported code-fence format.")

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CopilotDirectorError(
            f"Copilot did not return one strict JSON director plan: {exc.msg} at character {exc.pos}."
        ) from exc
    if not isinstance(parsed, dict):
        raise CopilotDirectorError("Copilot response must be a JSON object.")
    try:
        return require_valid_director_plan(parsed)
    except DirectorPlanError as exc:
        raise CopilotDirectorError(str(exc)) from exc


def generate_director_plan(
    story_context: dict[str, Any],
    *,
    creator_preferences: dict[str, Any] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Ask Copilot CLI to direct one verified story and validate its JSON output.

    Required CI credential: COPILOT_GITHUB_TOKEN, created as a fine-grained
    personal access token with the account-level Copilot Requests permission.
    No repository write permission is needed by this adapter.
    """
    token = os.environ.get("COPILOT_GITHUB_TOKEN", "").strip()
    if not token:
        raise CopilotDirectorError(
            "Master Creative Director is not connected: add the fine-grained Copilot token "
            "as the COPILOT_GITHUB_TOKEN Actions secret."
        )

    executable = shutil.which("copilot")
    if not executable:
        raise CopilotDirectorError(
            "GitHub Copilot CLI is not installed. Install @github/copilot before invoking the director."
        )
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1:
        raise CopilotDirectorError("Copilot timeout must be a positive integer.")

    try:
        request = build_director_request(
            story_context,
            creator_preferences=creator_preferences,
        )
    except DirectorPlanError as exc:
        raise CopilotDirectorError("Story context is not ready for the Master Creative Director: " + str(exc)) from exc

    prompt = (
        request["system"]
        + "\n\n--- VERIFIED STORY INPUT ---\n\n"
        + request["user"]
        + "\n\nReturn only the JSON object. Do not call tools or attempt research."
    )
    if len(prompt) > MAX_PROMPT_CHARACTERS:
        raise CopilotDirectorError(
            f"Director prompt is too large ({len(prompt)} characters; maximum {MAX_PROMPT_CHARACTERS})."
        )

    # A fresh temporary home and working directory prevent repository-specific
    # MCP servers, hooks, plugins, and stored permissions from entering the run.
    # --available-tools=view plus --deny-tool=read leaves no usable tool.
    # Built-in MCP servers are also disabled as a second isolation layer.
    with tempfile.TemporaryDirectory(prefix="violin-prince-copilot-director-") as temporary:
        isolated_home = Path(temporary)
        child_env = os.environ.copy()
        child_env["COPILOT_GITHUB_TOKEN"] = token
        child_env["COPILOT_HOME"] = str(isolated_home / "copilot-home")
        child_env["COPILOT_AUTO_UPDATE"] = "false"
        child_env.pop("GH_TOKEN", None)
        child_env.pop("GITHUB_TOKEN", None)

        command = [
            executable,
            "-p",
            prompt,
            "-s",
            "--model=auto",
            "--max-ai-credits=" + str(MAX_AI_CREDITS_PER_RESPONSE),
            "--available-tools=view",
            "--deny-tool=read,shell,write,url,memory",
            "--disable-builtin-mcps",
            "--disable-client-telemetry",
            "--no-banner",
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=isolated_home,
                env=child_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CopilotDirectorError(
                f"Copilot director request timed out after {timeout_seconds} seconds."
            ) from exc
        except OSError as exc:
            raise CopilotDirectorError("Could not start GitHub Copilot CLI: " + str(exc)) from exc

    stdout = str(completed.stdout or "").strip()
    stderr = str(completed.stderr or "").strip().replace(token, "[REDACTED]")
    if completed.returncode != 0:
        detail = stderr[-1200:] if stderr else "No diagnostic output was returned."
        raise CopilotDirectorError(
            f"GitHub Copilot CLI exited with status {completed.returncode}. "
            "Check Copilot entitlement, monthly AI credits and token permission. "
            + detail
        )
    if not stdout:
        raise CopilotDirectorError("GitHub Copilot CLI returned an empty director response.")
    if len(stdout) > MAX_RESPONSE_CHARACTERS:
        raise CopilotDirectorError(
            f"Copilot director response exceeded {MAX_RESPONSE_CHARACTERS} characters."
        )

    plan = _decode_director_json(stdout)
    plan["_director_provider"] = {
        "provider": "github-copilot-cli",
        "model_selection": "auto",
        "contract_version": DIRECTOR_CONTRACT_VERSION,
        "tool_access": "disabled",
        "response_ai_credit_cap": MAX_AI_CREDITS_PER_RESPONSE,
    }
    return plan


def write_director_plan(plan: dict[str, Any], output_path: str | Path) -> Path:
    """Validate and atomically save the generated plan for downstream renderers."""
    if not isinstance(plan, dict):
        raise CopilotDirectorError("Director plan must be a JSON object.")
    provider = plan.get("_director_provider")
    clean_plan = {key: value for key, value in plan.items() if key != "_director_provider"}
    try:
        require_valid_director_plan(clean_plan)
    except DirectorPlanError as exc:
        raise CopilotDirectorError(str(exc)) from exc

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination
