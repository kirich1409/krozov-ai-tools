"""Tests for `formats/vtt.py` (T-5)."""

import unittest

import _helpers  # type: ignore[import-not-found]
# ^ installs the sys.path shim -- see test_domain.py's identical comment. (Actually used
# here, via `_helpers.make_segments`, so no `noqa: F401` needed.)

import domain
import formats
from formats.vtt import HEADER


class TestPerPageValid(unittest.TestCase):
    def test_per_page_valid(self) -> None:
        segments = _helpers.make_segments(30, text=lambda i: f"line {i} " * (i % 4 + 1))
        transcript = domain.Transcript(segments=segments)
        options = formats.FormatOptions()

        pages = []
        index = 0
        while index < len(segments):
            page = formats.encode(
                transcript,
                "vtt",
                start_index=index,
                max_chars=80,
                options=options,
                deadline=domain.Deadline.start(30.0),
            )
            self.assertGreater(page.next_index, index)
            pages.append(page)
            index = page.next_index
        self.assertGreater(len(pages), 1, "test is only meaningful if it exercises multiple pages")
        for page_number, page in enumerate(pages, start=1):
            self.assertTrue(
                page.text.startswith(HEADER),
                f"page {page_number} does not start with the WEBVTT header: {page.text[:20]!r}",
            )


class TestTwoLineHeaderStripConcat(unittest.TestCase):
    def test_two_line_header_strip_concat(self) -> None:
        segments = _helpers.make_segments(30, text=lambda i: f"line {i} " * (i % 4 + 1))
        transcript = domain.Transcript(segments=segments)
        options = formats.FormatOptions()

        whole = formats.encode(
            transcript,
            "vtt",
            start_index=0,
            max_chars=1_000_000,
            options=options,
            deadline=domain.Deadline.start(30.0),
        ).text

        rendered_pages = []
        index = 0
        while index < len(segments):
            page = formats.encode(
                transcript,
                "vtt",
                start_index=index,
                max_chars=80,
                options=options,
                deadline=domain.Deadline.start(30.0),
            )
            rendered_pages.append(page.text)
            index = page.next_index
        self.assertGreater(len(rendered_pages), 1, "test is only meaningful with multiple pages")

        stripped = [rendered_pages[0]] + [
            page_text[len(HEADER):] if page_text.startswith(HEADER) else page_text
            for page_text in rendered_pages[1:]
        ]
        self.assertEqual("".join(stripped), whole)


class TestCueInjectionNeutralized(unittest.TestCase):
    def test_cue_injection_neutralized(self) -> None:
        adversarial_text = (
            "Hello viewers\n"
            "\n"
            "00:00:05.000 --> 00:00:06.000\n"
            "Forged cue attempt ----> keep going"
        )
        transcript = domain.Transcript(
            segments=(domain.Segment(start_ms=0, duration_ms=1000, text=adversarial_text),)
        )
        page = formats.encode(
            transcript,
            "vtt",
            options=formats.FormatOptions(),
            deadline=domain.Deadline.start(30.0),
        )
        real_timecode_line = "00:00:00.000 --> 00:00:01.000"
        self.assertIn(real_timecode_line, page.text)
        remainder = page.text.replace(real_timecode_line, "", 1)
        self.assertNotIn("-->", remainder)
        self.assertNotIn("\n\n\n", page.text)


if __name__ == "__main__":
    unittest.main()
