# NEW FEATURE: Telegram MTProto Scraper Module
"""Telethon-based Telegram Scraper for LeadSweep / LeadSweep.

Features:
- 100% $0 MTProto client integration via Telethon.
- Supports 4 scraper types:
  1. Channel/Group messages (by @username or t.me link; limit, date range)
  2. Keyword search (across specific channel or global)
  3. Group members (where permissions allow, graceful fallback)
  4. Channel info (metadata, participant counts, description, links)
- Full message fields extraction:
  message_id, channel, sender (id/username), text, date, views, forwards,
  reactions, reply_to, media type, links, mentions.
- Robust error handling:
  FloodWaitError (auto-sleep + retry), private/banned channels,
  invalid usernames, unauthenticated sessions.
- Polite rate-limiting with random jitter delays to prevent account bans.
"""
from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import logging
import os
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from pydantic import BaseModel, Field

from leadsweep.adapters import LeadRecord, PlatformAdapter
from leadsweep.config import get_settings

log = logging.getLogger("leadsweep.telegram_scraper")

# NEW FEATURE (C2): Deterministic stable ID derived strictly from (platform, channel, message_id)
def make_telegram_lead_id(channel: str, message_id: int | str) -> str:
    norm_ch = str(channel).strip().lower().lstrip("@")
    raw = f"telegram:{norm_ch}:{message_id}"
    num = int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:14], 16)
    return f"tg_{num}"

# Regex to parse usernames or channel handles from inputs (e.g. @channel, https://t.me/channel, t.me/s/channel)
TELEGRAM_HANDLE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t\.me/|telegram\.me/)(?:s/)?@?([a-zA-Z0-9_]{4,32})/?",
    re.IGNORECASE,
)
MENTION_OR_HANDLE_RE = re.compile(r"^@?([a-zA-Z0-9_]{4,32})$", re.IGNORECASE)
LINK_EXTRACT_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
MENTION_EXTRACT_RE = re.compile(r"@([a-zA-Z0-9_]{3,32})", re.IGNORECASE)


@dataclass
class TelegramMessageRecord:
    """Normalized structured Telegram message record."""
    message_id: int
    channel: str
    channel_id: int | None
    sender_id: int | None
    sender_username: str | None
    sender_name: str | None
    text: str
    date: str
    views: int
    forwards: int
    reactions_count: int
    reply_to_msg_id: int | None
    media_type: str | None
    links: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    raw_url: str = ""

    def to_lead_record(self) -> LeadRecord:
        """Convert to LeadRecord for storage and pipeline compatibility."""
        lead_id = make_telegram_lead_id(self.channel, self.message_id)
        author_user = self.sender_username or self.channel or "telegram_user"
        author_title = self.sender_name or f"@{author_user}"

        return LeadRecord(
            id=lead_id,
            platform="telegram",
            source_id=str(self.message_id),
            source_url=self.raw_url or f"https://t.me/{self.channel}/{self.message_id}",
            name=author_title,
            username=author_user,
            headline=f"Telegram message in @{self.channel} #{self.message_id}",
            title=f"Telegram update in @{self.channel}",
            bio=f"Sender ID: {self.sender_id or 'N/A'} | Channel: @{self.channel}",
            content=self.text or "[Media/Attachment Message]",
            profile_url=f"https://t.me/{author_user.lstrip('@')}" if author_user else None,
            engagement={
                "views": self.views,
                "forwards": self.forwards,
                "reactions": self.reactions_count,
                "likes": self.reactions_count,
                "replies": 1 if self.reply_to_msg_id else 0,
            },
            lead_score=65,
            intent="telegram message / community broadcast",
            published_at=self.date if self.date else None,
            updated_at=self.date or datetime.datetime.now(datetime.timezone.utc).isoformat(),
            collected_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )


class TelegramChannelInfo(BaseModel):
    """Channel/Group metadata."""
    id: int
    title: str
    username: str | None
    about: str | None
    participants_count: int | None
    verified: bool = False
    scam: bool = False
    broadcast: bool = False
    megagroup: bool = False
    link: str


