#!/usr/bin/env python3
"""Read-only Cloudflare billing-plan and Workers AI usage preflight.

This script must run before any Workers AI inference in a fresh-visual test.
It fails closed if account plan or usage headroom cannot be verified.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

API_ROOT = "https://api.cloudflare.com/client/v4"
GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"
FREE_NEURON_ALLOWANCE = 10_000
REQUIRED_RESERVE_NEURONS = 4_000
MAX_OBSERVED_USAGE_NEURONS = FREE_NEURON_ALLOWANCE - REQUIRED_RESERVE_NEURONS
GRAPHQL_GROUP_LIMIT = 1_000
TIMEOUT_SECONDS = 30

USAGE_QUERY = """
query WorkersAIUsagePreflight(
  $accountTag: string!,
  $todayStart: string!,
  $rollingStart: string!,
  $now: string!
) {
  viewer {
    accounts(filter: {accountTag: $accountTag}) {
      today: aiInferenceAdaptiveGroups(
        limit: 1000,
        filter: {datetime_geq: $todayStart, datetime_leq: $now}
      ) {
        dimensions { datetimeFifteenMinutes }
        sum { totalNeurons }
      }
      rolling24h: aiInferenceAdaptiveGroups(
        limit: 1000,
        filter: {datetime_geq: $rollingStart, datetime_leq: $now}
      ) {
        dimensions { datetimeFifteenMinutes }
        sum { totalNeurons }
      }
    }
  }
}
"""


class PreflightError(RuntimeError):
    """Raised when Cloudflare account plan or usage cannot be verified safely."""


def _active_subscription(subscription: dict[str, Any]) -> bool:
    state = str(subscription.get("state") or "").casefold()
    return state not in {"cancelled", "expired", "failed"}


def detect_workers_plan(subscriptions: list[dict[str, Any]]) -> str:
    """Return 'free', 'paid', or 'unknown' based on active Workers subscriptions."""
    workers_rows = []
    for item in subscriptions:
        if not isinstance(item, dict) or not _active_subscription(item):
            continue
        rate_plan = item.get("rate_plan") or {}
        sets = item.get("sets") or []
        text = " ".join(
            str(value or "")
            for value in (
                item.get("id"),
                item.get("name"),
                item.get("product"),
                item.get("scope"),
                rate_plan.get("id") if isinstance(rate_plan, dict) else "",
                rate_plan.get("public_name") if isinstance(rate_plan, dict) else "",
                " ".join(str(value) for value in sets) if isinstance(sets, list) else sets,
            )
        ).casefold()
        if "worker" in text:
            workers_rows.append(text)

    if not workers_rows:
        # The subscriptions endpoint was successfully queried. No active
        # Workers Paid subscription means the account has no paid Workers add-on.
        return "free"

    if any("paid" in row for row in workers_rows):
        return "paid"
    if any("free" in row for row in workers_rows):
        return "free"
    return "unknown"


def sum_neurons(groups: list[dict[str, Any]]) -> float:
    """Sum all sampled time buckets; refuse silently truncated results."""
    if not isinstance(groups, list):
        raise PreflightError("Cloudflare returned an invalid AI usage dataset.")
    if len(groups) >= GRAPHQL_GROUP_LIMIT:
        raise PreflightError("Cloudflare AI usage results hit the query limit; refusing an incomplete usage total.")
    total = 0.0
    for group in groups:
        if not isinstance(group, dict):
            raise PreflightError("Cloudflare returned a malformed AI usage group.")
        values = group.get("sum")
        if not isinstance(values, dict) or values.get("totalNeurons") is None:
            raise PreflightError("Cloudflare AI usage response omitted totalNeurons.")
        try:
            value = float(values["totalNeurons"])
        except (TypeError, ValueError) as exc:
            raise PreflightError("Cloudflare returned a non-numeric Neuron total.") from exc
        if value < 0:
            raise PreflightError("Cloudflare returned a negative Neuron total.")
        total += value
    return total


def evaluate_headroom(plan: str, today: float, rolling24h: float) -> dict[str, Any]:
    observed = max(today, rolling24h)
    remaining = max(0.0, FREE_NEURON_ALLOWANCE - observed)
    safe = (
        plan in {"free", "paid"}
        and observed <= MAX_OBSERVED_USAGE_NEURONS
        and remaining >= REQUIRED_RESERVE_NEURONS
    )
    return {
        "workers_plan": plan,
        "free_neuron_allowance": FREE_NEURON_ALLOWANCE,
        "observed_neurons_utc_day": round(today, 2),
        "observed_neurons_rolling_24h": round(rolling24h, 2),
        "conservative_observed_usage": round(observed, 2),
        "estimated_remaining_before_test": round(remaining, 2),
        "required_reserve_neurons": REQUIRED_RESERVE_NEURONS,
        "max_observed_usage_to_start": MAX_OBSERVED_USAGE_NEURONS,
        "safe_to_start": safe,
    }


def _cloudflare_json(response: requests.Response, purpose: str) -> dict[str, Any]:
    if not response.ok:
        if response.status_code in (401, 403):
            raise PreflightError(
                f"Cloudflare denied the read-only {purpose} check (HTTP {response.status_code}). "
                "A token with the required read permission is needed; no AI generation was attempted."
            )
        raise PreflightError(f"Cloudflare {purpose} check failed with HTTP {response.status_code}.")
    try:
        body = response.json()
    except ValueError as exc:
        raise PreflightError(f"Cloudflare {purpose} check returned invalid JSON.") from exc
    if not isinstance(body, dict):
        raise PreflightError(f"Cloudflare {purpose} check returned an unexpected response.")
    return body


def fetch_workers_plan(account_id: str, token: str) -> tuple[str, list[dict[str, Any]]]:
    response = requests.get(
        f"{API_ROOT}/accounts/{account_id}/subscriptions",
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT_SECONDS,
    )
    body = _cloudflare_json(response, "subscription/Billing Read")
    if body.get("success") is not True or not isinstance(body.get("result"), list):
        raise PreflightError("Cloudflare did not return a readable account subscription list.")
    subscriptions = body["result"]
    plan = detect_workers_plan(subscriptions)
    if plan == "unknown":
        raise PreflightError("A Workers subscription was found, but its Free/Paid tier could not be identified.")
    return plan, subscriptions


def fetch_neuron_usage(
    account_id: str,
    token: str,
    now: datetime | None = None,
) -> tuple[float, float, dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rolling_start = now - timedelta(hours=24)
    variables = {
        "accountTag": account_id,
        "todayStart": today_start.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "rollingStart": rolling_start.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "now": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    response = requests.post(
        GRAPHQL_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"query": USAGE_QUERY, "variables": variables},
        timeout=TIMEOUT_SECONDS,
    )
    body = _cloudflare_json(response, "Workers AI Account Analytics Read")
    errors = body.get("errors") or []
    if errors:
        raise PreflightError(
            "Cloudflare rejected the Workers AI Neuron analytics query. "
            "A token with Account Analytics Read permission is required; no AI generation was attempted."
        )
    data = body.get("data")
    accounts = data.get("viewer", {}).get("accounts") if isinstance(data, dict) else None
    if not isinstance(accounts, list) or len(accounts) != 1:
        raise PreflightError("Cloudflare did not return exactly one matching account for Neuron usage.")
    account = accounts[0]
    today_groups = account.get("today")
    rolling_groups = account.get("rolling24h")
    today = sum_neurons(today_groups)
    rolling = sum_neurons(rolling_groups)
    details = {
        "usage_source": "Cloudflare GraphQL aiInferenceAdaptiveGroups",
        "query_window_utc_day_start": variables["todayStart"],
        "query_window_rolling_24h_start": variables["rollingStart"],
        "query_window_end": variables["now"],
        "today_group_count": len(today_groups),
        "rolling_24h_group_count": len(rolling_groups),
        "usage_note": (
            "GraphQL AI inference analytics are an observed usage estimate, not a guaranteed real-time billing meter. "
            "The gate therefore requires a 4,000-Neuron reserve and checks both UTC-day and rolling-24-hour windows."
        ),
    }
    return today, rolling, details


def run_preflight(account_id: str, analytics_token: str, billing_token: str) -> dict[str, Any]:
    if not account_id.strip():
        raise PreflightError("CF_ACCOUNT_ID is missing.")
    if not analytics_token.strip():
        raise PreflightError("A Cloudflare token is required for Account Analytics Read.")
    if not billing_token.strip():
        raise PreflightError("A Cloudflare token is required for Billing Read.")

    plan, subscriptions = fetch_workers_plan(account_id.strip(), billing_token.strip())
    today, rolling, details = fetch_neuron_usage(account_id.strip(), analytics_token.strip())
    decision = evaluate_headroom(plan, today, rolling)
    active_workers_subscriptions = []
    for item in subscriptions:
        if isinstance(item, dict) and _active_subscription(item):
            rate_plan = item.get("rate_plan") or {}
            descriptor = " ".join(
                str(value or "")
                for value in (
                    item.get("id"),
                    rate_plan.get("id") if isinstance(rate_plan, dict) else "",
                    rate_plan.get("public_name") if isinstance(rate_plan, dict) else "",
                    item.get("scope"),
                )
            )
            if "worker" in descriptor.casefold():
                active_workers_subscriptions.append(descriptor[:180])
    return {
        "schema_version": 1,
        "status": "passed" if decision["safe_to_start"] else "blocked",
        "account_plan_status": decision["workers_plan"],
        "active_workers_subscriptions": active_workers_subscriptions,
        **decision,
        **details,
        "ai_generation_attempted": False,
        "publishing_enabled": False,
        "production_renderer_changed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="work/output/motion-prototype/cloudflare-usage-preflight.json")
    args = parser.parse_args()

    account_id = os.environ.get("CF_ACCOUNT_ID", "")
    ai_token = os.environ.get("CF_AI_TOKEN", "")
    analytics_token = os.environ.get("CF_ANALYTICS_TOKEN", "") or ai_token
    billing_token = os.environ.get("CF_BILLING_TOKEN", "") or ai_token

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        report = run_preflight(account_id, analytics_token, billing_token)
        if not report["safe_to_start"]:
            report["status"] = "blocked"
            report["block_reason"] = (
                "Observed usage leaves less than the required 4,000-Neuron reserve, "
                "or the Workers plan could not be verified."
            )
            raise PreflightError(report["block_reason"])
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({
            "status": report["status"],
            "workers_plan": report["workers_plan"],
            "observed_neurons_utc_day": report["observed_neurons_utc_day"],
            "observed_neurons_rolling_24h": report["observed_neurons_rolling_24h"],
            "estimated_remaining_before_test": report["estimated_remaining_before_test"],
            "required_reserve_neurons": report["required_reserve_neurons"],
            "ai_generation_attempted": False,
        }, indent=2))
        return 0
    except (PreflightError, requests.RequestException) as exc:
        failure = {
            "schema_version": 1,
            "status": "blocked",
            "account_plan_status": "unknown",
            "safe_to_start": False,
            "ai_generation_attempted": False,
            "publishing_enabled": False,
            "production_renderer_changed": False,
            "block_reason": str(exc),
        }
        report_path.write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"::error::{exc}")
        print(json.dumps(failure, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
