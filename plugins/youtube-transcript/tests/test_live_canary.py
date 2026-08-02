"""Live canary for AC-13's real (non-mocked) InnerTube network check (T-15).

This is the ONE test file in this suite that makes REAL network calls against
real YouTube infrastructure. Gated behind an explicit opt-in
(YOUTUBE_TRANSCRIPT_LIVE_CANARY=1) so it is collected by `unittest discover -s
plugins/youtube-transcript/tests` (matches the default `test*.py` pattern) but
SKIPPED by default -- mirrors `plugins/maven-mcp/tests/test_live_canary.py`'s
opt-in-skip pattern exactly (see T-15's brief,
`docs/plans/youtube-transcript/tasks.md`). It is NOT part of the default CI test
job; it is invoked ONLY by the dedicated weekly scheduled workflow
(`.github/workflows/youtube-transcript-live-canary.yml`, T-P2).

Why this exists: every other test in this suite exercises `providers/innertube.py`
against a mocked/fixture transport (`tests/_helpers.py`'s `mock_urlopen`,
`tests/fixtures/innertube_player_response.json`) -- that proves the *parsing* code
works against a shape the test author chose, but it cannot detect the underlying
LIVE assumption breaking: YouTube changing the InnerTube response shape, rotating
away from the current player-response markers, or blocking this mechanism outright
(the Phase 2 trigger documented in the spec's Decisions Made, plan.md). This test
re-queries two independently-pinned, real, previously-confirmed-captioned public
videos (`dQw4w9WgXcQ`, `9bZkp7q19f0` -- see
`swarm-report/research/youtube-transcript-size-measurements.md`, T-P3 section 9)
plus a third, lower-confidence bonus video (`P0uMXS6emHA`), through the exact same
`composition.build_provider()` -> `tools.get_transcript.handle()` pipeline the real
MCP server uses end-to-end -- no fake transport anywhere in this file.

Env-var read/import ORDER below is load-bearing, not incidental:
`tests/_helpers.py` unconditionally `os.environ.pop("YOUTUBE_TRANSCRIPT_LIVE_CANARY",
None)`s at import time (its own hermetic-reset comment: an ambient env var left in a
developer's shell must not silently make an otherwise-mocked full-suite run reach
the real network). This module therefore reads the env var into
`_LIVE_CANARY_ENABLED` BEFORE importing `_helpers` -- reversing the two lines would
always observe an empty string, since `_helpers` would already have stripped the
variable from `os.environ` by the time it was read. In a full `unittest discover`
run (default `test*.py` pattern) this read-order fix is moot either way: an
earlier-alphabetical test module (e.g. `test_composition.py`) has already imported
`_helpers` and stripped the var before this module is even loaded, which IS the
intended skip-by-default behavior -- it only matters for the isolated invocation
this file's own `check` uses (`-p test_live_canary.py`, see tasks.md's T-15 block
and the live-canary workflow), where this module's import of `_helpers` is the
first and only one in the process.

Stdlib only.
"""

import os
import unittest

# See the module docstring's "Env-var read/import ORDER" note above: this line
# must run before `_helpers` is imported, or the value would already be gone.
_LIVE_CANARY_ENABLED = os.environ.get("YOUTUBE_TRANSCRIPT_LIVE_CANARY", "") == "1"

import _helpers  # type: ignore[import-not-found]  # noqa: E402,F401
# ^ installs the sys.path shim -- see _helpers.py's module docstring. Also resets
# YOUTUBE_TRANSCRIPT_LIVE_CANARY (see above) and other ambient env vars; nothing
# below depends on any of those being set.

import composition  # noqa: E402
import domain  # noqa: E402
from tools.get_transcript import handle as get_transcript_handle  # noqa: E402

