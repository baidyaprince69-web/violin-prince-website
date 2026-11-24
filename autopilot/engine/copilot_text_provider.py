"""Isolated GitHub Copilot text-planning adapter for Violin Prince research.

The model receives only the verified research text assembled by run.py. It has
no repository, shell, web, MCP or write tools; publisher discovery and article
verification remain deterministic Python/network code in the runner.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class CopilotTextProviderError(RuntimeError):
    """Raised when the text planner cannot safely return a structured result."""


DEFAULT_TIMEOUT_SECONDS = 180
MAX_PROMPT_CHARACTERS = 60000
MAX_RESPONSE_CHARACTERS = 30000
MAX_AI_CREDITS_PER_RESPONSE = 8


def build_prompt(payload: dict[str, Any]) -> str:
    """Convert the existing chat-completions payload into a strict JSON-only CLI prompt."""
    if not isinstance(payload, dict):
        raise CopilotTextProviderError("Text-planning payload must be an object.")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise CopilotTextProviderError("Text-planning payload must contain messages.")

    system_parts: list[str] = []
    conversation_parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip().upper()
        content = message.get("content")
        if isinstance(content, list):
            content = "\n".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        text = str(content or "").strip()
        if not text:
            continue
        if role == "SYSTEM":
            system_parts.append(text)
        else:
            conversation_parts.append(f"{role}:\n{text}")

    if not conversation_parts:
        raise CopilotTextProviderError("Text-planning payload has no user content.")

    tools = payload.get("tools") or []
    tool_instruction = ""
    if tools:
        if not isinstance(tools, list) or len(tools) != 1:
            raise CopilotTextProviderError("Only one strict function schema is supported for narration correction.")
        tool = tools[0]
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict):
            raise CopilotTextProviderError("Narration correction function schema is malformed.")
        name = str(function.get("name") or "").strip()
        parameters = function.get("parameters")
        if not name or not isinstance(parameters, dict):
            raise CopilotTextProviderError("Narration correction requires a named JSON schema.")
        tool_instruction = (
            "\n\nSTRUCTURED OUTPUT CONTRACT\n"
            "The original application requested this function call: " + name + ".\n"
            "Return the function arguments as one JSON object only. Do not return a tool-call wrapper, "
            "Markdown, code fence, explanation or additional keys. The JSON object must conform exactly "
            "to this schema:\n" + json.dumps(parameters, ensure_ascii=False, separators=(",", ":"))
        )

    prompt = (
        "\n\n".join(system_parts)
        + "\n\n--- REQUEST ---\n\n"
        + "\n\n".join(conversation_parts)
        + tool_instruction
        + "\n\nReturn exactly one JSON object. Do not use tools, browse, access files, "
        "invent sources, add unsupported factual claims, or include private reasoning."
    )
    if len(prompt) > MAX_PROMPT_CHARACTERS:
        raise CopilotTextProviderError(
            f"Text-planning prompt exceeds {MAX_PROMPT_CHARACTERS} characters."
        )
    return prompt


def generate_text_completion(
    payload: dict[str, Any],
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Run Copilot CLI in a clean temporary home with no usable tools."""
    token = os.environ.get("COPILOT_GITHUB_TOKEN", "").strip()
    if not token:
        raise CopilotTextProviderError(
            "Live story planning is not connected: configure COPILOT_GITHUB_TOKEN "
            "as a repository Actions secret."
        )
    executable = shutil.which("copilot")
    if not executable:
        raise CopilotTextProviderError(
            "GitHub Copilot CLI is not installed in this runner."
        )
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1:
        raise CopilotTextProviderError("Text-planning timeout must be a positive integer.")

    prompt = build_prompt(payload)
    with tempfile.TemporaryDirectory(prefix="violin-prince-copilot-text-") as temporary:
        isolated_home = Path(temporary)
        child_env = os.environ.copy()
        child_env["COPILOT_GITHUB_TOKEN"] = token
        child_env["COPILOT_HOME"] = str(isolated_home / "copilot-home")
        child_env["COPILOT_AUTO_UPDATE"] = "false"
        child_env.pop("GH_TOKEN", None)
        child_env.pop("GITHUB_TOKEN", None)
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
            raise CopilotTextProviderError(
                f"GitHub Copilot text planning timed out after {timeout_seconds} seconds."
            ) from exc
        except OSError as exc:
            raise CopilotTextProviderError("Could not start GitHub Copilot CLI: " + str(exc)) from exc

    stdout = str(completed.stdout or "").strip()
    stderr = str(completed.stderr or "").strip().replace(token, "[REDACTED]")
    if completed.returncode != 0:
        detail = stderr[-1000:] if stderr else "No diagnostic output was returned."
        raise CopilotTextProviderError(
            f"GitHub Copilot text planner exited with status {completed.returncode}. "
            "Check Copilot Requests permission, entitlement and available AI credits. " + detail
        )
    if not stdout:
        raise CopilotTextProviderError("GitHub Copilot text planner returned an empty response.")
    if len(stdout) > MAX_RESPONSE_CHARACTERS:
        raise CopilotTextProviderError(
            f"GitHub Copilot text response exceeded {MAX_RESPONSE_CHARACTERS} characters."
        )

    # The planner's downstream parser tolerates one JSON object preceded by prose;
    # narration correction requires a strict JSON arguments object.
    stripped = stdout.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            if lines[0].strip().casefold() not in {"```", "```json"}:
                raise CopilotTextProviderError("Copilot returned an unsupported code fence.")
            stripped = "\n".join(lines[1:-1]).strip()
    try:
        json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise CopilotTextProviderError(
            f"Copilot must return exactly one JSON object; received {exc.msg} at character {exc.pos}."
        ) from exc
    if not isinstance(json.loads(stripped), dict):
        raise CopilotTextProviderError("Copilot text response must be a JSON object.")
    return stripped
