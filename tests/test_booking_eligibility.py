import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.models.bookings import Booking, BookingResourceType, BookingStatus
from app.models.memberships import (
    Membership,
    MembershipEntitlement,
    MembershipPlan,
    MembershipStatus,
    PlanEntitlement,
)
from app.modules.bookings.eligibility import (
    BookingContext,
    EligibilityFailure,
    EligibilityRule,
    build_eligibility_chain,
    week_bounds,
)

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)


def membership(window=3, limit=5, entitlements=(MembershipEntitlement.CLASS_BOOKING,)):
    return Membership(
        status=MembershipStatus.ACTIVE,
        starts_on=NOW.date(),
        ends_on=(NOW + timedelta(days=30)).date(),
        plan=MembershipPlan(
            name="Configurable plan",
            booking_window_days=window,
            weekly_booking_limit=limit,
            entitlements=[PlanEntitlement(entitlement=value) for value in entitlements],
        ),
    )


def booking(start, status=BookingStatus.CONFIRMED):
    return Booking(starts_at=start, status=status)


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.context = BookingContext(
            NOW, NOW + timedelta(days=1), BookingResourceType.CLASS, membership(), []
        )

    def codes(self, **changes):
        return [
            failure.code
            for failure in build_eligibility_chain().handle(replace(self.context, **changes))
        ]

    def test_valid_booking(self):
        self.assertEqual(self.codes(), [])

    def test_collects_all_independent_failures(self):
        start = NOW + timedelta(days=4)
        self.assertEqual(
            self.codes(
                membership=membership(limit=1, entitlements=()),
                starts_at=start,
                bookings=[booking(start)],
            ),
            ["plan_entitlement", "booking_window", "weekly_limit", "time_conflict"],
        )

    def test_missing_membership_does_not_crash_dependent_rules(self):
        self.assertEqual(
            self.codes(membership=None, starts_at=NOW), ["session_started", "membership_inactive"]
        )

    def test_inactive_expired_future_and_cancelled_memberships(self):
        for status in (MembershipStatus.CANCELLED, MembershipStatus.EXPIRED):
            member = membership()
            member.status = status
            with self.subTest(status=status):
                self.assertIn("membership_inactive", self.codes(membership=member))
        member = membership()
        member.ends_on = NOW.date()
        self.assertEqual(self.codes(membership=member), ["membership_inactive"])
        member = membership()
        member.starts_on = (NOW + timedelta(days=1)).date()
        self.assertEqual(self.codes(membership=member), ["membership_inactive"])

    def test_plan_window_boundaries(self):
        for window in (2, 3, 7):
            with self.subTest(window=window):
                self.assertEqual(
                    self.codes(
                        membership=membership(window=window), starts_at=NOW + timedelta(days=window)
                    ),
                    [],
                )
                self.assertEqual(
                    self.codes(
                        membership=membership(window=window),
                        starts_at=NOW + timedelta(days=window, microseconds=1),
                    ),
                    ["booking_window"],
                )

    def test_entitlements_for_each_resource(self):
        for resource, entitlement in (
            (BookingResourceType.CLASS, MembershipEntitlement.CLASS_BOOKING),
            (BookingResourceType.POOL, MembershipEntitlement.POOL_BOOKING),
            (BookingResourceType.PERSONAL_TRAINING, MembershipEntitlement.PERSONAL_TRAINING),
        ):
            with self.subTest(resource=resource):
                self.assertEqual(
                    self.codes(
                        resource_type=resource, membership=membership(entitlements=(entitlement,))
                    ),
                    [],
                )
                self.assertEqual(
                    self.codes(resource_type=resource, membership=membership(entitlements=())),
                    ["plan_entitlement"],
                )

    def test_weekly_limits_and_cancelled_exclusion(self):
        for limit in (3, 5, 10):
            entries = [booking(NOW + timedelta(minutes=i)) for i in range(limit)]
            with self.subTest(limit=limit):
                self.assertEqual(
                    self.codes(membership=membership(limit=limit), bookings=entries),
                    ["weekly_limit"],
                )
                entries[0].status = BookingStatus.CANCELLED
                self.assertEqual(
                    self.codes(membership=membership(limit=limit), bookings=entries), []
                )

    def test_requested_week_and_monday_boundary(self):
        start, end = week_bounds(NOW)
        self.assertEqual(start, datetime(2026, 10, 19, tzinfo=UTC))
        self.assertEqual(end, datetime(2026, 10, 26, tzinfo=UTC))
        self.assertEqual(
            self.codes(
                membership=membership(limit=1),
                bookings=[booking(start - timedelta(microseconds=1)), booking(end)],
            ),
            [],
        )
        self.assertEqual(
            self.codes(
                membership=membership(window=7, limit=1),
                starts_at=NOW + timedelta(days=7),
                bookings=[booking(NOW)],
            ),
            [],
        )

    def test_same_instant_with_different_offset_conflicts(self):
        from datetime import timezone

        existing = booking(self.context.starts_at.astimezone(timezone(timedelta(hours=2))))
        self.assertEqual(self.codes(bookings=[existing]), ["time_conflict"])
        existing.status = BookingStatus.CANCELLED
        self.assertEqual(self.codes(bookings=[existing]), [])

    def test_custom_rule_can_be_registered(self):
        class ExtraRule(EligibilityRule):
            def check(self, context):
                return EligibilityFailure("extra", "extra check")

        from app.modules.bookings.eligibility import DEFAULT_RULES

        chain = build_eligibility_chain((*DEFAULT_RULES, ExtraRule))
        self.assertEqual([failure.code for failure in chain.handle(self.context)], ["extra"])

    def test_empty_chain_rejected(self):
        with self.assertRaises(ValueError):
            build_eligibility_chain(())
