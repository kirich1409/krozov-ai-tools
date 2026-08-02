"""`InnertubeProvider`/`InnertubeSession` -- the concrete `TranscriptProvider` port
(T-3) implementing the watch-page GET -> player POST -> timedtext GET pipeline
`swarm-report/research/research-youtube-subtitles-plugin.md`'s empirical spike (47+
live InnerTube calls) and `swarm-report/research/youtube-transcript-size-measurements.md`
(T-P3) established.

`providers/innertube.py` may import only `domain/`, `net/` (`ALLOWED_EDGES`), plus
same-package `providers/base.py`/`providers/video_ref.py`. Stdlib only.

**Wire-protocol details this module pins that could not be captured against live
traffic in this task's own sandbox (T-P3 found leg 2's player POST returns
`FAILED_PRECONDITION` and leg 3's real caption bytes are unreachable in that same
sandbox, on 2026-08-02 -- see that report's §2/§3) are called out individually
below, each flagged UNVERIFIED, synthesized structurally from the research report's
already-confirmed mechanism (never invented from nothing) per this task's own
fallback instruction:**

- `_CLIENT_VERSION`/`_USER_AGENT`: the research report confirms `ANDROID`/`IOS`
  client context is required (never `WEB`) but does not record an exact client
  version or User-Agent string. **UNVERIFIED** -- a conservative, commonly-cited
  `ANDROID` client version/UA shape, not captured live this pass.
- `_PLAYER_ENDPOINT`: T-P3 §8 states `www.youtube.com` served all 3 legs "in
  practice" for this project's confirmed host set, with `youtubei.googleapis.com`
  recorded as a documented alternate tried but not confirmed working (both attempts
  returned `FAILED_PRECONDITION` in that sandbox). This module uses
  `www.youtube.com` for the player POST on that basis. **UNVERIFIED against a
  successful live player-POST response** (T-P3 never got one, from either host).
- **No `fmt`/`format` query parameter is appended to a track's `baseUrl` before the
  timedtext GET.** This is evidence-grounded, not a guess: the real, live-captured
  `baseUrl` values in `tests/fixtures/innertube_player_response.json` (T-P3) carry
  no `fmt`/`format` parameter at all, and the research report separately observed
  `format="3"` responses from equivalent real captured URLs -- consistent with
  `format=3` being the server's default when the parameter is omitted. Still
  **UNVERIFIED end-to-end** (T-P3 could not fetch real caption bytes this pass --
  every captured `baseUrl` carries an `exp=xpe` marker and returned an empty body
  when fetched live, §3).
- `_build_player_request_body()`'s exact field set (only `context.client.{clientName,
  clientVersion,hl,gl}` + top-level `videoId`) is the minimal shape the research
  report's mechanism describes; a real capture may need additional fields
  (`contentCheckOk`, `racyCheckOk`, `thirdParty`, ...) not documented there.

Every one of the above is the *conservative, most-grounded* choice available from
the research artifacts on hand, not an invented shape -- and every one is called out
again in this task's own report for `/acceptance`'s live-canary pass (T-15) to
confirm or correct against real traffic.
"""

import json
import logging
import random
import re
import time
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Set, Tuple, Type
from urllib.parse import urlencode

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

# --- Client identity (see module docstring: UNVERIFIED, synthesized) -------------
#
# One constant, used for every leg's `User-Agent` header (cycle 9 fix, tasks.md) --
# never `server.py`'s own constant, which this module has no `ALLOWED_EDGES` route
# to anyway (`providers/innertube.py` may only reach `domain/`/`net/`).
_CLIENT_NAME = "ANDROID"
_CLIENT_VERSION = "19.09.37"
_USER_AGENT = f"com.google.android.youtube/{_CLIENT_VERSION} (Linux; U; Android 11) gzip"

_WATCH_PAGE_URL = "https://www.youtube.com/watch?v={video_id}"
_PLAYER_ENDPOINT = "https://www.youtube.com/youtubei/v1/player"

_YT_INITIAL_PLAYER_RESPONSE_MARKER = "ytInitialPlayerResponse"
_API_KEY_PATTERN = re.compile(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"')


def _build_player_request_body(video_id: VideoId) -> Dict[str, Any]:
    return {
        "context": {
            "client": {
                "clientName": _CLIENT_NAME,
                "clientVersion": _CLIENT_VERSION,
                "hl": "en",
                "gl": "US",
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
    further by this provider (leg 2's `ANDROID`/`IOS`-context player response is
    the actual source of truth for playability/captions/videoDetails/microformat --
    a `WEB`-client response is known, per the research report, to hit an earlier
    barrier) -- its presence is used only as a gate: a watch page with the
    assignment genuinely absent (e.g. a consent-interstitial page) is `UpstreamChanged`
    before leg 2 is ever attempted (tasks.md's T-10 block, plan.md's two-step
    dependency note)."""
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

        base_url = self._base_urls[track.track_id]
        # No `fmt`/`format` query parameter appended (see module docstring) -- the
        # URL is used verbatim, so this still passes through `net.fetch()`'s full
        # host/scheme/port allowlist re-check trivially (host unchanged), which is
        # deliberately not skipped here even though it cannot reject anything new.
        response = _fetch_checked(
            base_url,
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

        if deadline.expired():
            raise DeadlineExpired("deadline expired between watch-page parse and player POST")

        # --- Leg 2: player POST (ANDROID client context, never WEB) --------------
        player_url = f"{_PLAYER_ENDPOINT}?{urlencode({'key': api_key})}"
        player_body = json.dumps(_build_player_request_body(video_id)).encode("utf-8")
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
