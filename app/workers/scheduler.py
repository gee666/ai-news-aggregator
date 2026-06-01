"""APScheduler-based worker entrypoint with import-safe fallback."""

import asyncio
import logging

from app.config import get_settings
from app.logging_config import configure_logging
from app.workers.jobs import JOBS, run_once

logger = logging.getLogger(__name__)

# Conservative MVP cadence. Individual jobs stay named exactly as in .agent-task.md.
JOB_INTERVAL_SECONDS = {
    "collect_telegram_channels": 300,
    "collect_gmail_newsletters": 600,
    "collect_rss_sources": 600,
    "process_new_raw_items": 300,
    "fetch_and_parse_links": 300,
    "run_pre_summary_dedup": 600,
    "summarize_ready_items": 600,
    "embed_new_summaries": 600,
    "cluster_new_summaries": 900,
    "generate_or_update_cluster_summaries": 1800,
    "send_digest_to_telegram": 3600,
}


async def _run_logged(job_name: str) -> None:
    try:
        result = await run_once(job_name)
        logger.info("job finished", extra={"job_name": job_name, "result": result})
    except Exception:
        logger.exception("job failed", extra={"job_name": job_name})


async def _fallback_loop() -> None:
    logger.warning("apscheduler is not installed; using simple asyncio scheduler fallback")
    while True:
        for job_name in JOBS:
            await _run_logged(job_name)
        await asyncio.sleep(300)


async def main_async() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        await _fallback_loop()
        return

    scheduler = AsyncIOScheduler(timezone="UTC")
    for job_name, seconds in JOB_INTERVAL_SECONDS.items():
        scheduler.add_job(
            _run_logged,
            "interval",
            seconds=seconds,
            args=[job_name],
            id=job_name,
            name=job_name,
            max_instances=1,
            coalesce=True,
        )
    scheduler.start()
    logger.info("worker scheduler started with %d jobs", len(JOB_INTERVAL_SECONDS))
    await asyncio.Event().wait()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
