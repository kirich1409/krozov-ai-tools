"""Shared domain types, exceptions, and policy tables for the youtube-transcript server.

`domain/` has zero imports from any other in-project package (`net/`, `providers/`,
`formats/`, `protocol/`, `tools/`) -- every other package imports `domain/`, never the
reverse (see `docs/plans/youtube-transcript/plan.md`'s module-layout diagram). Symbols
that would otherwise need a cross-package edge no permitted route reaches live here
instead ("symbol-placement rule", plan.md cycle 7): `FORMATS`, `MAX_SEGMENTS`,
`HTTP_TIMEOUT`, and the rest of the deadline/timeout constants below are examples of
this, moved here from `formats/__init__.py` and `net/client.py` respectively so their
cross-package consumers can reach them via an edge they already have to `domain/`.

Stdlib only. `urllib.parse` is fine to use directly here (only `urllib.request`,
`http.client`, `socket`, `ssl`, and the other egress-capable stdlib modules are
restricted to `net/client.py` by T-3's import-boundary test).
"""

import re
import secrets
import time
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, FrozenSet, Mapping, Optional, Tuple
from urllib.parse import urlsplit

# --- Status enum + policy table ---------------------------------------------


class Status(str, Enum):
    """The closed set of outcomes either tool can report (spec's canonical `status`
    enum) -- 13 members, never added to, renamed, or removed by a later task."""

    OK = "ok"
    NO_TRANSCRIPT = "no_transcript"
    LANGUAGE_UNAVAILABLE = "language_unavailable"
    VIDEO_NOT_FOUND = "video_not_found"
    VIDEO_UNAVAILABLE = "video_unavailable"
    AGE_RESTRICTED = "age_restricted"
    REGION_BLOCKED = "region_blocked"
    LIVE_NOT_READY = "live_not_ready"
    RATE_LIMITED = "rate_limited"
    BLOCKED_BY_PROVIDER = "blocked_by_provider"
    UPSTREAM_CHANGED = "upstream_changed"
    TRANSCRIPT_TOO_LARGE = "transcript_too_large"
    TRANSPORT_ERROR = "transport_error"


# --- Domain-modeled failure hierarchy ---------------------------------------
#
# `DomainFailure` is the common base for every failure this server anticipates and
# can map to a `Status` (as opposed to a genuine bug, which propagates as some other
# exception type and becomes a JSON-RPC -32603, T-13a). `protocol/` is permitted to
# catch `DomainFailure` via its already-allowed `domain/` edge without needing an edge
# to `providers/base.py` (where `ProviderError` itself is declared, T-3) -- that's the
# whole reason this base class lives here rather than in `providers/base.py`.


class DomainFailure(Exception):  # noqa: N818 -- name pinned literally by tasks.md's T-2 block
    """Common base for every domain-modeled failure: `ProviderError` (and its ten
    subclasses, declared in `providers/base.py`, T-3), `DeadlineExpired`,
    `CursorInvalid`, and `TrackFieldInvalid`."""


class TrackFieldInvalid(DomainFailure):
    """Raised by `TrackDescriptor.__post_init__` when `language_code` or `kind` fails
    its validation pattern, or `language_name` exceeds its length bound. Maps to
    `Status.UPSTREAM_CHANGED` via `tools/__init__.py::outcome_from_error` (T-3), same
    as `CursorInvalid` -- this is upstream data drift, not a caller error."""


class CursorInvalid(DomainFailure):
    """Raised by `tools/cursor.py::decode()` (T-8) on a malformed or forged pagination
    cursor. Declared here, not in `tools/cursor.py`, so T-3's/T-14's `DomainFailure`
    totality tests can see it independent of Wave-1's completion (symbol-placement
    rule, same reasoning as `TrackFieldInvalid`)."""


class DeadlineExpired(DomainFailure):
    """Raised when the whole-invocation `Deadline` (below) is exhausted mid-operation.
    Uniformly translated to `Status.TRANSPORT_ERROR` by `outcome_from_error` (T-3)."""


# --- Core data types ---------------------------------------------------------


@dataclass(frozen=True)
class Segment:
    """One decoded caption cue."""

    start_ms: int
    duration_ms: int
    text: str


@dataclass(frozen=True)
class Transcript:
    """The full decoded caption track `ProviderSession.fetch()` (T-3) returns for one
    `TrackDescriptor`."""

    segments: Tuple[Segment, ...]


# `TrackDescriptor.language_code`/`kind` are validated against the same rules AC-18
# applies to a caller-supplied `trackId` at parse time (`providers/base.py::parse_track_id`,
# T-3) -- both patterns are pinned here since `TrackDescriptor.__post_init__` is the
# single point every `TrackDescriptor` -- provider-constructed or response-only -- is
# validated at, with no way to bypass it.
_LANGUAGE_CODE_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,20}$")
_VALID_KINDS = frozenset({"manual", "auto"})
_LANGUAGE_NAME_MAX_LENGTH = 100