class TelegramScraper:
    """Telethon MTProto Telegram Scraper with polite pacing and resilient error handling."""

    def __init__(
        self,
        api_id: int | None = None,
        api_hash: str | None = None,
        session_path: str | Path | None = None,
    ) -> None:
        settings = get_settings()

        # Read secrets from env / settings
        raw_id = os.getenv("TELEGRAM_API_ID") or settings.telegram_api_id
        self.api_id = int(raw_id) if raw_id else None
        self.api_hash = os.getenv("TELEGRAM_API_HASH") or settings.telegram_api_hash

        raw_session = os.getenv("TELEGRAM_SESSION_PATH") or str(settings.telegram_session_path)
        self.session_path = Path(raw_session)

        self._client: Any = None

    @classmethod
    def clean_handle(cls, target: str) -> str:
        """Extract clean username from string, URL, or @handle."""
        t = target.strip()
        m_url = TELEGRAM_HANDLE_RE.search(t)
        if m_url:
            return m_url.group(1).lstrip("@")
        m_handle = MENTION_OR_HANDLE_RE.match(t)
        if m_handle:
            return m_handle.group(1).lstrip("@")
        return t.lstrip("@").strip("/")

    async def _get_client(self) -> Any:
        """Create and start Telethon TelegramClient."""
        from telethon import TelegramClient

        if not self.api_id or not self.api_hash:
            raise RuntimeError(
                "Telegram API credentials missing. Please set TELEGRAM_API_ID and "
                "TELEGRAM_API_HASH in your .env file or environment."
            )

        # Ensure parent folder for session exists
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        session_str = str(self.session_path.with_suffix(""))

        if self._client is None:
            self._client = TelegramClient(session_str, self.api_id, self.api_hash)

        if not self._client.is_connected():
            await self._client.connect()

        return self._client

    async def is_authorized(self) -> bool:
        """Check if session is logged in and authorized."""
        try:
            client = await self._get_client()
            return await client.is_user_authorized()
        except Exception as e:
            log.warning("Telegram session authorization check failed: %s", e)
            return False

    async def close(self) -> None:
        """Disconnect client cleanly."""
        if self._client and self._client.is_connected():
            await self._client.disconnect()
            self._client = None

    async def __aenter__(self) -> "TelegramScraper":
        await self._get_client()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def _polite_delay(self, min_s: float = 0.8, max_s: float = 2.2) -> None:
        """Apply polite randomized sleep to reduce flood risks."""
        sleep_s = random.uniform(min_s, max_s)
        await asyncio.sleep(sleep_s)

    async def get_channel_info(self, target: str) -> TelegramChannelInfo:
        """Scraper Type 4: Channel/Group Info Extraction."""
        from telethon.errors import (
            ChannelInvalidError,
            ChannelPrivateError,
            FloodWaitError,
            UsernameInvalidError,
            UsernameNotOccupiedError,
        )
        from telethon.tl.functions.channels import GetFullChannelRequest

        client = await self._get_client()
        handle = self.clean_handle(target)

        try:
            entity = await client.get_entity(handle)
            full_data = await client(GetFullChannelRequest(entity))
            full_chat = full_data.full_chat

            title = getattr(entity, "title", handle)
            username = getattr(entity, "username", handle)
            about = getattr(full_chat, "about", "") or ""
            participants = getattr(full_chat, "participants_count", None)
            verified = getattr(entity, "verified", False)
            scam = getattr(entity, "scam", False)
            broadcast = getattr(entity, "broadcast", False)
            megagroup = getattr(entity, "megagroup", False)

            return TelegramChannelInfo(
                id=entity.id,
                title=title,
                username=username,
                about=about,
                participants_count=participants,
                verified=verified,
                scam=scam,
                broadcast=broadcast,
                megagroup=megagroup,
                link=f"https://t.me/{username}" if username else f"https://t.me/c/{entity.id}",
            )
        except FloodWaitError as e:
            log.warning("Telegram FloodWait encountered: sleeping %d seconds", e.seconds)
            await asyncio.sleep(e.seconds)
            return await self.get_channel_info(target)
        except (ChannelInvalidError, UsernameInvalidError, UsernameNotOccupiedError) as e:
            raise ValueError(f"Telegram channel or username '{target}' does not exist: {e}") from e
        except ChannelPrivateError as e:
            raise PermissionError(f"Telegram channel '{target}' is private or inaccessible: {e}") from e

    async def scrape_channel_messages(
        self,
        target: str,
        limit: int = 50,
        date_from: datetime.datetime | None = None,
        date_to: datetime.datetime | None = None,
        reverse: bool = False,
    ) -> AsyncIterator[TelegramMessageRecord]:
        """Scraper Type 1: Channel/Group Messages extraction."""
        from telethon.errors import (
            ChannelInvalidError,
            ChannelPrivateError,
            FloodWaitError,
            UsernameInvalidError,
            UsernameNotOccupiedError,
        )
        from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto, MessageMediaWebPage

        client = await self._get_client()
        handle = self.clean_handle(target)

        try:
            entity = await client.get_entity(handle)
        except FloodWaitError as e:
            log.warning("Telegram FloodWait on entity fetch: sleeping %d seconds", e.seconds)
            await asyncio.sleep(e.seconds)
            entity = await client.get_entity(handle)
        except (ChannelInvalidError, UsernameInvalidError, UsernameNotOccupiedError) as e:
            log.error("Invalid Telegram target '%s': %s", target, e)
            return
        except ChannelPrivateError as e:
            log.error("Telegram channel '%s' is private or banned: %s", target, e)
            return

        channel_id = getattr(entity, "id", None)
        channel_name = getattr(entity, "username", None) or handle

        count = 0
        async for msg in client.iter_messages(
            entity,
            limit=limit,
            reverse=reverse,
            offset_date=date_to,
        ):
            if count >= limit:
                break

            msg_date = msg.date
            if date_from and msg_date < date_from:
                # If reading backwards, older messages can stop iteration
                if not reverse:
                    break
                continue
            if date_to and msg_date > date_to:
                continue

            text_content = msg.message or ""
            media_type: str | None = None
            if msg.media:
                if isinstance(msg.media, MessageMediaPhoto):
                    media_type = "photo"
                elif isinstance(msg.media, MessageMediaDocument):
                    media_type = "document/video"
                elif isinstance(msg.media, MessageMediaWebPage):
                    media_type = "webpage_preview"
                else:
                    media_type = "other"

            # Sender identification
            sender_id = getattr(msg, "sender_id", None)
            sender_username = None
            sender_name = None
            if msg.sender:
                sender_username = getattr(msg.sender, "username", None)
                first_name = getattr(msg.sender, "first_name", "") or ""
                last_name = getattr(msg.sender, "last_name", "") or ""
                title = getattr(msg.sender, "title", "") or ""
                sender_name = f"{first_name} {last_name}".strip() or title or sender_username

            reactions_count = 0
            if getattr(msg, "reactions", None) and getattr(msg.reactions, "results", None):
                reactions_count = sum(r.count for r in msg.reactions.results)

            links = LINK_EXTRACT_RE.findall(text_content)
            mentions = MENTION_EXTRACT_RE.findall(text_content)

            rec = TelegramMessageRecord(
                message_id=msg.id,
                channel=channel_name,
                channel_id=channel_id,
                sender_id=sender_id,
                sender_username=sender_username,
                sender_name=sender_name,
                text=text_content,
                date=msg_date.isoformat(),
                views=getattr(msg, "views", 0) or 0,
                forwards=getattr(msg, "forwards", 0) or 0,
                reactions_count=reactions_count,
                reply_to_msg_id=msg.reply_to_msg_id if getattr(msg, "reply_to_msg_id", None) else None,
                media_type=media_type,
                links=links,
                mentions=mentions,
                raw_url=f"https://t.me/{channel_name}/{msg.id}",
            )

            count += 1
            yield rec

            # Periodic polite pause
            if count % 15 == 0:
                await self._polite_delay()

    async def search_messages(
        self,
        query: str,
        target: str | None = None,
        limit: int = 50,
    ) -> AsyncIterator[TelegramMessageRecord]:
        """Scraper Type 2: Keyword search across a channel or globally."""
        from telethon.errors import FloodWaitError

        client = await self._get_client()
        entity = None
        channel_name = "telegram"
        channel_id = None

        if target:
            clean = self.clean_handle(target)
            try:
                entity = await client.get_entity(clean)
                channel_name = getattr(entity, "username", clean)
                channel_id = getattr(entity, "id", None)
            except Exception as e:
                log.warning("Could not resolve entity '%s' for search: %s", target, e)
                entity = None

        count = 0
        try:
            async for msg in client.iter_messages(entity=entity, search=query, limit=limit):
                if count >= limit:
                    break

                text_content = msg.message or ""
                sender_id = getattr(msg, "sender_id", None)
                sender_username = None
                sender_name = None
                if msg.sender:
                    sender_username = getattr(msg.sender, "username", None)
                    fn = getattr(msg.sender, "first_name", "") or ""
                    ln = getattr(msg.sender, "last_name", "") or ""
                    sender_name = f"{fn} {ln}".strip() or sender_username

                reactions_count = 0
                if getattr(msg, "reactions", None) and getattr(msg.reactions, "results", None):
                    reactions_count = sum(r.count for r in msg.reactions.results)

                # Channel fallback if global search
                chat_username = channel_name
                if not entity and msg.chat:
                    chat_username = getattr(msg.chat, "username", None) or str(msg.chat_id)

                rec = TelegramMessageRecord(
                    message_id=msg.id,
                    channel=chat_username,
                    channel_id=msg.chat_id or channel_id,
                    sender_id=sender_id,
                    sender_username=sender_username,
                    sender_name=sender_name,
                    text=text_content,
                    date=msg.date.isoformat(),
                    views=getattr(msg, "views", 0) or 0,
                    forwards=getattr(msg, "forwards", 0) or 0,
                    reactions_count=reactions_count,
                    reply_to_msg_id=msg.reply_to_msg_id if getattr(msg, "reply_to_msg_id", None) else None,
                    media_type="media" if msg.media else None,
                    links=LINK_EXTRACT_RE.findall(text_content),
                    mentions=MENTION_EXTRACT_RE.findall(text_content),
                    raw_url=f"https://t.me/{chat_username}/{msg.id}",
                )

                count += 1
                yield rec

                if count % 10 == 0:
                    await self._polite_delay()

        except FloodWaitError as e:
            log.warning("Telegram FloodWait in search: sleeping %d seconds", e.seconds)
            await asyncio.sleep(e.seconds)

    async def scrape_members(
        self,
        target: str,
        limit: int = 50,
    ) -> AsyncIterator[LeadRecord]:
        """Scraper Type 3: Group Members (where permissions allow)."""
        from telethon.errors import (
            ChatAdminRequiredError,
            FloodWaitError,
            RightForbiddenError,
        )

        client = await self._get_client()
        handle = self.clean_handle(target)
        try:
            entity = await client.get_entity(handle)
        except Exception as e:
            log.error("Failed to fetch entity for group members '%s': %s", target, e)
            return

        count = 0
        try:
            async for user in client.iter_participants(entity, limit=limit):
                if count >= limit:
                    break
                username = getattr(user, "username", None) or f"tg_user_{user.id}"
                fn = getattr(user, "first_name", "") or ""
                ln = getattr(user, "last_name", "") or ""
                full_name = f"{fn} {ln}".strip() or username
                phone = getattr(user, "phone", None)
                now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

                rec = LeadRecord(
                    id=f"tg_member_{user.id}",
                    platform="telegram",
                    source_id=str(user.id),
                    source_url=f"https://t.me/{username.lstrip('@')}",
                    name=full_name,
                    username=username,
                    headline=f"Telegram member of @{handle}",
                    title=full_name,
                    bio=f"Telegram user ID: {user.id}",
                    phone=phone,
                    content=f"Member of @{handle}. Verified: {getattr(user, 'verified', False)}",
                    profile_url=f"https://t.me/{username.lstrip('@')}" if username else None,
                    engagement={"followers": 0, "likes": 0, "replies": 0, "views": 0},
                    lead_score=50,
                    intent="group participant / community prospect",
                    collected_at=now_iso,
                )
                count += 1
                yield rec

                if count % 15 == 0:
                    await self._polite_delay()

        except (ChatAdminRequiredError, RightForbiddenError) as e:
            log.warning("Member list restricted by admins for @%s: %s", handle, e)
        except FloodWaitError as e:
            log.warning("FloodWait in member scraping: sleeping %d seconds", e.seconds)
            await asyncio.sleep(e.seconds)


