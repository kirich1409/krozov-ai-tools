"""T-P3 (network spike): allowlist-based structural check against the scrubbed,
committed InnerTube player-response fixture.

**Allowlist, not denylist** (tasks.md's T-P3 acceptance clause, cycle 8 fix): a
denylist grepping for known secret-field names (`visitorData`/`INNERTUBE_API_KEY`/
`pot`/`signature`/`expire`/`sig`) cannot catch a secret arriving under a NEW key
name in a future recorded capture -- it can only catch names it already knows to
look for. This test instead asserts every top-level key, and every key nested
under `captions.playerCaptionsTracklistRenderer.captionTracks`/`playerConfig`,
is a member of an explicitly enumerated **expected** key set: an unrecognized
key fails the test outright, rather than silently passing through.

The fixture itself (`fixtures/innertube_player_response.json`) is a real,
live-captured 2026-08-02 InnerTube WEB-client watch-page-embedded
`ytInitialPlayerResponse` (video `dQw4w9WgXcQ`), scrubbed: every leaf value
replaced with a generic placeholder (a handful of enum-like fields -- `status`,
`languageCode`, `kind`, etc. -- kept verbatim since they carry no secret
material and keep the fixture useful), with `captionTracks[].baseUrl` and the
`mediaUstreamerRequestConfig` device-token blob additionally overwritten with an
explicitly fake, structurally-shaped placeholder on top of the generic scrub.
Sections this plugin never reads (`streamingData`, `endscreen`, `cards`,
`annotations`, `storyboards`, etc.) are collapsed to a one-line stub -- this
test only deep-checks `captionTracks`/`playerConfig`, matching the brief's own
scope, so collapsing the rest loses no asserted coverage while keeping the
committed fixture small.

This test does not import any product code under `plugin/server/**` (T-P3 does
not touch product code) -- it is a pure fixture-shape check.
"""

import json
import os
import unittest
from typing import Any, Set

_FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "innertube_player_response.json"
)

# Every top-level key observed in the real 2026-08-02 capture, plus this
# fixture's own collapsed-stub sections.
EXPECTED_TOP_LEVEL_KEYS: Set[str] = {
    "adBreakHeartbeatParams",
    "adPlacements",
    "annotations",
    "captions",
    "cards",
    "endscreen",
    "frameworkUpdates",
    "microformat",
    "playabilityStatus",
    "playbackTracking",
    "playerConfig",
    "responseContext",
    "storyboards",
    "streamingData",
    "trackingParams",
    "videoDetails",
}

# Every key observed anywhere under
# `captions.playerCaptionsTracklistRenderer.captionTracks` in the real capture.
EXPECTED_CAPTION_TRACK_KEYS: Set[str] = {
    "baseUrl",
    "isTranslatable",
    "kind",
    "languageCode",
    "name",
    "simpleText",
    "trackName",
    "vssId",
}

# Every key observed anywhere under `playerConfig` in the real capture (this
# plugin never reads playerConfig at all -- it is deep-checked here purely as
# a broad secret/token tripwire, per the brief's explicit scope).
EXPECTED_PLAYER_CONFIG_KEYS: Set[str] = {
    "action",
    "actions",
    "addToWatchLaterCommand",
    "addedVideoId",
    "apiUrl",
    "applyStatefulNormalization",
    "audioConfig",
    "channelIds",
    "clickTrackingParams",
    "commandMetadata",
    "daiConfig",
    "defaultPlaybackRateOptions",
    "dynamicReadaheadConfig",
    "enable",
    "enablePerFormatLoudness",
    "fixLivePlaybackModelDefaultPosition",
    "getSharePanelCommand",
    "granularVariableSpeedConfig",
    "isPremiumUpsell",
    "label",
    "loudnessDb",
    "loudnessNormalizationConfig",
    "loudnessTargetLkfs",
    "maxBitrate",
    "maxReadAheadMediaTimeMs",
    "maxStatefulTimeThresholdSec",
    "maximumPlaybackRate",
    "mediaCommonConfig",
    "mediaUstreamerRequestConfig",
    "minReadAheadMediaTimeMs",
    "minReadaheadMs",
    "minimumLoudnessTargetLkfs",
    "minimumPlaybackRate",
    "params",
    "perceptualLoudnessDb",
    "platypusUseEnvoyNetFetch",
    "playbackStartPolicy",
    "playerControlsConfig",
    "playlistEditEndpoint",
    "playlistId",
    "preserveStatefulLoudnessTarget",
    "priority",
    "readAheadGrowthRateMs",
    "removeFromWatchLaterCommand",
    "removedVideoId",
    "sendPost",
    "sendSsdaiMissingAdBreakReasons",
    "serializedShareEntity",
    "serverPlaybackStartConfig",
    "showCachedInTimebar",
    "startMinReadaheadPolicy",
    "stepSize",
    "streamSelectionConfig",
    "subscribeCommand",
    "subscribeEndpoint",
    "trackAbsoluteLoudnessLkfs",
    "unsubscribeCommand",
    "unsubscribeEndpoint",
    "useCobaltTvosDash",
    "useServerDrivenAbr",
    "value",
    "videoPlaybackUstreamerConfig",
    "vssClientConfig",
    "vssUsePostRequest",
    "webCommandMetadata",
    "webPlayerActionsPorting",
    "webPlayerConfig",
    "webPlayerShareEntityServiceEndpoint",
}


