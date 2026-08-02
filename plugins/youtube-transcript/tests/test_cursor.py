"""Tests for `tools/cursor.py` (T-8): the pagination cursor codec's wire
encoding, first-phase validation order, and round-trip property. See
`docs/plans/youtube-transcript/tasks.md`'s T-8 block and
`docs/specs/2026-08-01-youtube-transcript.md`'s AC-11 for the full acceptance
criteria this file's `check` list is drawn from.
"""

import base64
import json
import unittest

import _helpers  # type: ignore[import-not-found]  # noqa: F401
# ^ installs the sys.path shim before the imports below -- see _helpers.py's module
# docstring and test_domain.py's identical comment for the mypy-vs-runtime reason
# this bare top-level import needs the suppression.

import domain
import providers.base as providers_base
import tools.cursor as cursor

_VALID_FIELDS = cursor.CursorFields(
    video_id="dQw4w9WgXcQ",
    track_id="manual:en",
    format="text",
    include_timestamps=True,
    segment_index=42,
)


def _valid_payload() -> dict:
    return {
        "videoId": _VALID_FIELDS.video_id,
        "trackId": _VALID_FIELDS.track_id,
        "format": _VALID_FIELDS.format,
        "includeTimestamps": _VALID_FIELDS.include_timestamps,
        "segmentIndex": _VALID_FIELDS.segment_index,
    }


def _encode_payload(payload: dict) -> str:
    raw_json = json.dumps(payload).encode("utf-8")
    return base64.b64encode(raw_json, altchars=b"-_").decode("ascii")


class TestSizeCap(unittest.TestCase):
    def test_size_cap(self) -> None:
        # Longer than MAX_CURSOR_CHARS -- rejected before any decode work, even
        # though this string isn't valid base64 at all (proving the size check
        # runs first, not as a side effect of a failed decode).
        oversized = "a" * (cursor.MAX_CURSOR_CHARS + 1)
        with self.assertRaises(domain.CursorInvalid):
            cursor.decode(oversized)

        # At exactly the cap, the size check itself doesn't reject -- confirms
        # the boundary is "longer than", not "at least".
        at_cap = cursor.encode(_VALID_FIELDS)
        self.assertLessEqual(len(at_cap), cursor.MAX_CURSOR_CHARS)


class TestBase64Validation(unittest.TestCase):
    def test_base64_validation(self) -> None:
        # `validate=True` rejects a character outside the base64url alphabet --
        # `urlsafe_b64decode` would have silently stripped it instead of raising.
        with self.assertRaises(domain.CursorInvalid):
            cursor.decode("not!valid#base64$$$")

        # A non-ascii character fails the `raw.encode("ascii")` step, a
        # different failure mode than an invalid-but-ascii base64 alphabet
        # character -- both must raise CursorInvalid.
        with self.assertRaises(domain.CursorInvalid):
            cursor.decode("café")

        # Valid base64url but not valid JSON underneath.
        garbage = base64.b64encode(b"not json at all", altchars=b"-_").decode("ascii")
        with self.assertRaises(domain.CursorInvalid):
            cursor.decode(garbage)


class TestExactlyFiveKeys(unittest.TestCase):
    def test_exactly_five_keys(self) -> None:
        # A JSON value that isn't even a dict.
        with self.assertRaises(domain.CursorInvalid):
            cursor.decode(_encode_payload([1, 2, 3]))  # type: ignore[arg-type]

        # Missing a key.
        missing = _valid_payload()
        del missing["segmentIndex"]
        with self.assertRaises(domain.CursorInvalid):
            cursor.decode(_encode_payload(missing))

        # An extra key beyond the five.
        extra = _valid_payload()
        extra["pageOrdinal"] = 3
        with self.assertRaises(domain.CursorInvalid):
            cursor.decode(_encode_payload(extra))

        # Exactly five, correct keys -- decodes fine.
        self.assertEqual(cursor.decode(_encode_payload(_valid_payload())), _VALID_FIELDS)


class TestVideoIdRegexRejected(unittest.TestCase):
    def test_video_id_regex_rejected(self) -> None:
        for bad_video_id in ("", "short", "toolongvideoid1234", "has space!!", "twelvecharsxx"):
            with self.subTest(bad_video_id=bad_video_id):
                payload = _valid_payload()
                payload["videoId"] = bad_video_id
                with self.assertRaises(domain.CursorInvalid):
                    cursor.decode(_encode_payload(payload))

        # Wrong type entirely.
        payload = _valid_payload()
        payload["videoId"] = 12345
        with self.assertRaises(domain.CursorInvalid):
            cursor.decode(_encode_payload(payload))


