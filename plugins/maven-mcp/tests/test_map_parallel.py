"""Tests for the ``_map_parallel`` bounded fan-out helper (#400/#402).

Import discipline: use ``import unittest.mock`` and fully-qualified refs
(``unittest.mock.patch``, ``unittest.mock.MagicMock``, etc.) throughout.
No ``from unittest import ...`` or ``from unittest.mock import ...`` — CodeQL
py/import-and-import-from blocks mixed-import patterns.

These tests exercise ``server._map_parallel`` directly (not through a tool
handler) so the concurrency contract itself — index-mapped ordering, bounded
worker count, per-item isolation, deadline-triggered partial results, and the
zero/one-item fast paths — is pinned independently of any single handler's
business logic. Handler-level order-preservation regressions are covered
separately in test_handlers.py / test_verify_coordinates.py / test_license.py.
"""

import threading
import time
import unittest
import unittest.mock

from _helpers import server


class MapParallelBasicsTest(unittest.TestCase):
    def test_empty_items_returns_empty(self):
        results, partial = server._map_parallel([], lambda x: x)
        self.assertEqual(results, [])
        self.assertFalse(partial)

    def test_single_item_skips_executor(self):
        # The single-item fast path must not spin up a ThreadPoolExecutor at
        # all — patch it to raise if constructed, proving the shortcut fires.
        with unittest.mock.patch.object(
            server.concurrent.futures, "ThreadPoolExecutor",
            side_effect=AssertionError("executor must not be created for len(items) <= 1"),
        ):
            results, partial = server._map_parallel(["only"], lambda x: x.upper())
        self.assertEqual(results, ["ONLY"])
        self.assertFalse(partial)

    def test_preserves_input_order_regardless_of_completion_order(self):
        # item 0 sleeps far longer than item 1 -- if results were assembled in
        # COMPLETION order instead of being index-mapped to the input, this
        # would come back reversed.
        def fn(item):
            delay, value = item
            time.sleep(delay)
            return value

        items = [(0.1, "slow"), (0.0, "fast")]
        results, partial = server._map_parallel(items, fn, max_workers=2)
        self.assertEqual(results, ["slow", "fast"])
        self.assertFalse(partial)

    def test_runs_on_more_than_one_thread(self):
        seen_threads = set()
        lock = threading.Lock()

        def fn(item):
            with lock:
                seen_threads.add(threading.get_ident())
            time.sleep(0.02)  # hold the thread briefly so workers overlap
            return item * 2

        results, partial = server._map_parallel(list(range(8)), fn, max_workers=4)
        self.assertEqual(results, [i * 2 for i in range(8)])
        self.assertFalse(partial)
        self.assertGreater(len(seen_threads), 1, "expected more than one worker thread")

    def test_max_workers_bounds_concurrency(self):
        # Track the PEAK number of concurrently-running fn() calls and assert
        # it never exceeds max_workers, proving the executor is actually
        # bounded rather than spawning one thread per item.
        lock = threading.Lock()
        state = {"current": 0, "peak": 0}

        def fn(item):
            with lock:
                state["current"] += 1
                state["peak"] = max(state["peak"], state["current"])
            time.sleep(0.03)
            with lock:
                state["current"] -= 1
            return item

        results, partial = server._map_parallel(list(range(12)), fn, max_workers=3)
        self.assertEqual(results, list(range(12)))
        self.assertFalse(partial)
        self.assertLessEqual(state["peak"], 3)
        self.assertGreater(state["peak"], 1)  # actually overlapped, not accidentally serial

    def test_per_item_error_shaped_fn_isolates_failures(self):
        # Mirrors the real call-site contract: fn catches its OWN exceptions
        # and returns an error-shaped result, so one bad item never fails the
        # batch.
        def fn(item):
            try:
                if item == 2:
                    raise ValueError("boom")
                return {"item": item}
            except Exception as e:
                return {"item": item, "error": str(e)}

        results, partial = server._map_parallel([0, 1, 2, 3], fn, max_workers=2)
        self.assertFalse(partial)
        self.assertEqual(results[0], {"item": 0})
        self.assertEqual(results[2], {"item": 2, "error": "boom"})
        self.assertEqual(results[3], {"item": 3})

    def test_uncaught_exception_propagates(self):
        # fn WITHOUT its own try/except -- an uncaught exception must
        # propagate out of _map_parallel (matching what an equivalent
        # sequential loop with no try/except would do), not be silently
        # swallowed.
        def fn(item):
            if item == 1:
                raise ValueError("boom")
            return item

        with self.assertRaises(ValueError):
            server._map_parallel([0, 1, 2], fn, max_workers=2)


class MapParallelDeadlineTest(unittest.TestCase):
    def test_deadline_returns_partial_with_none_for_unfinished(self):
        # One item blocks on a gate the test only releases AFTER inspecting
        # the (already-returned) partial result, so the still-pending item is
        # deterministically NOT done when the short deadline elapses. The
        # gate's own wait() is bounded (2s) so a real regression fails this
        # test quickly instead of hanging the suite.
        gate = threading.Event()

        def fn(item):
            if item == "blocked":
                gate.wait(timeout=2)
                return "late"
            return "done"

        start = server._now()
        results, partial = server._map_parallel(
            ["fast", "blocked"], fn, max_workers=2, deadline=start + 0.05,
        )
        gate.set()  # release the blocked worker so it does not outlive the test
        self.assertTrue(partial)
        self.assertEqual(results[0], "done")
        self.assertIsNone(results[1])

    def test_deadline_none_waits_for_all_items(self):
        # No deadline supplied -> behaves like an unbounded gather (waits for
        # every item), matching every non-#402 call site.
        def fn(item):
            time.sleep(0.01)
            return item

        results, partial = server._map_parallel(list(range(5)), fn, max_workers=2)
        self.assertEqual(results, list(range(5)))
        self.assertFalse(partial)

    def test_already_past_deadline_marks_partial(self):
        # _now pinned to a constant AHEAD of the deadline so the very first
        # remaining-time check inside _map_parallel already reads negative --
        # deterministic, no real timing dependency. The loop exits before
        # ever calling concurrent.futures.wait(), so every slot stays
        # unfinished (None), regardless of how fast fn() itself would run.
        def fn(item):
            return item

        with unittest.mock.patch.object(server, "_now", return_value=1000.0):
            results, partial = server._map_parallel(
                [0, 1, 2], fn, max_workers=2, deadline=999.0,
            )
        self.assertTrue(partial)
        self.assertEqual(results, [None, None, None])


if __name__ == "__main__":
    unittest.main()
