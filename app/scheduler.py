"""
Durable scheduler.

Uses APScheduler with a SQLAlchemy job store backed by its OWN sqlite
file (jobs.db, separate from campaigns.db to avoid lock contention).
Because jobs live in a real database file - not just in memory - a
scheduled job survives the process crashing and restarting: on startup
BackgroundScheduler reloads any jobs it hasn't run yet from jobs.db and
fires them (or fires them immediately if their time already passed,
governed by misfire_grace_time).

The job function itself (run_publish_job) must be a plain importable
module-level function, NOT a closure, because APScheduler needs to be
able to serialize a reference to it into the job store.
"""

import asyncio

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from app.services.publish_service import publish_campaign

JOBS_DB_URL = "sqlite:///jobs.db"

jobstores = {
    "default": SQLAlchemyJobStore(url=JOBS_DB_URL),
}

scheduler = BackgroundScheduler(
    jobstores=jobstores,
    # A job whose scheduled time has already passed (e.g. because the
    # process was down when it should have fired) still runs, as long
    # as it's within this grace window - this is what makes a missed
    # publish during downtime get picked up on restart instead of
    # silently vanishing.
    job_defaults={"misfire_grace_time": 3600},
)


def run_publish_job(campaign_id: str):
    """
    Synchronous entry point APScheduler calls. Bridges into the async
    publish_campaign() using its own event loop, since APScheduler's
    BackgroundScheduler runs jobs in plain worker threads.
    """
    asyncio.run(publish_campaign(campaign_id))


def schedule_campaign_publish(campaign_id: str, run_date):
    """
    Schedules a one-off publish job for campaign_id at run_date
    (a datetime). Uses the campaign_id as the job id so re-scheduling
    the same campaign replaces the old job instead of creating a
    duplicate.
    """
    scheduler.add_job(
        run_publish_job,
        trigger="date",
        run_date=run_date,
        args=[campaign_id],
        id=f"publish-{campaign_id}",
        replace_existing=True,
    )


def start_scheduler():
    if not scheduler.running:
        scheduler.start()


def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)