def _collect_keys(node: Any, acc: Set[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            acc.add(k)
            _collect_keys(v, acc)
    elif isinstance(node, list):
        for item in node:
            _collect_keys(item, acc)


class TestInnertubeFixtureAllowlist(unittest.TestCase):
    def setUp(self) -> None:
        with open(_FIXTURE_PATH, encoding="utf-8") as f:
            self.fixture = json.load(f)

    def test_top_level_keys_are_all_expected(self) -> None:
        actual = set(self.fixture.keys())
        unexpected = actual - EXPECTED_TOP_LEVEL_KEYS
        self.assertEqual(
            unexpected,
            set(),
            f"unrecognized top-level key(s) in fixture, not in the enumerated "
            f"allowlist -- a new key here may carry a secret/token not "
            f"previously reviewed: {sorted(unexpected)}",
        )

    def test_caption_track_nested_keys_are_all_expected(self) -> None:
        tracks = (
            self.fixture.get("captions", {})
            .get("playerCaptionsTracklistRenderer", {})
            .get("captionTracks", [])
        )
        self.assertTrue(tracks, "fixture has no captionTracks -- fixture is stale/broken")
        actual: Set[str] = set()
        _collect_keys(tracks, actual)
        unexpected = actual - EXPECTED_CAPTION_TRACK_KEYS
        self.assertEqual(
            unexpected,
            set(),
            f"unrecognized key nested under captionTracks, not in the "
            f"enumerated allowlist: {sorted(unexpected)}",
        )

    def test_player_config_nested_keys_are_all_expected(self) -> None:
        player_config = self.fixture.get("playerConfig")
        self.assertIsInstance(player_config, dict, "fixture has no playerConfig -- fixture is stale/broken")
        actual: Set[str] = set()
        _collect_keys(player_config, actual)
        unexpected = actual - EXPECTED_PLAYER_CONFIG_KEYS
        self.assertEqual(
            unexpected,
            set(),
            f"unrecognized key nested under playerConfig, not in the "
            f"enumerated allowlist: {sorted(unexpected)}",
        )

    def test_fixture_contains_no_known_secret_markers(self) -> None:
        # Belt-and-suspenders on top of the allowlist checks above: a residual
        # denylist scan, cheap to run, for the specific field-name patterns a
        # real signed baseUrl carries. This does NOT replace the allowlist
        # tests above (see module docstring) -- it catches accidental
        # un-scrubbing of a value under an already-known field name.
        raw = json.dumps(self.fixture)
        for marker in ("visitorData", "INNERTUBE_API_KEY"):
            self.assertNotIn(marker, raw, f"fixture must not contain a real {marker!r} value")
        # A real signed baseUrl's signature param is a long hex-like token;
        # the scrubbed fixture's placeholder baseUrl uses the literal string
        # "SCRUBBED" in that position instead.
        for track in self.fixture["captions"]["playerCaptionsTracklistRenderer"]["captionTracks"]:
            base_url = track["baseUrl"]
            self.assertIn("SCRUBBED", base_url, "baseUrl must be the scrubbed placeholder, not a real signed URL")


if __name__ == "__main__":
    unittest.main()