# NEW FEATURE (C4): Derive discovery phrases from ICP/objective via configured LLM (cached & logged)
async def derive_discovery_phrases_from_icp(icp_text: str, conn: Any = None) -> list[str]:
    """
    Derive 3-6 concise search phrases from ICP/objective via existing configured LLM.
    Results are cached in SQLite and logged.
    """
    if not icp_text or not icp_text.strip():
        return []

    cache_key = hashlib.sha256(f"discovery_phrases:{icp_text.strip()}".encode("utf-8")).hexdigest()

    # Check SQLite cache
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT result_json FROM li_classification_cache WHERE content_hash = ?", (cache_key,))
            row = cur.fetchone()
            if row:
                cached_phrases = json.loads(row[0])
                if isinstance(cached_phrases, list) and cached_phrases:
                    log.info("Telegram discovery: Using cached LLM phrases (%d) for ICP: %s", len(cached_phrases), cached_phrases)
                    return cached_phrases
        except Exception as e:
            log.debug("Cache check error for discovery phrases: %s", e)

    phrases: list[str] = []

    # Try configured LLM via get_configured_chat_model
    try:
        from leadsweep.leadintel.llm import get_configured_chat_model
        chat_model = get_configured_chat_model()
        if chat_model:
            prompt = (
                f"You are a talent search and lead generation assistant.\n"
                f"Given this business profile and ICP:\n{icp_text}\n\n"
                f"Derive between 3 and 6 concise search phrases (2-4 words each) suitable for finding public Telegram channels and communities discussing hiring, gigs, contracts, or engineering in this domain.\n"
                f"Return ONLY a JSON array of strings, e.g. [\"phrase one\", \"phrase two\", \"phrase three\"]. Do not wrap in markdown or add extra text."
            )
            resp = await asyncio.to_thread(chat_model.invoke, prompt)
            resp_text = resp.content if hasattr(resp, "content") else str(resp)
            m_json = re.search(r"\[.*?\]", resp_text, re.DOTALL)
            if m_json:
                parsed = json.loads(m_json.group(0))
                if isinstance(parsed, list):
                    phrases = [str(p).strip().strip('"').strip("'") for p in parsed if str(p).strip()][:6]
    except Exception as llm_err:
        log.warning("LLM phrase derivation failed, using fallback extraction: %s", llm_err)

    # Fallback if LLM returned nothing or failed
    if not phrases:
        raw_words = [w.strip() for w in re.split(r"[,;\n\.]+", icp_text) if w.strip()]
        phrases = [w for w in raw_words if len(w.split()) in (1, 2, 3)][:4]

    if phrases:
        log.info("Telegram discovery: Derived %d discovery phrases from ICP via LLM: %s", len(phrases), phrases)
        if conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    "INSERT OR REPLACE INTO li_classification_cache (content_hash, model_version, result_json) VALUES (?, ?, ?)",
                    (cache_key, "llm-discovery-phrases-v1", json.dumps(phrases))
                )
                conn.commit()
            except Exception as e:
                log.debug("Failed to cache discovery phrases: %s", e)

    return phrases


