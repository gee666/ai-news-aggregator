from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RawItem, Source, StoryCluster, Summary
from app.config import get_settings
from app.db.session import get_session
from app.workers.jobs import JOB_NAMES, run_once

router = APIRouter()


class SubmitRequest(BaseModel):
    url: str | None = None
    text: str | None = None
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubmitResponse(BaseModel):
    accepted: bool
    raw_item_id: str


def _dt(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _check_owner_token(authorization: str | None = Header(default=None)) -> None:
    expected = get_settings().api_owner_token
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _source_row(source: Source) -> dict[str, Any]:
    return {
        "id": str(source.id),
        "source_type": source.source_type,
        "name": source.name,
        "url": source.url,
        "identifier": source.identifier,
        "active": source.active,
        "dt_created": _dt(source.dt_created),
    }


def _raw_item_row(item: RawItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "source_id": str(item.source_id) if item.source_id else None,
        "title": item.title,
        "original_url": item.original_url,
        "status": item.status,
        "published_at": _dt(item.published_at),
        "collected_at": _dt(item.collected_at),
    }


def _summary_row(summary: Summary) -> dict[str, Any]:
    return {
        "id": str(summary.id),
        "target_type": summary.target_type,
        "target_id": str(summary.target_id),
        "summary_title": summary.summary_title,
        "summary_text": summary.summary_text,
        "source_links_json": summary.source_links_json,
        "dt_created": _dt(summary.dt_created),
    }


def _cluster_row(cluster: StoryCluster) -> dict[str, Any]:
    return {
        "id": str(cluster.id),
        "title": cluster.title,
        "status": cluster.status,
        "combined_summary_id": str(cluster.combined_summary_id) if cluster.combined_summary_id else None,
        "first_seen_at": _dt(cluster.first_seen_at),
        "last_seen_at": _dt(cluster.last_seen_at),
    }


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/sources")
async def sources(
    limit: int = Query(default=100, ge=1, le=500),
    _: None = Depends(_check_owner_token),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = await session.scalars(select(Source).order_by(Source.name).limit(limit))
    return [_source_row(row) for row in rows]


@router.get("/raw-items")
async def raw_items(
    limit: int = Query(default=50, ge=1, le=500),
    _: None = Depends(_check_owner_token),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = await session.scalars(select(RawItem).order_by(desc(RawItem.collected_at)).limit(limit))
    return [_raw_item_row(row) for row in rows]


@router.get("/summaries")
async def summaries(
    limit: int = Query(default=50, ge=1, le=500),
    _: None = Depends(_check_owner_token),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = await session.scalars(select(Summary).order_by(desc(Summary.dt_created)).limit(limit))
    return [_summary_row(row) for row in rows]


@router.get("/clusters")
async def clusters(
    limit: int = Query(default=50, ge=1, le=500),
    _: None = Depends(_check_owner_token),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = await session.scalars(select(StoryCluster).order_by(desc(StoryCluster.dt_created)).limit(limit))
    return [_cluster_row(row) for row in rows]


@router.get("/search")
async def search(
    q: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
    _: None = Depends(_check_owner_token),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    pattern = f"%{q}%"
    summary_rows = await session.scalars(
        select(Summary)
        .where(or_(Summary.summary_title.ilike(pattern), Summary.summary_text.ilike(pattern)))
        .order_by(desc(Summary.dt_created))
        .limit(limit)
    )
    cluster_rows = await session.scalars(
        select(StoryCluster)
        .where(StoryCluster.title.ilike(pattern))
        .order_by(desc(StoryCluster.dt_created))
        .limit(limit)
    )
    return {
        "query": q,
        "results": {
            "summaries": [_summary_row(row) for row in summary_rows],
            "clusters": [_cluster_row(row) for row in cluster_rows],
        },
    }


@router.post("/submit", response_model=SubmitResponse)
async def submit(
    payload: SubmitRequest,
    _: None = Depends(_check_owner_token),
    session: AsyncSession = Depends(get_session),
) -> SubmitResponse:
    if not payload.url and not payload.text:
        raise HTTPException(status_code=422, detail="Provide url or text")
    item = RawItem(
        source_id=None,
        title=payload.title,
        raw_text=payload.text or payload.url,
        original_url=payload.url,
        metadata_json={"submitted_via": "api", **payload.metadata},
        status="new",
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return SubmitResponse(accepted=True, raw_item_id=str(item.id))


@router.post("/jobs/run-once/{job_name}")
async def run_job_once(job_name: str, _: None = Depends(_check_owner_token)) -> dict[str, Any]:
    if job_name not in JOB_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_name}")
    return await run_once(job_name)
