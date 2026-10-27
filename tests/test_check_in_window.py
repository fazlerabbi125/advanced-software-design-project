import unittest
from datetime import timedelta

from app.models.bookings import Booking, BookingStatus
from app.modules.bookings.service import check_in_deadline, check_in_problem
from app.utils.constants import CHECK_IN_GRACE_MINUTES, CHECK_IN_OPENS_MINUTES
from tests.test_booking_eligibility import NOW


def booking(status=BookingStatus.CONFIRMED, made=NOW - timedelta(days=1)):
    return Booking(
        starts_at=NOW,
        ends_at=NOW + timedelta(minutes=45),
        created_at=made,
        status=status,
    )


class CheckInWindowTests(unittest.TestCase):
    def test_window_boundaries(self):
        opens = NOW - timedelta(minutes=CHECK_IN_OPENS_MINUTES)
        closes = NOW + timedelta(minutes=CHECK_IN_GRACE_MINUTES)
        for moment, allowed in (
            (opens - timedelta(seconds=1), False),
            (opens, True),
            (NOW, True),
            (closes - timedelta(seconds=1), True),
            (closes, False),
        ):
            with self.subTest(moment=moment):
                self.assertEqual(check_in_problem(booking(), moment) is None, allowed)

    def test_closes_exactly_when_the_no_show_job_takes_over(self):
        item = booking()
        deadline = check_in_deadline(item)
        self.assertIsNone(check_in_problem(item, deadline - timedelta(microseconds=1)))
        self.assertIn("closed", check_in_problem(item, deadline))

    def test_only_confirmed_bookings(self):
        for status in (BookingStatus.CANCELLED, BookingStatus.CHECKED_IN, BookingStatus.NO_SHOW):
            with self.subTest(status=status):
                self.assertIn("only a confirmed", check_in_problem(booking(status), NOW))

    def test_late_booking_gets_the_full_grace_period(self):
        late = booking(made=NOW + timedelta(minutes=5))
        moment = NOW + timedelta(minutes=5 + CHECK_IN_GRACE_MINUTES - 1)
        self.assertIsNone(check_in_problem(late, moment))


if __name__ == "__main__":
    unittest.main()
