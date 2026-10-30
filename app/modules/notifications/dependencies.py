from typing import Annotated

from fastapi import Depends

from app.core.dependencies import RedisClientDep
from app.modules.notifications.service import (
    NotificationFeed,
    NotificationObserver,
    NotificationPublisher,
)


def get_notification_observer() -> NotificationObserver:
    return NotificationObserver()


def get_notification_publisher(redis: RedisClientDep) -> NotificationPublisher:
    return NotificationPublisher(redis)


def get_notification_feed(redis: RedisClientDep) -> NotificationFeed:
    return NotificationFeed(redis)


NotificationObserverDep = Annotated[NotificationObserver, Depends(get_notification_observer)]
NotificationPublisherDep = Annotated[NotificationPublisher, Depends(get_notification_publisher)]
NotificationFeedDep = Annotated[NotificationFeed, Depends(get_notification_feed)]
