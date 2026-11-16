"""SSRF-Protected Public Contact and Website Enrichment Service.

Architecture (PHASE 4 & 16 & 63):
- Safe URL resolution & Private IP / Loopback / Cloud metadata protection.
- Uses httpx (async HTTP) + selectolax (Fast native C HTML parser).
- Extracts public emails, phone numbers, contact pages, and social links.
- Strictly adheres to $0 API and privacy guidelines (no private data collection).
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
import urllib.parse
from typing import Any

import httpx
from pydantic import BaseModel
from selectolax.lexbor import LexborHTMLParser

log = logging.getLogger("leadsweep.enrichment")

# Blocked internal/private subnets and cloud metadata endpoints
BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # IPv4 loopback
    ipaddress.ip_network("10.0.0.0/8"),       # Private RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),    # Private RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),   # Private RFC 1918
    ipaddress.ip_network("169.254.0.0/16"),   # Link-local / Cloud Metadata (AWS/GCP/Azure)
    ipaddress.ip_network("0.0.0.0/8"),        # Broadcast
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
]


def is_safe_public_url(url: str) -> bool:
    """Validate that the target URL resolves strictly to a public internet IP address (Anti-SSRF)."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        if hostname.lower() in ("localhost", "metadata.google.internal", "instance-data"):
            return False

        # Resolve hostname to IP
        addr_info = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)
            for blocked_net in BLOCKED_IP_NETWORKS:
                if ip_obj in blocked_net:
                    log.warning("Blocked SSRF attempt to private IP %s for url %s", ip_str, url)
                    return False
        return True
    except Exception as e:
        log.debug("URL safety verification error for '%s': %s", url, e)
        return False


class EnrichedContact(BaseModel):
    website: str
    emails: list[str] = []
    phones: list[str] = []
    social_links: list[str] = []
    title: str | None = None
    description: str | None = None


class ContactEnrichmentService:
    """Fast, safe public contact extraction using httpx and selectolax."""

    @staticmethod
    async def enrich_website(url: str, timeout_s: float = 8.0) -> EnrichedContact:
        """Fetch static page, extract contact info, with SSRF protection."""
        if not is_safe_public_url(url):
            return EnrichedContact(website=url)

        emails: set[str] = set()
        phones: set[str] = set()
        socials: set[str] = set()
        page_title: str | None = None
        page_desc: str | None = None

        try:
            async with httpx.AsyncClient(
                timeout=timeout_s,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
            ) as client:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    return EnrichedContact(website=url)

                html_text = resp.text
                parser = LexborHTMLParser(html_text)

                # Page title & description
                t_node = parser.css_first("title")
                if t_node:
                    page_title = t_node.text(strip=True)

                desc_node = parser.css_first('meta[name="description"]')
                if desc_node:
                    page_desc = desc_node.attributes.get("content", "")

                # Email regex scanning
                raw_emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", html_text)
                for em in raw_emails:
                    em_lower = em.lower()
                    if not any(em_lower.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".js", ".css")):
                        emails.add(em_lower)

                # Public tel: links
                for a_tel in parser.css('a[href^="tel:"]'):
                    href = a_tel.attributes.get("href", "")
                    clean_phone = href.replace("tel:", "").strip()
                    if clean_phone:
                        phones.add(clean_phone)

                # Social profile links
                for a_link in parser.css("a[href]"):
                    href = a_link.attributes.get("href", "")
                    if any(domain in href for domain in ("linkedin.com/in/", "twitter.com/", "x.com/", "github.com/")):
                        socials.add(href)

        except Exception as err:
            log.debug("Website enrichment failed for %s: %s", url, err)

        return EnrichedContact(
            website=url,
            emails=list(emails)[:5],
            phones=list(phones)[:3],
            social_links=list(socials)[:5],
            title=page_title,
            description=page_desc,
        )
