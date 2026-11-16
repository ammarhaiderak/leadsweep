"""Per-session browser identity + human-like pacing.

Design rule: randomise what a real user population varies (viewport, scale, theme),
keep CONSISTENT what must match reality (UA vs real Chromium version/OS, locale/timezone vs IP).
"""
from __future__ import annotations

import asyncio
import random
import sys
from dataclasses import dataclass

from playwright.async_api import Page

VIEWPORTS = [(1366, 768), (1440, 900), (1536, 864), (1920, 1080), (1280, 800), (1600, 900)]

INIT_SCRIPT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


@dataclass(frozen=True)
class Fingerprint:
    width: int
    height: int
    device_scale_factor: float
    color_scheme: str


def random_fingerprint(rng: random.Random | None = None) -> Fingerprint:
    r = rng or random
    w, h = r.choice(VIEWPORTS)
    return Fingerprint(
        width=w + r.randint(-24, 24),
        height=h + r.randint(-16, 16),
        device_scale_factor=r.choice([1.0, 1.0, 1.25, 1.5]),
        color_scheme=r.choice(["light", "light", "dark"]),
    )


def build_user_agent(browser_version: str) -> str:
    """UA built from the REAL browser version so headless doesn't leak 'HeadlessChrome'."""
    major = browser_version.split(".")[0]
    if sys.platform == "win32":
        plat = "Windows NT 10.0; Win64; x64"
    elif sys.platform == "darwin":
        plat = "Macintosh; Intel Mac OS X 10_15_7"
    else:
        plat = "X11; Linux x86_64"
    return f"Mozilla/5.0 ({plat}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"


async def jitter(min_s: float, max_s: float) -> None:
    """Skewed-short delay (triangular) — humans mostly pause briefly, occasionally long."""
    await asyncio.sleep(random.triangular(min_s, max_s, min_s + (max_s - min_s) * 0.35))


async def human_scroll(page: Page) -> None:
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    except Exception:
        pass
    vp = page.viewport_size or {"width": 1366, "height": 768}
    try:
        await page.mouse.move(
            random.randint(int(vp["width"] * 0.3), int(vp["width"] * 0.7)),
            random.randint(int(vp["height"] * 0.3), int(vp["height"] * 0.7)),
            steps=random.randint(5, 12),
        )
    except Exception:
        pass

