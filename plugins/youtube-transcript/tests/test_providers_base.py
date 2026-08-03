"""Tests for `providers/base.py` (T-3): the `trackId` codec, the `ProviderError`
hierarchy, and `tools/__init__.py::outcome_from_error`'s totality across every
concrete `DomainFailure` subclass. See `docs/plans/youtube-transcript/tasks.md`'s
T-3 block for the full acceptance criteria this file's `check` list is drawn from.
"""

import unittest
from typing import List, Type

import _helpers  # type: ignore[import-not-found]  # noqa: F401
# ^ installs the sys.path shim before the imports below -- see _helpers.py's module
# docstring and test_domain.py's identical comment for the mypy-vs-runtime reason
# this bare top-level import needs the suppression.

import domain
import providers.base as providers_base
import tools as tools_module
from protocol import envelope


class TestTrackIdCodec(unittest.TestCase):
    def test_track_id_roundtrip_and_rejection(self) -> None:
        encoded = providers_base.encode_track_id("manual", "en")
        self.assertEqual(encoded, "manual:en")
        self.assertEqual(providers_base.parse_track_id(encoded), ("manual", "en"))

        encoded_auto = providers_base.encode_track_id("auto", "pt-BR")
        self.assertEqual(providers_base.parse_track_id(encoded_auto), ("auto", "pt-BR"))

        for bad in (
            "",
            "manual",
            "manual:",
            ":en",
            "weird:en",  # kind not in {manual, auto}
            "manual:has space",  # language_code fails the character class
            "manual:" + "a" * 21,  # language_code exceeds the 20-char bound
            "manual:en:extra",  # trailing content
            " manual:en",  # leading whitespace
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(providers_base.parse_track_id(bad))

    def test_parse_track_id_non_string_rejected_cleanly(self) -> None:
        # `trackId` (AC-5) is untrusted, JSON-decoded `tools/call` input --
        # `tools/get_transcript.py` reads `args.get("trackId")` without a type
        # check upstream, so a JSON array/object/int/bool must be treated as
        # "does not match" (returns `None`), not raise a raw `TypeError` from
        # `re.Pattern.match` on a non-string/bytes object.
        for bad in ([1, 2, 3], {"a": 1}, 42, True, None):
            with self.subTest(bad=bad):
                self.assertIsNone(providers_base.parse_track_id(bad))  # type: ignore[arg-type]

    def test_track_id_pattern_rejects_trailing_newline(self) -> None:
        # `$` matches at end-of-string OR immediately before a trailing `\n` in
        # Python's `re` module -- `\Z` (true end-of-string only) is required for
        # this AC-18 shape check, same class of defect as AC-6's video-ID pattern.
        self.assertIsNone(providers_base.parse_track_id("manual:en\n"))


class TestProviderErrorHierarchy(unittest.TestCase):
    def test_provider_error_is_domain_failure(self) -> None:
        self.assertTrue(issubclass(providers_base.ProviderError, domain.DomainFailure))

        subclass_status = {
            providers_base.VideoNotFound: domain.Status.VIDEO_NOT_FOUND,
            providers_base.VideoUnavailable: domain.Status.VIDEO_UNAVAILABLE,
            providers_base.AgeRestricted: domain.Status.AGE_RESTRICTED,
            providers_base.RegionBlocked: domain.Status.REGION_BLOCKED,
            providers_base.LiveNotReady: domain.Status.LIVE_NOT_READY,
            providers_base.RateLimited: domain.Status.RATE_LIMITED,
            providers_base.BlockedByProvider: domain.Status.BLOCKED_BY_PROVIDER,
            providers_base.UpstreamChanged: domain.Status.UPSTREAM_CHANGED,
            providers_base.TranscriptTooLarge: domain.Status.TRANSCRIPT_TOO_LARGE,
            providers_base.TransportError: domain.Status.TRANSPORT_ERROR,
        }
        # Exactly 10 subclasses -- `NoTranscript` is deliberately absent (plan.md
        # cycle 2's redesign removed it from the hierarchy entirely).
        self.assertEqual(len(subclass_status), 10)

        for cls, expected_status in subclass_status.items():
            with self.subTest(cls=cls.__name__):
                self.assertTrue(issubclass(cls, providers_base.ProviderError))
                self.assertTrue(issubclass(cls, domain.DomainFailure))
                self.assertEqual(cls.status, expected_status)
                instance = cls("synthetic message", retry_after=42)
                self.assertEqual(instance.retry_after, 42)
                self.assertIsInstance(instance, Exception)


def _leaf_domain_failure_subclasses() -> List[Type[BaseException]]:
    """Every concrete `DomainFailure` subclass with no further subclasses of its
    own -- i.e. every leaf `outcome_from_error` must actually handle.
    `ProviderError` itself (an intermediate base, never raised directly) is
    excluded by construction: it has ten subclasses, so it is never a leaf."""
    leaves: List[Type[BaseException]] = []
    stack: List[Type[BaseException]] = [domain.DomainFailure]
    while stack:
        cls = stack.pop()
        subs = cls.__subclasses__()
        if subs:
            stack.extend(subs)
        else:
            leaves.append(cls)
    return leaves


class TestOutcomeFromErrorTotality(unittest.TestCase):
    def test_outcome_from_error_totality(self) -> None:
        leaves = _leaf_domain_failure_subclasses()
        # Sanity: the 10 ProviderError subclasses + DeadlineExpired + CursorInvalid
        # + TrackFieldInvalid == 13 -- guards this totality test against silently
        # walking zero classes if domain/providers.base's import ever broke.
        self.assertEqual(
            len(leaves),
            13,
            f"expected exactly 13 leaf DomainFailure subclasses, found "
            f"{[c.__name__ for c in leaves]}",
        )
        for cls in leaves:
            with self.subTest(cls=cls.__name__):
                instance = cls("synthetic")
                outcome = tools_module.outcome_from_error(instance)  # type: ignore[arg-type]
                self.assertIsInstance(outcome, domain.ToolOutcome)
                self.assertIn(outcome.status, domain.STATUS_POLICY)

        # The two non-ProviderError mappings plan.md's cycle 6 pins explicitly.
        deadline_outcome = tools_module.outcome_from_error(domain.DeadlineExpired("x"))
        self.assertEqual(deadline_outcome.status, domain.Status.TRANSPORT_ERROR)
        cursor_outcome = tools_module.outcome_from_error(domain.CursorInvalid("x"))
        self.assertEqual(cursor_outcome.status, domain.Status.UPSTREAM_CHANGED)


class TestOutcomeFromErrorRetryAfter(unittest.TestCase):
    """Regression test for the acceptance-fix pass (AC-22): `RateLimited.retry_after`
    must survive `outcome_from_error()` and reach `envelope.build()`'s clamp, not be
    silently dropped by an empty payload. Exercises the real pipeline end-to-end
    (`RateLimited(retry_after=N)` -> `outcome_from_error` -> `envelope.build`), not
    just `envelope.build()` constructed directly with the payload already populated
    (`test_envelope.py`'s own coverage never exercises `outcome_from_error` at all,
    so it would not have caught this bug)."""

    def test_retry_after_threaded_through_to_wire_clamp(self) -> None:
        exc = providers_base.RateLimited("rate limited (429)", retry_after=3600)
        outcome = tools_module.outcome_from_error(exc)
        self.assertEqual(outcome.payload.get("retry_after_seconds"), 3600)

        result = envelope.build(outcome)
        # AC-22's ceiling: an upstream value above 300 clamps to 300, not the
        # fixed `STATUS_POLICY` default of 30 that a dropped payload would
        # silently fall back to.
        self.assertEqual(result["retryAfterSeconds"], 300)

    def test_retry_after_absent_falls_back_to_status_policy_default(self) -> None:
        """When upstream sent no `Retry-After` at all (`retry_after=None`), the
        payload stays empty and `envelope.build()` legitimately falls back to
        `STATUS_POLICY`'s fixed default -- this is not the bug case, kept as a
        contrast so the positive case above can't pass by accident (e.g. a
        change that always populates a default retry_after would break this)."""
        exc = providers_base.RateLimited("rate limited (429)")
        outcome = tools_module.outcome_from_error(exc)
        self.assertEqual(outcome.payload, {})

        result = envelope.build(outcome)
        self.assertEqual(result["retryAfterSeconds"], 30)


if __name__ == "__main__":
    unittest.main()
