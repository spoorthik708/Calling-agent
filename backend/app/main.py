from contextlib import asynccontextmanager
import time
import uuid
from typing import AsyncGenerator
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.endpoints.health import router as health_router
from app.api.v1.router import api_v1_router
from app.auth.context import clear_current_tenant_context, clear_current_user_context
from app.core.config import get_settings
from app.core.exceptions import YavuraBaseException, http_exception_from_domain
from app.core.logging import get_logger, setup_logging
from app.database.session import close_db_engine

settings = get_settings()
logger = get_logger("yavura.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context managing startup and graceful shutdown."""
    setup_logging(log_level=settings.LOG_LEVEL, log_format=settings.LOG_FORMAT)
    logger.info(
        f"Starting {settings.APP_NAME} v{settings.APP_VERSION} in {settings.ENVIRONMENT} mode"
    )
    yield
    logger.info(f"Shutting down {settings.APP_NAME}...")
    await close_db_engine()
    logger.info("Database connection pools closed.")


def create_application() -> FastAPI:
    """FastAPI application factory."""
    app = FastAPI(
        title="YAVURA Conversational AI SaaS Platform",
        description="Production-grade API backend for multi-tenant conversational AI agents.",
        version=settings.APP_VERSION,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Security Headers and Request Context Middleware
    @app.middleware("http")
    async def security_and_context_middleware(request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        start_time = time.perf_counter()

        try:
            response: Response = await call_next(request)
        finally:
            # Clear ContextVar state at the end of each HTTP request
            clear_current_tenant_context()
            clear_current_user_context()

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Inject Security Headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.2f}"

        # Structured request logging
        logger.info(
            f"{request.method} {request.url.path} returned {response.status_code} in {duration_ms:.2f}ms"
        )
        return response

    # Global Domain Exception Handler
    @app.exception_handler(YavuraBaseException)
    async def domain_exception_handler(request: Request, exc: YavuraBaseException) -> JSONResponse:
        http_exc = http_exception_from_domain(exc)
        return JSONResponse(
            status_code=http_exc.status_code,
            content=http_exc.detail,
        )

    # Global Unhandled Exception Handler
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(f"Unhandled error processing {request.method} {request.url.path}: {str(exc)}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An internal server error occurred.",
            },
        )

    # Mount minimal infrastructure health check directly at /health
    app.include_router(health_router, prefix="")

    # Mount API v1 router
    app.include_router(api_v1_router, prefix="/api/v1")

    return app


app = create_application()
