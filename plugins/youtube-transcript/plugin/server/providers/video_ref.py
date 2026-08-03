"""AC-6's `video` reference normalizer -- turns a caller-supplied `video` string
(bare video ID or one of five recognized YouTube URL forms) into a validated
`VideoId`, or `None` if it doesn't resolve to one.

`providers/video_ref.py` may import only `domain/` (`ALLOWED_EDGES`, plan.md) --
never `providers/innertube.py` or anything else cross-package. Stdlib only
(`urllib.parse`, `re`).

Security-relevant: this is the function AC-6's two named attack payloads
(`https://www.youtube.com@evil.com/...`, `https://youtube.com.evil.com/...`) are
checked against. Host matching is `urlsplit(value).hostname` **exact equality**
against the allowlist below -- never substring/`in`/`startswith`, and never a
regex applied to the raw URL string, since either of those would treat
`youtube.com` as a match anywhere it appears (as a subdomain label of an attacker
host, or after an `@` userinfo separator) rather than only as the actual host.
`urlsplit(...).hostname` already discards userinfo and lowercases the result, so
`https://www.youtube.com@evil.com/...` resolves to the host `evil.com` (not
`www.youtube.com`) by construction, and `youtube.com.evil.com` is simply not a
member of the allowlist under exact equality.
"""

from typing import Optional
from urllib.parse import parse_qs, urlsplit

from domain import VIDEO_ID_PATTERN, VideoId

# AC-6's allowlist -- `youtu.be` doubles as both a host and (via its path) the ID
# carrier for that one form.
_ALLOWED_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }
)

# Path-prefix forms sharing one extraction rule: the ID is the first path segment
# after the prefix.
_PATH_PREFIXES = ("/shorts/", "/live/", "/embed/")

# AC-6's post-normalization validation pattern -- applied to whatever candidate ID
# extraction above produced, regardless of which input form it came from.
# `domain.VIDEO_ID_PATTERN` is the single, `domain/`-owned copy (acceptance-fix
# pass) -- this module no longer maintains its own.


def _extract_candidate(value: str) -> Optional[str]:
    """Returns the raw (not yet validated) candidate ID string embedded in `value`,
    or `None` if `value` isn't a recognizable bare ID or URL form at all. Never
    raises -- malformed input is exactly the case this returns `None` for."""
    if "://" not in value and not value.startswith("//"):
        # No scheme/authority marker at all -- not a URL, treat as a (possible)
        # bare video ID candidate.
        return value

    parsed = urlsplit(value)
    host = parsed.hostname
    if host is None or host not in _ALLOWED_HOSTS:
        return None

    if host == "youtu.be":
        return parsed.path.lstrip("/").split("/", 1)[0]

    for prefix in _PATH_PREFIXES:
        if parsed.path.startswith(prefix):
            return parsed.path[len(prefix) :].split("/", 1)[0]

    if parsed.path == "/watch":
        query_values = parse_qs(parsed.query).get("v")
        if query_values:
            return query_values[0]
        return None

    return None


def normalize(value: str) -> Optional[VideoId]:
    """Normalizes a caller-supplied `video` string into a `VideoId`, or `None` if
    it isn't a bare video ID or one of AC-6's recognized URL forms, or the
    extracted candidate fails the `^[A-Za-z0-9_-]{11}$` pattern. Never raises."""
    if not isinstance(value, str) or not value:
        return None

    candidate = _extract_candidate(value)
    if candidate is None:
        return None
    if not VIDEO_ID_PATTERN.match(candidate):
        return None
    return VideoId(value=candidate)
