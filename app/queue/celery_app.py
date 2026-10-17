from celery import Celery

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "bfs_gym",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_default_queue=settings.celery_default_queue,
    imports=("app.queue.tasks",),
)
