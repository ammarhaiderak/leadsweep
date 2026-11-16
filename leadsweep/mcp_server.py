"""Phase 2 — MCP server exposing the scraper as tools.

Run (stdio):            python -m leadsweep.mcp_server
Run (HTTP, for Docker): python -m leadsweep.mcp_server --transport streamable-http --port 8765

stdout is reserved for the MCP protocol on stdio -> all logs go to stderr.
"""
import argparse
import asyncio
import logging
import random
import re
import sys
import time
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncIterator, Awaitable, Callable

try:  # UPDATED LOGIC: friendly dependency hint (mcp 2.x removed mcp.server.fastmcp)
    from mcp.server.fastmcp import FastMCP
except ImportError:
    raise SystemExit('Needs mcp 1.x. Run:  pip install "mcp>=1.10,<2"')
from pydantic import Field

from .config import get_settings
from .exceptions import (
    EndpointChangedError,
    NoSessionAvailableError,
    RateLimitedError,
    SessionExpiredError,
    UserNotFoundError,
)
from .models import Tweet, XUser
from .schemas import (
    ErrorInfo,
    FollowersResponse,
    ProfileResponse,
    SearchResponse,
    SessionInfo,
    SessionStatusResponse,
)
from .scraper import XScraper

log = logging.getLogger("leadsweep.mcp")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")


class _State:
    scraper: XScraper | None = None
    lock: asyncio.Lock = asyncio.Lock()  # one browser flow at a time -> gentler on rate limits
    last_end: float = 0.0


STATE = _State()


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[None]:
    async with XScraper() as sc:  # one long-lived browser for the whole server lifetime
        STATE.scraper = sc
        log.info("leadsweep MCP server ready")
        yield
    STATE.scraper = None


mcp = FastMCP(
    "leadsweep",
    instructions="Read-only X/Twitter intelligence tools. Results are structured; check `ok` and `error` first.",
    lifespan=lifespan,
)


def to_error(e: Exception) -> ErrorInfo:
    s = get_settings()
    if isinstance(e, ValueError):
        return ErrorInfo(code="INVALID_INPUT", message=str(e), retryable=False)
    if isinstance(e, RateLimitedError):
        return ErrorInfo(code="RATE_LIMITED", message=str(e), retryable=True, retry_after_s=s.session_cooldown_s,
                         hint="Session is cooling down; retry later or add another session.")
    if isinstance(e, SessionExpiredError):
        return ErrorInfo(code="SESSION_EXPIRED", message=str(e), retryable=False,
                         hint="Refresh cookies: python -m scripts.capture_session --id <id>")
    if isinstance(e, NoSessionAvailableError):
        return ErrorInfo(code="NO_SESSION_AVAILABLE", message=str(e), retryable=True)
    if isinstance(e, EndpointChangedError):
        return ErrorInfo(code="ENDPOINT_CHANGED", message=str(e), retryable=False,
                         hint="X changed its internal API/page flow; see data/debug and data/raw.")
    if isinstance(e, UserNotFoundError):
        return ErrorInfo(code="USER_NOT_FOUND", message=str(e), retryable=False)
    return ErrorInfo(code="INTERNAL", message=f"{type(e).__name__}: {e}", retryable=False)


async def _guarded(call: Callable[[XScraper], Awaitable[Any]]) -> tuple[Any, ErrorInfo | None]:
    sc = STATE.scraper
    if sc is None:
        return [], ErrorInfo(code="INTERNAL", message="Scraper not initialised", retryable=False)
    s = get_settings()
    async with STATE.lock:
        need = random.uniform(s.call_gap_min, s.call_gap_max)
        waited = time.monotonic() - STATE.last_end
        if STATE.last_end and waited < need:
            await asyncio.sleep(need - waited)
        try:
            return await call(sc), None
        except Exception as e:  # noqa: BLE001 - convert everything into structured errors
            err = to_error(e)
            (log.exception if err.code == "INTERNAL" else log.warning)("tool failed: %s %s", err.code, err.message)
            return [], err
        finally:
            STATE.last_end = time.monotonic()


@mcp.tool()
async def search_tweets(
    query: Annotated[str, Field(min_length=1, max_length=512,
                                description="X search query. Operators work: from:, lang:en, -filter:retweets, min_faves:5")],
    max_results: Annotated[int, Field(ge=1, le=100, description="Maximum tweets to return")] = 15,
) -> SearchResponse:
    """Search X (Latest tab) and return structured tweets. On failure `ok=false` and `error` explains why."""
    t0 = time.monotonic()
    q = query.strip()
    if not q:
        return SearchResponse(ok=False, query=query, count=0,
                              error=ErrorInfo(code="INVALID_INPUT", message="query is empty", retryable=False))
    tweets, err = await _guarded(lambda sc: sc.search_with_failover(q, max_results))
    return SearchResponse(ok=err is None, query=q, count=len(tweets), tweets=tweets, error=err,
                          elapsed_s=round(time.monotonic() - t0, 2))


@mcp.tool()
async def fetch_user_profile_tweets(
    username: Annotated[str, Field(min_length=1, max_length=16, description="X handle, with or without @")],
    limit: Annotated[int, Field(ge=1, le=100, description="Maximum tweets to return")] = 10,
) -> ProfileResponse:
    """Fetch recent posts from a public profile (may include a pinned post and retweets)."""
    t0 = time.monotonic()
    u = username.strip().lstrip("@")
    if not _USERNAME_RE.fullmatch(u):
        return ProfileResponse(ok=False, username=username, count=0,
                               error=ErrorInfo(code="INVALID_INPUT", message="username must be 1-15 letters/digits/underscore",
                                               retryable=False))
    tweets, err = await _guarded(lambda sc: sc.profile_with_failover(u, limit))
    return ProfileResponse(ok=err is None, username=u, count=len(tweets), tweets=tweets, error=err,
                           elapsed_s=round(time.monotonic() - t0, 2))


@mcp.tool()
async def fetch_user_followers(
    username: Annotated[str, Field(min_length=1, max_length=16, description="X handle, with or without @")],
    limit: Annotated[int, Field(ge=1, le=300, description="Maximum follower profiles to return")] = 50,
) -> FollowersResponse:
    """Followers Intelligence (Stage 1): extract followers from a public profile with profile attributes."""
    t0 = time.monotonic()
    u = username.strip().lstrip("@")
    if not _USERNAME_RE.fullmatch(u):
        return FollowersResponse(ok=False, username=username, count=0,
                                 error=ErrorInfo(code="INVALID_INPUT", message="username must be 1-15 letters/digits/underscore",
                                                 retryable=False))
    users, err = await _guarded(lambda sc: sc.followers_with_failover(u, limit))
    return FollowersResponse(ok=err is None, username=u, count=len(users), users=users, error=err,
                             elapsed_s=round(time.monotonic() - t0, 2))


@mcp.tool()
async def session_status() -> SessionStatusResponse:
    """Health of the cookie sessions (dead / cooling down). Never exposes cookie values."""
    sc = STATE.scraper
    if sc is None:
        return SessionStatusResponse(ok=False, sessions=[])
    return SessionStatusResponse(sessions=[SessionInfo(**x) for x in sc.pool.summary()])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    logging.basicConfig(level=get_settings().log_level, stream=sys.stderr,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    if args.transport != "stdio":
        mcp.settings.host, mcp.settings.port = args.host, args.port
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
