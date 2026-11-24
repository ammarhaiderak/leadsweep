# NEW FEATURE: Public Telegram Channel Scraper ($0 Cost, Zero Account/API Requirements)
"""
Telegram Public Channel Scraper for LeadSweep / LeadSweep.

Extracts messages from public Telegram channels via public web previews (https://t.me/s/{channel}).
Features:
- $0 cost: Uses standard HTTP GET without Telethon, API keys, phone numbers, OTPs, or sessions.
- Direct DOM parsing via selectolax / BeautifulSoup fallback.
- Pagination backwards using ?before={oldest_message_id}.
- Extraction of verifiable fields: message_id, channel, text, date, views, forwards, links, media flag.
- Structured statuses: OK, EMPTY, ACCESS_RESTRICTED, SOURCE_UNAVAILABLE, RATE_LIMITED, PARSE_ERROR.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
import datetime
import logging
import math
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal

import httpx
from selectolax.lexbor import LexborHTMLParser

log = logging.getLogger("leadsweep.services.telegram_public_scraper")

# URL & Handle patterns
TELEGRAM_HANDLE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t\.me/|telegram\.me/)(?:s/)?@?([a-zA-Z0-9_]{4,32})/?",
    re.IGNORECASE,
)
HANDLE_ONLY_RE = re.compile(r"^@?([a-zA-Z0-9_]{4,32})$", re.IGNORECASE)
LINK_EXTRACT_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# Realistic browser headers for t.me/s/ requests. Telegram serves a stripped page
# (or redirects) to clients that look like bots, so send what a desktop browser sends.
BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Human-readable detail used whenever a handle has no public web preview.
ACCESS_RESTRICTED_DETAIL = "Channel is private or does not exist (no public web preview exists for this handle)."

# Path segments on t.me that are never channel handles.
_RESERVED_TME_PATHS = {"s", "joinchat", "share", "addlist", "contact", "proxy", "socks", "login", "iv", "c"}

PublicScraperStatus = Literal[
    "OK",
    "EMPTY",
    "ACCESS_RESTRICTED",
    "SOURCE_UNAVAILABLE",
    "RATE_LIMITED",
    "PARSE_ERROR",
]


# UPDATED LOGIC: Verifiable fields with NULL for absent metrics (no fabricated defaults)
@dataclass
class PublicTelegramMessage:
    """Verifiable message extracted from t.me/s/{channel}."""
    message_id: int
    channel: str
    channel_title: str
    text: str
    channel_description: str = ""
    source_published_at: str | None = None  # Verifiable published ISO-8601 from <time datetime>
    date: str | None = None  # Backwards compatibility
    views: int | None = None  # None if missing in HTML
    forwards: int | None = None  # None if missing in HTML
    reactions: int | None = None  # None if missing in HTML
    post_url: str = ""
    has_media: bool = False
    media_type: str | None = None
    links: list[str] = field(default_factory=list)
    author: str | None = None  # Post signature / sender name when Telegram renders one
    transport_used: str = "direct"  # direct | relay | telethon
    fetched_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())


@dataclass
class ChannelScrapeReport:
    """Detailed diagnostic report of a Telegram scraping execution."""
    channel: str
    status: PublicScraperStatus
    requested: int
    extracted: int
    duplicates_skipped: int
    qualified: int
    shortfall: int
    error_message: str | None = None


# NEW FEATURE (Phase 1): Input Grammar and Plan Dataclass
@dataclass
class TelegramInputPlan:
    """Structured plan derived from raw Telegram query input."""
    mode: Literal["GLOBAL", "DIRECT", "DIRECT_SEARCH", "KEYWORD"]
    raw_query: str
    channels: list[str] = field(default_factory=list)
    keyword: str | None = None
    search_q: str | None = None


def parse_telegram_input(raw: str) -> TelegramInputPlan:
    """
    Parse and classify Telegram query according to strict input grammar:
    - empty or whitespace -> GLOBAL mode
    - private invites (t.me/+, joinchat) -> reject immediately with ValueError
    - handle + keywords ("@name keyword...") -> DIRECT_SEARCH mode
    - one or more @handles/t.me/<name> links -> DIRECT mode
    - plain words -> KEYWORD mode
    """
    clean = raw.strip()
    if not clean:
        return TelegramInputPlan(mode="GLOBAL", raw_query=raw)

    # UPDATED LOGIC (C5): Distinct rejection for private invite links
    if "joinchat" in clean or "/+" in clean or "t.me/+" in clean:
        raise ValueError("Private groups and chats can't be read without joining with an account. Only public channels with a web preview are supported.")

    # Check for comma-separated list of direct handles (or space-separated only if all tokens have @ or t.me/ prefix)
    # e.g. "@channel1, @channel2" or "t.me/chan1, t.me/chan2"
    has_comma = "," in clean
    possible_tokens = [tok.strip().rstrip(",") for tok in re.split(r"[\s,]+", clean) if tok.strip()]
    if len(possible_tokens) > 1:
        if has_comma or all(tok.startswith("@") or "t.me/" in tok for tok in possible_tokens):
            parsed_handles: list[str] = []
            is_all_valid = True
            for tok in possible_tokens:
                try:
                    parsed_handles.append(normalize_channel_handle(tok))
                except Exception:
                    is_all_valid = False
                    break
            if is_all_valid and parsed_handles:
                return TelegramInputPlan(
                    mode="DIRECT",
                    raw_query=raw,
                    channels=parsed_handles,
                )

    # Check for handle + keywords pattern: e.g. "@web3hiring python remote"
    parts = clean.split(None, 1)
    first_token = parts[0]
    if (first_token.startswith("@") or "t.me/" in first_token) and len(parts) > 1:
        channel_norm = normalize_channel_handle(first_token)
        search_kw = parts[1].strip()
        return TelegramInputPlan(
            mode="DIRECT_SEARCH",
            raw_query=raw,
            channels=[channel_norm],
            search_q=search_kw,
            keyword=search_kw,
        )

    # Check for single direct handle or URL (e.g. "@web3hiring", "https://t.me/remotejobs_dev", "web3hiring")
    if len(clean.split()) == 1 and not any(ch in clean for ch in (" ", "|", ",", ";")):
        try:
            ch_norm = normalize_channel_handle(clean)
            return TelegramInputPlan(
                mode="DIRECT",
                raw_query=raw,
                channels=[ch_norm],
            )
        except Exception:
            pass

    # Plain words -> KEYWORD discovery mode
    return TelegramInputPlan(
        mode="KEYWORD",
        raw_query=raw,
        keyword=clean,
    )


def normalize_channel_handle(raw_input: str) -> str:
    """
    Validate and extract clean username from string, @handle, or URL.
    Rejects invalid links, joinchat/invite links, or invalid characters.
    """
    s = (raw_input or "").strip().strip("\"'<>")
    if not s:
        raise ValueError("Channel username or URL cannot be empty.")

    # UPDATED LOGIC (C5): Distinct rejection for private invite links
    if "joinchat" in s or "/+" in s or "t.me/+" in s:
        raise ValueError("Private groups and chats can't be read without joining with an account. Only public channels with a web preview are supported.")

    # Strip query string / fragment and trailing slashes before matching, so inputs like
    # "https://t.me/s/channel/?before=10", "t.me/channel/123" or "@channel/" all normalize.
    s = s.split("?", 1)[0].split("#", 1)[0].strip().rstrip("/")
    url_body = re.sub(r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/", "", s, flags=re.IGNORECASE)
    if url_body != s:
        segments = [seg for seg in url_body.split("/") if seg]
        if segments and segments[0].lower() == "s":
            segments = segments[1:]
        if segments and segments[0].lower() not in _RESERVED_TME_PATHS:
            cand = segments[0].lstrip("@")
            if HANDLE_ONLY_RE.match(cand):
                return cand
        raise ValueError(f"Invalid Telegram channel identifier: '{raw_input}'. Expected public @channel or t.me/channel.")

    m_url = TELEGRAM_HANDLE_RE.search(s)
    if m_url:
        return m_url.group(1).lstrip("@")

    m_handle = HANDLE_ONLY_RE.match(s)
    if m_handle:
        return m_handle.group(1).lstrip("@")

    clean = s.lstrip("@").strip("/").split("/")[-1]
    if HANDLE_ONLY_RE.match(clean):
        return clean

    raise ValueError(f"Invalid Telegram channel identifier: '{raw_input}'. Expected public @channel or t.me/channel.")


class TelegramPublicScraper:
    """Zero-Account, $0 Cost Public Telegram Channel Scraper."""

    def __init__(
        self,
        connect_timeout: float = 10.0,
        read_timeout: float = 20.0,
        max_retries: int = 3,
        request_delay: float = 1.5,
        max_pages_cap: int = 25,
    ) -> None:
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_retries = max_retries
        self.request_delay = request_delay
        self.max_pages_cap = max_pages_cap

    # UPDATED LOGIC: Return None for missing metrics (never fake 0 or placeholders)
    def _parse_views_str(self, views_str: str) -> int | None:
        """Parse Telegram view string like '1.2K', '3.5M', or '850' into integer, or None if absent."""
        if not views_str:
            return None
        v = views_str.strip().upper()
        try:
            if v.endswith("K"):
                return int(float(v[:-1]) * 1000)
            if v.endswith("M"):
                return int(float(v[:-1]) * 1000000)
            return int(v.replace(",", ""))
        except Exception:
            return None

    @staticmethod
    def _extract_message_text(text_el: Any) -> str:
        """
        # UPDATED LOGIC (N1): Separator-aware text extraction for Telegram HTML.
        - Replaces <br> and <br/> tags with newline characters so paragraphs don't squash.
        - Uses separator=' ' so inline elements (<a>, <b>, <i>, <code>, <span>, emoji containers)
          do not join without spaces (e.g. 'Crypto.com' + 'is hiring' -> 'Crypto.com is hiring').
        - Preserves emojis and unicode characters intact.
        - Normalizes runs of horizontal spaces/tabs on each line while preserving intentional line breaks.
        - Collapses 3+ consecutive newlines to 2.
        """
        if not text_el:
            return ""
        try:
            for br in text_el.css("br"):
                br.replace_with("\n")
            raw_text = text_el.text(separator=" ", strip=False)
            lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in raw_text.split("\n")]
            cleaned = "\n".join(lines)
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
            return cleaned.strip()
        except Exception:
            return text_el.text(strip=True) if text_el else ""

    def parse_page_html(self, html: str, channel: str) -> tuple[list[PublicTelegramMessage], int | None, str]:
        """
        Parse t.me/s/{channel} HTML page using selectolax.
        Returns:
            messages: list of PublicTelegramMessage
            oldest_id: int | None (for pagination ?before=)
            channel_title: str
        """
        tree = LexborHTMLParser(html)

        # Extract channel title from header
        title_el = tree.css_first(".tgme_channel_info_header_title")
        channel_title = title_el.text(strip=True) if title_el else f"@{channel}"

        # Extract channel description from header (C2)
        desc_el = tree.css_first(".tgme_channel_info_description") or tree.css_first(".tgme_page_description")
        channel_desc = desc_el.text(strip=True) if desc_el else ""

        # Find all message nodes. Prefer the canonical wrapper, but fall back to any element
        # carrying data-post so minor wrapper-class changes on Telegram's side don't zero us out.
        msg_elements: list[Any] = []
        for wrap in tree.css(".tgme_widget_message_wrap"):
            el = wrap.css_first(".tgme_widget_message") or wrap.css_first("[data-post]")
            if el is not None:
                msg_elements.append(el)
        if not msg_elements:
            msg_elements = list(tree.css(".tgme_widget_message[data-post]")) or list(tree.css("[data-post]"))

        messages: list[PublicTelegramMessage] = []
        oldest_id: int | None = None
        seen_in_page: set[int] = set()

        for msg_el in msg_elements:
            # Extract message ID from data-post attribute (e.g., "remotejobs_dev/5197"),
            # falling back to the date permalink (e.g., "https://t.me/remotejobs_dev/5197").
            msg_id: int | None = None
            data_post = (msg_el.attributes.get("data-post") or "").strip()
            if "/" in data_post:
                try:
                    msg_id = int(data_post.rsplit("/", 1)[-1])
                except ValueError:
                    msg_id = None
            if not msg_id:
                date_link = msg_el.css_first("a.tgme_widget_message_date")
                href = (date_link.attributes.get("href") or "") if date_link else ""
                m_id = re.search(r"/(\d+)/?(?:\?.*)?$", href)
                if m_id:
                    msg_id = int(m_id.group(1))

            if not msg_id or msg_id in seen_in_page:
                continue
            seen_in_page.add(msg_id)

            if oldest_id is None or msg_id < oldest_id:
                oldest_id = msg_id

            # Extract text content using separator-aware and br-preserving extractor (N1)
            text_el = msg_el.css_first(".tgme_widget_message_text") or msg_el.css_first(".js-message_text")
            text_content = self._extract_message_text(text_el)

            # Author signature (optional; present on channels with signed posts / groups)
            author_el = (
                msg_el.css_first(".tgme_widget_message_from_author")
                or msg_el.css_first(".tgme_widget_message_author .tgme_widget_message_owner_name")
            )
            author = author_el.text(strip=True) if author_el else None

            # Extract published date, preferring the message date link's <time datetime>
            time_el = msg_el.css_first(".tgme_widget_message_date time[datetime]") or msg_el.css_first("time[datetime]") or msg_el.css_first("time")
            datetime_str: str | None = None
            if time_el:
                datetime_str = time_el.attributes.get("datetime")

            # Views (None if absent in HTML)
            views_el = msg_el.css_first(".tgme_widget_message_views")
            views_count = self._parse_views_str(views_el.text(strip=True)) if views_el else None

            # Forwards / shares count if visible
            forwards_count: int | None = None
            fwd_el = msg_el.css_first(".tgme_widget_message_forwards")
            if fwd_el:
                forwards_count = self._parse_views_str(fwd_el.text(strip=True))

            # Reactions count if visible
            reactions_count: int | None = None
            react_el = msg_el.css_first(".tgme_widget_message_reactions, .tgme_widget_message_reaction_count")
            if react_el:
                reactions_count = self._parse_views_str(react_el.text(strip=True))

            # Media presence
            has_media = False
            media_type = None
            if msg_el.css_first(".tgme_widget_message_photo_wrap"):
                has_media = True
                media_type = "photo"
            elif msg_el.css_first(".tgme_widget_message_video"):
                has_media = True
                media_type = "video"
            elif msg_el.css_first(".tgme_widget_message_document"):
                has_media = True
                media_type = "document"

            # Canonical post URL
            post_url = f"https://t.me/{channel}/{msg_id}"

            # Outbound links
            links = LINK_EXTRACT_RE.findall(text_content)
            for a in (text_el.css("a") if text_el else []):
                href = a.attributes.get("href", "")
                if href and href not in links:
                    links.append(href)

            messages.append(
                PublicTelegramMessage(
                    message_id=msg_id,
                    channel=channel,
                    channel_title=channel_title,
                    channel_description=channel_desc,
                    text=text_content,
                    source_published_at=datetime_str,
                    date=datetime_str,
                    views=views_count,
                    forwards=forwards_count,
                    reactions=reactions_count,
                    post_url=post_url,
                    has_media=has_media,
                    media_type=media_type,
                    links=links,
                    author=author,
                )
            )

        return messages, oldest_id, channel_title

    # NEW FEATURE (N5 & A1/A6): Configuration-driven Telegram Transport with Direct-First, Relay Fallback,
    # Circuit-Breaker, Short-TTL Page Cache, and per-job Relay Budget.
    async def fetch_channel_page(
        self,
        client: httpx.AsyncClient,
        channel: str,
        before_id: int | None = None,
        search_q: str | None = None,
        job_id: str = "default",
    ) -> tuple[PublicScraperStatus, str, str | None, str]:
        """
        Fetch HTML for t.me/s/{channel} respecting transport config and circuit breaker.
        Supports in-channel search ?q={search_q}.
        Returns: (status, html, error_detail, transport_used)
        """
        from leadsweep.config import get_settings
        settings = get_settings()
        transport_pref = getattr(settings, "telegram_transport", "auto").lower()  # auto | direct | relay
        relay_budget = getattr(settings, "telegram_relay_max_requests", 25)
        direct_timeout = getattr(settings, "telegram_direct_timeout", 2.0)

        direct_url = f"https://t.me/s/{channel}"
        cache_key = f"{channel}:{before_id or 'latest'}:{search_q or ''}"

        # 1. Page Cache Check (short TTL to avoid redundant fetches)
        now = time.time()
        if cache_key in _PAGE_CACHE:
            ts, cached_html, cached_transport = _PAGE_CACHE[cache_key]
            if now - ts < _PAGE_CACHE_TTL:
                _TRANSPORT_MGR.record_cache_hit()
                log.info("Telegram page cache hit for %s (age=%.1fs, transport=%s)", cache_key, now - ts, cached_transport)
                return "OK", cached_html, None, f"{cached_transport}:cache"

        params: dict[str, Any] = {}
        if before_id:
            params["before"] = before_id
        if search_q:
            params["q"] = search_q

        # 2. Determine transport execution order
        transports_to_try: list[str] = []
        if transport_pref == "direct":
            transports_to_try = ["direct"]
        elif transport_pref == "relay":
            transports_to_try = ["relay"]
        else:  # auto
            if _TRANSPORT_MGR.is_direct_circuit_open():
                log.info("Direct transport circuit open for Telegram. Bypassing direct and attempting relay.")
                transports_to_try = ["relay"]
            else:
                transports_to_try = ["direct", "relay"]

        last_error = ""

        for transport in transports_to_try:
            if transport == "direct":
                # Single direct attempt with tight configurable timeout (default 2s)
                # Fail fast to relay instead of wasting 15s in retry loops!
                _TRANSPORT_MGR.record_direct_attempt()
                try:
                    resp = await client.get(direct_url, params=params, timeout=direct_timeout)
                    if resp.status_code == 429:
                        retry_after = 5
                        try:
                            retry_after = int(resp.headers.get("Retry-After", 5))
                        except Exception:
                            pass
                        _TRANSPORT_MGR.record_direct_failure()
                        return "RATE_LIMITED", "", f"Telegram 429 Rate Limit (Retry-After: {retry_after}s)", "direct"

                    try:
                        final_url = str(resp.url or "")
                    except Exception:
                        final_url = ""
                    # t.me/s/<x> redirects to t.me/<x> when a handle has no public preview
                    # (private channel, user account, bot, or non-existent username).
                    redirected_off_preview = bool(final_url) and "/s/" not in final_url

                    if resp.status_code in (404, 302, 301):
                        _TRANSPORT_MGR.record_direct_success()  # Telegram answered; transport is healthy
                        if resp.status_code == 404 or redirected_off_preview:
                            return "ACCESS_RESTRICTED", "", ACCESS_RESTRICTED_DETAIL, "direct"
                        return "EMPTY", "", f"Channel @{channel} returned status {resp.status_code}.", "direct"

                    if resp.status_code == 200:
                        html = resp.text
                        has_preview_markup = "tgme_channel_info" in html or "tgme_widget_message" in html
                        if not has_preview_markup or (redirected_off_preview and "tgme_widget_message" not in html):
                            _TRANSPORT_MGR.record_direct_success()
                            return "ACCESS_RESTRICTED", html, ACCESS_RESTRICTED_DETAIL, "direct"
                        _TRANSPORT_MGR.record_direct_success()
                        _PAGE_CACHE[cache_key] = (now, html, "direct")
                        return "OK", html, None, "direct"

                    last_error = f"Direct HTTP {resp.status_code}"
                except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as e:
                    _TRANSPORT_MGR.record_direct_failure()
                    last_error = f"Direct connection timeout/error: {e}"
                    log.info("Direct transport failed for @%s: %s (falling back to relay immediately)", channel, e)
                except Exception as e:
                    last_error = str(e)

            elif transport == "relay":
                if not _TRANSPORT_MGR.can_use_relay(job_id=job_id, max_relay_budget=relay_budget):
                    msg = f"Telegram relay request budget exhausted ({relay_budget} reqs/job limit)."
                    log.warning(msg)
                    return "SOURCE_UNAVAILABLE", "", msg, "relay"

                _TRANSPORT_MGR.record_relay_use(job_id=job_id, call_type="channel")
                relay_url = f"https://r.jina.ai/{direct_url}"
                p_headers = {"X-Return-Format": "html", "X-No-Cache": "true"}
                try:
                    p_resp = await client.get(relay_url, params=params, headers=p_headers, timeout=12.0)
                    if p_resp.status_code == 200 and p_resp.text:
                        p_text = p_resp.text
                        if "tgme_channel_info" in p_text or "tgme_widget_message" in p_text or f"/{channel}/" in p_text:
                            _PAGE_CACHE[cache_key] = (now, p_text, "relay")
                            log.info("Telegram page successfully fetched via public relay for @%s", channel)
                            return "OK", p_text, None, "relay"
                        if "Contact @" in p_text or "Send Message" in p_text or "tgme_page_extra" in p_text:
                            return "ACCESS_RESTRICTED", p_text, ACCESS_RESTRICTED_DETAIL, "relay"
                    last_error = f"Relay returned HTTP {p_resp.status_code}"
                except Exception as p_err:
                    last_error = f"Relay transport failure: {p_err}"
                    log.warning("Public mirror relay failed for @%s: %s", channel, p_err)

        # Both transports failed or requested transport failed
        return "SOURCE_UNAVAILABLE", "", f"All transports failed for @{channel}. Last error: {last_error}", "none"

    # NEW FEATURE (N1, N5, A1, A2): Scrape channel with detailed status reporting
    async def scrape_channel(
        self,
        channel: str,
        limit: int = 50,
        search_q: str | None = None,
        job_id: str = "default",
    ) -> AsyncIterator[PublicTelegramMessage]:
        """
        Asynchronously stream authentic messages backwards from t.me/s/{channel}.
        Guarantees deduplication, stop at limit, and attaches transport_used to each message.
        """
        clean_channel = normalize_channel_handle(channel)
        seen_ids: set[int] = set()
        yielded = 0
        before_id: int | None = None
        pages_fetched = 0

        async with httpx.AsyncClient(
            headers=BROWSER_HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(self.read_timeout, connect=self.connect_timeout),
        ) as client:
            while yielded < limit and pages_fetched < self.max_pages_cap:
                pages_fetched += 1
                status, html, err, transport_used = await self.fetch_channel_page(
                    client,
                    clean_channel,
                    before_id=before_id,
                    search_q=search_q,
                    job_id=job_id,
                )

                if status != "OK" or not html:
                    log.info("Telegram fetch stopped for @%s: status=%s, err=%s", clean_channel, status, err)
                    break

                messages, oldest_id, _ = self.parse_page_html(html, clean_channel)
                if not messages:
                    break

                new_messages_found = False
                for msg in messages:
                    if msg.message_id not in seen_ids:
                        seen_ids.add(msg.message_id)
                        msg.transport_used = transport_used
                        yield msg
                        yielded += 1
                        new_messages_found = True
                        if yielded >= limit:
                            break

                # If no new messages were encountered in this page or oldest_id didn't advance, stop
                if not new_messages_found or oldest_id is None or (before_id is not None and oldest_id >= before_id):
                    break

                before_id = oldest_id
                if self.request_delay > 0:
                    await asyncio.sleep(self.request_delay)

    # NEW FEATURE (A2 & F1): Direct scraping returning structured report
    async def scrape_channel_with_status(
        self,
        channel: str,
        limit: int = 50,
        search_q: str | None = None,
        job_id: str = "default",
    ) -> tuple[list[PublicTelegramMessage], PublicScraperStatus, str | None]:
        """Scrape channel and return (messages, final_status, status_detail)."""
        messages: list[PublicTelegramMessage] = []
        final_status: PublicScraperStatus = "OK"
        status_detail: str | None = None

        try:
            clean_channel = normalize_channel_handle(channel)
        except ValueError as ve:
            return [], "ACCESS_RESTRICTED", str(ve)

        pages_fetched = 0
        before_id: int | None = None
        seen_ids: set[int] = set()

        async with httpx.AsyncClient(
            headers=BROWSER_HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(self.read_timeout, connect=self.connect_timeout),
        ) as client:
            while len(messages) < limit and pages_fetched < self.max_pages_cap:
                pages_fetched += 1
                status, html, err, transport_used = await self.fetch_channel_page(
                    client, clean_channel, before_id=before_id, search_q=search_q, job_id=job_id
                )
                if pages_fetched == 1:
                    final_status = status
                    status_detail = err

                if status != "OK" or not html:
                    break

                parsed, oldest_id, _ = self.parse_page_html(html, clean_channel)
                if not parsed:
                    break

                new_found = False
                for m in parsed:
                    if m.message_id not in seen_ids:
                        seen_ids.add(m.message_id)
                        m.transport_used = transport_used
                        messages.append(m)
                        new_found = True
                        if len(messages) >= limit:
                            break

                if not new_found or oldest_id is None or (before_id is not None and oldest_id >= before_id):
                    break
                before_id = oldest_id
                if self.request_delay > 0 and len(messages) < limit:
                    await asyncio.sleep(self.request_delay)

            if not messages and final_status == "OK":
                final_status = "EMPTY"
                status_detail = f"Public web preview for @{clean_channel} contains no messages" + (f" matching '{search_q}'" if search_q else ".")

        return messages, final_status, status_detail


# NEW FEATURE (N5 & A6): Process-Wide Telegram Transport Circuit-Breaker, Page Cache, and Relay Budget
_PAGE_CACHE: dict[str, tuple[float, str, str]] = {}  # key -> (timestamp, html, transport)
_PAGE_CACHE_TTL = 180.0  # 3 minutes short TTL

class TelegramTransportManager:
    """Manages direct vs public mirror relay transport with process-wide circuit-breakers and per-job budgets."""
    def __init__(self):
        self.direct_failures = 0
        self.circuit_open_until = 0.0
        self.job_relay_counts: dict[str, int] = defaultdict(int)
        # Detailed request metrics (C3 accounting)
        self.direct_attempts = 0
        self.direct_successes = 0
        self.discovery_relay_calls = 0
        self.channel_relay_calls = 0
        self.cache_hits = 0

    def is_direct_circuit_open(self) -> bool:
        return time.time() < self.circuit_open_until

    def record_direct_attempt(self):
        self.direct_attempts += 1

    def record_direct_failure(self):
        self.direct_failures += 1
        from leadsweep.config import get_settings
        cb_ttl = getattr(get_settings(), "telegram_direct_cb_ttl_s", 300.0)
        # Open circuit immediately after 2 failures for cb_ttl seconds
        if self.direct_failures >= 2:
            self.circuit_open_until = time.time() + cb_ttl
            log.warning("Telegram direct transport circuit OPEN (failed %d times). Defaulting to public relay for %.0fs.",
                        self.direct_failures, cb_ttl)

    def record_direct_success(self):
        self.direct_successes += 1
        self.direct_failures = 0
        self.circuit_open_until = 0.0

    def can_use_relay(self, job_id: str = "default", max_relay_budget: int = 25) -> bool:
        return self.job_relay_counts[job_id] < max_relay_budget

    def record_relay_use(self, job_id: str = "default", call_type: str = "channel"):
        self.job_relay_counts[job_id] += 1
        if call_type == "discovery":
            self.discovery_relay_calls += 1
        else:
            self.channel_relay_calls += 1

    def record_cache_hit(self):
        self.cache_hits += 1

    def get_accounting_summary(self, job_id: str = "default") -> dict[str, Any]:
        return {
            "job_id": job_id,
            "job_relay_requests": self.job_relay_counts.get(job_id, 0),
            "total_discovery_relay_calls": self.discovery_relay_calls,
            "total_channel_relay_calls": self.channel_relay_calls,
            "total_relay_requests": self.discovery_relay_calls + self.channel_relay_calls,
            "total_direct_attempts": self.direct_attempts,
            "total_direct_successes": self.direct_successes,
            "total_direct_failures": self.direct_failures,
            "total_cache_hits": self.cache_hits,
            "direct_circuit_open": self.is_direct_circuit_open(),
        }

    def reset_for_tests(self):
        self.direct_failures = 0
        self.circuit_open_until = 0.0
        self.job_relay_counts.clear()
        self.direct_attempts = 0
        self.direct_successes = 0
        self.discovery_relay_calls = 0
        self.channel_relay_calls = 0
        self.cache_hits = 0
        _PAGE_CACHE.clear()

_TRANSPORT_MGR = TelegramTransportManager()


def parse_page_html_with_transport(
    parser_instance: Any,
    html: str,
    channel: str,
    transport_name: str = "direct"
) -> tuple[list[PublicTelegramMessage], int | None, str]:
    """Parse HTML and tag messages with the transport that delivered the payload."""
    messages, oldest_id, title = parser_instance.parse_page_html(html, channel)
    for m in messages:
        m.transport_used = transport_name
    return messages, oldest_id, title


# ---------------------------------------------------------------------------
# Flexible query matching (pre-LLM candidate filter)
# ---------------------------------------------------------------------------
# Real Telegram posts almost never contain a user's query verbatim ("We need to hire new
# developer" vs. "Hiring a Python developer"). Matching is therefore done on *concepts*:
# query words are stemmed, filler words dropped, and words that express the same idea
# (hire / hiring / looking for / vacancy, developer / dev / engineer) collapse into one
# concept. A post matches when it covers at least half of the query's concepts.

_QUERY_STOPWORDS = {
    "a", "an", "the", "in", "on", "at", "for", "to", "of", "and", "or", "is", "are", "be", "been",
    "with", "by", "from", "as", "it", "its", "this", "that", "these", "those", "there", "here",
    "we", "i", "you", "he", "she", "they", "our", "us", "my", "me", "your", "their", "them",
    "new", "some", "someone", "somebody", "any", "anyone", "who", "what", "which", "will", "would",
    "can", "could", "should", "please", "get", "got", "just", "also", "very", "really", "now",
    "do", "does", "did", "have", "has", "had", "am", "was", "were", "about", "into", "more",
}

_CONCEPT_GROUPS_RAW: dict[str, tuple[str, ...]] = {
    "HIRE": (
        "hire", "hiring", "hired", "hires", "recruit", "recruiting", "recruiter", "recruitment",
        "need", "needed", "needs", "seeking", "seek", "looking", "wanted", "want", "vacancy",
        "vacancies", "opening", "openings", "position", "positions", "job", "jobs", "role", "roles",
        "career", "careers", "employ", "employment", "join", "opportunity", "contract", "freelance",
        "gig", "gigs", "apply",
    ),
    "DEV": (
        "developer", "developers", "dev", "devs", "engineer", "engineers", "engineering",
        "programmer", "programmers", "coder", "coders", "swe", "sde", "fullstack", "frontend",
        "backend", "software",
    ),
    "DESIGN": ("designer", "designers", "design", "ux", "ui"),
    "MARKETING": ("marketer", "marketing", "growth", "seo", "smm"),
}


def stem_token(word: str) -> str:
    """Tiny suffix-stripping stemmer: hiring/hired/hire -> hir, developers -> develop."""
    w = word.lower()
    for suf in ("ments", "ment", "ings", "ing", "ers", "er", "ed", "es", "s", "e"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


_STEM_TO_CONCEPT: dict[str, str] = {}
for _concept, _words in _CONCEPT_GROUPS_RAW.items():
    for _w in _words:
        _STEM_TO_CONCEPT.setdefault(stem_token(_w), _concept)


def _word_tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", (text or "").lower(), flags=re.UNICODE)


def query_concepts(query: str) -> set[str]:
    """Reduce a free-text query to its set of concepts (concept names or stems)."""
    concepts: set[str] = set()
    for tok in _word_tokens(query):
        if tok in _QUERY_STOPWORDS or (len(tok) < 3 and tok not in ("ui", "ux", "qa", "ai", "ml")):
            continue
        stem = stem_token(tok)
        concepts.add(_STEM_TO_CONCEPT.get(stem, stem))
    return concepts


def text_concepts(text: str) -> set[str]:
    """Concepts present in a post (every token, stemmed, mapped through concept groups)."""
    found: set[str] = set()
    for tok in _word_tokens(text):
        stem = stem_token(tok)
        found.add(stem)
        concept = _STEM_TO_CONCEPT.get(stem)
        if concept:
            found.add(concept)
    return found


def query_match_score(query: str, text: str) -> float:
    """Fraction (0..1) of the query's concepts covered by ``text``. Empty query -> 1.0."""
    concepts = query_concepts(query)
    if not concepts:
        return 1.0
    if not text:
        return 0.0
    normalized_query = " ".join(_word_tokens(query))
    if normalized_query and normalized_query in " ".join(_word_tokens(text)):
        return 1.0
    present = text_concepts(text)
    hits = 0
    for c in concepts:
        if c in present:
            hits += 1
        elif c not in _CONCEPT_GROUPS_RAW and len(c) >= 4 and any(p.startswith(c) for p in present):
            hits += 1  # prefix match: "solid" ~ "solidity"
    return hits / len(concepts)


def matches_query(query: str, text: str, min_ratio: float = 0.5) -> bool:
    """
    True when ``text`` covers at least ``min_ratio`` of the query's concepts, and never fewer
    than two of them (or all of them for one-concept queries). Without that floor, a two-concept
    query like "hire developer" would accept any post that merely says "developers" or "join".
    """
    concepts = query_concepts(query)
    if not concepts:
        return True
    score = query_match_score(query, text)
    needed = max(min(len(concepts), 2), math.ceil(len(concepts) * min_ratio))
    return score > 0 and score * len(concepts) + 1e-9 >= needed


def search_term_for_query(query: str) -> str | None:
    """
    Pick a short, high-recall term for Telegram's in-channel ``?q=`` search.

    Telegram's preview search needs every word to appear, so sending a full sentence returns
    nothing. Prefer the most specific non-intent word (e.g. "developer"), else any content word.
    """
    words = [t for t in _word_tokens(query) if t not in _QUERY_STOPWORDS and len(t) >= 3]
    if not words:
        return None
    specific = [w for w in words if _STEM_TO_CONCEPT.get(stem_token(w)) != "HIRE"]
    pool = specific or words
    return max(pool, key=len)
