"""Tests for `protocol/schemas.py` (T-7).

See `docs/plans/youtube-transcript/tasks.md`'s T-7 block for the full acceptance
criteria this file's `check` list is drawn from.
"""

import unittest

import _helpers  # type: ignore[import-not-found]  # noqa: F401
# ^ installs the sys.path shim before the import below -- see _helpers.py's module
# docstring and test_domain.py's identical comment for the mypy-vs-runtime reason
# this bare top-level import needs the suppression.

import protocol.schemas as schemas


class TestAnnotationsAndUntrustedContentDescription(unittest.TestCase):
    def test_annotations_and_untrusted_content_description(self) -> None:
        self.assertEqual(len(schemas.TOOL_SCHEMAS), 2)
        by_name = {entry["name"]: entry for entry in schemas.TOOL_SCHEMAS}
        self.assertEqual(set(by_name.keys()), {"get_transcript", "list_transcript_tracks"})

        for entry in schemas.TOOL_SCHEMAS:
            with self.subTest(tool=entry["name"]):
                self.assertEqual(
                    entry["annotations"], {"readOnlyHint": True, "openWorldHint": True}
                )

        get_transcript_description = by_name["get_transcript"]["description"].lower()
        self.assertIn("untrusted", get_transcript_description)

        list_tracks_description = by_name["list_transcript_tracks"]["description"]
        self.assertIn("languageName", list_tracks_description)
        self.assertIn("untrusted", list_tracks_description.lower())

        # AC-3's 11-language cap is a domain-level rejection, never a schema-level
        # one (post-cycle-9 hostile-implementer-walkthrough finding) -- `languages`
        # must not declare `maxItems`, or an 11-language request would be rejected
        # at dispatch time with -32602 instead of reaching `tools/` as
        # `language_unavailable`.
        languages_schema = by_name["get_transcript"]["inputSchema"]["properties"]["languages"]
        self.assertNotIn("maxItems", languages_schema)


class TestGetTranscriptCallerRequirements(unittest.TestCase):
    """AC-29: the description is the only lever this server has over what the
    caller does with the transcript after it leaves the process (the plugin never
    writes files), so its four requirements are asserted, not assumed."""

    def setUp(self) -> None:
        self.description = next(
            entry["description"]
            for entry in schemas.TOOL_SCHEMAS
            if entry["name"] == "get_transcript"
        )

    def test_requires_verbatim_reproduction(self) -> None:
        lowered = self.description.lower()
        self.assertIn("verbatim", lowered)
        for token in ("numbers", "dates", "proper nouns"):
            with self.subTest(token=token):
                self.assertIn(token, lowered)

    def test_requires_naming_the_resolved_track(self) -> None:
        self.assertIn("resolvedTrack.languageCode", self.description)
        self.assertIn("resolvedTrack.kind", self.description)

    def test_requires_asking_when_alternatives_exist(self) -> None:
        self.assertIn("alternativeTracks", self.description)
        self.assertIn("ask", self.description.lower())

    def test_requires_repeating_available_languages(self) -> None:
        self.assertIn("availableLanguages", self.description)
        self.assertIn("language_unavailable", self.description)

    def test_untrusted_content_warning_survives_verbatim(self) -> None:
        """AC-29 adds to the description; it must not displace the delimiter /
        untrusted-content warning already there, which is about a different
        threat."""
        self.assertIn(schemas._UNTRUSTED_CONTENT_NOTE, self.description)
        self.assertIn("contentNotice", self.description)


if __name__ == "__main__":
    unittest.main()