@dataclass(frozen=True)
class TrackDescriptor:
    """One caption track's metadata, both as returned by the provider (`estimated_characters`
    left `None`) and as a response-only enriched copy `tools/list_transcript_tracks.py`
    (T-11) constructs with `estimated_characters` populated -- never the same object,
    never mutated in place (`TrackDescriptor` is frozen)."""

    track_id: str
    language_code: str
    language_name: str
    kind: str
    # `Mapping[str, int]` with keys `{"text", "srt", "vtt"}` once populated (AC-1);
    # `None` until `tools/list_transcript_tracks.py` fills it in for the response only
    # -- the provider itself never has `formats.estimate_characters` reachable from
    # `providers/`, see T-10.
    estimated_characters: Optional[Mapping[str, int]]
    is_default: bool

    def __post_init__(self) -> None:
        if not _LANGUAGE_CODE_PATTERN.match(self.language_code):
            raise TrackFieldInvalid("language_code failed validation pattern")
        if self.kind not in _VALID_KINDS:
            raise TrackFieldInvalid("kind failed validation pattern")
        if len(self.language_name) > _LANGUAGE_NAME_MAX_LENGTH:
            raise TrackFieldInvalid(
                f"language_name exceeds {_LANGUAGE_NAME_MAX_LENGTH} characters"
            )


@dataclass(frozen=True)
class TrackListing:
    """The set of caption tracks (possibly empty) plus video-level metadata `open()`
    (T-3/T-10) resolves for one video."""

    tracks: Tuple[TrackDescriptor, ...]
    duration_seconds: int
    default_audio_language: Optional[str]


@dataclass(frozen=True)
class VideoId:
    """An already-normalized, AC-6-validated video identifier -- never the caller's
    raw `video` string."""

    value: str


@dataclass(frozen=True)
class ToolOutcome:
    """The domain-level result of one tool invocation, before `protocol/envelope.py`
    (T-7) turns it into the wire response shape."""

    status: Status
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Deadline:
    """The whole-invocation deadline both tools race against. Constructed once per
    invocation via `Deadline.start(...)` (never re-started mid-call), then threaded
    explicitly through every phase that needs to check it -- never read from global
    state, so tests can inject a fake `clock` with no monkeypatching."""

    deadline_at: float
    clock: Callable[[], float]

    @classmethod
    def start(cls, budget: float, clock: Callable[[], float] = time.monotonic) -> "Deadline":
        return cls(deadline_at=clock() + budget, clock=clock)

    def remaining(self) -> float:
        return self.deadline_at - self.clock()

    def expired(self) -> bool:
        return self.remaining() <= 0


# `STATUS_POLICY` must have exactly one entry per `Status` member (AC-17's totality
# test) and `isError: False` in every row (AC-10) -- no status this server can name is
# ever a genuine bug, by definition; `isError: True` is reserved for exceptions this
# enum doesn't cover at all, which by construction have no row here.
#
# `rate_limited`'s `30` is the *default*, used when upstream sends no `Retry-After`;
# `protocol/envelope.py` (T-7) overrides it at response time with
# `min(max(upstream_value, 30), 300)` when upstream does send one (AC-22) -- that
# override logic is T-7's, not this table's.
STATUS_POLICY: Dict[Status, Tuple[bool, Optional[int], bool]] = {
    Status.OK: (False, None, False),
    Status.NO_TRANSCRIPT: (False, None, False),
    Status.LANGUAGE_UNAVAILABLE: (False, None, False),
    Status.VIDEO_NOT_FOUND: (False, None, False),
    Status.VIDEO_UNAVAILABLE: (False, None, False),
    Status.AGE_RESTRICTED: (False, None, False),
    Status.REGION_BLOCKED: (False, None, False),
    Status.LIVE_NOT_READY: (True, 300, False),
    Status.RATE_LIMITED: (True, 30, False),
    Status.BLOCKED_BY_PROVIDER: (False, None, False),
    Status.UPSTREAM_CHANGED: (False, None, False),
    Status.TRANSCRIPT_TOO_LARGE: (False, None, False),
    Status.TRANSPORT_ERROR: (True, 15, False),
}


# --- Untrusted-content boundary ----------------------------------------------
#
# Replaces an earlier fixed `CONTENT_SENTINEL` constant entirely (plan.md cycle 6
# escalation, spec AC-15's redesign). Six `multiexpert-review` cycles each found a
# genuine defect in some text-transform's obligation to scrub a *known*, predictable
# string out of untrusted caption text -- diagnosed as structural, not a sequence of
# unrelated bugs. `generate_content_boundary()` closes the forgery concern by
# construction instead: since the caption text being wrapped was authored on YouTube
# before this specific tool call (and therefore before this specific boundary value
# exists), an attacker cannot predict or embed a matching forged copy of it. This is
# deliberately NOT a module-level constant -- a fixed value would reintroduce exactly
# the predictability this redesign removes -- so it is a function returning a fresh
# value every call, called once per `protocol/envelope.build()` invocation (T-7).
def generate_content_boundary() -> str:
    return f"<<<UNTRUSTED_CONTENT_{secrets.token_hex(16)}>>>"


