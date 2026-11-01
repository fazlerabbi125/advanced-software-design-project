import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.models.bookings import Booking, BookingResourceType
from app.models.notifications import NotificationType
from app.modules.bookings.service import BookingService


class BookingNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_booking_notification_uses_the_flushed_booking_id(self) -> None:
        starts_at = datetime(2026, 11, 1, tzinfo=UTC)
        booking = Booking(
            user_id=uuid4(),
            timetable_session_id=7,
            resource_name="Pilates",
            resource_type=BookingResourceType.CLASS,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=45),
        )
        session = MagicMock()

        async def flush() -> None:
            booking.id = 42

        session.flush = AsyncMock(side_effect=flush)
        observer = MagicMock()
        observer.observe = AsyncMock()
        service = BookingService(MagicMock(), observer)

        await service._record_booking(session, [], booking, NotificationType.BOOKING_CONFIRMED)

        event = observer.observe.await_args.args[2]
        self.assertEqual(event.payload["booking_id"], 42)
        session.flush.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
