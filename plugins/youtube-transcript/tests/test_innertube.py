"""Tests for `providers/innertube.py` (T-10): the InnerTube provider port -- watch-page
GET -> player POST -> timedtext GET. See `docs/plans/youtube-transcript/tasks.md`'s
T-10 block for the full acceptance criteria this file's `check` list is drawn from,
and `swarm-report/youtube-transcript-report-T-10.md` for which wire-protocol details
(client version/UA, player host, request-body shape) are synthesized/unverified
against live traffic rather than captured this pass.

No live network egress is used anywhere in this file -- every test replaces
`providers.innertube.fetch` (the module-level name `_fetch_checked` calls) with an
in-process fake that returns/raises pre-built `net.client.Response`/exception values,
following the same "double the one crossing-the-boundary call" pattern
`tests/test_net_client_resources.py`/`_helpers.py`'s `mock_urlopen` use one layer
down. Real `net.client.parse_xml_guarded` runs unfaked against synthetic timedtext
XML bytes (no network involved, so no need to fake it too).
"""

import json
import unittest
from typing import Any, Dict, List, Optional, Sequence, Union
from unittest import mock
from urllib.parse import parse_qsl, urlsplit
from xml.etree import ElementTree

import _helpers  # type: ignore[import-not-found]  # noqa: F401
# ^ installs the sys.path shim -- see _helpers.py's module docstring.

import domain
import net.client as net_client
import providers.base as providers_base
import providers.innertube as innertube

_VIDEO_ID = domain.VideoId(value="dQw4w9WgXcQ")
_VIDEO_ID_2 = domain.VideoId(value="9bZkp7q19f0")


# --- Fixture builders ---------------------------------------------------------


def _watch_page_html(
    *,
    api_key: str = "TEST_INNERTUBE_API_KEY",
    with_player_response: bool = True,
    client_version: str = "2.20240101.00.00",
    sts: int = 12345,
) -> str:
    if not with_player_response:
        # A consent-interstitial-shaped page: no `ytInitialPlayerResponse` assignment
        # at all (tasks.md's T-10 block, plan.md's two-step-dependency note).
        return "<html><body>Before you continue, please accept cookies.</body></html>"
    return (
        "<html><head></head><body><script>"
        'var ytInitialPlayerResponse = {"videoDetails": {"videoId": "stub"}};'
        "</script>"
        "<script>"
        f'ytcfg.set({{"INNERTUBE_API_KEY":"{api_key}","INNERTUBE_CONTEXT":{{}},'
        f'"INNERTUBE_CONTEXT_CLIENT_VERSION":"{client_version}","STS":{sts}}});'
        "</script></body></html>"
    )


_DEFAULT_CAPTION_TRACKS: List[Dict[str, Any]] = [
    {
        "baseUrl": "https://www.youtube.com/api/timedtext?v=x&lang=en",
        "languageCode": "en",
        "name": {"simpleText": "English"},
        "trackName": "",
        "isTranslatable": True,
    },
    {
        "baseUrl": "https://www.youtube.com/api/timedtext?v=x&lang=en&kind=asr",
        "languageCode": "en",
        "kind": "asr",
        "name": {"simpleText": "English (auto-generated)"},
        "trackName": "",
        "isTranslatable": True,
    },
]

_MISSING = object()


