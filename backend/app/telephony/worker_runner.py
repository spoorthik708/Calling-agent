"""Daemon Runner for Durable Background Campaign Worker.

Provides continuous background polling, graceful shutdown signal handling,
worker crash recovery on startup, and error handling for production deployment.
Can be run via CLI: `python -m app.telephony.worker_runner`
"""

import asyncio
from datetime import datetime, timezone
import logging
import signal
import sys
from typing import Optional

from app.database.session import AsyncSessionLocal
from app.telephony.worker import CampaignWorkerService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker_runner")

_shutdown_requested = False


def _handle_shutdown_signal(signum, frame):
    global _shutdown_requested
    logger.info("Shutdown signal received (signal %s). Requesting worker graceful stop...", signum)
    _shutdown_requested = True


async def run_worker_loop(poll_interval: float = 2.0, stuck_reconcile_interval: float = 300.0) -> None:
    """
    Main asynchronous worker loop.
    Reconciles stuck targets on startup, then continuously dispatches pending targets.
    """
    global _shutdown_requested
    logger.info("Starting Durable Campaign Worker daemon loop...")

    # Set up signal handlers for graceful shutdown if supported on OS
    try:
        signal.signal(signal.SIGINT, _handle_shutdown_signal)
        signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    except (ValueError, AttributeError):
        pass  # Windows threading / signal restrictions fallback

    last_reconcile = 0.0

    # Startup crash recovery reconciliation
    try:
        async with AsyncSessionLocal() as db:
            worker = CampaignWorkerService(db)
            reconciled = await worker.reconcile_stuck_targets(stuck_threshold_minutes=15)
            if reconciled > 0:
                logger.info("Startup recovery: reconciled %d stuck campaign targets.", reconciled)
    except Exception as exc:
        logger.error("Error during startup target reconciliation: %s", exc, exc_info=True)

    while not _shutdown_requested:
        loop_start = asyncio.get_event_loop().time()

        # Periodically reconcile stuck targets
        if loop_start - last_reconcile >= stuck_reconcile_interval:
            try:
                async with AsyncSessionLocal() as db:
                    worker = CampaignWorkerService(db)
                    await worker.reconcile_stuck_targets(stuck_threshold_minutes=15)
                    last_reconcile = loop_start
            except Exception as exc:
                logger.error("Error during periodic stuck target reconciliation: %s", exc)

        # Batch dispatch pending targets
        try:
            async with AsyncSessionLocal() as db:
                worker = CampaignWorkerService(db)
                dispatched = await worker.dispatch_pending_targets(batch_size=10, default_max_concurrent=5)
                if dispatched > 0:
                    logger.info("Worker dispatched %d outbound campaign targets.", dispatched)
        except Exception as exc:
            logger.error("Error during campaign target dispatch iteration: %s", exc, exc_info=True)

        # Sleep before next poll iteration
        try:
            await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            break

    logger.info("Durable Campaign Worker daemon loop stopped gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(run_worker_loop())
    except KeyboardInterrupt:
        logger.info("Worker process interrupted by user. Exiting.")
        sys.exit(0)
