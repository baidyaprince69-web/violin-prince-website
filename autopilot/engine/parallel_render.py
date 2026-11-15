"""Bounded, deterministic-order fan-out for independent media-render jobs."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def parallel_map_ordered(
    items: Iterable[T],
    worker: Callable[[T], R],
    *,
    max_workers: int = 3,
) -> list[R]:
    """Run independent jobs concurrently and return results in input order.

    Exceptions are propagated to the caller. The worker limit is bounded by the
    number of items, so small storyboards do not allocate idle threads.
    """
    values = list(items)
    if not values:
        return []
    try:
        requested = int(max_workers)
    except (TypeError, ValueError):
        requested = 1
    worker_count = max(1, min(len(values), requested, 3))
    results: list[R | None] = [None] * len(values)
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="violin-prince-render",
    ) as pool:
        futures = {
            pool.submit(worker, value): index
            for index, value in enumerate(values)
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return [value for value in results if value is not None]
