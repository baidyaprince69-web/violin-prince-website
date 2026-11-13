import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cloudflare_usage_preflight import (
    detect_workers_plan,
    evaluate_headroom,
    sum_neurons,
)


class CloudflareUsagePreflightTests(unittest.TestCase):
    def test_sums_all_time_buckets(self):
        groups = [
            {"sum": {"totalNeurons": 120.5}},
            {"sum": {"totalNeurons": 379.5}},
        ]
        self.assertEqual(sum_neurons(groups), 500.0)

    def test_rejects_truncated_or_malformed_usage(self):
        with self.assertRaises(RuntimeError):
            sum_neurons([{"sum": {}}])

    def test_detects_free_workers_plan(self):
        subscriptions = [{
            "id": "workers-free",
            "rate_plan": {"id": "free", "public_name": "Workers Free"},
            "state": "Provisioned",
        }]
        self.assertEqual(detect_workers_plan(subscriptions), "free")

    def test_detects_paid_workers_plan(self):
        subscriptions = [{
            "id": "workers",
            "rate_plan": {"id": "workers-paid", "public_name": "Workers Paid"},
            "state": "Paid",
        }]
        self.assertEqual(detect_workers_plan(subscriptions), "paid")

    def test_no_active_paid_workers_subscription_means_free_workers_tier(self):
        subscriptions = [{
            "id": "workers",
            "rate_plan": {"id": "workers-paid", "public_name": "Workers Paid"},
            "state": "Cancelled",
        }]
        self.assertEqual(detect_workers_plan(subscriptions), "free")

    def test_unknown_workers_plan_is_not_guessed(self):
        subscriptions = [{
            "id": "workers",
            "rate_plan": {"id": "standard", "public_name": "Workers Standard"},
            "state": "Paid",
        }]
        self.assertEqual(detect_workers_plan(subscriptions), "unknown")

    def test_requires_four_thousand_neuron_reserve(self):
        safe = evaluate_headroom("free", today=5900, rolling24h=5700)
        blocked = evaluate_headroom("paid", today=6100, rolling24h=5900)
        self.assertTrue(safe["safe_to_start"])
        self.assertGreaterEqual(safe["estimated_remaining_before_test"], 4000)
        self.assertFalse(blocked["safe_to_start"])

    def test_unknown_plan_fails_closed(self):
        self.assertFalse(evaluate_headroom("unknown", 100, 100)["safe_to_start"])


if __name__ == "__main__":
    unittest.main()
