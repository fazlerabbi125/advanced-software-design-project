from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.cache.redis import close_redis_client
from app.core.config import get_settings
from app.core.exceptions import install_exception_handlers
from app.domains.router import api_router

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_redis_client()


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
def health_check() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.enable_debug,
    )
