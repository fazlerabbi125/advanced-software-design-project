from asyncio import gather, wait_for
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.database import close_db_engine, is_db_available
from app.core.exceptions import install_exception_handlers
from app.core.redis import close_redis_client, is_cache_redis_available
from app.core.scheduler import create_scheduler
from app.shared.constants import HEALTH_CHECK_TIMEOUT_SECONDS

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler = create_scheduler() if settings.enable_booking_jobs else None
    if scheduler is not None:
        scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await close_redis_client()
        await close_db_engine()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.enable_debug else settings.cors_allow_origins,
    allow_credentials=not settings.enable_debug,
    allow_methods=["*"],
    allow_headers=["*"],
)
install_exception_handlers(app)
app.include_router(api_router)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Returns 200 when both PostgreSQL and Redis are reachable."""
    try:
        database_available, cache_redis_available = await wait_for(
            gather(
                is_db_available(),
                is_cache_redis_available(),
            ),
            timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        database_available = cache_redis_available = False
    if not all((database_available, cache_redis_available)):
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
