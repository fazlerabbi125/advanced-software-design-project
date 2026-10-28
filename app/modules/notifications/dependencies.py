from typing import Annotated

from fastapi import Depends

from app.core.dependencies import DbSessionDep, RedisClientDep
from app.modules.notifications.service import (
    NotificationFeed,
    NotificationObserver,
    NotificationPublisher,
)


def get_notification_observer(session: DbSessionDep) -> NotificationObserver:
    return NotificationObserver(session)


def get_notification_publisher(redis: RedisClientDep) -> NotificationPublisher:
    return NotificationPublisher(redis)


def get_notification_feed(session: DbSessionDep, redis: RedisClientDep) -> NotificationFeed:
    return NotificationFeed(session, redis)


NotificationObserverDependency = Annotated[
    NotificationObserver, Depends(get_notification_observer)
]
NotificationPublisherDependency = Annotated[
    NotificationPublisher, Depends(get_notification_publisher)
]
NotificationFeedDependency = Annotated[NotificationFeed, Depends(get_notification_feed)]
