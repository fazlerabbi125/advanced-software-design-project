from asyncio import gather, wait_for
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.database import close_engine, is_database_available
from app.core.exceptions import install_exception_handlers
from app.core.redis import close_redis_client, is_cache_redis_available, is_redis_url_available
from app.utils.constants import HEALTH_CHECK_TIMEOUT_SECONDS

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        yield
    finally:
        await close_redis_client()
        await close_engine()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
install_exception_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.enable_debug else settings.cors_allow_origins,
    allow_credentials=not settings.enable_debug,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    try:
        database_available, cache_redis_available, queue_redis_available = await wait_for(
            gather(
                is_database_available(),
                is_cache_redis_available(),
                is_redis_url_available(settings.celery_broker_url),
            ),
            timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        database_available = cache_redis_available = queue_redis_available = False
    if not all((database_available, cache_redis_available, queue_redis_available)):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Required dependency unavailable",
        )
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.enable_debug,
    )
