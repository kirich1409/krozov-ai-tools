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


if __name__ == "__main__":
    unittest.main()
