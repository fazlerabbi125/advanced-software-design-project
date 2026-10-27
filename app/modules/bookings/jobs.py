"""Booking jobs the System Clock actor triggers: offer expiry and no-show detection.

Each job works one timetable session at a time and locks it with SKIP LOCKED, so a
session a member is booking or cancelling right now is left for the next run, and two
processes running the jobs never handle the same session twice.
"""

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookings import Booking, BookingStatus, WaitlistEntry, WaitlistStatus
from app.models.timetable_sessions import TimetableSession
from app.modules.bookings.service import BookingService, check_in_deadline, offer_deadline
from app.shared.helpers import utc_now


async def _lock_session(db: AsyncSession, session_id: int) -> TimetableSession | None:
    return await db.scalar(
        select(TimetableSession)
        .where(TimetableSession.id == session_id)
        .with_for_update(skip_locked=True)
    )


async def expire_waitlist_offers(db: AsyncSession, now: datetime) -> int:
    """Expire open offers past their deadline and pass each place on. Returns the count."""
    session_ids = (
        await db.scalars(
            select(WaitlistEntry.session_id)
            .where(
                WaitlistEntry.status == WaitlistStatus.OFFERED,
                WaitlistEntry.session_id.is_not(None),
            )
            .distinct()
        )
    ).all()
    await db.rollback()
    service = BookingService(db)
    expired = 0
    for session_id in session_ids:
        timetable_session = await _lock_session(db, session_id)
        if timetable_session is None:
            await db.rollback()
            continue
        entries = (
            await db.scalars(
                select(WaitlistEntry)
                .where(
                    WaitlistEntry.session_id == session_id,
                    WaitlistEntry.status == WaitlistStatus.OFFERED,
                )
                .with_for_update()
            )
        ).all()
        lapsed = [
            entry
            for entry in entries
            if entry.offered_at is None
            or offer_deadline(entry.offered_at, timetable_session) <= now
        ]
        for entry in lapsed:
            entry.status = WaitlistStatus.EXPIRED
        await service.release_places(timetable_session, len(lapsed), now)
        await db.commit()
        expired += len(lapsed)
    return expired


async def detect_no_shows(db: AsyncSession, now: datetime) -> int:
    """Mark confirmed session bookings past their check-in deadline as no-shows.

    Returns the count. A no-show gives its place back, so it can be offered to the
    waiting list while an offer is still possible (a pool lane up to 15 minutes before
    the end). Bookings made before timetable sessions existed had no way to check in,
    so they are left alone.
    """
    candidates = (
        await db.execute(
            select(Booking.id, Booking.timetable_session_id).where(
                Booking.status == BookingStatus.CONFIRMED,
                Booking.timetable_session_id.is_not(None),
                Booking.starts_at <= now,
            )
        )
    ).all()
    await db.rollback()
    by_session: defaultdict[int, list[int]] = defaultdict(list)
    for booking_id, session_id in candidates:
        by_session[session_id].append(booking_id)

    service = BookingService(db)
    marked = 0
    for session_id, booking_ids in by_session.items():
        timetable_session = await _lock_session(db, session_id)
        if timetable_session is None:
            await db.rollback()
            continue
        bookings = (
            await db.scalars(
                select(Booking)
                .where(Booking.id.in_(booking_ids), Booking.status == BookingStatus.CONFIRMED)
                .with_for_update(skip_locked=True)
            )
        ).all()
        missed = [booking for booking in bookings if check_in_deadline(booking) <= now]
        for booking in missed:
            booking.status = BookingStatus.NO_SHOW
        await service.release_places(timetable_session, len(missed), now)
        await db.commit()
        marked += len(missed)
    return marked


async def run_offer_expiry() -> None:
    from app.core.database import session_factory

    async with session_factory() as db:
        await expire_waitlist_offers(db, utc_now())


async def run_no_show_detection() -> None:
    from app.core.database import session_factory

    async with session_factory() as db:
        await detect_no_shows(db, utc_now())
