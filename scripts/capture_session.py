"""Task 1.0 — log in ONCE in a real browser window; cookies are saved to sessions.json.
Run: python -m scripts.capture_session --id acct-1
Do NOT click 'Log out' afterwards (that invalidates auth_token)."""
from __future__ import annotations

import argparse
import asyncio
import json
import time

from playwright.async_api import async_playwright

from leadsweep.config import get_settings


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="acct-1")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()
    s = get_settings()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False, channel=s.browser_channel, args=["--disable-blink-features=AutomationControlled"]
        )
        ctx = await browser.new_context(locale=s.locale, timezone_id=s.timezone_id, no_viewport=True)
        page = await ctx.new_page()
        await page.goto("https://x.com/i/flow/login")
        print(f"Log in inside the opened window (email/username + password, 2FA if asked). Waiting up to {args.timeout}s...")

        cookies: dict[str, str] = {}
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            cookies = {c["name"]: c["value"] for c in await ctx.cookies("https://x.com")}
            if "auth_token" in cookies and "ct0" in cookies and "/home" in page.url:
                break
            await asyncio.sleep(1.5)
        else:
            print("TIMEOUT: login not completed.")
            await browser.close()
            return 1

        entry = {"id": args.id, "auth_token": cookies["auth_token"], "ct0": cookies["ct0"]}
        try:
            data = json.loads(s.sessions_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {"sessions": []}
        data["sessions"] = [x for x in data["sessions"] if x.get("id") != args.id] + [entry]
        s.sessions_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"Saved session '{args.id}' to {s.sessions_file}. Close the window WITHOUT logging out.")
        await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
