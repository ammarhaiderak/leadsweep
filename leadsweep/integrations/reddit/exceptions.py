"""Typed Reddit ingestion failures.

Every failure mode is a distinct type so callers never have to guess whether a fault is
retryable, terminal, or an access-policy refusal. Nothing here evades Reddit's controls:
denials are surfaced, recorded, and left alone.
"""
from __future__ import annotations


class RedditError(RuntimeError):
    """Base class for every Reddit ingestion failure."""

    status_code: str = "ERROR"
    retryable: bool = False

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class RedditConfigError(RedditError):
    """Local configuration problem (bad mode, unreadable fixture directory)."""

    status_code = "CONFIG_ERROR"


class RedditAccessDeniedError(RedditError):
    """401/403: Reddit refused the request. Never retried, never worked around."""

    status_code = "ACCESS_RESTRICTED"

    def __init__(self, message: str, *, http_status: int = 403) -> None:
        super().__init__(message)
        self.http_status = http_status


class RedditAuthRequiredError(RedditAccessDeniedError):
    """401: the endpoint requires an authorised OAuth identity we do not have."""

    status_code = "AUTH_REQUIRED"


class RedditNotFoundError(RedditError):
    """404: the subreddit/post/endpoint does not exist or is private."""

    status_code = "NOT_FOUND"


class RedditRateLimitedError(RedditError):
    """429: Reddit asked us to slow down. Always honours Retry-After."""

    status_code = "RATE_LIMITED"
    retryable = True

    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class RedditServerError(RedditError):
    """5xx: bounded retry with exponential backoff and jitter."""

    status_code = "SOURCE_UNAVAILABLE"
    retryable = True


class RedditTimeoutError(RedditError):
    """Network timeout. Bounded retry; progress is checkpointed by the caller."""

    status_code = "SOURCE_UNAVAILABLE"
    retryable = True


class RedditCircuitOpenError(RedditError):
    """The breaker is open after repeated denials/failures; back off entirely."""

    status_code = "CIRCUIT_OPEN"


class RedditResponseError(RedditError):
    """Malformed or unexpected payload (never fabricated into data)."""

    status_code = "PARSE_ERROR"


def classify_http_status(status: int, *, retry_after: float | None = None) -> RedditError:
    """Map an HTTP status to the correct typed exception."""
    if status == 401:
        return RedditAuthRequiredError(
            "Reddit requires an authorised OAuth identity for this endpoint.",
            http_status=status,
        )
    if status == 403:
        return RedditAccessDeniedError(
            "Reddit refused this request (HTTP 403). Unauthenticated access is blocked.",
            http_status=status,
        )
    if status == 404:
        return RedditNotFoundError("Resource unavailable (HTTP 404).")
    if status == 429:
        return RedditRateLimitedError("Reddit rate limit reached (HTTP 429).", retry_after_s=retry_after)
    if 500 <= status <= 599:
        return RedditServerError(f"Reddit upstream error (HTTP {status}).")
    return RedditResponseError(f"Unexpected Reddit response (HTTP {status}).")
