"""HTTP fetching with optional httpx dependency and conservative network safety."""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urljoin, urlsplit

from app.config import get_settings
from app.preprocessing.urls import normalize_url

try:  # import-safe optional handling
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

_MAX_BYTES = 5 * 1024 * 1024
_MAX_REDIRECTS = 5
_ALLOWED_SCHEMES = {"http", "https"}


@dataclass(slots=True)
class FetchResult:
    url: str
    final_url: str | None = None
    status_code: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    text: str | None = None
    content: bytes | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code is not None and 200 <= self.status_code < 400


def is_configured() -> bool:
    return httpx is not None


def _ip_is_public(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return ip.is_global


def _host_is_public(host: str | None) -> bool:
    if not host:
        return False
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
        except OSError:
            return False
    return bool(addresses) and all(_ip_is_public(str(ip)) for ip in addresses)


def _peer_is_public(response: object) -> bool:
    """Validate the actual connected peer address exposed by httpcore/httpx."""
    try:
        stream = response.extensions.get("network_stream")  # type: ignore[attr-defined]
        peername = stream.get_extra_info("peername") if stream else None
        if not peername:
            sock = stream.get_extra_info("socket") if stream else None
            peername = sock.getpeername() if sock else None
        return bool(peername and _ip_is_public(str(peername[0])))
    except Exception:
        return False


def validate_fetch_url(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return "unsupported_scheme"
    if not _host_is_public(parsed.hostname):
        return "unsafe_host"
    return None


async def fetch_url(url: str, *, headers: Mapping[str, str] | None = None, timeout: float | None = None, max_bytes: int = _MAX_BYTES) -> FetchResult:
    if httpx is None:
        return FetchResult(url=url, error="httpx_not_installed")
    safety_error = validate_fetch_url(url)
    if safety_error:
        return FetchResult(url=url, error=safety_error)

    settings = get_settings()
    request_headers = {"User-Agent": "news-bot-ai/0.1 (+https://local)", "Accept": "text/html,application/xhtml+xml,application/xml,text/plain;q=0.9,*/*;q=0.1"}
    if headers:
        request_headers.update(headers)
    current_url = url
    try:
        async with httpx.AsyncClient(timeout=timeout or settings.fetch_timeout_seconds, headers=request_headers) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                safety_error = validate_fetch_url(current_url)
                if safety_error:
                    return FetchResult(url=url, final_url=current_url, error=safety_error)
                async with client.stream("GET", current_url) as response:
                    if not _peer_is_public(response):
                        return FetchResult(url=url, final_url=str(response.url), status_code=response.status_code, headers=dict(response.headers), error="unsafe_peer")
                    if response.is_redirect and response.headers.get("location"):
                        current_url = urljoin(current_url, response.headers["location"])
                        continue
                    length = response.headers.get("content-length")
                    if length and int(length) > max_bytes:
                        return FetchResult(url=url, final_url=str(response.url), status_code=response.status_code, headers=dict(response.headers), error="response_too_large")
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            return FetchResult(url=url, final_url=str(response.url), status_code=response.status_code, headers=dict(response.headers), error="response_too_large")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    ctype = response.headers.get("content-type", "").lower()
                    text = content.decode(response.encoding or "utf-8", "ignore") if ("text" in ctype or "html" in ctype or "xml" in ctype or not ctype) else None
                    return FetchResult(url=url, final_url=normalize_url(str(response.url)), status_code=response.status_code, headers=dict(response.headers), text=text, content=content)
            return FetchResult(url=url, final_url=current_url, error="too_many_redirects")
    except Exception as exc:  # network must not crash collectors
        return FetchResult(url=url, final_url=current_url, error=f"{type(exc).__name__}: {exc}")
