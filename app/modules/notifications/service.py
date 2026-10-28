import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notifications import Notification, NotificationType
from app.modules.notifications.schemas import NotificationResponse

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    user_id: UUID
    event_type: NotificationType
    payload: dict[str, Any]


class NotificationObserver:
    """Records domain events as durable notification rows in the current transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._pending: list[Notification] = []

    async def observe(self, event: NotificationEvent) -> Notification:
        notification = Notification(
            user_id=event.user_id,
            event_type=event.event_type,
            payload=event.payload,
        )
        self.session.add(notification)
        await self.session.flush()
        self._pending.append(notification)
        return notification

    def drain(self) -> list[Notification]:
        pending, self._pending = self._pending, []
        return pending


class NotificationPublisher:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def channel(user_id: UUID) -> str:
        return f"notify:user:{user_id}"

    @staticmethod
    def payload(notification: Notification) -> str:
        data = NotificationResponse.model_validate(notification).model_dump(mode="json")
        return json.dumps(data, separators=(",", ":"))

    async def publish_many(self, notifications: Iterable[Notification]) -> None:
        messages = list(notifications)
        results = await asyncio.gather(
            *(
                self.redis.publish(self.channel(item.user_id), self.payload(item))
                for item in messages
            ),
            return_exceptions=True,
        )
        for notification, result in zip(messages, results, strict=True):
            if isinstance(result, Exception):
                logger.warning(
                    "Notification persisted but live publish failed: notification_id=%s",
                    notification.id,
                    exc_info=(type(result), result, result.__traceback__),
                )


class NotificationFeed:
    def __init__(self, session: AsyncSession, redis: Redis) -> None:
        self.session = session
        self.redis = redis

    async def unread_for_user(self, user_id: UUID) -> list[Notification]:
        statement = (
            select(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .order_by(Notification.created_at, Notification.id)
        )
        return list((await self.session.scalars(statement)).all())

    async def mark_read(self, user_id: UUID, notification_id: int) -> Notification | None:
        notification = await self.session.scalar(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user_id
            )
        )
        if notification is None:
            return None
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = datetime.now(UTC)
        return notification

    async def stream(self, user_id: UUID, is_disconnected: Any) -> AsyncIterator[str]:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(NotificationPublisher.channel(user_id))
        try:
            for notification in await self.unread_for_user(user_id):
                yield self._sse(NotificationPublisher.payload(notification), notification.id)
            while not await is_disconnected():
                try:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                except RedisError:
                    logger.exception("Notification SSE subscription failed for user_id=%s", user_id)
                    return
                if message is None:
                    yield ": keep-alive\n\n"
                elif message["type"] == "message":
                    data = str(message["data"])
                    try:
                        notification_id = int(json.loads(data)["id"])
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                        logger.warning(
                            "Discarded malformed notification message for user_id=%s", user_id
                        )
                        continue
                    yield self._sse(data, notification_id)
        finally:
            await pubsub.unsubscribe(NotificationPublisher.channel(user_id))
            await pubsub.aclose()

    @staticmethod
    def _sse(data: str, notification_id: int | None = None) -> str:
        prefix = f"id: {notification_id}\n" if notification_id is not None else ""
        return f"{prefix}event: notification\ndata: {data}\n\n"