# T-P3's confirmed-stable canary videos (swarm-report/research/youtube-transcript-
# size-measurements.md, section 9, captured 2026-08-02): official uploads, globally
# high-traffic, extremely unlikely to be taken down or to lose captions.
_VIDEO_RICK_ASTLEY = "dQw4w9WgXcQ"  # recommended primary: 6 caption tracks incl. manual `en`
_VIDEO_GANGNAM_STYLE = "9bZkp7q19f0"  # recommended secondary: 1 caption track, `ko` asr
# Bonus third candidate (T-P3): deepest historical validation (2026-08-01 research:
# 1,699-segment full transcript decode succeeded) but a smaller, less permanent
# upload than the two above -- extra signal, not one of the required ">= 2".
_VIDEO_BONUS = "P0uMXS6emHA"

# Outcome mapping (AC-13 / T-15 brief): a provider-side or transport-side hiccup is
# a SKIP (loud, names which one) -- it says nothing about whether the InnerTube
# mechanism itself still works. Any OTHER non-ok status on a video previously
# confirmed to have captions IS the upstream-drift signal this canary exists to
# catch, and fails immediately (including statuses this mapping doesn't name
# explicitly -- e.g. language_unavailable or video_unavailable on one of these
# pinned videos would also be unexpected drift, not a case to special-case away).
_SKIP_STATUSES = {
    domain.Status.BLOCKED_BY_PROVIDER,
    domain.Status.RATE_LIMITED,
    domain.Status.TRANSPORT_ERROR,
}


@unittest.skipUnless(
    _LIVE_CANARY_ENABLED,
    "set YOUTUBE_TRANSCRIPT_LIVE_CANARY=1 to run the real-network InnerTube canary "
    "(also runs unconditionally in the weekly scheduled CI workflow, "
    ".github/workflows/youtube-transcript-live-canary.yml)",
)
class LiveCanaryTest(unittest.TestCase):
    def _run_canary(self, video_id: str, label: str) -> None:
        # Fresh provider + deadline per video: `composition.build_provider()` is a
        # cheap, stateless construction (T-13b) -- the "exactly one call site"
        # invariant `test_composition.py` enforces is scoped to `plugin/server/`
        # only, not `tests/` (this suite's own `test_request_budget.py` already
        # calls it directly, same as here).
        provider = composition.build_provider()
        deadline = composition.build_deadline()

        # No `except DomainFailure` / broad `except Exception` here on purpose: any
        # exception `get_transcript_handle` doesn't itself translate to a
        # `ToolOutcome` (i.e. a genuine response-shape mismatch deep in the real
        # InnerTube parsing) must propagate and fail this test loudly -- catching
        # and downgrading it to a skip or a softer assertion would defeat this
        # canary's entire purpose.
        outcome: domain.ToolOutcome = get_transcript_handle(provider, deadline, {"video": video_id})

        if outcome.status in _SKIP_STATUSES:
            self.skipTest(
                f"{label} ({video_id}): InnerTube mechanism reported "
                f"status={outcome.status.value!r} -- a provider/transport-side "
                f"condition, not a code-correctness failure. See this file's "
                f"module docstring for the outcome-mapping rule."
            )

        self.assertEqual(
            outcome.status,
            domain.Status.OK,
            f"{label} ({video_id}): expected status=ok for a previously-confirmed-"
            f"captioned video, got status={outcome.status.value!r} -- this is "
            f"exactly the upstream-drift signal this canary exists to catch "
            f"(upstream_changed, a response-shape mismatch, or no_transcript on a "
            f"known-good video all surface here).",
        )
        self.assertTrue(
            outcome.payload.get("transcript"),
            f"{label} ({video_id}): status=ok but the returned transcript text is "
            f"empty -- a confirmed-captioned video should never yield empty "
            f"page-1 content, so this is treated as a failure too.",
        )

    def test_rick_astley_dqw4w9wgxcq(self) -> None:
        self._run_canary(_VIDEO_RICK_ASTLEY, "Rick Astley (recommended primary)")

    def test_gangnam_style_9bzkp7q19f0(self) -> None:
        self._run_canary(_VIDEO_GANGNAM_STYLE, "Gangnam Style (recommended secondary)")

    def test_bonus_p0umxs6emha(self) -> None:
        self._run_canary(_VIDEO_BONUS, "bonus third candidate, lower stability guarantee")


if __name__ == "__main__":
    unittest.main()