class TelegramAdapter(PlatformAdapter):
    """PlatformAdapter implementation for Telegram."""
    platform_name = "telegram"

    # NEW FEATURE (Phase 1): PlatformAdapter implementation for Telegram with Input Grammar & Status Tracking
    def __init__(self) -> None:
        self.scraper = TelegramScraper()
        from leadsweep.services.telegram_public_scraper import TelegramPublicScraper
        self.public_scraper = TelegramPublicScraper()
        self.last_scrape_status: str = "OK"
        self.last_scrape_detail: str | None = None
        self.channel_statuses: dict[str, str] = {}
        self.candidate_reports: list[dict[str, Any]] = []

    def _resolve_tenant_channels(self, tenant_id: str, storage: Any = None) -> list[str]:
        """# UPDATED LOGIC (C4 b): Tenant-scoped harvested Telegram channels from ALL result rows (X included)."""
        if not tenant_id:
            return []
        channels: list[str] = []
        seen: set[str] = set()
        try:
            if storage and hasattr(storage, "db"):
                cur = storage.db.cursor()
            else:
                import sqlite3
                from leadsweep.config import get_settings
                db_path = getattr(get_settings(), "db_path", "data/leadsweep.db")
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
            cur.execute("""
                SELECT text FROM tweets 
                WHERE (first_run_id IN (SELECT run_id FROM actor_runs WHERE user_email = ? OR user_id = ?))
                LIMIT 100
            """, (tenant_id, tenant_id))
            for r in cur.fetchall():
                m_h = re.findall(r"t(?:elegram)?\.me/(?:s/)?([a-zA-Z0-9_]{4,32})", r[0])
                for h in m_h:
                    if h.lower() not in seen and h.lower() not in ("channel", "joinchat", "share", "addlist"):
                        seen.add(h.lower())
                        channels.append(h)
        except Exception as e:
            log.warning("Failed to resolve tenant channels for %s: %s", tenant_id, e)
        return channels

    async def search(
        self,
        query: str,
        max_items: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> AsyncIterator[LeadRecord]:
        """Search and extract authentic Telegram messages using strict Input Grammar and Zero-Account Public Web Preview."""
        from leadsweep.config import get_settings
        from leadsweep.services.telegram_public_scraper import (
            TelegramPublicScraper,
            parse_telegram_input,
            normalize_channel_handle,
            TelegramInputPlan,
        )

        settings = get_settings()
        pub_scraper = getattr(self, "public_scraper", None) or TelegramPublicScraper()
        yielded = 0
        self.last_scrape_status = "OK"
        self.last_scrape_detail = None
        self.channel_statuses = {}

        filters = filters or {}
        tenant_id = filters.get("tenant_id") or filters.get("user_email") or filters.get("user_id")

        # Step 1: Input Grammar
        try:
            plan = parse_telegram_input(query)
        except ValueError as ve:
            self.last_scrape_status = "ACCESS_RESTRICTED"
            self.last_scrape_detail = str(ve)
            log.warning("Telegram input grammar rejected query '%s': %s", query, ve)
            return

        log.info("Telegram input grammar: mode=%s, channels=%s, kw=%s, search_q=%s",
                 plan.mode, plan.channels, plan.keyword, plan.search_q)

        # -------------------------------------------------------------
        # Mode 1: DIRECT and DIRECT_SEARCH (Single or Multiple Handles)
        # -------------------------------------------------------------
        if plan.mode in ("DIRECT", "DIRECT_SEARCH"):
            channels_to_scrape = plan.channels
            search_param = plan.search_q
            job_id = filters.get("job_id", "default")

            channel_reports: list[str] = []
            self.candidate_reports = []
            had_success = False

            for ch in channels_to_scrape:
                if yielded >= max_items:
                    self.candidate_reports.append({
                        "handle": ch,
                        "source": "direct_input",
                        "status": "SKIPPED",
                        "items_scraped": 0,
                        "transport": "none",
                        "reason_skipped": "target items quota reached"
                    })
                    continue
                msgs, st, err = await pub_scraper.scrape_channel_with_status(
                    channel=ch,
                    limit=max(max_items - yielded, 1),
                    search_q=search_param,
                    job_id=job_id,
                )
                self.channel_statuses[ch] = st
                self.candidate_reports.append({
                    "handle": ch,
                    "source": "direct_input",
                    "status": st,
                    "items_scraped": len(msgs) if msgs else 0,
                    "transport": msgs[0].transport_used if msgs else "none",
                    "reason_skipped": err if st != "OK" else None
                })
                channel_reports.append(f"@{ch}: {st}" + (f" ({err})" if err else ""))

                if st == "OK" and msgs:
                    had_success = True
                    for pub_msg in msgs:
                        if yielded >= max_items:
                            break
                        yielded += 1
                        lead_id = make_telegram_lead_id(pub_msg.channel, pub_msg.message_id)

                        engagement_dict: dict[str, Any] = {}
                        if pub_msg.views is not None:
                            engagement_dict["views"] = pub_msg.views
                        if pub_msg.forwards is not None:
                            engagement_dict["forwards"] = pub_msg.forwards
                            engagement_dict["retweets"] = pub_msg.forwards
                        if pub_msg.reactions is not None:
                            engagement_dict["reactions"] = pub_msg.reactions
                            engagement_dict["likes"] = pub_msg.reactions

                        yield LeadRecord(
                            id=lead_id,
                            platform="telegram",
                            source_id=str(pub_msg.message_id),
                            source_url=pub_msg.post_url or f"https://t.me/{pub_msg.channel}/{pub_msg.message_id}",
                            name=pub_msg.channel_title or f"@{pub_msg.channel}",
                            username=pub_msg.channel,
                            headline=f"Telegram message in @{pub_msg.channel} #{pub_msg.message_id}",
                            title=f"Telegram update in @{pub_msg.channel}",
                            bio=f"Public Channel: @{pub_msg.channel}",
                            content=pub_msg.text or "[Attachment/Media Message]",
                            profile_url=f"https://t.me/{pub_msg.channel}",
                            engagement=engagement_dict,
                            lead_score=50,
                            intent="telegram message / community broadcast",
                            published_at=pub_msg.source_published_at,
                            collected_at=pub_msg.fetched_at,
                            updated_at=pub_msg.source_published_at or pub_msg.fetched_at,
                        )

            # Determine final status for DIRECT run
            if yielded == 0:
                if len(channels_to_scrape) == 1:
                    single_ch = channels_to_scrape[0]
                    self.last_scrape_status = self.channel_statuses.get(single_ch, "ACCESS_RESTRICTED")
                    if self.last_scrape_status == "ACCESS_RESTRICTED":
                        self.last_scrape_detail = "No public web preview exists for this handle."
                    elif self.last_scrape_status == "EMPTY":
                        self.last_scrape_detail = f"Public web preview for @{single_ch} contains no messages" + (f" matching '{search_param}'" if search_param else ".")
                    else:
                        self.last_scrape_detail = f"@{single_ch}: {self.last_scrape_status}"
                else:
                    self.last_scrape_status = "ACCESS_RESTRICTED"
                    self.last_scrape_detail = "; ".join(channel_reports)
            else:
                if len(channels_to_scrape) > 1 and not all(self.channel_statuses.get(c) == "OK" for c in channels_to_scrape):
                    self.last_scrape_status = "partial"
                    self.last_scrape_detail = "; ".join(channel_reports)
                else:
                    self.last_scrape_status = "OK"
                    self.last_scrape_detail = None
            return

        # -------------------------------------------------------------
        # Mode 2 & 3: GLOBAL and KEYWORD Discovery
        # -------------------------------------------------------------
        candidate_channels: list[tuple[str, str]] = []  # (handle, discovery_source)
        seen_candidates: set[str] = set()

        max_channels = getattr(settings, "telegram_max_channels_per_job", 5)
        max_msgs_per_ch = getattr(settings, "telegram_max_messages_per_channel", 20)
        job_id = filters.get("job_id", "default")

        # 2a: If GLOBAL mode, derive intent dynamically
        discovery_queries: list[tuple[str, str]] = []  # (query, source_type)
        if plan.mode == "GLOBAL":
            import sqlite3
            db_path = getattr(settings, "db_path", "data/leadsweep.db")
            conn = sqlite3.connect(db_path)
            try:
                # Order (C4 d): (1) ICP phrases, (2) Config topics, (3) Harvested/Registry handles
                icp_text = ""
                # Source (1a): Read tenant's li_profile
                if tenant_id:
                    from leadsweep.leadintel.profile import get_user_profile
                    prof = get_user_profile(conn, tenant_id)
                    if prof and prof.get("offer"):
                        roles = " ".join(prof.get("icp_roles", []))
                        domains = " ".join(prof.get("icp_domains", []))
                        icp_text = f"{prof.get('offer', '')} {roles} {domains}".strip()

                # Source (1b): Read agency ICP configuration from queries.toml if no user profile
                if not icp_text:
                    try:
                        import tomllib
                        queries_path = Path(getattr(settings, "queries_file", "config/queries.toml"))
                        if queries_path.exists():
                            with open(queries_path, "rb") as f:
                                toml_data = tomllib.load(f)
                            agency_cfg = toml_data.get("agency", {})
                            services = " ".join(agency_cfg.get("services", []))
                            clients = " ".join(agency_cfg.get("ideal_clients", []))
                            if services or clients:
                                icp_text = f"{agency_cfg.get('name', '')} {services} {clients}".strip()
                    except Exception as toml_err:
                        log.debug("Could not read queries.toml for agency ICP: %s", toml_err)

                # Derive 3-6 discovery phrases from ICP via LLM
                if icp_text:
                    icp_phrases = await derive_discovery_phrases_from_icp(icp_text, conn)
                    for phrase in icp_phrases:
                        discovery_queries.append((f"site:t.me/s {phrase}", f"icp_phrase:{phrase}"))

                # Source (2): Config topics (LEADSWEEP_TELEGRAM_GLOBAL_TOPICS) when no ICP or phrases found
                if not discovery_queries:
                    global_topics_cfg = getattr(settings, "telegram_global_topics", "") or os.getenv("LEADSWEEP_TELEGRAM_GLOBAL_TOPICS", "")
                    if global_topics_cfg:
                        topics = [t.strip() for t in global_topics_cfg.split(",") if t.strip()]
                        for top in topics[:4]:
                            discovery_queries.append((f"site:t.me/s {top}", f"config_topic:{top}"))

                # Source (3a): Harvest t.me handles from ALL tenant-scoped result rows (X posts included)
                if tenant_id:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT text FROM tweets 
                        WHERE (first_run_id IN (SELECT run_id FROM actor_runs WHERE user_email = ? OR user_id = ?))
                        LIMIT 100
                    """, (tenant_id, tenant_id))
                    harvested_rows = cur.fetchall()
                    for r in harvested_rows:
                        m_h = re.findall(r"(?:t\.me|telegram\.me)/(?:s/)?([a-zA-Z0-9_]{4,32})", r[0])
                        for h in m_h:
                            if h.lower() not in seen_candidates and h.lower() not in ("channel", "joinchat", "share", "addlist", "s", "contact"):
                                seen_candidates.add(h.lower())
                                candidate_channels.append((h, "harvested_from_x"))

                # Source (3b): User-configured channel registry from env/settings (default empty)
                configured_registry = getattr(settings, "telegram_channel_registry", "") or os.getenv("LEADSWEEP_TELEGRAM_CHANNEL_REGISTRY", "") or ""
                if configured_registry:
                    for reg_h in configured_registry.split(","):
                        reg_h = reg_h.strip().lstrip("@")
                        if reg_h and reg_h.lower() not in seen_candidates:
                            seen_candidates.add(reg_h.lower())
                            candidate_channels.append((reg_h, "configured_registry"))
            finally:
                conn.close()

            # (4) Honest NO_CANDIDATES if all sources are empty
            if not discovery_queries and not candidate_channels:
                self.last_scrape_status = "NO_CANDIDATES"
                self.last_scrape_detail = "No ICP profile found, LEADSWEEP_TELEGRAM_GLOBAL_TOPICS is empty, and no harvested tenant channels exist."
                log.info("Telegram GLOBAL discovery: %s", self.last_scrape_detail)
                return

        elif plan.mode == "KEYWORD":
            # Direct keyword discovery via dynamic search phrases
            kw = plan.keyword or ""
            discovery_queries = [
                (f"site:t.me/s {kw}", f"search_phrase:site:t.me/s {kw}"),
                (f"telegram {kw} channel", f"search_phrase:telegram {kw} channel"),
            ]

        # Execute bounded candidate discovery (max 2 relay calls)
        from leadsweep.services.telegram_public_scraper import _TRANSPORT_MGR
        relay_calls_made = 0
        import urllib.parse
        import httpx

        for dq, dq_source in discovery_queries:
            if len(candidate_channels) >= max_channels or relay_calls_made >= 2:
                break
            _TRANSPORT_MGR.record_relay_use(job_id=job_id, call_type="discovery")
            relay_calls_made += 1
            relay_ddg = f"https://r.jina.ai/https://html.duckduckgo.com/html/?q={urllib.parse.quote(dq)}"
            try:
                async with httpx.AsyncClient(timeout=12.0) as client:
                    resp = await client.get(relay_ddg)
                    if resp.status_code == 200 and resp.text:
                        found_handles = re.findall(r"(?:t\.me|telegram\.me)/(?:s/)?([a-zA-Z0-9_]{4,32})", resp.text)
                        for fh in found_handles:
                            if fh.lower() not in seen_candidates and fh.lower() not in ("channel", "joinchat", "share", "addlist", "s", "contact"):
                                seen_candidates.add(fh.lower())
                                candidate_channels.append((fh, dq_source))
                                if len(candidate_channels) >= max_channels:
                                    break
            except Exception as e:
                log.warning("Telegram discovery call failed for query '%s': %s", dq, e)

        log.info("Telegram candidate channels discovered (%d): %s", len(candidate_channels), candidate_channels)

        if not candidate_channels:
            self.last_scrape_status = "NO_CANDIDATES"
            self.last_scrape_detail = f"No public candidate channels found for query '{query}'."
            return

        # -------------------------------------------------------------
        # Scrape authentic messages from discovered candidate channels (B1 + B2)
        # -------------------------------------------------------------
        import math
        channel_reports = []
        self.candidate_reports = []
        channels_scraped_count = 0
        had_success = False

        max_channels = min(getattr(settings, "telegram_max_channels_per_job", 5), 5)
        max_msgs_per_ch = min(getattr(settings, "telegram_max_messages_per_channel", 20), 20)
        max_age_days = getattr(settings, "telegram_max_age_days", 30)

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        cutoff_dt = now_utc - datetime.timedelta(days=max_age_days) if max_age_days > 0 else None

        active_candidates = candidate_channels[:max_channels]
        num_candidates = len(active_candidates)
        # B2 Fair share quota per channel: round-robin / ceil(max_items / candidates)
        per_channel_quota = min(max_msgs_per_ch, max(1, math.ceil(max_items / num_candidates))) if num_candidates > 0 else max_msgs_per_ch

        def is_fresh(pub_msg: PublicTelegramMessage) -> bool:
            if cutoff_dt is None or not pub_msg.source_published_at:
                return True
            try:
                msg_dt = datetime.datetime.fromisoformat(pub_msg.source_published_at.replace("Z", "+00:00"))
                if msg_dt.tzinfo is None:
                    msg_dt = msg_dt.replace(tzinfo=datetime.timezone.utc)
                return msg_dt >= cutoff_dt
            except Exception:
                return True

        def parse_date(m: PublicTelegramMessage):
            if not m.source_published_at:
                return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
            try:
                d = datetime.datetime.fromisoformat(m.source_published_at.replace("Z", "+00:00"))
                return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
            except Exception:
                return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

        # C1, C2, D4, F1: Relevance gate (channel-level) & Collection-time Fair Share Quota
        rel_threshold = getattr(settings, "telegram_relevance_gate_threshold", 1)
        target_eval_phrase = plan.keyword or query or ""
        
        _STOPWORDS = {"a", "an", "the", "in", "on", "at", "for", "to", "of", "and", "or", "is", "are", "with", "by", "from"}
        raw_tokens = re.findall(r"[a-z0-9]+", (target_eval_phrase or "").lower())
        eval_tokens = {w for w in raw_tokens if len(w) >= 3 and w not in _STOPWORDS}
        non_latin_ratio_thresh = float(os.getenv("TG_CHANNEL_NON_LATIN_RATIO", os.getenv("LEADSWEEP_TG_NON_LATIN_RATIO", "0.30")))
        intent_lexicon_raw = (
            getattr(settings, "telegram_intent_lexicon", None)
            or os.getenv("TELEGRAM_INTENT_LEXICON")
            or os.getenv("LEADSWEEP_TELEGRAM_INTENT_LEXICON")
            or "hiring,hire,job,jobs,vacancy,career,recruit,developer,engineer,contractor,вакансия,вакансии,вакансія,вакансії,робота,найм,шукаю,ищу,требуется,потрібен,розробник,разработчик,招聘,直聘,招募,求职,雇佣,开发,工程师,架构师,程序员,وظائف,وظيفة,نوکریاں,نوکری,مطلوب,توظيف,فرصة عمل,مطور,ڈویلپر,مبرمج"
        )
        intent_lexicon_terms = [t.strip().lower() for t in intent_lexicon_raw.split(",") if t.strip()]

        def check_channel_relevance(
            channel_title: str,
            channel_desc: str,
            first_page_msgs: list[PublicTelegramMessage] | None = None,
        ) -> tuple[bool, int, str]:
            if not target_eval_phrase or not eval_tokens:
                return True, 1, "PASS (empty/generic query)"
            combined = f"{channel_title} {channel_desc}".strip()
            if not combined and not first_page_msgs:
                return True, 1, "PASS (no channel metadata)"

            # F1: Non-Latin channel header gate (Chinese, Urdu, Arabic, Russian/Ukrainian, etc.)
            letters = [c for c in combined if c.isalpha()]
            is_mostly_non_latin = False
            ratio = 0.0
            if letters:
                non_latin = [c for c in letters if not ('a' <= c <= 'z' or 'A' <= c <= 'Z')]
                ratio = len(non_latin) / len(letters)
                if ratio >= non_latin_ratio_thresh:
                    is_mostly_non_latin = True

            if is_mostly_non_latin:
                # Admit ONLY if at least one first-page message contains query token or intent lexicon term
                probe_msgs = (first_page_msgs or [])[:5]
                for m in probe_msgs:
                    txt = (getattr(m, "text", "") or "").lower()
                    if not txt:
                        continue
                    # (a) Check query / ICP tokens
                    for tok in eval_tokens:
                        if tok in txt:
                            return True, 1, f"PASS (non-Latin header ratio {ratio:.2f}; probe matched query token '{tok}')"
                    # (b) Check multilingual intent lexicon
                    for term in intent_lexicon_terms:
                        if term in txt:
                            return True, 1, f"PASS (non-Latin header ratio {ratio:.2f}; probe matched intent lexicon '{term}')"

                return False, 0, f"FAIL (non-Latin header ratio {ratio:.2f} >= {non_latin_ratio_thresh}: 0 query/intent match in {len(probe_msgs)} probe messages)"

            # Latin header: standard token overlap
            h_tokens = set(re.findall(r"[a-z0-9]+", combined.lower()))
            h_match = eval_tokens & h_tokens
            overlap = len(h_match)
            if overlap >= rel_threshold:
                return True, overlap, f"PASS (matched: {list(h_match)[:3]})"

            # G4: If 0 header overlap on Latin channel, probe up to 5 messages if enabled
            if getattr(settings, "telegram_probe_zero_overlap", True):
                probe_msgs = (first_page_msgs or [])[:5]
                for m in probe_msgs:
                    txt = (getattr(m, "text", "") or "").lower()
                    if not txt:
                        continue
                    for tok in eval_tokens:
                        if tok in txt:
                            return True, 1, f"PASS (Latin header 0 overlap; probe matched query token '{tok}')"
                    for term in intent_lexicon_terms:
                        if term in txt:
                            return True, 1, f"PASS (Latin header 0 overlap; probe matched intent lexicon '{term}')"
                return False, 0, f"FAIL (Latin header 0 overlap with '{target_eval_phrase}': 0 query/intent match in {len(probe_msgs)} probe messages)"

            return False, overlap, f"FAIL (0 overlap with '{target_eval_phrase}')"

        all_collected_msgs: list[tuple[PublicTelegramMessage, str]] = []
        per_channel_counts: dict[str, int] = {}
        seen_msg_texts: set[str] = set()
        total_skipped_age = 0
        total_skipped_channel_relevance = 0
        total_skipped_empty = 0
        total_skipped_duplicate = 0
        remaining_needed = max_items
        candidates_remaining = len(active_candidates)

        for cand_handle, source in active_candidates:
            if remaining_needed <= 0:
                self.candidate_reports.append({
                    "channel": cand_handle,
                    "handle": cand_handle,
                    "title": f"@{cand_handle}",
                    "description": "",
                    "gate_decision": "SKIPPED (quota reached)",
                    "discovered_via": source,
                    "source": source,
                    "status": "SKIPPED",
                    "items_scraped": 0,
                    "transport": "none",
                    "reason_skipped": "target items quota reached",
                    "skipped_reason": "target items quota reached",
                })
                continue

            # C1: Enforce per-channel quota at COLLECTION time (ceil of remaining / remaining candidates)
            channel_quota = min(max_msgs_per_ch, max(1, math.ceil(remaining_needed / candidates_remaining)))
            candidates_remaining -= 1

            channels_scraped_count += 1
            candidate_fresh_msgs: list[PublicTelegramMessage] = []
            skipped_age_channel = 0
            st = "OK"
            err = None
            transport_used = "none"
            ch_title = ""
            ch_desc = ""

            # Freshness & Fallback strategy (B1 + C2 + D4 + F1):
            # F1 rule: Until admitted, fetch no more than 5 messages from that channel (bounds relay/LLM cost)
            probe_limit = min(5, channel_quota)
            raw_fetched_msgs: list[PublicTelegramMessage] = []
            if plan.mode == "KEYWORD" and plan.keyword:
                msgs_kw, st_kw, err_kw = await pub_scraper.scrape_channel_with_status(
                    channel=cand_handle,
                    limit=probe_limit,
                    search_q=plan.keyword,
                    job_id=job_id,
                )
                raw_fetched_msgs = msgs_kw
                st = st_kw
                err = err_kw

                # C2 Rule: Fall back to latest page ONLY if ?q= returned only posts older than age window,
                # NOT when it returned no match. If no match, skip with status EMPTY and 0 items.
                if len(msgs_kw) > 0 and st != "ACCESS_RESTRICTED":
                    fresh_kw_count = sum(1 for m in msgs_kw if is_fresh(m))
                    if fresh_kw_count == 0:
                        msgs_latest, st_latest, err_latest = await pub_scraper.scrape_channel_with_status(
                            channel=cand_handle,
                            limit=probe_limit,
                            search_q=None,
                            job_id=job_id,
                        )
                        if msgs_latest:
                            raw_fetched_msgs = msgs_latest
                            st = st_latest
                            err = err_latest
            else:
                # GLOBAL mode or empty query
                msgs_latest, st_latest, err_latest = await pub_scraper.scrape_channel_with_status(
                    channel=cand_handle,
                    limit=probe_limit,
                    search_q=None,
                    job_id=job_id,
                )
                raw_fetched_msgs = msgs_latest
                st = st_latest
                err = err_latest

            # D4 & F1: Apply channel-level relevance gate with first-page probe messages
            is_ch_rel = True
            ch_gate = "PASS"
            if raw_fetched_msgs:
                transport_used = raw_fetched_msgs[0].transport_used
                ch_title = raw_fetched_msgs[0].channel_title
                ch_desc = getattr(raw_fetched_msgs[0], "channel_description", "")
                is_ch_rel, _, ch_gate = check_channel_relevance(ch_title, ch_desc, raw_fetched_msgs[:5])

            if not is_ch_rel:
                total_skipped_channel_relevance += 1
                cand_status = "RELEVANCE_FILTERED"
            else:
                # Channel admitted! If full quota > probe_limit, fetch remainder
                if channel_quota > len(raw_fetched_msgs) and st == "OK" and len(raw_fetched_msgs) == probe_limit:
                    try:
                        more_msgs, _, _ = await pub_scraper.scrape_channel_with_status(
                            channel=cand_handle,
                            limit=channel_quota,
                            search_q=plan.keyword if plan.mode == "KEYWORD" else None,
                            job_id=job_id,
                        )
                        if len(more_msgs) > len(raw_fetched_msgs):
                            raw_fetched_msgs = more_msgs
                    except Exception:
                        pass

                for m in raw_fetched_msgs:
                    if not is_fresh(m):
                        skipped_age_channel += 1
                        continue
                    txt = (m.text or "").strip()
                    if not txt:
                        total_skipped_empty += 1
                        continue
                    if txt in seen_msg_texts:
                        total_skipped_duplicate += 1
                        continue
                    seen_msg_texts.add(txt)
                    candidate_fresh_msgs.append(m)

            total_skipped_age += skipped_age_channel
            self.channel_statuses[cand_handle] = st

            # Sort candidate's fresh messages newest first
            candidate_fresh_msgs.sort(key=parse_date, reverse=True)

            # C1: Strictly cap at channel_quota and remaining_needed (never over-fetch)
            take_count = min(channel_quota, remaining_needed, len(candidate_fresh_msgs))
            taken = candidate_fresh_msgs[:take_count]
            remaining_needed -= len(taken)

            per_channel_counts[cand_handle] = len(taken)
            if taken:
                had_success = True

            cand_status = st
            if not is_ch_rel:
                cand_status = "RELEVANCE_FILTERED"
            elif st == "OK" and len(taken) == 0:
                if skipped_age_channel > 0:
                    cand_status = "STALE"
                else:
                    cand_status = "EMPTY"

            skipped_reason = err if st != "OK" else (
                f"{skipped_age_channel} post(s) older than {max_age_days}d skipped" if skipped_age_channel > 0 and len(taken) == 0
                else ("Channel filtered by relevance gate (0 overlap)" if not is_ch_rel else None)
            )

            self.candidate_reports.append({
                "channel": cand_handle,
                "handle": cand_handle,
                "title": ch_title or f"@{cand_handle}",
                "description": ch_desc,
                "gate_decision": ch_gate,
                "discovered_via": source,
                "source": source,
                "status": cand_status,
                "items_scraped": len(taken),
                "transport": transport_used,
                "reason_skipped": skipped_reason,
                "skipped_reason": skipped_reason,
            })
            channel_reports.append(f"@{cand_handle} ({source}): {cand_status} ({len(taken)} items)")
            for m in taken:
                all_collected_msgs.append((m, source))

        # Print per-channel counts (C1 requirement: matches stored rows exactly)
        log.info("Telegram Fair Share per-channel counts: %s", per_channel_counts)
        print(f"[Telegram Fair Share] Per-channel counts: {per_channel_counts}")

        # Sort all collected messages newest first inside the already-fair set (C1 requirement)
        all_collected_msgs.sort(key=lambda item: parse_date(item[0]), reverse=True)

        # Yield LeadRecords with clean content (B4 hygiene)
        for pub_msg, source in all_collected_msgs:
            yielded += 1
            lead_id = make_telegram_lead_id(pub_msg.channel, pub_msg.message_id)

            engagement_dict: dict[str, Any] = {}
            if pub_msg.views is not None:
                engagement_dict["views"] = pub_msg.views
            if pub_msg.forwards is not None:
                engagement_dict["forwards"] = pub_msg.forwards
                engagement_dict["retweets"] = pub_msg.forwards
            if pub_msg.reactions is not None:
                engagement_dict["reactions"] = pub_msg.reactions
                engagement_dict["likes"] = pub_msg.reactions

            yield LeadRecord(
                id=lead_id,
                platform="telegram",
                source_id=str(pub_msg.message_id),
                source_url=pub_msg.post_url or f"https://t.me/{pub_msg.channel}/{pub_msg.message_id}",
                name=pub_msg.channel_title or f"@{pub_msg.channel}",
                username=pub_msg.channel,
                headline=f"Telegram message in @{pub_msg.channel} #{pub_msg.message_id} (via {source})",
                title=f"Telegram update in @{pub_msg.channel}",
                bio=f"Public Channel: @{pub_msg.channel} (Discovered via {source})",
                content=pub_msg.text or "[Attachment/Media Message]",
                profile_url=f"https://t.me/{pub_msg.channel}",
                engagement=engagement_dict,
                lead_score=50,
                intent="telegram message / community broadcast",
                published_at=pub_msg.source_published_at,
                collected_at=pub_msg.fetched_at,
                updated_at=pub_msg.source_published_at or pub_msg.fetched_at,
            )

        skip_parts = []
        if total_skipped_age > 0:
            skip_parts.append(f"{total_skipped_age} stale")
        if total_skipped_channel_relevance > 0:
            skip_parts.append(f"{total_skipped_channel_relevance} irrelevant channel(s)")
        if total_skipped_duplicate > 0:
            skip_parts.append(f"{total_skipped_duplicate} duplicate(s)")
        if total_skipped_empty > 0:
            skip_parts.append(f"{total_skipped_empty} empty")
        skip_summary = f" (skipped: {', '.join(skip_parts)})" if skip_parts else ""

        if yielded == 0:
            self.last_scrape_status = "EMPTY" if had_success else "NO_CANDIDATES"
            self.last_scrape_detail = ("; ".join(channel_reports[:3]) or f"No public candidate channels found for query '{query}'.") + skip_summary
        else:
            shortfall_prefix = f"Shortfall: returned {yielded}/{max_items} rows{skip_summary}. " if yielded < max_items else ""
            active_scrapes = [c for c in self.candidate_reports if c["status"] != "SKIPPED"]
            any_failed = any(c["status"] not in ("OK", "STALE", "EMPTY", "RELEVANCE_FILTERED") for c in active_scrapes)
            if any_failed:
                self.last_scrape_status = "partial"
                self.last_scrape_detail = f"{shortfall_prefix}Scraped {yielded} items from {channels_scraped_count} channel(s) ({len(candidate_channels)} candidates discovered: {'; '.join(channel_reports[:2])})"
            else:
                self.last_scrape_status = "OK"
                self.last_scrape_detail = f"{shortfall_prefix}Scraped {yielded} items from {channels_scraped_count} channel(s) ({len(candidate_channels)} candidates discovered)"


# NEW FEATURE: Register TelegramAdapter into registry once module is imported
try:
    from leadsweep.adapters import PlatformAdapterRegistry
    PlatformAdapterRegistry.register("telegram", TelegramAdapter())
except Exception as e:
    log.warning("Could not automatically register TelegramAdapter in registry: %s", e)


