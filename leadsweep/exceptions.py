class LeadSweepError(Exception):
    """Base error for leadsweep."""


class SessionExpiredError(LeadSweepError):
    """Cookies rejected / redirected to login. Session must be replaced."""


class RateLimitedError(LeadSweepError):
    """X returned 429 (or equivalent). Session goes on cooldown."""


class EndpointChangedError(LeadSweepError):
    """No SearchTimeline payload seen. X likely changed its internal API or page flow."""


class NoSessionAvailableError(LeadSweepError):
    """All sessions are dead or cooling down."""


class UserNotFoundError(LeadSweepError):
    """NEW FEATURE (P2): profile does not exist, is suspended, or is unavailable."""


class ServerOutageError(LeadSweepError):
    """X / Cloudflare edge timeout or 5xx outage (e.g. 524, 502, 503, 504). Transient server failure."""
