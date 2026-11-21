"""Four-slot daily production contract and isolated workspace helpers.

Foundation only: validates a four-plan batch and allocates per-slot paths.
It does not schedule jobs or enable any publisher.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any

SLOT_CATALOG = {
    "music-secrets": "Violin & Music Secrets",
    "production-tech": "Production & Audio Tech",
    "melody-stories": "Melody Stories",
    "real-performance": "Real Violin Performance",
}

class SlotContractError(ValueError):
    """Invalid or incomplete daily slot batch."""

def production_identity(production_date: str, slot_id: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\\d{2}", str(production_date or "")):
        raise SlotContractError("production_date must use YYYY-MM-DD.")
    if slot_id not in SLOT_CATALOG:
        raise SlotContractError(f"Unknown slot_id: {slot_id!r}.")
    return f"{production_date}:{slot_id}"

def slot_workspace(root: str | Path, production_date: str, slot_id: str) -> Path:
    production_identity(production_date, slot_id)
    return Path(root) / production_date / slot_id

def load_daily_batch(path: str | Path, *, expected_date: str | None = None) -> list[dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlotContractError("Daily slot batch is missing or invalid JSON.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("plans"), list):
        raise SlotContractError("Daily slot batch must contain a plans array.")
    plans = payload["plans"]
    if len(plans) != 4:
        raise SlotContractError("Daily slot batch must contain exactly four plans.")
    date = str(payload.get("production_date") or "")
    if expected_date and date != expected_date:
        raise SlotContractError(f"production_date must be {expected_date}.")
    seen: set[str] = set()
    for plan in plans:
        if not isinstance(plan, dict):
            raise SlotContractError("Every slot plan must be a JSON object.")
        slot_id = str(plan.get("slot_id") or "")
        if slot_id not in SLOT_CATALOG:
            raise SlotContractError(f"Unknown slot_id: {slot_id!r}.")
        if slot_id in seen:
            raise SlotContractError(f"Duplicate slot_id: {slot_id}.")
        seen.add(slot_id)
        if str(plan.get("production_date") or "") != date:
            raise SlotContractError(f"Plan {slot_id} does not match the batch production_date.")
        if not str(plan.get("narration_script") or "").strip():
            raise SlotContractError(f"Plan {slot_id} has no narration_script.")
        if not str(plan.get("title") or "").strip():
            raise SlotContractError(f"Plan {slot_id} has no title.")
    missing = set(SLOT_CATALOG) - seen
    if missing:
        raise SlotContractError("Missing slot(s): " + ", ".join(sorted(missing)))
    return sorted(plans, key=lambda item: list(SLOT_CATALOG).index(item["slot_id"]))

def write_slot_receipt(path: str | Path, *, production_date: str, slot_id: str,
                       run_id: str, status: str, output_dir: str | Path) -> dict[str, str]:
    identity = production_identity(production_date, slot_id)
    receipt = {
        "schema_version": "1", "production_date": production_date,
        "slot_id": slot_id, "production_identity": identity,
        "run_id": str(run_id), "status": str(status), "output_dir": str(output_dir),
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt
