"""
Retry wrapper for Supabase calls over an unreliable connection.

The store's network is not a datacentre link. During one backfill run this
machine lost DNS six separate times ("[Errno 11001] getaddrinfo failed"),
each one killing a long job outright. The scripts that mattered already
retried; the live request path did not, so a two-second blip surfaced to a
customer standing at the mirror as a hard failure.

Retries only what is genuinely transient -- DNS, connection resets, read
timeouts, 5xx, and Postgres statement timeouts (57014), which show up here
when the database is briefly overloaded. A 404, a 409 or a bad payload is
not retried: those fail the same way every time and retrying just delays the
error.

Usage:
    from app.db.resilience import with_retry
    rows = with_retry(lambda: sb.table("inventory").select("*").execute())
"""
import logging
import random
import time

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 4
BASE_DELAY_S = 0.5
MAX_DELAY_S = 8.0

# Matched against the stringified exception, because the supabase/postgrest/
# httpx stack raises several different types for the same underlying network
# fault and the type alone isn't a reliable signal.
_TRANSIENT_MARKERS = (
    "getaddrinfo failed",        # DNS died (the one that kept happening here)
    "name or service not known",
    "temporary failure in name resolution",
    "connection reset",
    "connection refused",
    "connection aborted",
    "server disconnected",
    "read timeout",
    "readtimeout",
    "timed out",
    "connecterror",
    "remote end closed",
    "57014",                     # Postgres: canceling statement due to timeout
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway timeout",
)


def is_transient(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def with_retry(fn, *, what: str = "supabase call", max_attempts: int = MAX_ATTEMPTS):
    """Run `fn`, retrying transient network/database faults with exponential
    backoff and jitter. Re-raises anything that isn't transient immediately,
    and re-raises the last error once attempts are exhausted."""
    last: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except BaseException as exc:      # noqa: BLE001 -- re-raised below
            if not is_transient(exc) or attempt == max_attempts:
                raise
            last = exc
            # Jitter so parallel callers (the styled-look search runs 8 threads)
            # don't all retry in lockstep and hit the same moment again.
            delay = min(BASE_DELAY_S * (2 ** (attempt - 1)), MAX_DELAY_S)
            delay += random.uniform(0, delay * 0.25)
            log.warning("%s failed (attempt %d/%d), retrying in %.1fs: %s",
                        what, attempt, max_attempts, delay, str(exc)[:160])
            time.sleep(delay)
    raise last   # unreachable; keeps type checkers happy
