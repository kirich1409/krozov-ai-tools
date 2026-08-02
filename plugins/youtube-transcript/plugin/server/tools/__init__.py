"""`outcome_from_error()` -- the single owner translating either exception family
(`ProviderError` and its ten subclasses, `DeadlineExpired`) plus the other
`DomainFailure` subclasses raised elsewhere in this tree (`CursorInvalid`,
`TrackFieldInvalid`) into a `ToolOutcome`. No other module performs this
translation (plan.md's "single owner" section).

`tools/` (including `tools/cursor.py`, T-8) may import `domain/`, `formats/`, and
`providers/base.py` (`ALLOWED_EDGES`) -- never `providers/innertube.py` directly.
"""

from domain import CursorInvalid, DeadlineExpired, DomainFailure, Status, ToolOutcome, TrackFieldInvalid
from providers.base import ProviderError

# Maps every non-`ProviderError` `DomainFailure` subclass this server currently
# raises to its `Status`. `ProviderError` subclasses carry their own `status`
# (`ClassVar[Status]`, `providers/base.py`) and are handled separately, first, below
# -- this table only needs an entry per *other* concrete `DomainFailure` leaf.
# `tests/test_providers_base.py::test_outcome_from_error_totality` walks
# `DomainFailure.__subclasses__()` recursively and asserts every concrete leaf --
# every `ProviderError` subclass, plus everything named here -- is covered, so a
# future `DomainFailure` subclass with no mapping fails loudly instead of silently.
_OTHER_DOMAIN_FAILURE_STATUS = {
    DeadlineExpired: Status.TRANSPORT_ERROR,
    CursorInvalid: Status.UPSTREAM_CHANGED,
    TrackFieldInvalid: Status.UPSTREAM_CHANGED,
}


def outcome_from_error(exc: DomainFailure) -> ToolOutcome:
    if isinstance(exc, ProviderError):
        # AC-22: thread the real upstream `Retry-After` value (if any) into the
        # payload under the exact key `protocol/envelope.py::build()` already
        # reads (`retry_after_seconds`) -- otherwise `RateLimited.retry_after`
        # never reaches the wire and AC-22's clamp is permanently dead code.
        payload = {"retry_after_seconds": exc.retry_after} if exc.retry_after is not None else {}
        return ToolOutcome(status=exc.status, payload=payload)
    for exc_type, status in _OTHER_DOMAIN_FAILURE_STATUS.items():
        if isinstance(exc, exc_type):
            return ToolOutcome(status=status)
    raise TypeError(f"outcome_from_error: no mapping for {type(exc).__name__}")
