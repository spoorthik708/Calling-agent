from contextlib import asynccontextmanager
import time
from typing import AsyncGenerator, Dict, Optional
import uuid
from app.core.logging import get_logger

logger = get_logger("yavura.observability")


@asynccontextmanager
async def measure_latency(
    operation_name: str,
    tenant_id: Optional[uuid.UUID] = None,
    extra_labels: Optional[Dict[str, str]] = None,
) -> AsyncGenerator[None, None]:
    """Context manager measuring async operation latency in milliseconds."""
    start_time = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        log_payload = {
            "operation": operation_name,
            "duration_ms": round(duration_ms, 2),
            "tenant_id": str(tenant_id) if tenant_id else None,
            **(extra_labels or {}),
        }
        logger.info(f"Latency measurement: {log_payload}")
