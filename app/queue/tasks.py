import logging

from app.queue.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="bfs_gym.send_notification")
def send_notification(recipient_id: int, message: str) -> dict[str, str | int]:
    logger.info("notification for member %s", recipient_id)
    return {"recipient_id": recipient_id, "message": message}
