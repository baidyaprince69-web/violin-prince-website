"""Tests for bounded parallel rendering fan-out."""
from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
import sys

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from parallel_render import parallel_map_ordered


class ParallelRenderTests(unittest.TestCase):
    def test_workers_overlap_and_results_keep_input_order(self):
        state_lock = threading.Lock()
        active = 0
        peak_active = 0

        def worker(value):
            nonlocal active, peak_active
            with state_lock:
                active += 1
                peak_active = max(peak_active, active)
            try:
                time.sleep(0.08)
                return value * 10
            finally:
                with state_lock:
                    active -= 1

        result = parallel_map_ordered([1, 2, 3, 4], worker, max_workers=3)
        self.assertEqual(result, [10, 20, 30, 40])
        self.assertGreaterEqual(peak_active, 2)

    def test_worker_count_is_bounded_to_three(self):
        names = set()
        lock = threading.Lock()

        def worker(value):
            with lock:
                names.add(threading.current_thread().name)
            time.sleep(0.03)
            return value

        result = parallel_map_ordered(range(8), worker, max_workers=99)
        self.assertEqual(result, list(range(8)))
        self.assertLessEqual(len(names), 3)

    def test_empty_input_does_not_start_workers(self):
        self.assertEqual(parallel_map_ordered([], lambda value: value), [])

    def test_worker_exception_propagates(self):
        def worker(value):
            if value == 2:
                raise RuntimeError("render failed")
            return value

        with self.assertRaisesRegex(RuntimeError, "render failed"):
            parallel_map_ordered([1, 2, 3], worker, max_workers=3)


if __name__ == "__main__":
    unittest.main()
