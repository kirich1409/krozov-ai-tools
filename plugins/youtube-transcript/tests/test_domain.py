"""Tests for `domain/__init__.py` (T-2).

Closes AC-17's `STATUS_POLICY` totality, AC-10's `isError` totality, and AC-21's
control-character clause. See `docs/plans/youtube-transcript/tasks.md`'s T-2 block for
the full acceptance criteria this file's `check` list is drawn from.
"""

import re
import unittest

import _helpers  # type: ignore[import-not-found]  # noqa: F401
# ^ installs the sys.path shim before the import below. Bare top-level `import
# _helpers` is this test harness's own documented convention (see _helpers.py's
# module docstring) and resolves fine at runtime (`unittest discover -s tests -t
# tests` puts `tests/` itself on sys.path, matching plugins/maven-mcp/tests'
# identical, `__init__.py`-less convention). mypy, unlike the runtime discovery
# invocation, DOES see `tests/__init__.py` (T-1) and so qualifies this module as
# `tests._helpers` instead -- a static-vs-runtime module-identity mismatch inherent
# to T-1's package layout, not something this file can resolve without changing the
# established import convention every other test module will also need (T-3+).

import domain

_BOUNDARY_PATTERN = re.compile(r"^<<<UNTRUSTED_CONTENT_[0-9a-f]{32}>>>$")


class TestStatusPolicyTotality(unittest.TestCase):
    def test_status_policy_totality(self) -> None:
        # Exactly one entry per Status member -- no more, no fewer (AC-17).
        self.assertEqual(set(domain.STATUS_POLICY.keys()), set(domain.Status))
        # isError is False in every row (AC-10) -- no status this server can name is
        # ever a genuine bug, by definition.
        for status, (_retryable, _retry_after, is_error) in domain.STATUS_POLICY.items():
            self.assertFalse(is_error, f"{status} has isError=True")


class TestDeadline(unittest.TestCase):
    def test_deadline_expired_is_domain_failure(self) -> None:
        self.assertTrue(issubclass(domain.DeadlineExpired, domain.DomainFailure))

    def test_deadline_injected_clock(self) -> None:
        clock_value = [0.0]

        def fake_clock() -> float:
            return clock_value[0]

        deadline = domain.Deadline.start(10.0, clock=fake_clock)
        self.assertFalse(deadline.expired())
        first_remaining = deadline.remaining()

        clock_value[0] += 4.0
        second_remaining = deadline.remaining()
        self.assertLess(second_remaining, first_remaining)
        self.assertFalse(deadline.expired())

        clock_value[0] += 4.0
        third_remaining = deadline.remaining()
        self.assertLess(third_remaining, second_remaining)
        self.assertFalse(deadline.expired())

        # Advance past the 10s budget -- expired() flips True.
        clock_value[0] += 5.0
        self.assertTrue(deadline.expired())


class TestSanitizeText(unittest.TestCase):
    def test_sanitize_text_strips_control_chars_widened_set(self) -> None:
        # Every stripped codepoint is built via chr(...)/\N escapes rather than a
        # literal glyph, deliberately, so this source file itself never embeds a real
        # bidi-override or invisible-formatting character.
        c0 = chr(0x00) + chr(0x01)  # C0 control (Cc)
        c1 = chr(0x80) + chr(0x9F)  # C1 control (Cc)
        del_char = chr(0x7F)  # DEL (Cc)
        bidi_override = chr(0x202E)  # RIGHT-TO-LEFT OVERRIDE (Cf)
        bidi_isolate = chr(0x2066)  # LEFT-TO-RIGHT ISOLATE (Cf)
        bom = chr(0xFEFF)  # ZERO WIDTH NO-BREAK SPACE / BOM (Cf)
        line_sep = chr(0x2028)  # LINE SEPARATOR (Zl, listed explicitly)
        para_sep = chr(0x2029)  # PARAGRAPH SEPARATOR (Zp, listed explicitly)
        surrogate = chr(0xD800)  # unpaired surrogate (Cs)

        fixture = (
            "keep\n\tme"
            + c0
            + c1
            + del_char
            + bidi_override
            + bidi_isolate
            + bom
            + line_sep
            + para_sep
            + surrogate
        )
        self.assertEqual(domain.sanitize_text(fixture), "keep\n\tme")


class TestGenerateContentBoundary(unittest.TestCase):
    def test_generate_content_boundary_is_random_and_well_formed(self) -> None:
        first = domain.generate_content_boundary()
        second = domain.generate_content_boundary()
        # Two different values -- proves this isn't a disguised constant.
        self.assertNotEqual(first, second)
        self.assertRegex(first, _BOUNDARY_PATTERN)
        self.assertRegex(second, _BOUNDARY_PATTERN)


class TestRedactUrl(unittest.TestCase):
    def test_redact_url_strips_query_fragment_and_userinfo(self) -> None:
        redacted = domain.redact_url("https://user:token@host/path?q=1#frag")
        for forbidden in ("user", "token", "q=1", "frag"):
            self.assertNotIn(forbidden, redacted)


class TestTrackDescriptorValidation(unittest.TestCase):
    def test_language_name_length_bound_rejected(self) -> None:
        with self.assertRaises(domain.TrackFieldInvalid):
            domain.TrackDescriptor(
                track_id="manual:abc123",
                language_code="en",
                language_name="a" * 101,
                kind="manual",
                estimated_characters=None,
                is_default=False,
            )


class TestEncodeReserveDerivation(unittest.TestCase):
    def test_encode_reserve_is_derived_in_domain(self) -> None:
        # Both operands importable directly from within domain/ itself (cycle 8) --
        # not restated as a separate literal, no cross-package import needed.
        self.assertEqual(domain.ENCODE_RESERVE, domain.HTTP_TIMEOUT + domain.CPU_PHASE_BUDGET)


if __name__ == "__main__":
    unittest.main()
