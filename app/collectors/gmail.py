"""Gmail newsletter collector using OAuth token/client-secret files when Google APIs are installed."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from app.config import get_settings
from app.collectors.telegram_user import add_raw_item_links, load_source_config, upsert_raw_item, upsert_source
from app.preprocessing.urls import extract_urls

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except Exception:  # pragma: no cover
    Credentials = InstalledAppFlow = Request = build = None  # type: ignore[assignment]


def is_configured() -> bool:
    s = get_settings()
    return build is not None and (s.gmail_token_path.exists() or s.gmail_client_secret_path.exists())


def _gmail_service() -> Any | None:
    if build is None:
        return None
    s = get_settings()
    scopes = [x.strip() for x in s.gmail_scopes.split(",") if x.strip()]
    creds = Credentials.from_authorized_user_file(str(s.gmail_token_path), scopes) if s.gmail_token_path.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not s.gmail_client_secret_path.exists() or InstalledAppFlow is None:
            return None
        flow = InstalledAppFlow.from_client_secrets_file(str(s.gmail_client_secret_path), scopes)
        creds = flow.run_local_server(port=0)
        s.gmail_token_path.parent.mkdir(parents=True, exist_ok=True)
        s.gmail_token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _body(payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    stack = [payload]
    while stack:
        part = stack.pop()
        stack.extend(part.get("parts") or [])
        data = (part.get("body") or {}).get("data")
        if data:
            try:
                chunks.append(base64.urlsafe_b64decode(data + "===").decode("utf-8", "ignore"))
            except Exception:
                pass
    return "\n".join(chunks)


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    return {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers") or []}


def _date(value: str | None) -> datetime:
    if value:
        try:
            return parsedate_to_datetime(value)
        except Exception:
            pass
    return datetime.now(timezone.utc)


async def collect_gmail_newsletters(max_results: int = 25) -> int:
    service = _gmail_service()
    if service is None:
        return 0
    from app.db.session import AsyncSessionLocal

    count = 0
    async with AsyncSessionLocal() as session:
        for cfg in load_source_config().get("email") or []:
            if cfg.get("active", True) is False:
                continue
            sender = cfg.get("sender")
            labels = cfg.get("labels") or ["INBOX"]
            query = cfg.get("query") or (f"from:{sender}" if sender else "")
            source = await upsert_source(session, source_type="gmail", name=cfg.get("name") or sender or "gmail", identifier=sender or cfg.get("name"), config=cfg)
            resp = service.users().messages().list(userId="me", q=query, labelIds=labels, maxResults=cfg.get("limit", max_results)).execute()
            for ref in resp.get("messages") or []:
                msg = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
                payload = msg.get("payload") or {}
                headers = _headers(payload)
                text = _body(payload) or msg.get("snippet") or ""
                urls = extract_urls(text)
                item = await upsert_raw_item(
                    session,
                    source=source,
                    external_id=msg.get("id"),
                    title=headers.get("subject"),
                    raw_text=text,
                    raw_html=text,
                    original_url=None,
                    published_at=_date(headers.get("date")),
                    metadata={"gmail_thread_id": msg.get("threadId"), "headers": headers},
                )
                await add_raw_item_links(session, item, urls)
                count += 1
        await session.commit()
    return count
