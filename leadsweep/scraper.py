"""Core extraction engine: Playwright + cookie session + GraphQL response interception.

We never parse the DOM. We let the real X web app make its own request, listen for the
response whose operation NAME matches (SearchTimeline / UserTweets - the rotating query-hash in
the URL doesn't matter) and read the clean JSON body.

Phase 2 (UPDATED LOGIC): one shared flow `_run()` serves both search and profile fetches.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone  # UPDATED LOGIC: Import datetime and timezone
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urlparse

from playwright.async_api import Browser, BrowserContext, Page, Playwright, Response, async_playwright

from .config import Settings, get_settings
from .exceptions import (
    EndpointChangedError,
    NoSessionAvailableError,
    RateLimitedError,
    ServerOutageError,
    SessionExpiredError,
    UserNotFoundError,
)
from .fingerprint import INIT_SCRIPT, build_user_agent, human_scroll, jitter, random_fingerprint
from .models import Tweet, XUser
from .parser import parse_followers_timeline, parse_search_timeline, parse_user_tweets, user_exists
from .session_pool import SessionCreds, SessionPool

log = logging.getLogger("leadsweep.scraper")

# Media CDNs and heavy static assets. Post/user data comes from x.com/i/api/graphql JSON,
# which never matches this pattern, so blocking it does not affect what gets parsed.
_MEDIA_URL_RE = re.compile(
    r"^https://(?:pbs|video)\.twimg\.com/"
    r"|\.(?:png|jpe?g|gif|webp|avif|mp4|m3u8|m4s|woff2?|ttf)(?:[?#]|$)",
    re.IGNORECASE,
)


async def _abort_route(route: Any) -> None:
    try:
        await route.abort()
    except Exception:  # noqa: BLE001 - page/context may already be closing
        pass

_LOGIN_MARKERS = ("/i/flow/login", "/login", "/i/flow/single_sign_on", "/i/jf/onboarding", "redirect_after_login")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
TimelineParser = Callable[[dict], tuple[list[Any], "str | None"]]
_OP_ALIASES: dict[str, tuple[str, ...]] = {
    "UserTweets": ("UserTweets", "UserOriginalsTimeline"),
    "UserTweetsAndReplies": ("UserTweetsAndReplies", "UserRepliesTimeline", "UserTweets", "UserOriginalsTimeline"),
    "Followers": ("Followers", "UserFollowers", "FollowersTimeline"),
}


@dataclass
class _Collector:
    op: str = "SearchTimeline"  # which GraphQL operation we are listening for
    parse: TimelineParser = parse_search_timeline
    accept: tuple[str, ...] = ("SearchTimeline",)
    tweets: dict[str, Tweet] = field(default_factory=dict)
    users: dict[str, XUser] = field(default_factory=dict)
    cursor: str | None = None
    payloads: int = 0
    ops: list[str] = field(default_factory=list)  # every GraphQL op seen, e.g. 'HomeTimeline:200'
    rate_limited: bool = False
    unauthorized: bool = False
    user_missing: bool = False
    user_suspended: bool = False
    user_protected: bool = False
    profile_data: XUser | None = None
    wake: asyncio.Event = field(default_factory=asyncio.Event)


class XScraper:
    def __init__(self, settings: Settings | None = None, pool: SessionPool | None = None) -> None:
        self.settings = settings or get_settings()
        self.pool = pool or SessionPool(self.settings.sessions_file, self.settings.state_file)
        self._pw: Playwright | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> "XScraper":
        # PHASE 7 / leak fix: if chromium.launch() raises, an `async with` never calls
        # __aexit__, which would leave the Playwright driver subprocess (and its transport)
        # alive for the lifetime of the process. Tear the driver down before re-raising.
        self._pw = await async_playwright().start()
        try:
            self._browser = await self._pw.chromium.launch(
                headless=self.settings.headless,
                channel=self.settings.browser_channel,
                args=["--disable-blink-features=AutomationControlled"],
            )
        except BaseException:
            try:
                await self._pw.stop()
            except Exception:  # noqa: BLE001 - preserve the original failure
                log.debug("Failed to stop Playwright driver during failed startup", exc_info=True)
            self._pw = None
            self._browser = None
            raise
        log.info("browser launched (version %s, headless=%s)", self._browser.version, self.settings.headless)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._browser:
            try:
                await self._browser.close()
            except Exception:  # noqa: BLE001 - shutdown must not raise
                log.warning("Error closing browser during shutdown", exc_info=True)
            self._browser = None
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:  # noqa: BLE001
                log.warning("Error stopping Playwright during shutdown", exc_info=True)
            self._pw = None

    # ------------------------------------------------------------------ public API
    async def search_tweets(self, query: str, max_results: int = 15, tab: str = "live") -> list[Tweet]:
        """One attempt with the next available session. tab: 'live' (Latest) or 'top'."""
        query = query.strip()
        if not query or len(query) > 512:
            raise ValueError("query must be 1..512 chars")
        if not 1 <= max_results <= 500:
            raise ValueError("max_results must be 1..500")
        if tab not in ("live", "top"):
            raise ValueError("tab must be 'live' or 'top'")
        url = f"https://x.com/search?q={quote(query)}&src=typed_query&f={tab}"
        return await self._run(url, "SearchTimeline", parse_search_timeline, max_results)

    async def fetch_user_profile_tweets(self, username: str, limit: int = 10, with_replies: bool = False) -> list[Tweet]:
        """NEW FEATURE (P2): recent posts from a public profile (UserTweets interception)."""
        username = username.strip().lstrip("@")
        if not _USERNAME_RE.fullmatch(username):
            raise ValueError("username must be 1-15 letters/digits/underscore")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be 1..500")
        target_url = f"https://x.com/{username}/with_replies" if with_replies else f"https://x.com/{username}"
        op = "UserTweetsAndReplies" if with_replies else "UserTweets"
        return await self._run(target_url, op, parse_user_tweets, limit)

    async def search_with_failover(self, query: str, max_results: int = 15, attempts: int = 3) -> list[Tweet]:
        """Retry on the next session when one is expired/rate-limited."""
        return await self._failover(lambda: self.search_tweets(query, max_results), attempts)

    async def profile_with_failover(self, username: str, limit: int = 10, with_replies: bool = False, attempts: int = 3) -> list[Tweet]:
        """NEW FEATURE (P2)."""
        return await self._failover(lambda: self.fetch_user_profile_tweets(username, limit, with_replies=with_replies), attempts)

    async def fetch_user_followers(self, username: str, limit: int = 50) -> list[XUser]:
        """Follower Intelligence (Stage 1): extract followers from a public profile."""
        username = username.strip().lstrip("@")
        if not _USERNAME_RE.fullmatch(username):
            raise ValueError("username must be 1-15 letters/digits/underscore")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be 1..500")
        return await self._run_users(f"https://x.com/{username}/followers", "Followers", parse_followers_timeline, limit)

    async def followers_with_failover(self, username: str, limit: int = 50, attempts: int = 3) -> list[XUser]:
        """Fetch followers with session rotation on 429/expired session."""
        return await self._failover(lambda: self.fetch_user_followers(username, limit), attempts)

    # ------------------------------------------------------------------ shared flow
    async def _failover(self, fn: Callable[[], Awaitable[Any]], attempts: int) -> Any:
        last: Exception | None = None
        for n in range(1, attempts + 1):
            try:
                return await fn()
            except (SessionExpiredError, RateLimitedError) as e:
                log.warning("attempt %d/%d failed: %s - rotating session", n, attempts, e)
                last = e
            except ServerOutageError as e:
                log.warning("attempt %d/%d hit X/Cloudflare edge outage (%s) - retrying in 3s...", n, attempts, e)
                last = e
                await asyncio.sleep(3)
            except NoSessionAvailableError:
                raise
        raise last or RuntimeError("failover exhausted")

    async def _run(self, url: str, op: str, parse: TimelineParser, max_results: int) -> list[Tweet]:
        if self._browser is None:
            raise RuntimeError("Use 'async with XScraper() as s:'")
        session = self.pool.acquire()
        ctx: BrowserContext | None = None
        page: Page | None = None
        try:
            ctx, page, col = await self._open(session, op, parse)
            log.info("[nav] %s (op=%s session=%s)", url, op, session.id)
            try:
                # UPDATED LOGIC: wait_until="domcontentloaded" ensures initial scripts load and trigger GraphQL SearchTimeline requests
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            except Exception as e:
                log.warning("Initial navigation to %s encountered %s, retrying...", url, e)
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                except Exception:
                    pass
            await self._wait_first_payload(page, col)
            self._raise_flags(col)

            stale = 0
            # Scale scrolls so large requests (like 100 or 200 items) can gather enough tweets (X yields ~10-20 tweets per batch)
            needed_scrolls = max((max_results // 3) + 12, 16)
            scroll_budget = max(self.settings.max_scrolls, needed_scrolls)
            for i in range(scroll_budget):
                if len(col.tweets) >= max_results:
                    break
                before = len(col.tweets)
                col.wake.clear()
                await human_scroll(page)
                try:
                    await asyncio.wait_for(col.wake.wait(), timeout=7)
                except asyncio.TimeoutError:
                    pass
                self._raise_flags(col)
                stale = stale + 1 if len(col.tweets) == before else 0
                log.info("[scroll %d/%d] tweets=%d/%d payloads=%d stale=%d", i + 1, scroll_budget, len(col.tweets), max_results, col.payloads, stale)
                # Allow more resilience before assuming page is exhausted
                if stale >= 8:
                    break
                # Randomized non-linear pacing delay (3.0 - 6.5s) between backfill scrolls to protect account
                import random
                await asyncio.sleep(random.uniform(3.0, 6.5))
                if (i + 1) % random.randint(5, 8) == 0:
                    await asyncio.sleep(random.uniform(4.0, 8.0))

            # Robust DOM Extraction Fallback: If GraphQL response listener was blocked or silent,
            # extract real live tweets directly from visible article[data-testid="tweet"] elements.
            if len(col.tweets) < max_results:
                try:
                    tweet_articles = await page.query_selector_all('article[data-testid="tweet"]')
                    for art in tweet_articles:
                        if len(col.tweets) >= max_results:
                            break
                        # Find the status anchor tag (contains /status/<id>)
                        status_anchor = await art.query_selector('a[href*="/status/"]')
                        if not status_anchor:
                            continue
                        href = await status_anchor.get_attribute("href") or ""
                        # Expected format: /<username>/status/<tweet_id>
                        match = re.search(r"/([^/]+)/status/(\d+)", href)
                        if not match:
                            continue
                        author_user = match.group(1)
                        tweet_id_str = match.group(2)
                        if tweet_id_str in col.tweets:
                            continue

                        # Extract visible text from tweetText container
                        text_el = await art.query_selector('[data-testid="tweetText"]')
                        tweet_text = (await text_el.inner_text()) if text_el else ""

                        # Extract display name
                        name_el = await art.query_selector('[data-testid="User-Name"]')
                        author_name = (await name_el.inner_text()).split("\n")[0] if name_el else author_user

                        clean_tweet = Tweet(
                            id=tweet_id_str,
                            url=f"https://x.com/{author_user}/status/{tweet_id_str}",
                            text=tweet_text.strip(),
                            author_username=author_user,
                            author_name=author_name.strip(),
                            author_followers=None,
                            created_at=datetime.now(timezone.utc),
                            platform="twitter",
                        )
                        col.tweets[tweet_id_str] = clean_tweet
                        log.info("[dom_fallback] extracted authentic live tweet %s by @%s", tweet_id_str, author_user)
                except Exception as dom_err:
                    log.debug("DOM fallback extraction encountered non-fatal error: %s", dom_err)

            self.last_profile_data = col.profile_data
            if col.profile_data:
                for t in col.tweets.values():
                    if not t.author_followers and col.profile_data.followers_count:
                        t.author_followers = col.profile_data.followers_count
                    if not t.author_name and col.profile_data.name:
                        t.author_name = col.profile_data.name

            self.pool.mark_used(session.id)
            return list(col.tweets.values())[:max_results]

        except SessionExpiredError as e:
            self.pool.mark_dead(session.id, str(e))
            await self._snapshot(page, "session_expired")
            raise
        except RateLimitedError:
            self.pool.mark_cooldown(session.id, self.settings.session_cooldown_s)
            raise
        except EndpointChangedError:
            await self._snapshot(page, "endpoint_changed")
            raise
        except UserNotFoundError:  # NEW FEATURE (P2): not the session's fault
            self.pool.mark_used(session.id)
            raise
        finally:
            if ctx:
                await ctx.close()

    async def _run_users(self, url: str, op: str, parse: TimelineParser, max_results: int) -> list[XUser]:
        """Follower extraction loop using conservative human-like pacing and safety caps."""
        if self._browser is None:
            raise RuntimeError("Use 'async with XScraper() as s:'")
        effective_limit = min(max_results, self.settings.max_users_per_run)
        session = self.pool.acquire()
        ctx: BrowserContext | None = None
        page: Page | None = None
        try:
            ctx, page, col = await self._open(session, op, parse)
            log.info("[nav] %s (op=%s session=%s limit=%d)", url, op, session.id, effective_limit)
            try:
                # UPDATED LOGIC: wait_until="domcontentloaded" ensures scripts load
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            except Exception as e:
                log.warning("Initial navigation to %s encountered %s, retrying...", url, e)
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                except Exception:
                    pass
            await self._wait_first_payload(page, col)
            self._raise_flags(col)

            stale = 0
            max_pages = min(self.settings.max_pages_per_run, (effective_limit // 20) + 3)
            for i in range(max_pages):
                if len(col.users) >= effective_limit:
                    break
                before = len(col.users)
                col.wake.clear()
                await human_scroll(page)
                try:
                    await asyncio.wait_for(col.wake.wait(), timeout=12)
                except asyncio.TimeoutError:
                    pass
                self._raise_flags(col)
                stale = stale + 1 if len(col.users) == before else 0
                log.info("[scroll %d] users=%d payloads=%d", i + 1, len(col.users), col.payloads)
                if stale >= 2:
                    break
                # Human triangular jitter between page fetches
                await jitter(self.settings.follower_page_delay_min, self.settings.follower_page_delay_max)

            self.pool.mark_used(session.id)
            return list(col.users.values())[:effective_limit]

        except SessionExpiredError as e:
            self.pool.mark_dead(session.id, str(e))
            await self._snapshot(page, "session_expired")
            raise
        except RateLimitedError:
            self.pool.mark_cooldown(session.id, self.settings.session_cooldown_s)
            raise
        except EndpointChangedError:
            await self._snapshot(page, "endpoint_changed")
            raise
        except UserNotFoundError:
            self.pool.mark_used(session.id)
            raise
        finally:
            if ctx:
                await ctx.close()

    # ------------------------------------------------------------------ internals
    async def _open(self, session: SessionCreds, op: str, parse: TimelineParser) -> tuple[BrowserContext, Page, _Collector]:
        assert self._browser is not None
        fp = random_fingerprint()
        ctx = await self._browser.new_context(
            viewport={"width": fp.width, "height": fp.height},
            device_scale_factor=fp.device_scale_factor,
            color_scheme=fp.color_scheme,  # type: ignore[arg-type]
            user_agent=build_user_agent(self._browser.version),
            locale=self.settings.locale,
            timezone_id=self.settings.timezone_id,
        )
        await ctx.add_init_script(INIT_SCRIPT)
        if self.settings.block_media:
            await ctx.route(_MEDIA_URL_RE, _abort_route)
        await ctx.add_cookies(
            [
                {"name": "auth_token", "value": session.auth_token, "domain": ".x.com", "path": "/",
                 "httpOnly": True, "secure": True, "sameSite": "None"},
                {"name": "ct0", "value": session.ct0, "domain": ".x.com", "path": "/",
                 "httpOnly": False, "secure": True, "sameSite": "Lax"},
            ]
        )
        page = await ctx.new_page()
        col = _Collector(op=op, parse=parse, accept=_OP_ALIASES.get(op, (op,)))  # UPDATED LOGIC (P2.1)
        page.on("response", lambda r: asyncio.ensure_future(self._on_response(r, col)))
        log.info("[ctx] viewport=%dx%d dsf=%s scheme=%s", fp.width, fp.height, fp.device_scale_factor, fp.color_scheme)
        return ctx, page, col

    async def _on_response(self, resp: Response, col: _Collector) -> None:
        if "/i/api/graphql/" not in resp.url or resp.request.method == "OPTIONS":
            return
        op = urlparse(resp.url).path.rsplit("/", 1)[-1]  # UPDATED LOGIC: exact op-name match (UserTweets != UserTweetsAndReplies)
        col.ops.append(f"{op}:{resp.status}")
        (log.info if self.settings.debug_save_raw else log.debug)("[graphql] %s %s -> %s", resp.request.method, op, resp.status)

        # NEW FEATURE (P2): detect missing/suspended profile from the lookup call
        if op == "UserByScreenName" and col.op in ("UserTweets", "UserTweetsAndReplies", "Followers"):
            if resp.status == 200:
                try:
                    data = await resp.json()
                    from .parser import _dig, parse_user_profile
                    user_data = _dig(data, "data", "user", "result")
                    if not user_data or user_data.get("__typename") in ("UserUnavailable", "UserTombstone"):
                        reason = user_data.get("reason") if user_data else "NotFound"
                        if reason == "Suspended":
                            col.user_suspended = True
                        else:
                            col.user_missing = True
                        col.wake.set()
                    elif user_data.get("legacy", {}).get("protected"):
                        col.user_protected = True
                        col.wake.set()
                    else:
                        col.profile_data = parse_user_profile(user_data)
                except Exception as ex:  # noqa: BLE001
                    log.warning("[graphql] Error in UserByScreenName: %s", ex)
            return

        if op not in col.accept:  # UPDATED LOGIC (P2.1)
            return
        if resp.status == 429:
            col.rate_limited = True
            col.wake.set()
            return
        if resp.status in (401, 403):
            col.unauthorized = True
            col.wake.set()
            return
        if resp.status != 200:
            log.warning("[%s] unexpected status %s", col.op, resp.status)
            return
        try:
            data = await resp.json()
        except Exception as e:  # noqa: BLE001
            log.warning("[%s] 200 but body unreadable: %r", col.op, e)
            return
        col.payloads += 1
        if self.settings.debug_save_raw:
            self.settings.raw_dump_dir.mkdir(parents=True, exist_ok=True)
            p = self.settings.raw_dump_dir / f"{int(time.time())}_{op}_{col.payloads}.json"
            p.write_text(json.dumps(data), encoding="utf-8")
        items, cursor = col.parse(data)
        if col.op in ("Followers", "UserFollowers", "FollowersTimeline"):
            for u in items:
                col.users.setdefault(u.rest_id, u)
            log.info("[payload %d] +%d users (total %d)", col.payloads, len(items), len(col.users))
        else:
            for t in items:
                col.tweets.setdefault(t.id, t)
            log.info("[payload %d] +%d tweets (total %d)", col.payloads, len(items), len(col.tweets))
        col.cursor = cursor or col.cursor
        col.wake.set()

    async def _wait_first_payload(self, page: Page, col: _Collector) -> None:
        self._raise_flags(col)
        if any(m in page.url for m in _LOGIN_MARKERS):
            raise SessionExpiredError(f"Redirected to login: {page.url}")
        try:
            deadline = time.monotonic() + self.settings.first_payload_timeout_s
            while True:
                self._raise_flags(col)
                if any(m in page.url for m in _LOGIN_MARKERS):
                    raise SessionExpiredError(f"Redirected to login: {page.url}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                try:
                    # If X transiently shows 'Something went wrong. Try reloading.', click Retry
                    retry_btn = page.locator('button:has-text("Retry")')
                    if await retry_btn.count() > 0 and await retry_btn.first.is_visible():
                        log.info("X displayed transient 'Retry' button, clicking...")
                        await retry_btn.first.click()
                    await asyncio.wait_for(col.wake.wait(), timeout=min(1.0, remaining))
                    self._raise_flags(col)
                    break
                except asyncio.TimeoutError:
                    continue
        except asyncio.TimeoutError:
            self._raise_flags(col)
            try:
                logged_out_ui = await page.locator('[data-testid="loginButton"], a[href="/login"]').count() > 0
                title = await page.title()
                body = (await page.inner_text("body"))[:300].replace("\n", " | ")
            except Exception:  # noqa: BLE001
                logged_out_ui, title, body = False, "?", "?"
            log.error("[diag] url=%s title=%r logged_out_ui=%s ops_seen=%s", page.url, title, logged_out_ui, col.ops)
            log.error("[diag] body: %s", body)
            if "524" in title or "522" in title or "524: A timeout occurred" in body or "Error code 524" in body or "Error code 522" in body or "Connection timed out" in body or "502 Bad Gateway" in body or "503 Service" in body:
                raise ServerOutageError(f"X/Cloudflare edge outage: {title} - {body[:140]}") from None
            if title == "?" and body == "?" and not col.ops:
                raise ServerOutageError("Page failed to load HTML body from X (connection dropped/blank response)") from None
            if "This account doesn’t exist" in body or "This account doesn't exist" in body or "account doesn't exist" in body.lower():
                raise UserNotFoundError("NOT_FOUND - Profile not found or unavailable")
            if logged_out_ui or "Continue with" in body or "Sign in" in body:
                raise SessionExpiredError("Logged-out UI detected: X did not accept auth_token/ct0") from None
            raise EndpointChangedError(
                f"No {'/'.join(col.accept)} response. Possibly renamed timeline ops: "
                f"{[o for o in col.ops if 'Timeline' in o or 'Tweets' in o] or 'none'}. All ops seen: {col.ops or 'none'}. "
                "See data/debug screenshot; enable LEADSWEEP_DEBUG_SAVE_RAW."
            ) from None

    @staticmethod
    def _raise_flags(col: _Collector) -> None:
        if col.user_missing:
            raise UserNotFoundError("NOT_FOUND - Profile not found or unavailable")
        if getattr(col, "user_suspended", False):
            raise UserNotFoundError("SUSPENDED - Account has been suspended")
        if getattr(col, "user_protected", False):
            raise UserNotFoundError("PROTECTED - Profile posts are protected")
        if col.rate_limited:
            raise RateLimitedError(f"{col.op} returned 429")
        if col.unauthorized:
            raise SessionExpiredError(f"{col.op} returned 401/403 (cookies rejected)")

    async def _snapshot(self, page: Page | None, tag: str) -> None:
        if page is None:
            return
        try:
            self.settings.debug_dir.mkdir(parents=True, exist_ok=True)
            path = self.settings.debug_dir / f"{int(time.time())}_{tag}.png"
            await page.screenshot(path=str(path))
            log.info("[debug] screenshot saved: %s", path)
        except Exception:  # noqa: BLE001
            pass
