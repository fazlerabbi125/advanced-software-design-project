from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.modules.bookings.jobs import run_no_show_detection, run_offer_expiry
from app.utils.constants import BOOKING_JOBS_INTERVAL_SECONDS


def create_scheduler() -> AsyncIOScheduler:
    """Scheduler for the periodic booking jobs, started and stopped with the app."""
    # coalesce and max_instances: a run that falls behind is not stacked up or overlapped.
    scheduler = AsyncIOScheduler(job_defaults={"coalesce": True, "max_instances": 1})
    for job in (run_offer_expiry, run_no_show_detection):
        scheduler.add_job(job, "interval", seconds=BOOKING_JOBS_INTERVAL_SECONDS, id=job.__name__)
    return scheduler
