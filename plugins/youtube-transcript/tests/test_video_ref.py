"""Tests for `providers/video_ref.py::normalize` (T-4): the full AC-6 URL-form
table (`watch?v=`, `youtu.be/`, `/shorts/`, `/live/`, `/embed/`, bare video ID)
plus the two named attack payloads (`@evil.com`, `youtube.com.evil.com`), which
must both return `None`. See `docs/plans/youtube-transcript/tasks.md`'s T-4 block
and `docs/specs/2026-08-01-youtube-transcript.md`'s AC-6 for the full acceptance
criteria this file's `check` is drawn from.
"""

import unittest

import _helpers  # type: ignore[import-not-found]  # noqa: F401
# ^ installs the sys.path shim before the imports below -- see _helpers.py's module
# docstring and test_domain.py's identical comment for the mypy-vs-runtime reason
# this bare top-level import needs the suppression.

from domain import VideoId
from providers.video_ref import normalize

_VIDEO_ID = "dQw4w9WgXcQ"  # a syntactically valid 11-char id, used throughout


class TestValidForms(unittest.TestCase):
    """Every URL form AC-6's table names, plus a bare video ID, across every
    allowlisted host each form can legitimately appear under."""

    def test_bare_video_id(self) -> None:
        self.assertEqual(normalize(_VIDEO_ID), VideoId(value=_VIDEO_ID))

    def test_watch_form(self) -> None:
        for host in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
            with self.subTest(host=host):
                url = f"https://{host}/watch?v={_VIDEO_ID}"
                self.assertEqual(normalize(url), VideoId(value=_VIDEO_ID))

    def test_watch_form_with_extra_query_params(self) -> None:
        url = f"https://www.youtube.com/watch?v={_VIDEO_ID}&t=42s&list=PLxyz"
        self.assertEqual(normalize(url), VideoId(value=_VIDEO_ID))

    def test_youtu_be_form(self) -> None:
        self.assertEqual(
            normalize(f"https://youtu.be/{_VIDEO_ID}"), VideoId(value=_VIDEO_ID)
        )

    def test_youtu_be_form_with_trailing_query(self) -> None:
        self.assertEqual(
            normalize(f"https://youtu.be/{_VIDEO_ID}?t=30"), VideoId(value=_VIDEO_ID)
        )

    def test_shorts_form(self) -> None:
        for host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
            with self.subTest(host=host):
                url = f"https://{host}/shorts/{_VIDEO_ID}"
                self.assertEqual(normalize(url), VideoId(value=_VIDEO_ID))

    def test_live_form(self) -> None:
        for host in ("youtube.com", "www.youtube.com"):
            with self.subTest(host=host):
                url = f"https://{host}/live/{_VIDEO_ID}"
                self.assertEqual(normalize(url), VideoId(value=_VIDEO_ID))

    def test_embed_form(self) -> None:
        for host in (
            "youtube.com",
            "www.youtube.com",
            "youtube-nocookie.com",
            "www.youtube-nocookie.com",
        ):
            with self.subTest(host=host):
                url = f"https://{host}/embed/{_VIDEO_ID}"
                self.assertEqual(normalize(url), VideoId(value=_VIDEO_ID))

    def test_http_scheme_also_accepted(self) -> None:
        # The allowlist is host-based, not scheme-based -- AC-6 doesn't restrict
        # to https specifically.
        self.assertEqual(
            normalize(f"http://www.youtube.com/watch?v={_VIDEO_ID}"),
            VideoId(value=_VIDEO_ID),
        )


class TestAttackPayloads(unittest.TestCase):
    """AC-6's two named auth-bypass-style payloads. Both must return `None` --
    exact `urlsplit(...).hostname` equality is the mechanism that defeats them,
    not a substring/`in`/`startswith` check that a naive implementation might use
    instead."""

    def test_userinfo_bypass_payload(self) -> None:
        # urlsplit(...).hostname resolves this to "evil.com" (userinfo discarded),
        # not "www.youtube.com" -- so this must NOT match the allowlist.
        url = f"https://www.youtube.com@evil.com/watch?v={_VIDEO_ID}"
        self.assertIsNone(normalize(url))

    def test_subdomain_suffix_bypass_payload(self) -> None:
        # "youtube.com.evil.com" contains "youtube.com" as a substring/prefix, but
        # is not equal to any allowlisted host.
        url = f"https://youtube.com.evil.com/watch?v={_VIDEO_ID}"
        self.assertIsNone(normalize(url))


class TestRejections(unittest.TestCase):
    """Malformed input, non-allowlisted hosts, and IDs that fail the post-
    normalization pattern -- all must return `None`, never raise."""

    def test_empty_string(self) -> None:
        self.assertIsNone(normalize(""))

    def test_non_string_input_does_not_raise(self) -> None:
        self.assertIsNone(normalize(None))  # type: ignore[arg-type]
        self.assertIsNone(normalize(12345))  # type: ignore[arg-type]

    def test_bare_id_wrong_length(self) -> None:
        self.assertIsNone(normalize("short"))
        self.assertIsNone(normalize(_VIDEO_ID + "x"))

    def test_bare_id_invalid_characters(self) -> None:
        self.assertIsNone(normalize("dQw4w9Wg X"))  # space, and only 10 chars
        self.assertIsNone(normalize("dQw4w9Wg#cQ"))  # '#' not in the character class

    def test_completely_unrelated_url(self) -> None:
        self.assertIsNone(normalize("https://example.com/watch?v=" + _VIDEO_ID))

    def test_non_allowlisted_youtube_lookalike_host(self) -> None:
        self.assertIsNone(normalize(f"https://youtube.com.au/watch?v={_VIDEO_ID}"))

    def test_watch_path_missing_v_param(self) -> None:
        self.assertIsNone(normalize("https://www.youtube.com/watch?list=PLxyz"))

    def test_watch_path_with_invalid_id(self) -> None:
        self.assertIsNone(normalize("https://www.youtube.com/watch?v=short"))

    def test_unrecognized_path_on_allowlisted_host(self) -> None:
        self.assertIsNone(normalize("https://www.youtube.com/channel/UCxxxx"))

    def test_youtube_com_root_path(self) -> None:
        self.assertIsNone(normalize("https://www.youtube.com/"))

    def test_shorts_form_wrong_id_length(self) -> None:
        self.assertIsNone(normalize("https://www.youtube.com/shorts/tooshort"))

    def test_youtu_be_root_path_has_no_id(self) -> None:
        self.assertIsNone(normalize("https://youtu.be/"))


if __name__ == "__main__":
    unittest.main()
