"""Tests for `formats/__init__.py`'s dispatch logic and `estimate_characters` (T-5).

`test_deadline_expires_within_stride_bound` and `test_count_pages_to_agrees_with_encode`
are the two "shared" checks from T-5's `check` list -- written once here, parametrized
across every entry in `formats.FORMATS`, rather than duplicated in each per-format test
file, since both properties are about the dispatch-level `encode`/`count_pages_to`
contract that all three formats share, not about any one format's rendering.
"""

import unittest
from typing import Tuple, cast

import _helpers  # type: ignore[import-not-found]
# ^ installs the sys.path shim -- see test_domain.py's identical comment. (Actually used
# here, via `_helpers.make_segments`, so no `noqa: F401` needed unlike test_domain.py's
# pure-side-effect import.)

import domain
import formats


class TestEstimateCharacters(unittest.TestCase):
    def test_estimate_characters_three_key_object(self) -> None:
        duration_seconds = 600  # 10 minutes
        result = formats.estimate_characters(duration_seconds)
        expected_text = round(duration_seconds * formats.CHARS_PER_SECOND)
        self.assertEqual(
            result,
            {
                "text": expected_text,
                "srt": expected_text * formats.CUE_OVERHEAD_FACTOR,
                "vtt": expected_text * formats.CUE_OVERHEAD_FACTOR,
            },
        )
        self.assertEqual(set(result.keys()), {"text", "srt", "vtt"})
        # Known fixture values, not just formula-echoing the implementation:
        # 600 * 15 = 9000; 9000 * 3 = 27000.
        self.assertEqual(result, {"text": 9000, "srt": 27000, "vtt": 27000})


class TestDispatch(unittest.TestCase):
    def test_encode_routes_by_format(self) -> None:
        transcript = domain.Transcript(segments=(domain.Segment(start_ms=0, duration_ms=1000, text="hi"),))
        options = formats.FormatOptions()
        text_page = formats.encode(
            transcript, "text", options=options, deadline=domain.Deadline.start(30.0)
        )
        srt_page = formats.encode(
            transcript, "srt", options=options, deadline=domain.Deadline.start(30.0)
        )
        vtt_page = formats.encode(
            transcript, "vtt", options=options, deadline=domain.Deadline.start(30.0)
        )
        self.assertEqual(text_page.text, "hi\n")
        self.assertTrue(srt_page.text.startswith("1\n"))
        self.assertTrue(vtt_page.text.startswith("WEBVTT\n\n"))

    def test_encode_unknown_format_raises_value_error(self) -> None:
        transcript = domain.Transcript(segments=())
        with self.assertRaises(ValueError):
            formats.encode(
                transcript, "srv", options=formats.FormatOptions(), deadline=domain.Deadline.start(30.0)
            )

    def test_count_pages_to_unknown_format_raises_value_error(self) -> None:
        transcript = domain.Transcript(segments=())
        with self.assertRaises(ValueError):
            formats.count_pages_to(
                transcript,
                "srv",
                target_index=0,
                max_chars=100,
                options=formats.FormatOptions(),
                deadline=domain.Deadline.start(30.0),
            )

    def test_count_pages_to_target_beyond_segment_count_terminates(self) -> None:
        # A target_index past the transcript's actual segment count is a malformed
        # caller-supplied value (never produced by this server's own encode() calls
        # under correct use) -- must not infinite-loop trying to reach it.
        transcript = domain.Transcript(
            segments=(domain.Segment(start_ms=0, duration_ms=1000, text="only one segment"),)
        )
        for fmt in sorted(formats.FORMATS):
            with self.subTest(fmt=fmt):
                counted = formats.count_pages_to(
                    transcript,
                    fmt,
                    target_index=1000,
                    max_chars=formats.MAX_PAGE_CHARS,
                    options=formats.FormatOptions(),
                    deadline=domain.Deadline.start(30.0),
                )
                self.assertEqual(counted, 1)


def _varied_transcript(count: int) -> domain.Transcript:
    segments: Tuple[domain.Segment, ...] = _helpers.make_segments(
        count, text=lambda i: f"segment number {i} " * (i % 4 + 1)
    )
    return domain.Transcript(segments=segments)


