import json
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.models.notifications import Notification, NotificationType
from app.modules.notifications.service import (
    NotificationEvent,
    NotificationFeed,
    NotificationObserver,
    NotificationPublisher,
)


def make_notification(*, notification_id: int = 1) -> Notification:
    return Notification(
        id=notification_id,
        user_id=uuid4(),
        event_type=NotificationType.BOOKING_CONFIRMED,
        payload={"booking_id": 42},
        is_read=False,
        created_at=datetime(2026, 10, 28, tzinfo=UTC),
        read_at=None,
    )


class NotificationObserverTests(unittest.IsolatedAsyncioTestCase):
    async def test_observer_flushes_a_durable_event_and_drains_once(self) -> None:
        session = MagicMock()
        session.flush = AsyncMock()
        observer = NotificationObserver(session)
        event = NotificationEvent(
            user_id=uuid4(),
            event_type=NotificationType.BOOKING_CONFIRMED,
            payload={"booking_id": 42},
        )

        notification = await observer.observe(event)

        session.add.assert_called_once_with(notification)
        session.flush.assert_awaited_once()
        self.assertEqual(observer.drain(), [notification])
        self.assertEqual(observer.drain(), [])


class NotificationPublisherTests(unittest.IsolatedAsyncioTestCase):
    async def test_publisher_serializes_and_publishes_to_member_channel(self) -> None:
        notification = make_notification()
        redis = MagicMock()
        redis.publish = AsyncMock(return_value=1)

        await NotificationPublisher(redis).publish_many([notification])

        channel, data = redis.publish.await_args.args
        self.assertEqual(channel, f"notify:user:{notification.user_id}")
        self.assertEqual(json.loads(data)["id"], notification.id)
        self.assertEqual(json.loads(data)["event_type"], "booking.confirmed")


class FakePubSub:
    def __init__(self, message: dict[str, str]) -> None:
        self.message = message
        self.subscribe = AsyncMock()
        self.unsubscribe = AsyncMock()
        self.aclose = AsyncMock()

    async def get_message(self, **_kwargs):
        message, self.message = self.message, None
        return message


class NotificationFeedTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_replays_unread_then_forwards_live_notification(self) -> None:
        unread = make_notification(notification_id=10)
        live = make_notification(notification_id=11)
        pubsub = FakePubSub(
            {"type": "message", "data": NotificationPublisher.payload(live)}
        )
        redis = MagicMock()
        redis.pubsub.return_value = pubsub
        feed = NotificationFeed(MagicMock(), redis)
        feed.unread_for_user = AsyncMock(return_value=[unread])
        disconnected = AsyncMock(side_effect=[False, True])

        stream = feed.stream(unread.user_id, disconnected)
        replay = await anext(stream)
        forwarded = await anext(stream)
        await stream.aclose()

        self.assertIn("id: 10", replay)
        self.assertIn("id: 11", forwarded)
        self.assertIn('"booking_id":42', forwarded)
        pubsub.subscribe.assert_awaited_once_with(f"notify:user:{unread.user_id}")
        pubsub.unsubscribe.assert_awaited_once_with(f"notify:user:{unread.user_id}")
        pubsub.aclose.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
