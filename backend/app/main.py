"""FastAPI application entry point"""
from fastapi import FastAPI
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
)
from app.api.routes import (
    clients,
    accounts,
    strategies,
    sleeves,
    trades,
    admin,
    benchmarks,
    connections,
    performance,
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

# Include routers
app.include_router(clients.router, prefix="/api/v1/clients", tags=["clients"])
app.include_router(accounts.router, prefix="/api/v1/clients", tags=["accounts"])
app.include_router(strategies.router, prefix="/api/v1/strategies", tags=["strategies"])
app.include_router(sleeves.router, prefix="/api/v1/clients", tags=["sleeves"])
app.include_router(trades.router, prefix="/api/v1/trades", tags=["trades"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(benchmarks.router, prefix="/api/v1/benchmarks", tags=["benchmarks"])
app.include_router(connections.router, prefix="/api/v1", tags=["connections"])
app.include_router(performance.router, prefix="/api/v1", tags=["performance"])


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