class TestCountPagesToAgreesWithEncode(unittest.TestCase):
    def test_count_pages_to_agrees_with_encode(self) -> None:
        transcript = _varied_transcript(60)
        options = formats.FormatOptions()
        max_chars = 200

        for fmt in sorted(formats.FORMATS):
            with self.subTest(fmt=fmt):
                boundaries = [0]
                index = 0
                while index < len(transcript.segments):
                    page = formats.encode(
                        transcript,
                        fmt,
                        start_index=index,
                        max_chars=max_chars,
                        options=options,
                        deadline=domain.Deadline.start(30.0),
                    )
                    self.assertGreater(page.next_index, index)
                    index = page.next_index
                    boundaries.append(index)
                self.assertGreater(len(boundaries), 2, "fixture must span multiple pages")

                for page_number, boundary in enumerate(boundaries[1:], start=1):
                    counted = formats.count_pages_to(
                        transcript,
                        fmt,
                        target_index=boundary,
                        max_chars=max_chars,
                        options=options,
                        deadline=domain.Deadline.start(30.0),
                    )
                    self.assertEqual(
                        counted,
                        page_number,
                        f"{fmt}: count_pages_to(target_index={boundary}) disagreed with "
                        f"encode()'s own page boundaries",
                    )


class _PoisonSegment:
    """A `Segment`-shaped double whose `.text` access fails the test loudly -- used to
    prove a paging pass never touches a segment beyond the stride bound
    `DEADLINE_CHECK_STRIDE` is supposed to enforce. Duck-typed rather than a real
    `domain.Segment` (needs a computed property on access, which a plain dataclass
    field can't do) -- the same kind of test-only double `_helpers.py` already uses for
    the provider ports."""

    start_ms = 0
    duration_ms = 1000

    @property
    def text(self) -> str:
        raise AssertionError(
            "a segment beyond the stride bound was processed -- DeadlineExpired "
            "should have fired before reaching it"
        )


class TestDeadlineExpiresWithinStrideBound(unittest.TestCase):
    def test_deadline_expires_within_stride_bound(self) -> None:
        stride = domain.DEADLINE_CHECK_STRIDE
        total_segments = domain.MAX_SEGMENTS  # 100,000 -- "a 100,000-segment pass"

        # `budget` sits strictly between two stride checkpoints (2000 and 3000), so the
        # expiry is only detected at the *next* checkpoint, not immediately -- the
        # interesting mid-stride overshoot case, not the degenerate on-the-boundary one.
        budget = 2 * stride + stride // 2
        expected_raise_at = 3 * stride  # first checkpoint at/after `budget`

        # A stateful clock: each call returns `calls_so_far * stride`, modeling "exactly
        # `stride` segments' worth of time passes between one deadline check and the
        # next" -- exact by construction (checks happen precisely every `stride`
        # segments, see formats/_paging.py's DeadlineStride), not an approximation.
        calls = [0]

        def fake_clock() -> float:
            value = float(calls[0] * stride)
            calls[0] += 1
            return value

        safe_segments = _helpers.make_segments(expected_raise_at)
        poison_segments = cast(
            "Tuple[domain.Segment, ...]",
            tuple(_PoisonSegment() for _ in range(total_segments - expected_raise_at)),
        )
        transcript = domain.Transcript(segments=safe_segments + poison_segments)

        for fmt in sorted(formats.FORMATS):
            with self.subTest(fmt=fmt):
                # Fresh clock/deadline per format so each dispatch gets its own
                # independent stride-check countdown.
                calls[0] = 0
                deadline = domain.Deadline.start(float(budget), clock=fake_clock)
                with self.assertRaises(domain.DeadlineExpired):
                    formats.count_pages_to(
                        transcript,
                        fmt,
                        target_index=total_segments,
                        max_chars=formats.MAX_PAGE_CHARS,
                        options=formats.FormatOptions(),
                        deadline=deadline,
                    )

    def test_encode_also_bounded_by_stride_within_one_call(self) -> None:
        # encode() renders only a single page, but a page can still span many
        # thousands of segments if they are short and max_chars is generous -- so
        # encode()'s own pass must be stride-checked too, not only count_pages_to()'s
        # multi-page replay.
        stride = domain.DEADLINE_CHECK_STRIDE
        expected_raise_at = 2 * stride
        budget = stride + stride // 2

        calls = [0]

        def fake_clock() -> float:
            value = float(calls[0] * stride)
            calls[0] += 1
            return value

        safe_segments = _helpers.make_segments(expected_raise_at)
        poison_segments = cast(
            "Tuple[domain.Segment, ...]",
            tuple(_PoisonSegment() for _ in range(domain.MAX_SEGMENTS - expected_raise_at)),
        )
        transcript = domain.Transcript(segments=safe_segments + poison_segments)

        for fmt in sorted(formats.FORMATS):
            with self.subTest(fmt=fmt):
                calls[0] = 0
                deadline = domain.Deadline.start(float(budget), clock=fake_clock)
                with self.assertRaises(domain.DeadlineExpired):
                    formats.encode(
                        transcript,
                        fmt,
                        start_index=0,
                        max_chars=10_000_000,
                        options=formats.FormatOptions(),
                        deadline=deadline,
                    )


if __name__ == "__main__":
    unittest.main()