class TestSegmentIndexBoundsRejected(unittest.TestCase):
    def test_segment_index_bounds_rejected(self) -> None:
        for bad_segment_index in (-1, domain.MAX_SEGMENTS, domain.MAX_SEGMENTS + 1000):
            with self.subTest(bad_segment_index=bad_segment_index):
                payload = _valid_payload()
                payload["segmentIndex"] = bad_segment_index
                with self.assertRaises(domain.CursorInvalid):
                    cursor.decode(_encode_payload(payload))

        # Non-int types, including bool (a subclass of int in Python, but not a
        # valid segment index). A separate loop variable name avoids a mypy
        # redefinition error against the first loop's inferred `int` type above.
        for bad_segment_index_wrong_type in (True, False, "42", 3.5, None):
            with self.subTest(bad_segment_index=bad_segment_index_wrong_type):
                payload = _valid_payload()
                payload["segmentIndex"] = bad_segment_index_wrong_type
                with self.assertRaises(domain.CursorInvalid):
                    cursor.decode(_encode_payload(payload))

        # 0 and MAX_SEGMENTS - 1 are both in bounds.
        for good_segment_index in (0, domain.MAX_SEGMENTS - 1):
            with self.subTest(good_segment_index=good_segment_index):
                payload = _valid_payload()
                payload["segmentIndex"] = good_segment_index
                decoded = cursor.decode(_encode_payload(payload))
                self.assertEqual(decoded.segment_index, good_segment_index)


class TestFormatNotInEnumRejected(unittest.TestCase):
    def test_format_not_in_enum_rejected(self) -> None:
        for bad_format in ("json3", "ttml", "TEXT", "", 42, None):
            with self.subTest(bad_format=bad_format):
                payload = _valid_payload()
                payload["format"] = bad_format
                with self.assertRaises(domain.CursorInvalid):
                    cursor.decode(_encode_payload(payload))

        for good_format in domain.FORMATS:
            with self.subTest(good_format=good_format):
                payload = _valid_payload()
                payload["format"] = good_format
                decoded = cursor.decode(_encode_payload(payload))
                self.assertEqual(decoded.format, good_format)


class TestIncludeTimestampsNonBoolRejected(unittest.TestCase):
    def test_include_timestamps_non_bool_rejected(self) -> None:
        # Truthy/falsy non-bool values must still be rejected -- this is a
        # strict type check, not a truthiness check.
        for bad_value in (1, 0, "true", "false", "", None, 1.0):
            with self.subTest(bad_value=bad_value):
                payload = _valid_payload()
                payload["includeTimestamps"] = bad_value
                with self.assertRaises(domain.CursorInvalid):
                    cursor.decode(_encode_payload(payload))

        for good_value in (True, False):
            with self.subTest(good_value=good_value):
                payload = _valid_payload()
                payload["includeTimestamps"] = good_value
                decoded = cursor.decode(_encode_payload(payload))
                self.assertEqual(decoded.include_timestamps, good_value)
                self.assertIsInstance(decoded.include_timestamps, bool)


class TestTrackIdFailsParseTrackIdRejected(unittest.TestCase):
    def test_track_id_fails_parse_track_id_rejected(self) -> None:
        for bad_track_id in (
            "",
            "manual",
            "manual:",
            ":en",
            "weird:en",
            "manual:has space",
            "manual:" + "a" * 21,
            "manual:en:extra",
            42,
            None,
        ):
            with self.subTest(bad_track_id=bad_track_id):
                if isinstance(bad_track_id, str):
                    # Sanity: confirms this string is actually rejected by
                    # `parse_track_id` itself, not by some other cursor.py check.
                    self.assertIsNone(providers_base.parse_track_id(bad_track_id))
                payload = _valid_payload()
                payload["trackId"] = bad_track_id
                with self.assertRaises(domain.CursorInvalid):
                    cursor.decode(_encode_payload(payload))

        # A syntactically valid trackId decodes fine and round-trips through
        # parse_track_id.
        payload = _valid_payload()
        payload["trackId"] = "auto:pt-BR"
        decoded = cursor.decode(_encode_payload(payload))
        self.assertEqual(decoded.track_id, "auto:pt-BR")
        self.assertEqual(providers_base.parse_track_id(decoded.track_id), ("auto", "pt-BR"))


class TestRoundtrip(unittest.TestCase):
    def test_roundtrip(self) -> None:
        self.assertEqual(cursor.decode(cursor.encode(_VALID_FIELDS)), _VALID_FIELDS)

        other_fields = cursor.CursorFields(
            video_id="AAAAAAAAAAA",
            track_id="auto:pt-BR",
            format="vtt",
            include_timestamps=False,
            segment_index=0,
        )
        self.assertEqual(cursor.decode(cursor.encode(other_fields)), other_fields)

    def test_encode_uses_urlsafe_alphabet_and_ascii_only(self) -> None:
        encoded = cursor.encode(_VALID_FIELDS)
        self.assertTrue(encoded.isascii())
        self.assertNotIn("+", encoded)
        self.assertNotIn("/", encoded)


if __name__ == "__main__":
    unittest.main()
