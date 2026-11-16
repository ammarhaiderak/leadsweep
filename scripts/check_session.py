"""Task 1.1 — verify cookies WITHOUT scraping.  Run: python -m scripts.check_session [--headed]"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re

from leadsweep.config import get_settings
from leadsweep.scraper import _LOGIN_MARKERS, XScraper
from leadsweep.session_pool import SessionCreds, SessionPool


def format_warnings(c: SessionCreds) -> list[str]:
    w: list[str] = []
    if "PASTE" in c.auth_token or "PASTE" in c.ct0:
        w.append("placeholder text still in sessions.json")
    if c.auth_token != c.auth_token.strip() or any(q in c.auth_token + c.ct0 for q in "\"'"):
        w.append("cookie value has spaces or quotes")
    if not re.fullmatch(r"[0-9a-f]{40}", c.auth_token.strip().strip("\"'")):
        w.append(f"auth_token looks unusual (len={len(c.auth_token)}, expected 40 hex chars)")
    if len(c.ct0) < 100:
        w.append(f"ct0 is short (len={len(c.ct0)}); a logged-in ct0 is usually ~160 chars")
    return w


async def probe(sc: XScraper, session: SessionCreds) -> str:
    ctx, page, _ = await sc._open(session)
    try:
        await page.goto("https://x.com/home", wait_until="domcontentloaded")
        for _ in range(20):
            if any(m in page.url for m in _LOGIN_MARKERS):
                return f"REJECTED (redirected to login: {page.url[:70]})"
            if await page.locator('[data-testid="SideNav_AccountSwitcher_Button"]').count():
                return "LOGGED IN"
            await asyncio.sleep(1)
        return "UNKNOWN (no redirect, no account menu) - rerun with --headed and look at the window"
    finally:
        await ctx.close()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    s = get_settings()
    if args.headed:
        s.headless = False
    logging.basicConfig(level="WARNING")
    pool = SessionPool(s.sessions_file, s.state_file)
    ok = True
    async with XScraper(s, pool) as sc:
        for sess in pool.sessions:
            for w in format_warnings(sess):
                print(f"[{sess.id}] WARN  {w}")
            result = await probe(sc, sess)
            print(f"[{sess.id}] {result}")
            ok &= result == "LOGGED IN"
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
