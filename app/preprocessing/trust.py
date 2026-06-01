"""Trusted source/account configuration and document trust classification."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.preprocessing.urls import domain_from_url, domain_matches, extract_social_handle, is_forbidden_url

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


def _read_yaml(path: Path) -> dict[str, Any]:
    if yaml is None or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=8)
def load_trusted_sources() -> list[dict[str, Any]]:
    return list(_read_yaml(get_settings().trusted_sources_path).get("sources") or [])


@lru_cache(maxsize=8)
def load_trusted_social_accounts() -> list[dict[str, Any]]:
    return list(_read_yaml(get_settings().trusted_social_accounts_path).get("accounts") or [])


def trusted_source_for_url(url: str) -> dict[str, Any] | None:
    domain = domain_from_url(url)
    for source in load_trusted_sources():
        if source.get("active", True) is False:
            continue
        source_domain = str(source.get("domain") or "").lower().removeprefix("www.")
        if domain_matches(domain, source_domain):
            return source
    return None


def trusted_social_for_url(url: str) -> dict[str, Any] | None:
    platform, handle = extract_social_handle(url)
    if not platform or not handle:
        return None
    for account in load_trusted_social_accounts():
        if account.get("active", True) is False:
            continue
        if str(account.get("platform") or "").lower() == platform and str(account.get("handle") or "").lstrip("@").lower() == handle.lower():
            return account
    return None


def classify_url(url: str) -> tuple[str | None, str | None]:
    verdict = is_forbidden_url(url, load_trusted_social_accounts())
    if not verdict.allowed:
        return None, verdict.reason
    social = trusted_social_for_url(url)
    if social:
        return social.get("trust_level") or "official", None
    source = trusted_source_for_url(url)
    if source:
        return source.get("trust_level") or "trusted", None
    return "untrusted", None


def is_configured() -> bool:
    settings = get_settings()
    return settings.trusted_sources_path.exists() or settings.trusted_social_accounts_path.exists()
