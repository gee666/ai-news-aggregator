"""URL extraction, normalization, redirect unwrapping, and source safety helpers."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

from app.config import get_settings

_URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>'\"\])}]+")
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src"}
_REDIRECT_PARAMS = ("url", "u", "target", "redirect", "redirect_url", "destination", "dest", "link")
_TELEGRAM_DOMAINS = {"t.me", "telegram.me", "telegram.org"}
_FACEBOOK_DOMAINS = {"facebook.com", "www.facebook.com", "fb.com", "m.facebook.com"}
_X_DOMAINS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}


@dataclass(frozen=True)
class UrlVerdict:
    allowed: bool
    reason: str | None = None
    trust_level: str | None = None
    platform: str | None = None
    handle: str | None = None


def extract_urls(text: str | None) -> list[str]:
    """Extract HTTP(S) URLs from plain text, preserving order and removing duplicates."""
    seen: set[str] = set()
    urls: list[str] = []
    for match in _URL_RE.findall(text or ""):
        url = match.rstrip(".,;:!?、。")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    host = urlsplit(url).hostname
    return host.lower().removeprefix("www.") if host else None


def root_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    parts = domain.lower().strip(".").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain.lower()


def domain_matches(host: str | None, base_domain: str | None) -> bool:
    """True when host is exactly base_domain or a subdomain of it."""
    if not host or not base_domain:
        return False
    host = host.lower().strip(".").removeprefix("www.")
    base = base_domain.lower().strip(".").removeprefix("www.")
    return host == base or host.endswith(f".{base}")


def normalize_url(url: str, base_url: str | None = None) -> str:
    """Canonical-ish URL normalization suitable for duplicate checks."""
    if base_url:
        url = urljoin(base_url, url)
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    netloc = host
    if parts.port and not ((scheme == "http" and parts.port == 80) or (scheme == "https" and parts.port == 443)):
        netloc = f"{host}:{parts.port}"
    path = quote(unquote(parts.path or "/"), safe="/%:@")
    if path != "/":
        path = path.rstrip("/")
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith(_TRACKING_PREFIXES)
    ]
    query = urlencode(sorted(query_pairs), doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def unwrap_redirect_url(url: str) -> str:
    """Unwrap common newsletter/search/social redirect URLs."""
    current = url.strip()
    for _ in range(4):
        parsed = urlsplit(current)
        qs = parse_qs(parsed.query)
        found = None
        for name in _REDIRECT_PARAMS:
            values = qs.get(name)
            if values and values[0].startswith(("http://", "https://")):
                found = values[0]
                break
        if not found:
            return current
        current = unquote(found)
    return current


def extract_social_handle(url: str) -> tuple[str | None, str | None]:
    parsed = urlsplit(url)
    domain = (parsed.hostname or "").lower()
    path_bits = [p for p in parsed.path.split("/") if p]
    if not path_bits:
        return None, None
    if domain in _X_DOMAINS:
        if path_bits[0].lower() in {"i", "intent", "share", "search", "hashtag"}:
            return "x", None
        return "x", path_bits[0].lstrip("@")
    if domain in _TELEGRAM_DOMAINS:
        return "telegram", path_bits[0].lstrip("@")
    if domain in _FACEBOOK_DOMAINS:
        return "facebook", path_bits[0]
    return None, None


def _trusted_account_map(accounts: list[dict[str, Any]] | None) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for account in accounts or []:
        if account.get("active", True) is False:
            continue
        platform = str(account.get("platform") or "").lower()
        handle = str(account.get("handle") or "").lstrip("@").lower()
        if platform and handle:
            result[(platform, handle)] = account
    return result


def is_forbidden_url(url: str, trusted_accounts: list[dict[str, Any]] | None = None) -> UrlVerdict:
    settings = get_settings()
    parsed_domain = (urlsplit(url).hostname or "").lower()
    platform, handle = extract_social_handle(url)
    if platform and handle:
        account = _trusted_account_map(trusted_accounts).get((platform, handle.lower()))
        if account:
            return UrlVerdict(True, trust_level=account.get("trust_level"), platform=platform, handle=handle)
    if settings.reject_telegram_links and any(domain_matches(parsed_domain, d) for d in _TELEGRAM_DOMAINS):
        return UrlVerdict(False, "telegram_link_rejected", platform="telegram", handle=handle)
    if settings.reject_facebook_links and any(domain_matches(parsed_domain, d) for d in _FACEBOOK_DOMAINS):
        return UrlVerdict(False, "facebook_link_rejected", platform="facebook", handle=handle)
    is_x_domain = any(domain_matches(parsed_domain, d) for d in _X_DOMAINS)
    if is_x_domain:
        account = _trusted_account_map(trusted_accounts).get(("x", (handle or "").lower()))
        if not (settings.allow_x_official_posts and platform == "x" and handle and account):
            return UrlVerdict(False, "untrusted_x_account", platform="x", handle=handle)
        return UrlVerdict(True, trust_level=account.get("trust_level"), platform="x", handle=handle)
    return UrlVerdict(True, platform=platform, handle=handle)


def prepare_url(url: str, base_url: str | None = None) -> str:
    return normalize_url(unwrap_redirect_url(urljoin(base_url, url) if base_url else url))
