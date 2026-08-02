"""`InnertubeProvider`/`InnertubeSession` -- the concrete `TranscriptProvider` port
(T-3) implementing the watch-page GET -> player POST -> timedtext GET pipeline
`swarm-report/research/research-youtube-subtitles-plugin.md`'s empirical spike (47+
live InnerTube calls) and `swarm-report/research/youtube-transcript-size-measurements.md`
(T-P3) established.

`providers/innertube.py` may import only `domain/`, `net/` (`ALLOWED_EDGES`), plus
same-package `providers/base.py`/`providers/video_ref.py`. Stdlib only.

**Client identity and timedtext format, CONFIRMED against real live YouTube traffic
on 2026-08-03** (the orchestrator ran live HTTP calls directly, from a session with
real network egress, against real video IDs -- not a sandboxed subagent lacking
egress; see `swarm-report/youtube-transcript-report-live-fix.md` for the receipt):

- **The `ANDROID` client is now blocked at the player-POST leg.** As of 2026-08-03,
  the `ANDROID`-client body this module previously sent returns HTTP 400
  `FAILED_PRECONDITION` on every retry, with no header/body variation curing it
  (proxy host swap, client-version bumps, `contentCheckOk`/`racyCheckOk` additions).
  This is a device-integrity/attestation check YouTube added to native-app client
  endpoints -- unsolvable with a plain HTTP client, and not this plugin's bug.
- **The `WEB` client works for the player-POST leg**, confirmed against two real
  videos, with no cookies and no `Origin`/`Referer` headers required. The two things
  that matter: `context.client.clientName = "WEB"`, and
  `playbackContext.contentPlaybackContext.signatureTimestamp` set to an integer
  extracted from the watch-page HTML (the literal substring `"STS":<digits>`,
  present alongside `INNERTUBE_API_KEY` in the same document already fetched at leg
  1 -- no new request needed). Without `signatureTimestamp`, the `WEB` client
  returns `playabilityStatus.status: "UNPLAYABLE"`, `reason: "Video unavailable"`.
  `_CLIENT_VERSION` is likewise extracted live from the same watch-page HTML
  (`INNERTUBE_CONTEXT_CLIENT_VERSION`) rather than hardcoded, since a fixed client
  version string goes stale. `_USER_AGENT` is a real desktop-browser UA string, since
  the client identity is now `WEB`, not an Android app.
  This does **not** contradict the earlier research report's "never `WEB`" finding --
  that finding was about the *watch-page leg* (leg 1) hitting an earlier barrier
  under a `WEB` request context, which this fix never touches (leg 1 still uses
  `_USER_AGENT` as its own header, independent of `context.client.clientName`, which
  only appears in leg 2's POST body). This fix is about the *player-POST leg* (leg 2)
  using `WEB` context WITH a correct `signatureTimestamp` -- a combination the
  original research never tried.
- `_PLAYER_ENDPOINT` stays `https://www.youtube.com/youtubei/v1/player` -- confirmed
  working as-is, no host switch needed.
- **The timedtext `baseUrl` needs `&fmt=srv3` appended.** A live `baseUrl` fetched
  without any `fmt` parameter returns `<transcript><text start="0.0"
  dur="6.96">...</text></transcript>` -- decimal-seconds `start`/`dur` attributes, a
  shape this module's cue-parsing code (`_decode_segments`) is NOT written against.
  Appending `&fmt=srv3` to the same `baseUrl` returns `<timedtext format="3"><body><p
  t="0" d="6960">...</p></body></timedtext>` -- integer-millisecond `t`/`d`
  attributes, the shape `_decode_segments` expects. The unparameterized default
  changed to the legacy `srv1`-style shape at some point after this module's
  original (correct-at-the-time) inference that `format=3` was the server's default;
  `fmt=srv3` is now appended explicitly, still through `net/client.py`'s full
  host/scheme/port allowlist re-check (unskipped, per this repo's own plan.md).

**Still UNVERIFIED / synthesized** (not covered by the 2026-08-03 live-traffic fix
above -- do not treat these as confirmed just because the client-identity/timedtext-
format facts now are):

- `_build_player_request_body()`'s exact field set beyond `context.client.*` and
  `playbackContext.contentPlaybackContext.signatureTimestamp` -- a real capture may
  need additional fields (`contentCheckOk`, `racyCheckOk`, `thirdParty`, ...) not
  exercised by this fix's live verification.
- The `blocked_by_provider`/age-gate/region-block discriminator marker lists
  (`_BLOCKED_BODY_MARKERS`, `_AGE_REASON_MARKERS`, `_REGION_REASON_MARKERS`) remain
  synthetic placeholders -- the research spike's 47+ live calls, and this fix's own
  2 live videos, never triggered any of them for real.
"""

