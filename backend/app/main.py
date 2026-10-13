"""FastAPI application entry point"""
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.config import settings
from app.models import (  # noqa: F401  — side-effect imports to register models with SQLAlchemy metadata
    Client,
    Account,
    Strategy,
    Sleeve,
    Trade,
    Position,
    SyncLog,
    SheetSyncConfig,
    BrokerageConnection,
    BrokerageAccount,
    CashActivity,
    User,
)
from app.api.deps import require_access
from app.api.routes import (
    auth,
    clients,
    accounts,
    strategies,
    sleeves,
    trades,
    admin,
    benchmarks,
    connections,
    performance,
    portal,
)

# Configure logging
_log_format = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_date_format = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(level=settings.log_level, format=_log_format, datefmt=_date_format)
for _uvicorn_logger in ("uvicorn", "uvicorn.access", "uvicorn.error"):
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(_log_format, datefmt=_date_format))
    logging.getLogger(_uvicorn_logger).handlers = [_handler]
logger = logging.getLogger(__name__)

# Schema is managed exclusively by Alembic (`alembic upgrade head`). The app no
# longer auto-creates tables — run migrations against Postgres before starting.


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle handler"""
    logger.info("Application starting...")
    if settings.scheduler_enabled:
        from app.services.scheduler import start_scheduler

        start_scheduler()
    yield
    if settings.scheduler_enabled:
        from app.services.scheduler import stop_scheduler

        stop_scheduler()
    logger.info("Application shutting down...")


app = FastAPI(
    title="Portfolio Management System",
    description="Backend API for portfolio management",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware — origins are configured via CORS_ALLOW_ORIGINS in .env
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers. Signing in and the SnapTrade webhook (which checks its own
# signature) are open; every data route goes through require_access.
_guarded = [Depends(require_access)]
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(connections.public_router, prefix="/api/v1", tags=["connections"])
# The portal answers only for its viewer (see deps.portal_viewer).
app.include_router(portal.router, prefix="/api/v1/portal", tags=["portal"])
app.include_router(
    auth.access_router, prefix="/api/v1", tags=["auth"], dependencies=_guarded
)
app.include_router(
    clients.router, prefix="/api/v1/clients", tags=["clients"], dependencies=_guarded
)
app.include_router(
    accounts.router, prefix="/api/v1/clients", tags=["accounts"], dependencies=_guarded
)
app.include_router(
    strategies.router,
    prefix="/api/v1/strategies",
    tags=["strategies"],
    dependencies=_guarded,
)
app.include_router(
    sleeves.router, prefix="/api/v1/clients", tags=["sleeves"], dependencies=_guarded
)
app.include_router(
    trades.router, prefix="/api/v1/trades", tags=["trades"], dependencies=_guarded
)
app.include_router(
    admin.router, prefix="/api/v1/admin", tags=["admin"], dependencies=_guarded
)
app.include_router(
    benchmarks.router,
    prefix="/api/v1/benchmarks",
    tags=["benchmarks"],
    dependencies=_guarded,
)
app.include_router(
    connections.router, prefix="/api/v1", tags=["connections"], dependencies=_guarded
)
app.include_router(
    performance.router, prefix="/api/v1", tags=["performance"], dependencies=_guarded
)


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy", "environment": settings.python_env}


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Portfolio Management System",
        "version": "1.0.0",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.python_env == "development",
    )