# `FORMATS` moved here from `formats/__init__.py` (plan.md cycle 7, symbol-placement
# rule): `protocol/schemas.py` (T-7) has no permitted edge to `formats/`, but every
# module already has one to `domain/`. `formats/__init__.py` re-exports this value
# rather than redefining it.
FORMATS: FrozenSet[str] = frozenset({"text", "srt", "vtt"})

# Moved here from `formats/__init__.py` (cycle 3): three consumers in three packages,
# and `providers/innertube.py` can only reach it via `domain/`.
MAX_SEGMENTS = 100_000

# Pins the mid-pass deadline-check interval used by `formats.encode`/`count_pages_to`
# and the provider's decode steps (cycle 3) -- bounds a `deadline.expired()` check's
# own overshoot to roughly this many segments' processing time.
DEADLINE_CHECK_STRIDE = 1000

# --- The deadline/timeout model, widened per the user's direction ------------
#
# See plan.md's "The deadline/timeout model, widened per the user's direction" section
# for the full derivation and rationale (three review cycles were spent trying to make
# a tight 45s budget close exactly; the user's resolution was to widen it with
# generous margin instead of a fourth round of precision arithmetic).
#
# `HTTP_TIMEOUT` moved here from `net/client.py` (cycle 8) specifically so
# `ENCODE_RESERVE` can be derived from both its operands within `domain/` itself --
# `domain/`'s `ALLOWED_EDGES` row is "nothing", so it could not previously import
# `net/client.py`'s `HTTP_TIMEOUT`. `net/client.py` re-exports `HTTP_TIMEOUT` from
# here for its own socket-level calls.
HTTP_TIMEOUT = 15
# Seconds carved out of `TOOL_CALL_DEADLINE` for the CPU phase itself (decode,
# sanitize, encode), sized against the worst realistic CPU-phase invocation.
CPU_PHASE_BUDGET = 20
# Seconds carved out of `TOOL_CALL_DEADLINE` for the whole invocation.
TOOL_CALL_DEADLINE = 180
# Derived, not chosen independently (cycle 7 fix) -- making the network-phase
# slow-drip reservation (`HTTP_TIMEOUT`) and the CPU-phase allowance
# (`CPU_PHASE_BUDGET`) additive instead of competing for the same headroom. There is
# a test (`test_encode_reserve_is_derived_in_domain`) asserting this exact invariant.
ENCODE_RESERVE = HTTP_TIMEOUT + CPU_PHASE_BUDGET
# Quantifies the previously-unquantified `margin` referenced by T-16's gate 4 and
# T-P3's stop condition (cycle 8) -- sized as roughly one worst-case leg plus
# CPU-phase headroom.
HOST_TIMEOUT_MARGIN = 30


# --- Text sanitization --------------------------------------------------------
#
# Strips Unicode `Cc` (control) union `Cf` (format) union `Cs` (surrogate) categories,
# plus U+2028/U+2029 (line/paragraph separator), preserving `\n`/`\t` -- widened from
# an initial C0/C1-only scope (AC-21). `Cs` (cycle 8) guards against an unpaired
# surrogate codepoint surviving `json.loads` from a malformed upstream response and
# later raising `UnicodeEncodeError` if `json.dumps(..., ensure_ascii=False)` is ever
# used, which in this server's single-threaded stdio loop would abort the whole
# process mid-response rather than just one call.
#
# No sentinel-scrubbing logic of any kind lives here -- that entire design was removed
# in favor of `generate_content_boundary()`'s per-call random values (see above). This
# function is exactly what its name says: control-character stripping, nothing else.
#
# The translation table is built once, at import time, as a module-level constant --
# not reconstructed per call.
def _build_sanitize_translation_table() -> Dict[int, None]:
    preserved = {0x09, 0x0A}  # \t, \n
    extra_strip = {0x2028, 0x2029}
    strip_categories = {"Cc", "Cf", "Cs"}
    table: Dict[int, None] = {}
    for codepoint in range(0x110000):
        if codepoint in preserved:
            continue
        if codepoint in extra_strip or unicodedata.category(chr(codepoint)) in strip_categories:
            table[codepoint] = None
    return table


_SANITIZE_TRANSLATION_TABLE = _build_sanitize_translation_table()


def sanitize_text(s: str) -> str:
    return s.translate(_SANITIZE_TRANSLATION_TABLE)


# --- URL redaction -------------------------------------------------------------
#
# Moved here from `net/` so both `net/` and `providers/` can use it. Strips query,
# fragment, AND reduces `netloc` to the bare hostname (userinfo and port dropped along
# with it) -- cycle 8 widened this from query-only redaction, closing a gap where
# userinfo credentials embedded in a URL would otherwise have survived.
def redact_url(url: str) -> str:
    parsed = urlsplit(url)
    return parsed._replace(query="", fragment="", netloc=parsed.hostname or "").geturl()