import json
import logging
import random
import re
import time
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Set, Tuple, Type
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from domain import (
    MAX_SEGMENTS,
    DEADLINE_CHECK_STRIDE,
    Deadline,
    DeadlineExpired,
    Segment,
    Transcript,
    TrackDescriptor,
    TrackFieldInvalid,
    TrackListing,
    VideoId,
    redact_url,
    sanitize_text,
)
from net.client import (
    MalformedUpstream,
    NetError,
    PolicyRejected,
    Response,
    ResponseTooLarge,
    Throttled,
    Transport,
    TransportFailed,
    fetch,
    parse_xml_guarded,
)
from providers.base import (
    AgeRestricted,
    BlockedByProvider,
    LiveNotReady,
    ProviderError,
    ProviderSession,
    RateLimited,
    RegionBlocked,
    TranscriptProvider,
    TranscriptTooLarge,
    TransportError,
    UpstreamChanged,
    VideoNotFound,
    VideoUnavailable,
    encode_track_id,
)
from providers.video_ref import normalize

_LOGGER = logging.getLogger(__name__)

# --- Client identity (see module docstring: confirmed live 2026-08-03) -----------
#
# `_CLIENT_NAME` is a fixed constant, used both for leg 2's POST body
# (`context.client.clientName`) and named here for clarity; `_CLIENT_VERSION` is
# NOT a fixed constant (a hardcoded WEB client version string would go stale) --
# it's extracted live from the watch-page HTML every call, see
# `_extract_client_version()` below. `_USER_AGENT` is used for every leg's
# `User-Agent` header (cycle 9 fix, tasks.md) -- never `server.py`'s own constant,
# which this module has no `ALLOWED_EDGES` route to anyway (`providers/innertube.py`
# may only reach `domain/`/`net/`).
_CLIENT_NAME = "WEB"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_WATCH_PAGE_URL = "https://www.youtube.com/watch?v={video_id}"
_PLAYER_ENDPOINT = "https://www.youtube.com/youtubei/v1/player"

