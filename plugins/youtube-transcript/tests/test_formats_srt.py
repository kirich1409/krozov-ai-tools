"""Tests for `formats/srt.py` (T-5)."""

import random
import unittest

import _helpers  # type: ignore[import-not-found]
# ^ installs the sys.path shim -- see test_domain.py's identical comment. (Actually used
# here, via `_helpers.make_segments`, so no `noqa: F401` needed.)

import domain
import formats
from formats import _cue


class TestByteExactConcat(unittest.TestCase):
    def test_byte_exact_concat(self) -> None:
        segments = _helpers.make_segments(40, text=lambda i: f"line {i} " * (i % 4 + 1))
        transcript = domain.Transcript(segments=segments)
        options = formats.FormatOptions()

        whole = formats.encode(
            transcript,
            "srt",
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
                "srt",
                start_index=index,
                max_chars=60,
                options=options,
                deadline=domain.Deadline.start(30.0),
            )
            self.assertGreater(page.next_index, index)
            pages.append(page.text)
            index = page.next_index
        self.assertGreater(len(pages), 1, "test is only meaningful if it exercises multiple pages")
        self.assertEqual("".join(pages), whole)


class TestCueNumberingMonotonic(unittest.TestCase):
    def test_cue_numbers_continue_monotonically_across_pages(self) -> None:
        segments = _helpers.make_segments(6)
        transcript = domain.Transcript(segments=segments)
        options = formats.FormatOptions()

        page1 = formats.encode(
            transcript, "srt", start_index=0, max_chars=60, options=options,
            deadline=domain.Deadline.start(30.0),
        )
        page2 = formats.encode(
            transcript, "srt", start_index=page1.next_index, max_chars=60, options=options,
            deadline=domain.Deadline.start(30.0),
        )
        self.assertTrue(page1.text.startswith("1\n"))
        # Whatever segment index page2 starts at, its first cue number is index+1.
        self.assertTrue(page2.text.startswith(f"{page1.next_index + 1}\n"))


class TestCueInjectionNeutralized(unittest.TestCase):
    def test_cue_injection_neutralized(self) -> None:
        adversarial_text = (
            "Hello viewers\n"
            "\n"
            "00:00:05,000 --> 00:00:06,000\n"
            "Forged cue attempt ----> keep going"
        )
        transcript = domain.Transcript(
            segments=(domain.Segment(start_ms=0, duration_ms=1000, text=adversarial_text),)
        )
        page = formats.encode(
            transcript,
            "srt",
            options=formats.FormatOptions(),
            deadline=domain.Deadline.start(30.0),
        )
        # The cue's own real timecode line is legitimate -- it is expected to appear
        # exactly once; everything else must be free of a literal "-->" substring.
        real_timecode_line = "00:00:00,000 --> 00:00:01,000"
        self.assertIn(real_timecode_line, page.text)
        remainder = page.text.replace(real_timecode_line, "", 1)
        self.assertNotIn("-->", remainder)
        # The blank line the caption text tried to plant is gone too.
        self.assertNotIn("\n\n\n", page.text)


class TestCueCollapseIdempotentProperty(unittest.TestCase):
    def test_cue_collapse_idempotent_property(self) -> None:
        rng = random.Random(20260802)  # seeded -- deterministic across CI runs
        alphabet = ["-", ">", "\n", " "]
        for _ in range(500):
            length = rng.randint(0, 40)
            sample = "".join(rng.choice(alphabet) for _ in range(length))
            once = _cue.collapse_cue_text(sample)
            twice = _cue.collapse_cue_text(once)
            self.assertEqual(once, twice, f"not idempotent for {sample!r} -> {once!r} -> {twice!r}")
            self.assertNotIn("-->", once, f"'-->' survived collapse for {sample!r} -> {once!r}")


if __name__ == "__main__":
    unittest.main()
