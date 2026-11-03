import asyncio
import json
import os
import unittest
from datetime import UTC, datetime
from inspect import isasyncgenfunction
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.sse import ServerSentEvent

from app.models.notifications import Notification, NotificationType
from app.modules.notifications.service import (
    NotificationEvent,
    NotificationFeed,
    NotificationObserver,
    NotificationPublisher,
)
from tests.settings import TEST_ENVIRONMENT


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
    async def test_observer_flushes_a_durable_event_and_returns_it(self) -> None:
        session = MagicMock()
        session.flush = AsyncMock()
        observer = NotificationObserver()
        event = NotificationEvent(
            user_id=uuid4(),
            event_type=NotificationType.BOOKING_CONFIRMED,
            payload={"booking_id": 42},
        )

        pending: list[Notification] = []
        notification = await observer.observe(session, pending, event)

        session.add.assert_called_once_with(notification)
        session.flush.assert_awaited_once()
        self.assertEqual(pending, [notification])


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


class TrackingPool:
    def __init__(self) -> None:
        self.in_use = 0


class BlockingPubSub:
    def __init__(self, pool: TrackingPool) -> None:
        self.pool = pool
        self.polling = asyncio.Event()
        self.unsubscribe_started = asyncio.Event()
        self.release_unsubscribe = asyncio.Event()
        self.closed = asyncio.Event()

    async def subscribe(self, _channel: str) -> None:
        self.pool.in_use += 1

    async def get_message(self, **_kwargs):
        self.polling.set()
        await asyncio.Event().wait()

    async def unsubscribe(self, _channel: str) -> None:
        self.unsubscribe_started.set()
        await self.release_unsubscribe.wait()

    async def aclose(self) -> None:
        self.pool.in_use -= 1
        self.closed.set()


class ExpiringNotification:
    def __init__(self, state):
        self.state = state

    def _value(self, value):
        if self.state["expired"]:
            raise AssertionError("notification was accessed after rollback")
        return value

    @property
    def id(self):
        return self._value(12)

    @property
    def event_type(self):
        return self._value(NotificationType.BOOKING_CONFIRMED)

    @property
    def payload(self):
        return self._value({"booking_id": 42})

    @property
    def is_read(self):
        return self._value(False)

    @property
    def created_at(self):
        return self._value(datetime(2026, 10, 28, tzinfo=UTC))

    @property
    def read_at(self):
        return self._value(None)


class NotificationFeedTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_disconnect_releases_blocked_pubsub_connection(self) -> None:
        pool = TrackingPool()
        pubsub = BlockingPubSub(pool)
        redis = MagicMock()
        redis.pubsub.return_value = pubsub
        session = MagicMock()
        session.rollback = AsyncMock()
        feed = NotificationFeed(redis)
        feed.unread_for_user = AsyncMock(return_value=[])
        stream = feed.stream(session, uuid4(), AsyncMock(return_value=False))
        pending_event = asyncio.create_task(anext(stream))

        await pubsub.polling.wait()
        self.assertEqual(pool.in_use, 1)
        pending_event.cancel()
        await pubsub.unsubscribe_started.wait()
        pending_event.cancel()
        pubsub.release_unsubscribe.set()

        with self.assertRaises(asyncio.CancelledError):
            await pending_event
        await pubsub.closed.wait()
        self.assertEqual(pool.in_use, 0)

    async def test_stream_closes_pubsub_when_unsubscribe_fails(self) -> None:
        notification = make_notification()
        pubsub = FakePubSub(None)
        pubsub.unsubscribe.side_effect = RuntimeError("unsubscribe failed")
        redis = MagicMock()
        redis.pubsub.return_value = pubsub
        session = MagicMock()
        session.rollback = AsyncMock()
        feed = NotificationFeed(redis)
        feed.unread_for_user = AsyncMock(return_value=[notification])
        stream = feed.stream(session, notification.user_id, AsyncMock(return_value=True))

        await anext(stream)
        with self.assertRaisesRegex(RuntimeError, "unsubscribe failed"):
            await stream.aclose()

        pubsub.aclose.assert_awaited_once()

    async def test_stream_serializes_unread_notifications_before_rollback(self) -> None:
        state = {"expired": False}
        notification = ExpiringNotification(state)
        pubsub = FakePubSub(None)
        redis = MagicMock()
        redis.pubsub.return_value = pubsub
        session = MagicMock()

        async def rollback():
            state["expired"] = True

        session.rollback = AsyncMock(side_effect=rollback)
        feed = NotificationFeed(redis)
        feed.unread_for_user = AsyncMock(return_value=[notification])
        stream = feed.stream(session, uuid4(), AsyncMock(return_value=True))

        replay = await anext(stream)
        await stream.aclose()

        self.assertIsInstance(replay, ServerSentEvent)
        self.assertEqual((replay.id, replay.event), ("12", "notification"))
        self.assertEqual(json.loads(replay.raw_data or "")["payload"], {"booking_id": 42})

    async def test_stream_replays_unread_then_forwards_live_notification(self) -> None:
        unread = make_notification(notification_id=10)
        live = make_notification(notification_id=11)
        pubsub = FakePubSub({"type": "message", "data": NotificationPublisher.payload(live)})
        redis = MagicMock()
        redis.pubsub.return_value = pubsub
        session = MagicMock()
        session.rollback = AsyncMock()
        feed = NotificationFeed(redis)
        feed.unread_for_user = AsyncMock(return_value=[unread])
        disconnected = AsyncMock(side_effect=[False, True])

        stream = feed.stream(session, unread.user_id, disconnected)
        replay = await anext(stream)
        forwarded = await anext(stream)
        await stream.aclose()

        self.assertEqual((replay.id, replay.event), ("10", "notification"))
        self.assertEqual((forwarded.id, forwarded.event), ("11", "notification"))
        self.assertEqual(json.loads(forwarded.raw_data or "")["payload"], {"booking_id": 42})
        pubsub.subscribe.assert_awaited_once_with(f"notify:user:{unread.user_id}")
        pubsub.unsubscribe.assert_awaited_once_with(f"notify:user:{unread.user_id}")
        pubsub.aclose.assert_awaited_once()
        session.rollback.assert_awaited_once()


class NotificationEndpointTests(unittest.TestCase):
    def test_stream_route_uses_fastapi_sse_generator(self) -> None:
        with patch.dict(os.environ, TEST_ENVIRONMENT):
            from fastapi.routing import APIRoute
            from fastapi.sse import EventSourceResponse

            from app.modules.notifications.endpoints.v1 import router

        route = next(
            item
            for item in router.routes
            if isinstance(item, APIRoute) and item.path == "/notifications/stream"
        )

        self.assertIs(route.response_class, EventSourceResponse)
        self.assertTrue(isasyncgenfunction(route.endpoint))


if __name__ == "__main__":
    unittest.main()
