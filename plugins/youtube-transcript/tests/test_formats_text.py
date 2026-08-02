"""Tests for `formats/text.py` (T-5)."""

import unittest

import _helpers  # type: ignore[import-not-found]
# ^ installs the sys.path shim -- see test_domain.py's identical comment for why this
# convention (bare `import _helpers` before anything under plugin/server/) is used.
# (Actually used here, via `_helpers.make_segments`, so no `noqa: F401` needed.)

import domain
import formats


class TestByteExactConcat(unittest.TestCase):
    def test_byte_exact_concat(self) -> None:
        segments = _helpers.make_segments(40, text=lambda i: f"word{i} " * (i % 5 + 1))
        transcript = domain.Transcript(segments=segments)
        options = formats.FormatOptions()

        whole = formats.encode(
            transcript,
            "text",
            start_index=0,
            max_chars=1_000_000,
            options=options,
            deadline=domain.Deadline.start(30.0),
        ).text

        pages = []
        index = 0
        while index < len(segments):
            page = formats.encode(
                transcript,
                "text",
                start_index=index,
                max_chars=37,
                options=options,
                deadline=domain.Deadline.start(30.0),
            )
            self.assertGreater(page.next_index, index, "must always make forward progress")
            pages.append(page.text)
            index = page.next_index
        self.assertGreater(len(pages), 1, "test is only meaningful if it exercises multiple pages")
        self.assertEqual("".join(pages), whole)


class TestIncludeTimestamps(unittest.TestCase):
    def test_include_timestamps_default_false(self) -> None:
        transcript = domain.Transcript(segments=(domain.Segment(start_ms=0, duration_ms=1000, text="hello"),))
        page = formats.encode(
            transcript,
            "text",
            options=formats.FormatOptions(),
            deadline=domain.Deadline.start(30.0),
        )
        self.assertEqual(page.text, "hello\n")

    def test_include_timestamps_true_adds_formatted_timecode(self) -> None:
        transcript = domain.Transcript(
            segments=(domain.Segment(start_ms=61_500, duration_ms=1000, text="hello"),)
        )
        page = formats.encode(
            transcript,
            "text",
            options=formats.FormatOptions(include_timestamps=True),
            deadline=domain.Deadline.start(30.0),
        )
        self.assertEqual(page.text, "[00:01:01.500] hello\n")


class TestForwardProgressOnOversizedSegment(unittest.TestCase):
    def test_single_oversized_segment_still_included(self) -> None:
        # A page must include at least one segment even if that segment alone
        # exceeds max_chars -- otherwise pagination could get stuck forever.
        transcript = domain.Transcript(segments=(domain.Segment(start_ms=0, duration_ms=1000, text="x" * 500),))
        page = formats.encode(
            transcript,
            "text",
            max_chars=10,
            options=formats.FormatOptions(),
            deadline=domain.Deadline.start(30.0),
        )
        self.assertEqual(page.next_index, 1)
        self.assertEqual(page.text, "x" * 500 + "\n")


if __name__ == "__main__":
    unittest.main()