def _player_response(
    *,
    status: str = "OK",
    reason: Union[str, None, object] = _MISSING,
    length_seconds: str = "600",
    default_audio_language: Optional[str] = None,
    microformat_default_audio_language: Optional[str] = None,
    include_video_details: bool = True,
    include_captions: bool = True,
    caption_tracks: Any = _MISSING,
    captions_renderer_missing: bool = False,
    caption_tracks_key_renamed: bool = False,
    audio_tracks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Builds a synthetic already-JSON-decodable player-response dict (the shape
    `InnertubeProvider.open()`'s leg 2 consumes). `_MISSING` sentinels distinguish
    "field genuinely absent" from "field present with value None", matching the
    real structural distinctions T-10's acceptance cares about."""
    playability: Dict[str, Any] = {"status": status}
    if reason is not _MISSING:
        playability["reason"] = reason
    response: Dict[str, Any] = {"playabilityStatus": playability}

    if include_video_details:
        video_details: Dict[str, Any] = {"lengthSeconds": length_seconds}
        if default_audio_language is not None:
            video_details["defaultAudioLanguage"] = default_audio_language
        response["videoDetails"] = video_details

    if microformat_default_audio_language is not None:
        response["microformat"] = {
            "playerMicroformatRenderer": {"defaultAudioLanguage": microformat_default_audio_language}
        }

    if include_captions:
        if captions_renderer_missing:
            response["captions"] = {"someOtherKey": True}
        else:
            renderer: Dict[str, Any] = {}
            tracks = _DEFAULT_CAPTION_TRACKS if caption_tracks is _MISSING else caption_tracks
            if caption_tracks_key_renamed:
                renderer["captionTrack"] = tracks  # typo'd key -- captionTracks absent
            else:
                renderer["captionTracks"] = tracks
            if audio_tracks is not None:
                renderer["audioTracks"] = audio_tracks
            response["captions"] = {"playerCaptionsTracklistRenderer": renderer}

    return response


def _timedtext_xml(cues: Sequence[tuple]) -> bytes:
    body = "".join(f'<p t="{t}" d="{d}">{text}</p>' for t, d, text in cues)
    return f'<timedtext format="3"><body>{body}</body></timedtext>'.encode("utf-8")


def _ok_response(body: bytes, *, status: int = 200) -> net_client.Response:
    return net_client.Response(status=status, headers={}, body=body)


def _player_ok_response(player_response: Dict[str, Any]) -> net_client.Response:
    return _ok_response(json.dumps(player_response).encode("utf-8"))


def _watch_ok_response(**kwargs: Any) -> net_client.Response:
    return _ok_response(_watch_page_html(**kwargs).encode("utf-8"))


class _FakeFetch:
    """Replaces `providers.innertube.fetch`: pops the next queued `Response` (or
    raises the next queued exception) per call, in order, recording every call's
    kwargs for assertions -- the same "queue of canned responses + call log"
    shape `_helpers.py::mock_urlopen` uses one layer down, at this module's own
    `fetch()` boundary instead."""

    def __init__(self, responses: Sequence[Union[net_client.Response, BaseException]]) -> None:
        self._queue: List[Union[net_client.Response, BaseException]] = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def __call__(
        self,
        url: str,
        *,
        method: str = "GET",
        body: Any = None,
        headers: Any = None,
        deadline: Any = None,
        transport: Any = None,
    ) -> net_client.Response:
        self.calls.append(
            {
                "url": url,
                "method": method,
                "body": body,
                "headers": headers,
                "deadline": deadline,
                "transport": transport,
            }
        )
        if not self._queue:
            raise AssertionError("_FakeFetch: no more responses queued")
        item = self._queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _queue_clock(values: Sequence[float]):
    remaining = list(values)

    def clock() -> float:
        if not remaining:
            raise AssertionError("_queue_clock: exhausted")
        return remaining.pop(0)

    return clock


# --- 1/2: the positive playability gate ----------------------------------------


class TestNonOkPlayabilityRaisesSpecificSubclass(unittest.TestCase):
    def test_non_ok_playability_raises_specific_subclass(self) -> None:
        cases = {
            "UNPLAYABLE": providers_base.LiveNotReady,
            "LOGIN_REQUIRED": providers_base.VideoUnavailable,
            "AGE_CHECK_REQUIRED": providers_base.AgeRestricted,
            "CONTENT_CHECK_REQUIRED": providers_base.AgeRestricted,
            "LIVE_STREAM_OFFLINE": providers_base.LiveNotReady,
            "SOME_FUTURE_VALUE": providers_base.VideoUnavailable,
        }
        for status_value, expected_cls in cases.items():
            with self.subTest(status=status_value), self.assertRaises(expected_cls):
                innertube._enforce_playability_gate(status_value, None)

        # Bonus branch coverage (not itself a separately-named check-list test, but
        # directly grounded in plan.md's discriminator table's reason-dependent
        # rows): a reason string that DOES match closes the other half of each
        # conditional branch `_enforce_playability_gate` has.
        with self.assertRaises(providers_base.AgeRestricted):
            innertube._enforce_playability_gate("LOGIN_REQUIRED", "Sign in to confirm your age")
        with self.assertRaises(providers_base.RegionBlocked):
            innertube._enforce_playability_gate("UNPLAYABLE", "This video is not available in your country")
        with self.assertRaises(providers_base.VideoNotFound):
            innertube._enforce_playability_gate("ERROR", "This video is unavailable")
        with self.assertRaises(providers_base.BlockedByProvider):
            innertube._enforce_playability_gate("ERROR", "We have detected unusual traffic")
        # And the positive case itself: "OK" returns, never raises.
        innertube._enforce_playability_gate("OK", None)


class TestAgeReasonMarkerDoesNotFalsePositiveOnUnrelatedSubstring(unittest.TestCase):
    """`_reason_matches`'s `_AGE_REASON_MARKERS = ("age",)` previously did a bare
    substring test (`"age" in lowered`), so any `LOGIN_REQUIRED` reason string
    containing "age" as a substring of an unrelated word -- "language", "storage",
    "usage" -- was misclassified as `AgeRestricted` instead of the correct
    `VideoUnavailable`. This is a synthetic, not-empirically-observed discriminator
    (`_enforce_playability_gate`'s own docstring) -- these reason strings are
    illustrative, not real reason text this project ever saw."""

    def test_language_substring_does_not_trigger_age_restricted(self) -> None:
        with self.assertRaises(providers_base.VideoUnavailable):
            innertube._enforce_playability_gate(
                "LOGIN_REQUIRED", "This video is not available in your language"
            )

    def test_storage_substring_does_not_trigger_age_restricted(self) -> None:
        with self.assertRaises(providers_base.VideoUnavailable):
            innertube._enforce_playability_gate("LOGIN_REQUIRED", "storage error")

    def test_usage_substring_does_not_trigger_age_restricted(self) -> None:
        with self.assertRaises(providers_base.VideoUnavailable):
            innertube._enforce_playability_gate("LOGIN_REQUIRED", "usage limit exceeded")

    def test_real_age_word_still_triggers_age_restricted(self) -> None:
        # Contrast case, so the fix above can't pass by vacuously rejecting
        # everything -- a reason where "age" really is its own word must still
        # raise AgeRestricted.
        with self.assertRaises(providers_base.AgeRestricted):
            innertube._enforce_playability_gate("LOGIN_REQUIRED", "Sign in to confirm your age")


class TestPlayabilityReasonReadViaGetNotSwallowed(unittest.TestCase):
    def test_playability_reason_read_via_get_not_swallowed_by_json_wrapper(self) -> None:
        # `reason` genuinely absent (not merely `None`) -- if the discrimination
        # block were wrapped by the same try/except as the JSON-structural-failure
        # handler, a `.get()`-free implementation's `KeyError` here could have been
        # silently turned into `UpstreamChanged` instead of tripping the specific
        # mapped subclass (cycle-4 finding). This proves the real path: a status of
        # `LOGIN_REQUIRED` with no `reason` key at all still raises the exact
        # expected subclass, never `UpstreamChanged`.
        response = _player_response(status="LOGIN_REQUIRED", reason=_MISSING)
        self.assertNotIn("reason", response["playabilityStatus"])
        fake_fetch = _FakeFetch([_watch_ok_response(), _player_ok_response(response)])
        provider = innertube.InnertubeProvider(sleep=lambda s: None, jitter=lambda a, b: 0.0)
        with mock.patch.object(innertube, "fetch", fake_fetch), \
                self.assertRaises(providers_base.VideoUnavailable) as ctx:
            provider.open(_VIDEO_ID, domain.Deadline.start(60))
        self.assertNotIsInstance(ctx.exception, providers_base.UpstreamChanged)


# --- 3/4: the three-way captions-container discrimination ----------------------


class TestOpenAlwaysSucceedsEmptyTracksWhenNoCaptions(unittest.TestCase):
    def _open_with(self, player_response: Dict[str, Any]) -> "innertube.InnertubeSession":
        fake_fetch = _FakeFetch([_watch_ok_response(), _player_ok_response(player_response)])
        provider = innertube.InnertubeProvider(sleep=lambda s: None, jitter=lambda a, b: 0.0)
        with mock.patch.object(innertube, "fetch", fake_fetch):
            return provider.open(_VIDEO_ID, domain.Deadline.start(60))

    def test_open_always_succeeds_empty_tracks_when_no_captions(self) -> None:
        # (a) `captions` key absent entirely.
        session_a = self._open_with(_player_response(include_captions=False, length_seconds="123"))
        self.assertEqual(session_a.listing.tracks, ())
        self.assertEqual(session_a.listing.duration_seconds, 123)

        # (b) `playerCaptionsTracklistRenderer` present with `captionTracks: []`.
        session_b = self._open_with(_player_response(caption_tracks=[], length_seconds="456"))
        self.assertEqual(session_b.listing.tracks, ())
        self.assertEqual(session_b.listing.duration_seconds, 456)


class TestCaptionsShapeChangeIsUpstreamChanged(unittest.TestCase):
    def _open_expect_upstream_changed(self, player_response: Dict[str, Any]) -> None:
        fake_fetch = _FakeFetch([_watch_ok_response(), _player_ok_response(player_response)])
        provider = innertube.InnertubeProvider(sleep=lambda s: None, jitter=lambda a, b: 0.0)
        with mock.patch.object(innertube, "fetch", fake_fetch), \
                self.assertRaises(providers_base.UpstreamChanged):
            provider.open(_VIDEO_ID, domain.Deadline.start(60))

    def test_captions_shape_change_is_upstream_changed_not_no_transcript(self) -> None:
        # (c) `captions` present, `playerCaptionsTracklistRenderer` missing.
        with self.subTest("renderer missing"):
            self._open_expect_upstream_changed(_player_response(captions_renderer_missing=True))

        # (c) `captions` present, `captionTracks` itself renamed/absent.
        with self.subTest("captionTracks renamed"):
            self._open_expect_upstream_changed(_player_response(caption_tracks_key_renamed=True))

        # Every track dropped by per-track validation from a non-empty upstream
        # list -- fails closed to `UpstreamChanged`, not a silent empty listing
        # (cycle 6 security fix).
        with self.subTest("all tracks dropped"):
            all_invalid = [
                {"baseUrl": "https://www.youtube.com/api/timedtext?v=x", "languageCode": "has space"},
                {"baseUrl": "https://www.youtube.com/api/timedtext?v=y", "languageCode": "de", "trackName": "x" * 101},
            ]
            with self.assertRaises(providers_base.UpstreamChanged):
                innertube._extract_listing(_player_response(caption_tracks=all_invalid))


# --- 5: statelessness ------------------------------------------------------------


class TestProviderHoldsNoPerVideoState(unittest.TestCase):
    def test_provider_holds_no_per_video_state(self) -> None:
        provider = innertube.InnertubeProvider(sleep=lambda s: None, jitter=lambda a, b: 0.0)
        before = dict(vars(provider))

        fake_fetch_1 = _FakeFetch(
            [_watch_ok_response(), _player_ok_response(_player_response(length_seconds="100"))]
        )
        with mock.patch.object(innertube, "fetch", fake_fetch_1):
            session_1 = provider.open(_VIDEO_ID, domain.Deadline.start(60))

        fake_fetch_2 = _FakeFetch(
            [_watch_ok_response(), _player_ok_response(_player_response(length_seconds="200"))]
        )
        with mock.patch.object(innertube, "fetch", fake_fetch_2):
            session_2 = provider.open(_VIDEO_ID_2, domain.Deadline.start(60))

        after = dict(vars(provider))
        self.assertEqual(before, after)
        self.assertIsNot(session_1.listing, session_2.listing)
        self.assertNotEqual(session_1.listing.duration_seconds, session_2.listing.duration_seconds)


# --- 6: fetch() precondition ------------------------------------------------------


class TestFetchRejectsForeignDescriptor(unittest.TestCase):
    def test_fetch_rejects_foreign_descriptor(self) -> None:
        fake_fetch = _FakeFetch([_watch_ok_response(), _player_ok_response(_player_response())])
        provider = innertube.InnertubeProvider(sleep=lambda s: None, jitter=lambda a, b: 0.0)
        with mock.patch.object(innertube, "fetch", fake_fetch):
            session = provider.open(_VIDEO_ID, domain.Deadline.start(60))

        foreign = domain.TrackDescriptor(
            track_id="manual:zz", language_code="zz", language_name="Zulu",
            kind="manual", estimated_characters=None, is_default=False,
        )
        self.assertNotIn(foreign, session.listing.tracks)
        with mock.patch.object(innertube, "fetch", _FakeFetch([])), \
                self.assertRaises(providers_base.UpstreamChanged):
            session.fetch(foreign, domain.Deadline.start(60))


# --- 7: NetError -> ProviderError structural totality -----------------------------


def _all_net_error_subclasses(base: type) -> List[type]:
    result: List[type] = []
    stack = list(base.__subclasses__())
    while stack:
        cls = stack.pop()
        result.append(cls)
        stack.extend(cls.__subclasses__())
    return result


class TestNetErrorMappingTotality(unittest.TestCase):
    def test_net_error_mapping_totality(self) -> None:
        subclasses = _all_net_error_subclasses(net_client.NetError)
        self.assertGreater(len(subclasses), 0)
        for cls in subclasses:
            with self.subTest(cls=cls.__name__):
                self.assertIn(cls, innertube._NET_ERROR_TO_PROVIDER_ERROR, f"{cls.__name__} has no STATUS_POLICY row")
                mapped = innertube._NET_ERROR_TO_PROVIDER_ERROR[cls]  # type: ignore[index]
                self.assertTrue(issubclass(mapped, providers_base.ProviderError))
                self.assertIn(mapped.status, domain.STATUS_POLICY)

        self.assertIs(innertube._NET_ERROR_TO_PROVIDER_ERROR[net_client.PolicyRejected], providers_base.UpstreamChanged)
        self.assertIs(
            innertube._NET_ERROR_TO_PROVIDER_ERROR[net_client.ResponseTooLarge], providers_base.TranscriptTooLarge
        )


# --- 8/9: JSON-structural-failure mapping -----------------------------------------


class TestJsonStructuralFailuresMapToUpstreamChanged(unittest.TestCase):
    def _open_expect_upstream_changed(self, leg2_body: bytes) -> None:
        fake_fetch = _FakeFetch([_watch_ok_response(), _ok_response(leg2_body)])
        provider = innertube.InnertubeProvider(sleep=lambda s: None, jitter=lambda a, b: 0.0)
        with mock.patch.object(innertube, "fetch", fake_fetch), \
                self.assertRaises(providers_base.UpstreamChanged):
            provider.open(_VIDEO_ID, domain.Deadline.start(60))

    def test_json_structural_failures_map_to_upstream_changed(self) -> None:
        with self.subTest("truncated JSON body"):
            self._open_expect_upstream_changed(b'{"playabilityStatus": {"stat')

        with self.subTest("HTML consent page instead of JSON"):
            self._open_expect_upstream_changed(b"<html><body>Before you continue</body></html>")

        with self.subTest("player response missing videoDetails"):
            response = _player_response()
            del response["videoDetails"]
            self._open_expect_upstream_changed(json.dumps(response).encode("utf-8"))

        with self.subTest("captionTracks renamed"):
            response = _player_response(caption_tracks_key_renamed=True)
            self._open_expect_upstream_changed(json.dumps(response).encode("utf-8"))


# --- WEB client identity + signatureTimestamp (live fix, 2026-08-03) --------------


class TestPlayerRequestBodyUsesWebClientAndSignatureTimestamp(unittest.TestCase):
    def test_player_request_body_uses_web_client_and_signature_timestamp(self) -> None:
        fake_fetch = _FakeFetch(
            [
                _watch_ok_response(client_version="2.20260803.01.00", sts=98765),
                _player_ok_response(_player_response()),
            ]
        )
        provider = innertube.InnertubeProvider(sleep=lambda s: None, jitter=lambda a, b: 0.0)
        with mock.patch.object(innertube, "fetch", fake_fetch):
            provider.open(_VIDEO_ID, domain.Deadline.start(60))

        player_call = fake_fetch.calls[1]
        body = json.loads(player_call["body"])
        self.assertEqual(body["context"]["client"]["clientName"], "WEB")
        self.assertEqual(body["context"]["client"]["clientVersion"], "2.20260803.01.00")
        self.assertEqual(body["playbackContext"]["contentPlaybackContext"]["signatureTimestamp"], 98765)
        self.assertIsInstance(
            body["playbackContext"]["contentPlaybackContext"]["signatureTimestamp"], int
        )

    def test_missing_client_version_in_watch_page_raises_upstream_changed(self) -> None:
        html = _watch_page_html().replace('"INNERTUBE_CONTEXT_CLIENT_VERSION":"2.20240101.00.00",', "")
        fake_fetch = _FakeFetch([_ok_response(html.encode("utf-8"))])
        provider = innertube.InnertubeProvider(sleep=lambda s: None, jitter=lambda a, b: 0.0)
        with mock.patch.object(innertube, "fetch", fake_fetch), \
                self.assertRaises(providers_base.UpstreamChanged):
            provider.open(_VIDEO_ID, domain.Deadline.start(60))

    def test_missing_sts_in_watch_page_raises_upstream_changed(self) -> None:
        html = _watch_page_html().replace('"STS":12345', "")
        fake_fetch = _FakeFetch([_ok_response(html.encode("utf-8"))])
        provider = innertube.InnertubeProvider(sleep=lambda s: None, jitter=lambda a, b: 0.0)
        with mock.patch.object(innertube, "fetch", fake_fetch), \
                self.assertRaises(providers_base.UpstreamChanged):
            provider.open(_VIDEO_ID, domain.Deadline.start(60))


class TestAppendFmtSrv3(unittest.TestCase):
    def test_fmt_srv3_appended_to_baseurl_with_existing_query(self) -> None:
        result = innertube._append_fmt_srv3("https://www.youtube.com/api/timedtext?v=x&lang=en")
        self.assertTrue(result.startswith("https://www.youtube.com/api/timedtext?"))
        query = dict(parse_qsl(urlsplit(result).query))
        self.assertEqual(query.get("fmt"), "srv3")
        self.assertEqual(query.get("v"), "x")
        self.assertEqual(query.get("lang"), "en")

    def test_fmt_srv3_appended_to_baseurl_with_no_query(self) -> None:
        result = innertube._append_fmt_srv3("https://www.youtube.com/api/timedtext")
        self.assertEqual(result, "https://www.youtube.com/api/timedtext?fmt=srv3")

    def test_fmt_srv3_appended_to_baseurl_with_trailing_question_mark(self) -> None:
        result = innertube._append_fmt_srv3("https://www.youtube.com/api/timedtext?")
        self.assertEqual(result, "https://www.youtube.com/api/timedtext?fmt=srv3")

    def test_session_fetch_uses_fmt_srv3_url_and_still_hits_allowlisted_host(self) -> None:
        provider = innertube.InnertubeProvider(sleep=lambda s: None, jitter=lambda a, b: 0.0)
        fake_fetch = _FakeFetch(
            [
                _watch_ok_response(),
                _player_ok_response(_player_response()),
                _ok_response(_timedtext_xml([(0, 900, "hi")])),
            ]
        )
        with mock.patch.object(innertube, "fetch", fake_fetch):
            session = provider.open(_VIDEO_ID, domain.Deadline.start(60))
            session.fetch(session.listing.tracks[0], domain.Deadline.start(60))

        timedtext_call = fake_fetch.calls[2]
        parsed = urlsplit(timedtext_call["url"])
        self.assertEqual(parsed.hostname, "www.youtube.com")
        self.assertIn("fmt=srv3", parsed.query)


class TestDeeplyNestedJsonRecursionError(unittest.TestCase):
    def test_deeply_nested_json_recursion_error_maps_to_upstream_changed(self) -> None:
        # Empirically confirmed (this task's own spike) to raise RecursionError from
        # json.loads on this interpreter at this depth -- see the report file.
        deep = ("[" * 200_000 + "]" * 200_000).encode("utf-8")
        fake_fetch = _FakeFetch([_watch_ok_response(), _ok_response(deep)])
        provider = innertube.InnertubeProvider(sleep=lambda s: None, jitter=lambda a, b: 0.0)
        with mock.patch.object(innertube, "fetch", fake_fetch), \
                self.assertRaises(providers_base.UpstreamChanged) as ctx:
            provider.open(_VIDEO_ID, domain.Deadline.start(60))
        self.assertIsInstance(ctx.exception.__cause__, RecursionError)


# --- 10: MAX_SEGMENTS enforcement --------------------------------------------------


class TestMaxSegmentsEnforcedDuringDecode(unittest.TestCase):
    def test_max_segments_enforced_during_decode(self) -> None:
        xml_bytes = _timedtext_xml([(i * 1000, 900, f"seg{i}") for i in range(4)])
        root = ElementTree.fromstring(xml_bytes)
        deadline = domain.Deadline.start(60)
        with mock.patch.object(innertube, "MAX_SEGMENTS", 3), \
                self.assertRaises(providers_base.TranscriptTooLarge):
            innertube._decode_segments(root, deadline)

        # Never materializes past the cap even when segments beyond it exist --
        # exactly `MAX_SEGMENTS` decoded before the raise, not fewer.
        with mock.patch.object(innertube, "MAX_SEGMENTS", 3):
            counted: List[ElementTree.Element] = []
            for element in root.iter("p"):
                if len(counted) >= innertube.MAX_SEGMENTS:
                    break
                counted.append(element)
            self.assertEqual(len(counted), 3)


# --- 11: deadline checks between open()'s phases -----------------------------------


class TestDeadlineCheckedBetweenDecodePhases(unittest.TestCase):
    def test_deadline_checked_between_decode_phases(self) -> None:
        provider = innertube.InnertubeProvider(sleep=lambda s: None, jitter=lambda a, b: 0.0)

        # Scenario A: expired immediately after leg 1 (watch-page) parse -- leg 2
        # (player POST) must never be attempted.
        with self.subTest("expires after leg 1"):
            fake_fetch = _FakeFetch([_watch_ok_response()])
            deadline = domain.Deadline(deadline_at=100.0, clock=_queue_clock([200.0]))
            with mock.patch.object(innertube, "fetch", fake_fetch), \
                    self.assertRaises(domain.DeadlineExpired):
                provider.open(_VIDEO_ID, deadline)
            self.assertEqual(len(fake_fetch.calls), 1, "leg 2 must not be attempted")

        # Scenario B: not expired after leg 1, but expires after leg 2 (player)
        # parse -- both network legs happen, but open() raises before returning a
        # session (so leg 3/timedtext is never reachable either).
        with self.subTest("expires after leg 2"):
            fake_fetch = _FakeFetch([_watch_ok_response(), _player_ok_response(_player_response())])
            deadline = domain.Deadline(deadline_at=100.0, clock=_queue_clock([50.0, 200.0]))
            with mock.patch.object(innertube, "fetch", fake_fetch), \
                    self.assertRaises(domain.DeadlineExpired):
                provider.open(_VIDEO_ID, deadline)
            self.assertEqual(len(fake_fetch.calls), 2, "both legs 1 and 2 must have been attempted")

        # fetch()'s own start-of-decode check, using fetch()'s OWN deadline (never
        # silently inherited from open()'s), per plan.md's cycle-3 fix.
        with self.subTest("fetch()'s own deadline checked before timedtext GET"):
            fake_fetch = _FakeFetch([_watch_ok_response(), _player_ok_response(_player_response())])
            with mock.patch.object(innertube, "fetch", fake_fetch):
                session = provider.open(_VIDEO_ID, domain.Deadline.start(60))
            already_expired = domain.Deadline.start(-1)
            with mock.patch.object(innertube, "fetch", _FakeFetch([])), \
                    self.assertRaises(domain.DeadlineExpired):
                session.fetch(session.listing.tracks[0], already_expired)


# --- 12: Retry-After fallback -----------------------------------------------------


class TestRetryAfterNonNumericFallsBack(unittest.TestCase):
    def test_retry_after_non_numeric_falls_back(self) -> None:
        # net/client.py's own `_retry_after` already normalizes a missing/non-numeric
        # `Retry-After` header to `0` before a `Throttled` ever reaches this module --
        # this provider's job is to not literally propagate that `0` as a real
        # override, so `STATUS_POLICY`'s own default (30) applies downstream instead.
        non_numeric_throttled = net_client.Throttled("rate limited", retry_after=0)
        mapped = innertube._translate_net_error(non_numeric_throttled)
        self.assertIsInstance(mapped, providers_base.RateLimited)
        self.assertIsNone(mapped.retry_after)

        numeric_throttled = net_client.Throttled("rate limited", retry_after=42)
        mapped_numeric = innertube._translate_net_error(numeric_throttled)
        self.assertEqual(mapped_numeric.retry_after, 42)


# --- 13: TrackDescriptor construction ---------------------------------------------


class TestTrackDescriptorCarriesTrackIdEstimatedCharactersNone(unittest.TestCase):
    def test_track_descriptor_carries_track_id_estimated_characters_none(self) -> None:
        parsed = innertube._extract_listing(_player_response())
        self.assertEqual(len(parsed.tracks), 2)
        manual_track = next(t for t in parsed.tracks if t.kind == "manual")
        asr_track = next(t for t in parsed.tracks if t.kind == "auto")

        self.assertEqual(manual_track.track_id, providers_base.encode_track_id("manual", "en"))
        self.assertEqual(asr_track.track_id, providers_base.encode_track_id("auto", "en"))
        self.assertIsNone(manual_track.estimated_characters)
        self.assertIsNone(asr_track.estimated_characters)


# --- 14: per-track validation drops only that track --------------------------------


class TestMalformedTrackFieldDropsTrackNotWholeCall(unittest.TestCase):
    def test_malformed_language_code_kind_or_overlong_name_drops_track_not_whole_call(self) -> None:
        tracks = [
            _DEFAULT_CAPTION_TRACKS[0],  # valid
            {  # invalid languageCode (space fails the pattern)
                "baseUrl": "https://www.youtube.com/api/timedtext?v=x&lang=bad",
                "languageCode": "has space",
                "name": {"simpleText": "Bad"},
            },
            {  # overlong languageName (via trackName fallback, > 100 chars)
                "baseUrl": "https://www.youtube.com/api/timedtext?v=x&lang=de",
                "languageCode": "de",
                "trackName": "x" * 101,
            },
        ]
        parsed = innertube._extract_listing(_player_response(caption_tracks=tracks))
        self.assertEqual(len(parsed.tracks), 1)
        self.assertEqual(parsed.tracks[0].language_code, "en")


# --- 15: Transport threaded through to net.fetch() ---------------------------------


class TestSessionFetchPassesTransportThrough(unittest.TestCase):
    def test_session_fetch_passes_transport_through_to_net_fetch(self) -> None:
        provider = innertube.InnertubeProvider(sleep=lambda s: None, jitter=lambda a, b: 0.0)
        fake_fetch = _FakeFetch(
            [
                _watch_ok_response(),
                _player_ok_response(_player_response()),
                _ok_response(_timedtext_xml([(0, 900, "hi")])),
            ]
        )
        with mock.patch.object(innertube, "fetch", fake_fetch):
            session = provider.open(_VIDEO_ID, domain.Deadline.start(60))
            session.fetch(session.listing.tracks[0], domain.Deadline.start(60))

        self.assertEqual(len(fake_fetch.calls), 3)
        for call in fake_fetch.calls:
            self.assertIs(call["transport"], provider._transport)


# --- 16: default_audio_language / is_default population ----------------------------


class TestDefaultAudioLanguageAndIsDefaultPopulated(unittest.TestCase):
    def test_default_audio_language_and_is_default_populated(self) -> None:
        response = _player_response(
            default_audio_language="de",
            audio_tracks=[{"defaultCaptionTrackIndex": 1}],
        )
        parsed = innertube._extract_listing(response)
        self.assertEqual(parsed.default_audio_language, "de")
        self.assertFalse(parsed.tracks[0].is_default)
        self.assertTrue(parsed.tracks[1].is_default)

        # microformat fallback when videoDetails.defaultAudioLanguage is absent.
        response_mf = _player_response(microformat_default_audio_language="ja")
        parsed_mf = innertube._extract_listing(response_mf)
        self.assertEqual(parsed_mf.default_audio_language, "ja")


# --- 17: User-Agent on every leg ---------------------------------------------------


class TestUserAgentPresentOnEveryLeg(unittest.TestCase):
    def test_user_agent_present_on_every_leg_is_client_string_not_server_constant(self) -> None:
        provider = innertube.InnertubeProvider(sleep=lambda s: None, jitter=lambda a, b: 0.0)
        fake_fetch = _FakeFetch(
            [
                _watch_ok_response(),
                _player_ok_response(_player_response()),
                _ok_response(_timedtext_xml([(0, 900, "hi")])),
            ]
        )
        with mock.patch.object(innertube, "fetch", fake_fetch):
            session = provider.open(_VIDEO_ID, domain.Deadline.start(60))
            session.fetch(session.listing.tracks[0], domain.Deadline.start(60))

        self.assertEqual(len(fake_fetch.calls), 3)
        for call in fake_fetch.calls:
            self.assertEqual(call["headers"]["User-Agent"], innertube._USER_AGENT)
        # It is the WEB client's own string (a desktop-browser UA, confirmed live
        # 2026-08-03), never net/client.py's `BASE_HEADERS` (which owns only
        # Accept-Encoding, T-6b) and -- once T-13b's server.py exists -- never that
        # module's constant either; this module has no `ALLOWED_EDGES` route there
        # regardless (`providers.innertube` may only reach `domain`/`net`).
        self.assertNotIn("User-Agent", net_client.BASE_HEADERS)
        self.assertTrue(innertube._USER_AGENT.startswith("Mozilla/5.0"))


# --- 18 (descriptive "exactly-3-requests-per-invocation" item): request budget ----


class TestExactlyThreeRequestsPerInvocation(unittest.TestCase):
    def test_exactly_3_requests_per_invocation(self) -> None:
        provider = innertube.InnertubeProvider(sleep=lambda s: None, jitter=lambda a, b: 0.0)
        fake_fetch = _FakeFetch(
            [
                _watch_ok_response(),
                _player_ok_response(_player_response()),
                _ok_response(_timedtext_xml([(0, 900, "hi")])),
            ]
        )
        with mock.patch.object(innertube, "fetch", fake_fetch):
            session = provider.open(_VIDEO_ID, domain.Deadline.start(60))
            self.assertEqual(len(fake_fetch.calls), 2, "open() issues exactly 2 requests")
            session.fetch(session.listing.tracks[0], domain.Deadline.start(60))
            self.assertEqual(len(fake_fetch.calls), 3, "fetch() issues exactly 1 more request")


if __name__ == "__main__":
    unittest.main()
