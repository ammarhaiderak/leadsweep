"""Enrichment Worker ($0 Cost OSINT Contact & Profile Discovery).
Uses httpx + selectolax for rapid static website & contact page extraction,
with Playwright as a controlled fallback only for JavaScript-heavy/dynamic sites.
"""
from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from typing import Any

import httpx
from selectolax.parser import HTMLParser

log = logging.getLogger("leadsweep.services.enrichment")

# Robust email regex
EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    re.IGNORECASE,
)

# Strict false positive blacklist for emails
EXCLUDED_EMAIL_DOMAINS = {
    "duckduckgo.com",
    "sentry.io",
    "wixpress.com",
    "github.com",
    "example.com",
    "test.com",
    "domain.com",
    "yourcompany.com",
    "email.com",
    "schema.org",
    "google.com",
    "bing.com",
    "microsoft.com",
    "apple.com",
    "twitter.com",
    "x.com",
}

EXCLUDED_EMAIL_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".js",
    ".css",
    ".woff",
    ".woff2",
    ".ttf",
)

LINKEDIN_URL_REGEX = re.compile(
    r"https?:\/\/(?:[a-z]{2,3}\.)?linkedin\.com\/(?:in|company)\/[a-zA-Z0-9%_-]+",
    re.IGNORECASE,
)

WEBSITE_URL_REGEX = re.compile(
    r"https?:\/\/(?!t\.co)(?!twitter\.com)(?!x\.com)[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:\/[^\s\"'<>]*)?",
    re.IGNORECASE,
)


def extract_emails_from_text(text: str) -> list[str]:
    """Extract and sanitize verified business emails from HTML or text."""
    if not text:
        return []
    raw_matches = EMAIL_REGEX.findall(text)
    clean_emails = []
    seen = set()

    for em in raw_matches:
        em_clean = em.strip().lower().rstrip(".,;:)'\"")
        if em_clean in seen:
            continue
        if any(bad in em_clean for bad in ("error", "noreply", "mailto:", "example")):
            continue
        if any(em_clean.endswith(ext) for ext in EXCLUDED_EMAIL_EXTENSIONS):
            continue
        parts = em_clean.split("@")
        if len(parts) != 2:
            continue
        local, domain = parts
        domain_parts = domain.split(".")
        if len(domain_parts) < 2:
            continue
        tld = domain_parts[-1]
        if not tld.isalpha() or len(tld) < 2 or len(tld) > 10:
            continue
        if any(char.isdigit() for char in domain_parts[-1]):
            continue
        if domain in EXCLUDED_EMAIL_DOMAINS:
            continue
        seen.add(em_clean)
        clean_emails.append(em_clean)

    return clean_emails


def extract_linkedin_urls_from_text(text: str) -> list[str]:
    """Extract LinkedIn profile or company page links."""
    if not text:
        return []
    matches = LINKEDIN_URL_REGEX.findall(text)
    seen = set()
    cleaned = []
    for link in matches:
        clean_link = link.split("?")[0].rstrip("/")
        if clean_link not in seen and not clean_link.endswith(("/in", "/company")):
            seen.add(clean_link)
            cleaned.append(clean_link)
    return cleaned


def extract_websites_from_text(text: str) -> list[str]:
    """Extract genuine external websites."""
    if not text:
        return []
    cleaned = []
    excluded = ("linkedin.com", "instagram.com", "facebook.com", "tiktok.com", "youtube.com", "t.me", "telegram.org", "t.co", "x.com", "twitter.com")

    matches = WEBSITE_URL_REGEX.findall(text)
    for site in matches:
        site_clean = site.split("?")[0].rstrip(".,;:/")
        if not any(ex in site_clean for ex in excluded):
            cleaned.append(site_clean)
    return cleaned