_YT_INITIAL_PLAYER_RESPONSE_MARKER = "ytInitialPlayerResponse"
_API_KEY_PATTERN = re.compile(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"')
# Both extracted from the same watch-page HTML as `INNERTUBE_API_KEY`, no new
# request (module docstring: confirmed live 2026-08-03).
_CLIENT_VERSION_PATTERN = re.compile(r'"INNERTUBE_CONTEXT_CLIENT_VERSION"\s*:\s*"([^"]+)"')
_STS_PATTERN = re.compile(r'"STS"\s*:\s*(\d+)')


def _build_player_request_body(
    video_id: VideoId, client_version: str, signature_timestamp: int
) -> Dict[str, Any]:
    return {
        "context": {
            "client": {
                "clientName": _CLIENT_NAME,
                "clientVersion": client_version,
                "hl": "en",
                "gl": "US",
            }
        },
        "playbackContext": {
            "contentPlaybackContext": {
                "signatureTimestamp": signature_timestamp,
            }
        },
        "videoId": video_id.value,
    }


# --- The two JSON-parsing legs' shared structural-failure set --------------------
#
# `json.JSONDecodeError` is itself a `ValueError` subclass -- listed in tasks.md's
# T-10 acceptance text by name for narrative clarity (it is the exception `json.loads`
# actually raises on malformed JSON), but NOT included again here as a separate tuple
# member: ruff's B014 (redundant exception types) would flag `(JSONDecodeError,
# ValueError)` as one type wholly subsuming the other, and `ValueError` alone already
# catches every `JSONDecodeError` instance -- equivalent coverage, no behavior lost.
_STRUCTURAL_ERRORS: Tuple[Type[BaseException], ...] = (
    KeyError, TypeError, IndexError, RecursionError, ValueError,
)


# --- `blocked_by_provider`/bot-check/age/region marker lists ---------------------
#
# Each an isolated, easily-updated list per plan.md's explicit direction (research
# found ZERO real blocks across 47+ live calls -- there is no empirical basis for
# any of these exact strings; synthetic placeholders only, expected to be corrected
# the moment a real trigger is ever observed instead of optimized for day-one
# correctness against data that doesn't exist yet).
_BLOCKED_BODY_MARKERS: Tuple[str, ...] = (
    "consent.youtube.com",
    "Before you continue to YouTube",
)
_BOT_CHECK_REASON_MARKERS: Tuple[str, ...] = (
    "unusual traffic",
    "not a robot",
)
_AGE_REASON_MARKERS: Tuple[str, ...] = ("age",)
_REGION_REASON_MARKERS: Tuple[str, ...] = ("not available in your country",)


def _looks_blocked_by_body(status: int, body: bytes) -> bool:
    if status != 403:
        return False
    text = body.decode("utf-8", errors="replace")
    return any(marker in text for marker in _BLOCKED_BODY_MARKERS)


def _reason_matches(reason: Optional[str], markers: Tuple[str, ...]) -> bool:
    if not reason:
        return False
    lowered = reason.lower()
    return any(marker in lowered for marker in markers)


# --- net/ NetError -> ProviderError translation (structural totality target) -----
#
# `providers/innertube.py` is the single place a `net/` exception crosses into the
# `ProviderError` hierarchy -- keyed by exact type, not `isinstance`, so
# `tests/test_innertube.py::test_net_error_mapping_totality`'s recursive
# `NetError.__subclasses__()` walk can assert every entry has a row here by exact
# membership.
_NET_ERROR_TO_PROVIDER_ERROR: Dict[Type[NetError], Type[ProviderError]] = {
    ResponseTooLarge: TranscriptTooLarge,
    TransportFailed: TransportError,
    Throttled: RateLimited,
    PolicyRejected: UpstreamChanged,
    MalformedUpstream: UpstreamChanged,
}


def _translate_net_error(error: NetError) -> ProviderError:
    mapped_type = _NET_ERROR_TO_PROVIDER_ERROR.get(type(error))
    if mapped_type is None:
        raise AssertionError(
            f"providers.innertube: no _NET_ERROR_TO_PROVIDER_ERROR row for {type(error).__name__}"
        )
    if isinstance(error, Throttled):
        # `net/client.py::_retry_after` already normalizes a missing/non-numeric
        # `Retry-After` header to `0` -- `retry_after=None` (rather than passing `0`
        # through literally) tells `STATUS_POLICY`'s own default (30) to apply at
        # `protocol/envelope.py` (T-7), instead of a provider-level `0` overriding
        # it with a value that was never really "zero seconds", just "absent/non-
        # numeric" (T-10's `test_retry_after_non_numeric_falls_back`).
        return mapped_type(str(error), retry_after=error.retry_after or None)
    return mapped_type(str(error))


def _fetch_checked(
    url: str,
    *,
    method: str = "GET",
    body: Optional[bytes] = None,
    headers: Optional[Mapping[str, str]] = None,
    deadline: Deadline,
    transport: Transport,
) -> Response:
    try:
        response = fetch(
            url, method=method, body=body, headers=headers, deadline=deadline, transport=transport
        )
    except NetError as error:
        raise _translate_net_error(error) from error
    if _looks_blocked_by_body(response.status, response.body):
        _LOGGER.debug("blocked_by_provider marker matched for %s", redact_url(url))
        raise BlockedByProvider("response matched a blocked_by_provider marker")
    _LOGGER.debug("fetch succeeded for %s (status=%d)", redact_url(url), response.status)
    return response


def _parse_xml_checked(data: bytes) -> Any:
    # Typed `Any`, not `xml.etree.ElementTree.Element` -- `xml.*` is restricted to
    # `net/client.py` everywhere else in this project (AST-enforced,
    # `test_import_boundaries.py`), including as a type-annotation-only import (the
    # checker walks source text via `ast.parse`, not a `TYPE_CHECKING` runtime
    # guard). `parse_xml_guarded`'s real return type is `ElementTree.Element`; this
    # module only ever calls `.iter()`/`.get()`/`.itertext()` on it, all present on
    # `Any` without needing the name imported here.
    try:
        return parse_xml_guarded(data)
    except NetError as error:
        raise _translate_net_error(error) from error


# --- Leg 1: watch-page HTML -> INNERTUBE_API_KEY ----------------------------------


def _extract_api_key(html: str) -> str:
    """Extracts `INNERTUBE_API_KEY` from a watch page's HTML. The embedded
    `ytInitialPlayerResponse = {...};` assignment's own JSON content is not read
    further by this provider (leg 2's player POST response is the actual source of
    truth for playability/captions/videoDetails/microformat) -- its presence is used
    only as a gate: a watch page with the assignment genuinely absent (e.g. a
    consent-interstitial page) is `UpstreamChanged` before leg 2 is ever attempted
    (tasks.md's T-10 block, plan.md's two-step dependency note)."""
    marker_index = html.find(_YT_INITIAL_PLAYER_RESPONSE_MARKER)
    if marker_index == -1:
        raise UpstreamChanged("ytInitialPlayerResponse assignment not found in watch page")

    brace_index = html.find("{", marker_index)
    if brace_index == -1:
        raise UpstreamChanged("ytInitialPlayerResponse assignment malformed (no JSON object found)")

    # Non-regex balanced-brace scan via `json.JSONDecoder().raw_decode` from the
    # found index (tasks.md's explicit instruction) -- the decoded value itself is
    # discarded (see docstring above), only used to prove the assignment parses.
    try:
        json.JSONDecoder().raw_decode(html, brace_index)
    except _STRUCTURAL_ERRORS as error:
        raise UpstreamChanged("malformed ytInitialPlayerResponse JSON") from error

    api_key_match = _API_KEY_PATTERN.search(html)
    if api_key_match is None:
        raise UpstreamChanged("INNERTUBE_API_KEY not found in watch page")
    return api_key_match.group(1)


def _extract_client_version(html: str) -> str:
    """Extracts `INNERTUBE_CONTEXT_CLIENT_VERSION` from the same watch-page HTML
    `_extract_api_key()` reads -- no new request. Used as the `WEB` client's
    `context.client.clientVersion`, live rather than hardcoded, so this module never
    ships a client version string that goes stale (module docstring)."""
    match = _CLIENT_VERSION_PATTERN.search(html)
    if match is None:
        raise UpstreamChanged("INNERTUBE_CONTEXT_CLIENT_VERSION not found in watch page")
    return match.group(1)


def _extract_signature_timestamp(html: str) -> int:
    """Extracts `STS` (signature timestamp) from the same watch-page HTML
    `_extract_api_key()` reads -- no new request. Required by leg 2's `WEB`-client
    player POST (`playbackContext.contentPlaybackContext.signatureTimestamp`);
    without it the player response is `UNPLAYABLE`/"Video unavailable" (module
    docstring, confirmed live 2026-08-03)."""
    match = _STS_PATTERN.search(html)
    if match is None:
        raise UpstreamChanged("STS not found in watch page")
    return int(match.group(1))


# --- Leg 2: playabilityStatus positive gate ---------------------------------------


def _enforce_playability_gate(status_value: Optional[str], reason: Optional[str]) -> None:
    """**Security-critical positive gate**: raises the mapped `ProviderError`
    subclass unless `status_value == "OK"`. Reads only the already-`.get()`-extracted
    plain `status_value`/`reason` values passed in -- this function, and its one
    caller in `InnertubeProvider.open()`, are both deliberately outside the scope of
    `_STRUCTURAL_ERRORS`'s try/except wrapper (cycle-4 finding restated in tasks.md's
    T-10 block: a wrapper scoped broadly enough to also cover this discrimination
    could turn a `KeyError` on a missing `reason` into `upstream_changed`, silently
    defeating this positive gate instead of tripping it).

    The discriminator table below is `docs/plans/youtube-transcript/plan.md`'s
    Provider-port section, transcribed exactly -- three rows empirically confirmed
    (`OK`, `ERROR`/"unavailable", `UNPLAYABLE`/"processing"), the rest synthetic
    fixtures with no observed real-world trigger (research's 47+ live calls never
    surfaced one). Do not invent a more "precise-looking" `reason` string than what
    is here -- see that section for the full rationale."""
    if status_value == "OK":
        return

    if _reason_matches(reason, _BOT_CHECK_REASON_MARKERS):
        raise BlockedByProvider(reason or "bot-check reason string")

    if status_value == "ERROR":
        raise VideoNotFound(reason or "video unavailable")

    if status_value == "UNPLAYABLE":
        if _reason_matches(reason, _REGION_REASON_MARKERS):
            raise RegionBlocked(reason or "")
        if reason is None or "processing" in reason.lower():
            raise LiveNotReady(reason or "")
        raise VideoUnavailable(reason or "")

    if status_value == "LOGIN_REQUIRED":
        if _reason_matches(reason, _AGE_REASON_MARKERS):
            raise AgeRestricted(reason or "")
        raise VideoUnavailable(reason or "")

    if status_value in ("AGE_CHECK_REQUIRED", "CONTENT_CHECK_REQUIRED"):
        raise AgeRestricted(reason or "")

    if status_value == "LIVE_STREAM_OFFLINE":
        raise LiveNotReady(reason or "")

    raise VideoUnavailable(reason or f"unrecognized playabilityStatus.status: {status_value!r}")


# --- Leg 2: captions/videoDetails/microformat structural extraction --------------

_MISSING = object()


class _ParsedListing(NamedTuple):
    tracks: Tuple[TrackDescriptor, ...]
    duration_seconds: int
    default_audio_language: Optional[str]
    base_urls: Dict[str, str]


def _default_track_indices(renderer: Mapping[str, Any]) -> Set[int]:
    """Which `captionTracks` indices are each an audio track's default, per
    `playerCaptionsTracklistRenderer.audioTracks[].defaultCaptionTrackIndex` --
    not documented explicitly by the research report (a structural inference from
    the field's own name and the fixture's shape, T-P3's committed
    `innertube_player_response.json`), flagged here as an assumption for
    `/acceptance` to verify against real multi-audio-track traffic."""
    indices: Set[int] = set()
    audio_tracks = renderer.get("audioTracks") or []
    for audio_track in audio_tracks:
        if isinstance(audio_track, dict):
            index = audio_track.get("defaultCaptionTrackIndex")
            if isinstance(index, int):
                indices.add(index)
    return indices


def _track_language_name(raw_track: Mapping[str, Any]) -> str:
    name_obj = raw_track.get("name")
    if isinstance(name_obj, dict) and isinstance(name_obj.get("simpleText"), str):
        return name_obj["simpleText"]
    track_name = raw_track.get("trackName")
    return track_name if isinstance(track_name, str) else ""


def _extract_listing(player_response: Any) -> _ParsedListing:
    """Structural extraction of `videoDetails`/`microformat`/`captions` from an
    already-JSON-decoded, already-`playabilityStatus`-gated (`status == "OK"`)
    player response. Every `KeyError`/`TypeError`/`IndexError`/`RecursionError`/
    `ValueError` this raises (directly, or via a raw dict/list access) is caught by
    this function's one caller and mapped to `UpstreamChanged` -- this function
    itself also raises `UpstreamChanged` directly for the two shapes tasks.md names
    explicitly (case (c) of the captions three-way discrimination, and "every track
    dropped"), which is NOT re-caught by that same wrapper (`UpstreamChanged` is not
    a member of `_STRUCTURAL_ERRORS`), so both raise paths are equally load-bearing."""
    if not isinstance(player_response, dict):
        raise TypeError("player response is not a JSON object")

    video_details = player_response["videoDetails"]
    if not isinstance(video_details, dict):
        raise TypeError("videoDetails is not a JSON object")
    duration_seconds = int(video_details["lengthSeconds"])

    default_audio_language = video_details.get("defaultAudioLanguage")
    if default_audio_language is None:
        microformat = player_response.get("microformat")
        if isinstance(microformat, dict):
            renderer = microformat.get("playerMicroformatRenderer")
            if isinstance(renderer, dict):
                default_audio_language = renderer.get("defaultAudioLanguage")

    # --- Three-way `captions`-container discrimination (tasks.md, plan.md) -------
    if "captions" not in player_response:
        # (a) `captions` key absent entirely -- legitimate, most videos have none.
        return _ParsedListing(
            tracks=(), duration_seconds=duration_seconds,
            default_audio_language=default_audio_language, base_urls={},
        )

    captions = player_response["captions"]
    renderer = captions.get("playerCaptionsTracklistRenderer") if isinstance(captions, dict) else None
    if not isinstance(renderer, dict):
        # (c) `captions` present, expected sub-structure missing/wrong type.
        raise UpstreamChanged("captions.playerCaptionsTracklistRenderer missing or malformed")

    raw_tracks = renderer.get("captionTracks", _MISSING)
    if raw_tracks is _MISSING or not isinstance(raw_tracks, list):
        # (c) same -- one level deeper (captionTracks itself absent/wrong type).
        raise UpstreamChanged(
            "captions.playerCaptionsTracklistRenderer.captionTracks missing or malformed"
        )

    if not raw_tracks:
        # (b) renderer present with captionTracks: [] -- legitimate, no captions.
        return _ParsedListing(
            tracks=(), duration_seconds=duration_seconds,
            default_audio_language=default_audio_language, base_urls={},
        )

    default_indices = _default_track_indices(renderer)
    tracks = []
    base_urls: Dict[str, str] = {}
    dropped = 0
    for index, raw_track in enumerate(raw_tracks):
        language_code = raw_track["languageCode"]
        base_url = raw_track["baseUrl"]
        if not isinstance(base_url, str) or not base_url:
            raise TypeError("captionTracks[].baseUrl missing or wrong type")
        kind = "auto" if raw_track.get("kind") == "asr" else "manual"
        try:
            descriptor = TrackDescriptor(
                track_id=encode_track_id(kind, language_code),
                language_code=language_code,
                language_name=sanitize_text(_track_language_name(raw_track)),
                kind=kind,
                estimated_characters=None,
                is_default=index in default_indices,
            )
        except TrackFieldInvalid:
            # Per-track drop -- a malformed language_code/kind/overlong name on one
            # track among several legitimate ones shouldn't fail the whole video
            # (tasks.md's T-10 block).
            dropped += 1
            continue
        tracks.append(descriptor)
        base_urls[descriptor.track_id] = base_url

    if dropped:
        _LOGGER.debug("dropped %d malformed caption track(s) during validation", dropped)

    if not tracks:
        # Validation dropped every single track from a non-empty upstream list --
        # fail closed to `UpstreamChanged`, not a silent empty `TrackListing`
        # (cycle 6 security fix, tasks.md's T-10 block).
        raise UpstreamChanged(
            f"all {len(raw_tracks)} caption track(s) were dropped during per-track validation"
        )

    return _ParsedListing(
        tracks=tuple(tracks),
        duration_seconds=duration_seconds,
        default_audio_language=default_audio_language,
        base_urls=base_urls,
    )


# --- Leg 3: timedtext XML -> Segment decode ---------------------------------------


def _append_fmt_srv3(base_url: str) -> str:
    """Appends `fmt=srv3` to a track's `baseUrl` query string via
    `urlsplit`/`parse_qsl`/`urlencode` (not naive string concatenation, which would
    mishandle a `baseUrl` that already ends in `?` vs. one that doesn't). Confirmed
    live 2026-08-03 (module docstring): without `fmt=srv3` the timedtext response is
    `<transcript><text start=".." dur="..">` (decimal seconds) -- a shape
    `_decode_segments()` is NOT written against; with it, the response is
    `<timedtext format="3"><body><p t=".." d="..">` (integer milliseconds), the
    shape `_decode_segments()` expects."""
    parts = urlsplit(base_url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("fmt", "srv3"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _decode_segments(root: Any, deadline: Deadline) -> Tuple[Segment, ...]:
    """Streams `<p t="ms" d="ms">text</p>` cues out of the parsed timedtext tree via
    `root.iter("p")` -- deliberately not anchored to a specific `<body>` nesting
    depth (the research report's own Evidence section and `net/client.py`'s XML-guard
    docstring describe this element's containing structure slightly differently;
    `iter("p")` is correct regardless of which is the real shape). Raises
    `TranscriptTooLarge` the instant the running count would exceed `MAX_SEGMENTS`,
    before appending that element -- never materializes an unbounded tuple first.
    `deadline.expired()` is checked every `DEADLINE_CHECK_STRIDE` cues (imported from
    `domain/`, same stride `formats/_paging.py` uses for its own decode-adjacent
    passes), cumulative across the whole decode, not reset per chunk."""
    segments: List[Segment] = []
    stride = 0
    for element in root.iter("p"):
        if len(segments) >= MAX_SEGMENTS:
            raise TranscriptTooLarge(f"transcript exceeds MAX_SEGMENTS={MAX_SEGMENTS}")

        raw_start = element.get("t")
        raw_duration = element.get("d")
        try:
            start_ms = int(raw_start) if raw_start is not None else 0
            duration_ms = int(raw_duration) if raw_duration is not None else 0
        except (TypeError, ValueError) as error:
            raise UpstreamChanged("malformed timedtext cue (t/d not numeric)") from error

        text = sanitize_text("".join(element.itertext()))
        segments.append(Segment(start_ms=start_ms, duration_ms=duration_ms, text=text))

        stride += 1
        if stride >= DEADLINE_CHECK_STRIDE:
            stride = 0
            if deadline.expired():
                raise DeadlineExpired(
                    "deadline expired during timedtext decode "
                    f"(checked every {DEADLINE_CHECK_STRIDE} segments)"
                )
    return tuple(segments)


# --- The session ------------------------------------------------------------------


class InnertubeSession(ProviderSession):
    """Holds one video's already-resolved `TrackListing` plus the private
    `track_id -> baseUrl` map `InnertubeProvider.open()` built for it (never on
    `TrackDescriptor` itself, which carries no upstream-URL field) -- both as this
    session's own instance attributes, never on `InnertubeProvider` (T-10's
    `test_provider_holds_no_per_video_state`)."""

    def __init__(
        self,
        listing: TrackListing,
        base_urls: Mapping[str, str],
        transport: Transport,
    ) -> None:
        self.listing = listing
        self._base_urls = base_urls
        # The exact same `Transport` object `InnertubeProvider.__init__` constructed
        # once and `open()` passed through -- never a fresh one, never just the bare
        # `sleep`/`jitter` callables re-threaded separately (cycle 8, tasks.md).
        self._transport = transport

    def fetch(self, track: TrackDescriptor, deadline: Deadline) -> Transcript:
        if track not in self.listing.tracks:
            raise UpstreamChanged("fetch() called with a track not in this session's listing")

        if deadline.expired():
            raise DeadlineExpired("deadline expired before timedtext decode")

        # `fmt=srv3` appended (see module docstring, confirmed live 2026-08-03) --
        # the resulting URL still passes through `net.fetch()`'s full
        # host/scheme/port allowlist re-check (host unchanged from the original
        # `baseUrl`'s host), which is deliberately not skipped even though it
        # cannot reject anything new.
        timedtext_url = _append_fmt_srv3(self._base_urls[track.track_id])
        response = _fetch_checked(
            timedtext_url,
            headers={"User-Agent": _USER_AGENT},
            deadline=deadline,
            transport=self._transport,
        )
        root = _parse_xml_checked(response.body)
        segments = _decode_segments(root, deadline)
        return Transcript(segments=segments)


# --- The provider -------------------------------------------------------------


class InnertubeProvider(TranscriptProvider):
    """Stateless port: `open()` never stores per-video state on `self` -- the one
    instance attribute this class ever has is `_transport`, set once in `__init__`
    and never reassigned (T-10's `test_provider_holds_no_per_video_state`)."""

    def __init__(
        self,
        *,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        # One `Transport` constructed here and stored -- never the two bare
        # `sleep`/`jitter` callables threaded separately (cycle 8, tasks.md).
        self._transport = Transport(sleep=sleep, jitter=jitter)

    def normalize_video_ref(self, value: str) -> Optional[VideoId]:
        return normalize(value)

    def open(self, video_id: VideoId, deadline: Deadline) -> "InnertubeSession":
        # --- Leg 1: watch-page GET -> INNERTUBE_API_KEY ---------------------------
        watch_url = _WATCH_PAGE_URL.format(video_id=video_id.value)
        watch_response = _fetch_checked(
            watch_url,
            headers={"User-Agent": _USER_AGENT},
            deadline=deadline,
            transport=self._transport,
        )
        html = watch_response.body.decode("utf-8", errors="replace")
        api_key = _extract_api_key(html)
        client_version = _extract_client_version(html)
        signature_timestamp = _extract_signature_timestamp(html)

        if deadline.expired():
            raise DeadlineExpired("deadline expired between watch-page parse and player POST")

        # --- Leg 2: player POST (WEB client context + signatureTimestamp, --------
        # confirmed live 2026-08-03 -- see module docstring) -----------------------
        player_url = f"{_PLAYER_ENDPOINT}?{urlencode({'key': api_key})}"
        player_body = json.dumps(
            _build_player_request_body(video_id, client_version, signature_timestamp)
        ).encode("utf-8")
        player_response_raw = _fetch_checked(
            player_url,
            method="POST",
            body=player_body,
            headers={"User-Agent": _USER_AGENT, "Content-Type": "application/json"},
            deadline=deadline,
            transport=self._transport,
        )

        try:
            player_response = json.loads(player_response_raw.body.decode("utf-8"))
        except _STRUCTURAL_ERRORS as error:
            raise UpstreamChanged("malformed player-response JSON") from error

        # --- Positive playability gate (security-critical, NOT wrapped above) ----
        playability = (
            player_response.get("playabilityStatus") if isinstance(player_response, dict) else None
        )
        if not isinstance(playability, dict):
            playability = {}
        _enforce_playability_gate(playability.get("status"), playability.get("reason"))

        # --- Structural extraction (captions/videoDetails/microformat) -----------
        try:
            parsed = _extract_listing(player_response)
        except _STRUCTURAL_ERRORS as error:
            raise UpstreamChanged("malformed player-response structure") from error

        if deadline.expired():
            raise DeadlineExpired("deadline expired after player-response parse")

        listing = TrackListing(
            tracks=parsed.tracks,
            duration_seconds=parsed.duration_seconds,
            default_audio_language=parsed.default_audio_language,
        )
        return InnertubeSession(listing=listing, base_urls=parsed.base_urls, transport=self._transport)
