# NEW FEATURE: Telegram Live Diagnostics & Probe Tool
"""
Telegram Public Scraper Probe Tool for LeadSweep.

Runs the real Telegram code path and prints per HTTP attempt:
URL, transport (direct/relay), status code, final URL, bytes, page <title>,
whether .tgme_widget_message elements exist, parsed message count, elapsed ms,
and circuit-breaker / relay-budget / cache state.
"""
from __future__ import annotations

import asyncio
import datetime
import re
import sys
import time
import urllib.parse
from typing import Any

import httpx
from selectolax.lexbor import LexborHTMLParser

from leadsweep.config import get_settings
from leadsweep.services.telegram_public_scraper import (
    TelegramPublicScraper,
    _PAGE_CACHE,
    _TRANSPORT_MGR,
    normalize_channel_handle,
)


async def probe_telegram_target(target: str, job_id: str = "probe_live") -> dict[str, Any]:
    """Execute live probe on a given Telegram target (channel or query)."""
    settings = get_settings()
    relay_budget = getattr(settings, "telegram_relay_max_requests", 15)
    start_time = time.time()

    clean_target = target.strip()
    is_empty = not clean_target
    is_direct = bool(clean_target.startswith("@") or "t.me/" in clean_target or (clean_target and len(clean_target.split()) == 1))

    print(f"\n{'='*70}")
    print(f"PROBING TELEGRAM TARGET: '{target}'")
    print(f"Mode: {'EMPTY (GLOBAL)' if is_empty else 'DIRECT' if is_direct else 'KEYWORD'}")
    print(f"Initial State -> Direct Circuit Open: {_TRANSPORT_MGR.is_direct_circuit_open()}, "
          f"Direct Failures: {_TRANSPORT_MGR.direct_failures}, "
          f"Relay Used ({job_id}): {_TRANSPORT_MGR.job_relay_counts[job_id]}/{relay_budget}, "
          f"Page Cache Entries: {len(_PAGE_CACHE)}")
    print(f"{'='*70}")

    results: dict[str, Any] = {
        "target": target,
        "is_empty": is_empty,
        "is_direct": is_direct,
        "attempts": [],
    }

    scraper = TelegramPublicScraper(connect_timeout=5.0, read_timeout=10.0)

    if is_direct:
        try:
            handle = normalize_channel_handle(clean_target)
        except Exception as ve:
            print(f"[ERROR] Normalization/Validation Failed: {ve}")
            results["validation_error"] = str(ve)
            return results

        direct_url = f"https://t.me/s/{handle}"
        relay_url = f"https://r.jina.ai/{direct_url}"

        # Attempt 1: Direct
        print(f"\n--- Attempt 1: Direct Fetch ({direct_url}) ---")
        t0 = time.time()
        attempt_direct = {"transport": "direct", "url": direct_url}
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                resp = await client.get(direct_url)
                elapsed_ms = int((time.time() - t0) * 1000)
                html = resp.text
                tree = LexborHTMLParser(html)
                title_tag = tree.css_first("title")
                title_text = title_tag.text(strip=True) if title_tag else "NO_TITLE"
                msg_elements = tree.css(".tgme_widget_message")
                msgs, _, _ = scraper.parse_page_html(html, handle)

                attempt_direct.update({
                    "status_code": resp.status_code,
                    "final_url": str(resp.url),
                    "bytes": len(html),
                    "title": title_text,
                    "has_widget_messages": len(msg_elements) > 0,
                    "parsed_messages_count": len(msgs),
                    "elapsed_ms": elapsed_ms,
                })
                print(f"Status: {resp.status_code} | Bytes: {len(html)} | Elapsed: {elapsed_ms}ms")
                print(f"Title: {title_text}")
                print(f"Has .tgme_widget_message: {len(msg_elements) > 0} (Parsed: {len(msgs)})")
        except Exception as e:
            elapsed_ms = int((time.time() - t0) * 1000)
            attempt_direct.update({
                "status_code": "EXCEPTION",
                "error": str(e),
                "elapsed_ms": elapsed_ms,
            })
            print(f"Direct connection failed: {type(e).__name__}: {e} (Elapsed: {elapsed_ms}ms)")
        results["attempts"].append(attempt_direct)

        # Attempt 2: Relay
        print(f"\n--- Attempt 2: Public Relay Fetch ({relay_url}) ---")
        t0 = time.time()
        attempt_relay = {"transport": "relay", "url": relay_url}
        try:
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                headers = {"X-Return-Format": "html", "X-No-Cache": "true"}
                resp = await client.get(relay_url, headers=headers)
                elapsed_ms = int((time.time() - t0) * 1000)
                html = resp.text
                tree = LexborHTMLParser(html)
                title_tag = tree.css_first("title")
                title_text = title_tag.text(strip=True) if title_tag else "NO_TITLE"
                msg_elements = tree.css(".tgme_widget_message")
                msgs, _, _ = scraper.parse_page_html(html, handle)

                attempt_relay.update({
                    "status_code": resp.status_code,
                    "final_url": str(resp.url),
                    "bytes": len(html),
                    "title": title_text,
                    "has_widget_messages": len(msg_elements) > 0,
                    "parsed_messages_count": len(msgs),
                    "elapsed_ms": elapsed_ms,
                })
                print(f"Status: {resp.status_code} | Bytes: {len(html)} | Elapsed: {elapsed_ms}ms")
                print(f"Title: {title_text}")
                print(f"Has .tgme_widget_message: {len(msg_elements) > 0} (Parsed: {len(msgs)})")
        except Exception as e:
            elapsed_ms = int((time.time() - t0) * 1000)
            attempt_relay.update({
                "status_code": "EXCEPTION",
                "error": str(e),
                "elapsed_ms": elapsed_ms,
            })
            print(f"Relay connection failed: {type(e).__name__}: {e} (Elapsed: {elapsed_ms}ms)")
        results["attempts"].append(attempt_relay)

        # Attempt 3: Scraper public service full execution
        print(f"\n--- High-Level Service Execution: scraper.fetch_channel_page ---")
        async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True) as client:
            status, html, err, transport_used = await scraper.fetch_channel_page(client, handle, job_id=job_id)
            tree = LexborHTMLParser(html) if html else None
            msg_count = len(tree.css(".tgme_widget_message")) if tree else 0
            print(f"Result Status: {status} | Error: {err} | Transport Used: {transport_used} | Messages: {msg_count}")
            results["service_status"] = status
            results["service_error"] = err
            results["transport_used"] = transport_used

    elif is_empty:
        print("\n--- Empty Query Behavior Diagnosis ---")
        print("Frontend/API Behavior: An empty string query submitted to the system.")
        print("TelegramAdapter currently checks:")
        print("  is_direct_handle = clean_q.startswith('@') or 't.me/' in clean_q or (len(clean_q.split()) == 1 ...)")
        print("  When clean_q is empty: clean_q.split() is [] -> len is 0 -> is_direct_handle is False.")
        print("  It falls into Mode B: clean_handle = '', phrase = ''")
        print("  search_variations: ['site:t.me freelance', 'site:t.me/s jobs', ...]")
        print("  However, DDG Lite returns 0 results or captchas, and no channel messages are scraped.")

    else:
        # Keyword discovery
        print(f"\n--- Keyword Discovery Mode ({clean_target}) ---")
        t0 = time.time()
        ddg_q = f"site:t.me/s {clean_target}"
        relay_ddg = f"https://r.jina.ai/https://html.duckduckgo.com/html/?q={urllib.parse.quote(ddg_q)}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(relay_ddg)
                elapsed_ms = int((time.time() - t0) * 1000)
                extracted_handles = list(set(re.findall(r"t(?:elegram)?\.me/s/([a-zA-Z0-9_]{4,32})", r.text)))
                print(f"DDG Relay Status: {r.status_code} | Bytes: {len(r.text)} | Elapsed: {elapsed_ms}ms")
                print(f"Discovered candidate channel handles ({len(extracted_handles)}): {extracted_handles[:10]}")
                results["discovered_candidates"] = extracted_handles
        except Exception as e:
            print(f"Keyword discovery failed: {e}")

    total_elapsed = int((time.time() - start_time) * 1000)
    print(f"\nTotal Probe Duration: {total_elapsed}ms")
    print(f"Final State -> Direct Circuit Open: {_TRANSPORT_MGR.is_direct_circuit_open()}, "
          f"Direct Failures: {_TRANSPORT_MGR.direct_failures}, "
          f"Relay Used ({job_id}): {_TRANSPORT_MGR.job_relay_counts[job_id]}/{relay_budget}")
    print(f"{'='*70}\n")
    return results


async def main():
    targets = [
        "@freelance_jobs_gigs",
        "@web3hiring",
        "blockchain hiring",
        "",
    ]
    for t in targets:
        await probe_telegram_target(t)


if __name__ == "__main__":
    asyncio.run(main())