class EnrichmentWorker:
    """Fast OSINT enrichment worker using httpx + selectolax, with Playwright fallback."""

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless

    async def enrich_lead(
        self,
        name: str = "",
        handle: str = "",
        bio: str = "",
        website_url: str = "",
    ) -> dict[str, Any]:
        """Discover verified email, website, and LinkedIn URL for prospect."""
        discovered: dict[str, Any] = {
            "email": None,
            "linkedin_url": None,
            "company_website": website_url.strip() if website_url else None,
            "is_enriched": 1,
        }

        # Step 0: Check if email, LinkedIn, or external website is already present in tweet text / bio
        bio_emails = extract_emails_from_text(bio)
        if bio_emails:
            discovered["email"] = bio_emails[0]

        bio_linkedins = extract_linkedin_urls_from_text(bio)
        if bio_linkedins:
            discovered["linkedin_url"] = bio_linkedins[0]

        if not discovered["company_website"]:
            bio_sites = extract_websites_from_text(bio)
            if bio_sites:
                discovered["company_website"] = bio_sites[0]

        # Step 1: Perform public OSINT web searches using lite DuckDuckGo
        search_terms = []
        if handle:
            search_terms.append(f"{handle} linkedin")
            search_terms.append(f"{handle} email contact")
        if name and name.strip() and name.strip().lower() != handle.lower():
            search_terms.append(f'"{name.strip()}" linkedin')

        for term in search_terms:
            if discovered["linkedin_url"] and discovered["email"]:
                break
            await self._search_lite_osint(term, discovered)

        # Step 2: Website enrichment via httpx + selectolax (with Playwright fallback)
        target_site = discovered["company_website"]
        if target_site:
            if not target_site.startswith(("http://", "https://")):
                target_site = f"https://{target_site}"
                discovered["company_website"] = target_site

            await self._scrape_website_httpx_selectolax(target_site, discovered)

        return discovered

    async def _search_lite_osint(self, query: str, discovered: dict[str, Any]) -> None:
        """Search public web via fast HTTP request without triggering captchas."""
        try:
            url = f"https://lite.duckduckgo.com/lite/?q={urllib.parse.quote(query)}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    html = resp.text
                    # Extract redirected links
                    uddg_links = []
                    for m in re.finditer(r'uddg=([^&"\']+)', html):
                        uddg_links.append(urllib.parse.unquote(m.group(1)))

                    # Check for LinkedIn profile or company
                    if not discovered["linkedin_url"]:
                        for link in uddg_links:
                            if "linkedin.com/in/" in link or "linkedin.com/company/" in link:
                                clean = link.split("?")[0].rstrip("/")
                                discovered["linkedin_url"] = clean
                                break

                    # Check for external company website
                    if not discovered["company_website"]:
                        for link in uddg_links:
                            if not any(ex in link for ex in ("duckduckgo", "twitter.com", "x.com", "linkedin.com", "instagram.com", "facebook.com", "youtube.com")):
                                parsed = urllib.parse.urlparse(link)
                                if parsed.netloc:
                                    discovered["company_website"] = f"{parsed.scheme}://{parsed.netloc}"
                                    break

                    # Check for email in snippets
                    if not discovered["email"]:
                        found_emails = extract_emails_from_text(html)
                        if found_emails:
                            discovered["email"] = found_emails[0]
        except Exception as e:
            log.debug("Lite search for query '%s' skipped: %s", query, e)

    async def _scrape_website_httpx_selectolax(self, url: str, discovered: dict[str, Any]) -> None:
        """Inspect domain + contact/about pages using httpx + selectolax (with Playwright fallback)."""
        base_parsed = urllib.parse.urlparse(url)
        base_domain = f"{base_parsed.scheme}://{base_parsed.netloc}"
        routes_to_check = [url, f"{base_domain}/contact", f"{base_domain}/about"]

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        needs_playwright = False
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, verify=False) as client:
            for route in routes_to_check:
                if discovered["email"] and discovered["linkedin_url"]:
                    break
                try:
                    resp = await client.get(route, headers=headers)
                    if resp.status_code == 200 and resp.text:
                        tree = HTMLParser(resp.text)
                        text_content = tree.text() or ""
                        
                        # Extract mailto links directly from DOM
                        for a in tree.css("a[href^='mailto:']"):
                            href = a.attributes.get("href", "")
                            mail = href.replace("mailto:", "").split("?")[0]
                            clean_mail = extract_emails_from_text(mail)
                            if clean_mail and not discovered["email"]:
                                discovered["email"] = clean_mail[0]
                                break

                        if not discovered["email"]:
                            found_emails = extract_emails_from_text(text_content)
                            if found_emails:
                                discovered["email"] = found_emails[0]

                        # Extract LinkedIn links directly from hrefs
                        if not discovered["linkedin_url"]:
                            for a in tree.css("a[href*='linkedin.com']"):
                                href = a.attributes.get("href", "")
                                clean_li = extract_linkedin_urls_from_text(href)
                                if clean_li:
                                    discovered["linkedin_url"] = clean_li[0]
                                    break

                        # Check if site appears to be a blank JS SPA shell needing dynamic render
                        if len(text_content.strip()) < 100:
                            needs_playwright = True
                except Exception as ex:
                    log.debug("httpx fetch failed for %s: %s", route, ex)
                    needs_playwright = True

        # Controlled Fallback: Only call Playwright if static HTML was empty or incomplete
        if needs_playwright and (not discovered["email"] or not discovered["linkedin_url"]):
            log.info("Invoking Playwright fallback for dynamic website %s", url)
            await self._playwright_fallback(url, discovered)

    async def _playwright_fallback(self, url: str, discovered: dict[str, Any]) -> None:
        """Controlled fallback using Playwright only when JavaScript rendering is required."""
        from playwright.async_api import async_playwright
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=self.headless,
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                page.set_default_timeout(12000)
                await page.goto(url, wait_until="domcontentloaded", timeout=12000)
                content = await page.content()
                
                tree = HTMLParser(content)
                text_content = tree.text() or ""
                if not discovered["email"]:
                    found = extract_emails_from_text(text_content)
                    if found:
                        discovered["email"] = found[0]
                if not discovered["linkedin_url"]:
                    found_li = extract_linkedin_urls_from_text(content)
                    if found_li:
                        discovered["linkedin_url"] = found_li[0]
                await browser.close()
        except Exception as e:
            log.debug("Playwright fallback for %s failed: %s", url, e)
