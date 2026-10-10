"""Durable Background Campaign Worker & Dispatch Engine.

Manages persistent campaign target state machines (queued, in_progress, completed,
failed, skipped_opt_out, cancelled), pre-call consent re-verification, rate limits,
tenant-scoped concurrency throttling, exponential backoff retries, and crash recovery.
"""

from datetime import datetime, timezone, timedelta
import logging
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contacts.models import Contact
from app.telephony.interfaces import OutboundCallRequest
from app.telephony.models import Campaign, CampaignTarget, CallSession
from app.telephony.service import TelephonyService

logger = logging.getLogger(__name__)


class CampaignWorkerService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.telephony_service = TelephonyService(db)

    async def initialize_campaign_targets(
        self,
        campaign_id: uuid.UUID,
        tenant_id: uuid.UUID,
        target_phones: List[str],
        max_retries: int = 3,
    ) -> List[CampaignTarget]:
        """Creates durable CampaignTarget records for each phone number in campaign."""
        targets = []
        for phone in target_phones:
            target = CampaignTarget(
                id=uuid.uuid4(),
                campaign_id=campaign_id,
                tenant_id=tenant_id,
                phone_number=phone,
                status="queued",
                attempts=0,
                max_retries=max_retries,
            )
            self.db.add(target)
            targets.append(target)

        await self.db.flush()
        return targets

    async def dispatch_pending_targets(
        self,
        batch_size: int = 10,
        default_max_concurrent: int = 5,
    ) -> int:
        """
        Processes pending campaign targets across active running campaigns.
        Enforces tenant concurrency limits, pre-call consent re-check,
        exponential backoff retries, and atomic target state transitions.
        """
        now = datetime.now(timezone.utc)

        # 1. Fetch running campaigns
        camp_stmt = select(Campaign).where(Campaign.status == "running")
        camps_res = await self.db.execute(camp_stmt)
        running_campaigns = list(camps_res.scalars().all())

        if not running_campaigns:
            return 0

        dispatched_count = 0

        for campaign in running_campaigns:
            # Check tenant concurrency limit
            max_concurrent = campaign.custom_parameters.get("max_concurrent_calls", default_max_concurrent)

            active_count_stmt = select(func.count(CampaignTarget.id)).where(
                CampaignTarget.tenant_id == campaign.tenant_id,
                CampaignTarget.status == "in_progress",
            )
            active_res = await self.db.execute(active_count_stmt)
            active_calls = active_res.scalar() or 0

            if active_calls >= max_concurrent:
                logger.info(
                    "Tenant %s reached max concurrency limit (%s/%s). Skipping batch dispatch.",
                    campaign.tenant_id,
                    active_calls,
                    max_concurrent,
                )
                continue

            available_slots = max_concurrent - active_calls
            fetch_limit = min(batch_size, available_slots)

            # Query queued targets ready for dispatch
            targets_stmt = (
                select(CampaignTarget)
                .where(
                    CampaignTarget.campaign_id == campaign.id,
                    CampaignTarget.status == "queued",
                    (CampaignTarget.next_retry_at == None) | (CampaignTarget.next_retry_at <= now),
                )
                .order_by(CampaignTarget.created_at.asc())
                .limit(fetch_limit)
            )
            targets_res = await self.db.execute(targets_stmt)
            pending_targets = list(targets_res.scalars().all())

            for target in pending_targets:
                # Pre-Call Consent Re-Verification
                contact_stmt = select(Contact).where(
                    Contact.tenant_id == campaign.tenant_id,
                    Contact.phone_number == target.phone_number,
                )
                contact = (await self.db.execute(contact_stmt)).scalar_one_or_none()

                if contact and contact.consent_status in ("opted_out", "suppressed"):
                    target.status = "skipped_opt_out"
                    target.last_error = "Contact opted out prior to call dispatch"
                    target.ended_at = now
                    logger.info("Target %s skipped due to opt-out consent status.", target.phone_number)
                    continue

                # Reserve target state atomically
                target.status = "in_progress"
                target.attempts += 1
                target.started_at = now
                target.updated_at = now
                await self.db.flush()

                # Dispatch Outbound Call via Telephony Layer
                try:
                    outbound_req = OutboundCallRequest(
                        tenant_id=campaign.tenant_id,
                        agent_id=campaign.agent_id,
                        from_phone=campaign.from_phone,
                        to_phone=target.phone_number,
                    )
                    call_session = await self.telephony_service.dispatch_outbound_call(outbound_req)
                    target.provider_call_id = call_session.provider_call_id
                    dispatched_count += 1
                except Exception as exc:
                    logger.warning("Error dispatching call for target %s: %s", target.phone_number, exc)
                    target.last_error = str(exc)

                    if target.attempts < target.max_retries:
                        # Exponential backoff: 5s, 10s, 20s...
                        backoff_sec = min(300, (2 ** target.attempts) * 5)
                        target.status = "queued"
                        target.next_retry_at = now + timedelta(seconds=backoff_sec)
                    else:
                        target.status = "failed"
                        target.ended_at = now

                await self.db.flush()

            # Recalculate and update Campaign Progress
            await self._update_campaign_progress(campaign.id)

        await self.db.commit()
        return dispatched_count

    async def update_target_from_call_session(
        self,
        provider_call_id: str,
        call_status: str,
        error_message: Optional[str] = None,
    ) -> Optional[CampaignTarget]:
        """Updates CampaignTarget state when a provider CallSession callback completes or fails."""
        stmt = select(CampaignTarget).where(CampaignTarget.provider_call_id == provider_call_id)
        res = await self.db.execute(stmt)
        target = res.scalar_one_or_none()

        if not target:
            return None

        now = datetime.now(timezone.utc)
        target.updated_at = now

        if call_status.lower() == "completed":
            target.status = "completed"
            target.ended_at = now
        elif call_status.lower() in ("failed", "busy", "no_answer"):
            target.last_error = error_message or f"Provider state: {call_status}"
            if target.attempts < target.max_retries:
                backoff_sec = min(300, (2 ** target.attempts) * 5)
                target.status = "queued"
                target.next_retry_at = now + timedelta(seconds=backoff_sec)
            else:
                target.status = "failed"
                target.ended_at = now

        await self.db.flush()
        await self._update_campaign_progress(target.campaign_id)
        await self.db.commit()
        return target

    async def pause_campaign(self, campaign_id: uuid.UUID, tenant_id: uuid.UUID) -> Campaign:
        campaign = await self.telephony_service.get_campaign(campaign_id, tenant_id)
        campaign.status = "paused"
        campaign.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        return campaign

    async def resume_campaign(self, campaign_id: uuid.UUID, tenant_id: uuid.UUID) -> Campaign:
        campaign = await self.telephony_service.get_campaign(campaign_id, tenant_id)
        campaign.status = "running"
        campaign.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        return campaign

    async def cancel_campaign(self, campaign_id: uuid.UUID, tenant_id: uuid.UUID) -> Campaign:
        campaign = await self.telephony_service.get_campaign(campaign_id, tenant_id)
        campaign.status = "cancelled"
        campaign.ended_at = datetime.now(timezone.utc)

        # Cancel queued / in_progress targets
        upd_stmt = (
            update(CampaignTarget)
            .where(
                CampaignTarget.campaign_id == campaign_id,
                CampaignTarget.status.in_(["queued", "in_progress"]),
            )
            .values(status="cancelled", ended_at=datetime.now(timezone.utc))
        )
        await self.db.execute(upd_stmt)
        await self.db.commit()
        return campaign

    async def retry_failed_targets(self, campaign_id: uuid.UUID, tenant_id: uuid.UUID) -> Campaign:
        campaign = await self.telephony_service.get_campaign(campaign_id, tenant_id)

        upd_stmt = (
            update(CampaignTarget)
            .where(
                CampaignTarget.campaign_id == campaign_id,
                CampaignTarget.status == "failed",
            )
            .values(status="queued", attempts=0, next_retry_at=None, last_error=None)
        )
        await self.db.execute(upd_stmt)

        campaign.status = "running"
        campaign.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self._update_campaign_progress(campaign_id)
        await self.db.commit()
        return campaign

    async def reconcile_stuck_targets(self, stuck_threshold_minutes: int = 15) -> int:
        """Reconciles targets left in_progress after a worker restart or network disconnection."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stuck_threshold_minutes)
        stmt = select(CampaignTarget).where(
            CampaignTarget.status == "in_progress",
            CampaignTarget.started_at <= cutoff,
        )
        res = await self.db.execute(stmt)
        stuck_targets = list(res.scalars().all())

        reconciled = 0
        now = datetime.now(timezone.utc)

        for target in stuck_targets:
            if target.provider_call_id:
                # Check linked CallSession
                cs_stmt = select(CallSession).where(CallSession.provider_call_id == target.provider_call_id)
                cs_res = await self.db.execute(cs_stmt)
                call = cs_res.scalar_one_or_none()

                if call and call.status == "completed":
                    target.status = "completed"
                    target.ended_at = now
                elif call and call.status in ("failed", "busy", "no_answer"):
                    target.status = "failed"
                    target.ended_at = now
                else:
                    # Re-queue stuck call
                    target.status = "queued"
                    target.next_retry_at = now + timedelta(seconds=10)
            else:
                target.status = "queued"
                target.next_retry_at = now + timedelta(seconds=10)

            reconciled += 1

        await self.db.commit()
        return reconciled

    async def _update_campaign_progress(self, campaign_id: uuid.UUID) -> None:
        """Calculates completed, failed, skipped target counts and sets Campaign status to completed when done."""
        camp_stmt = select(Campaign).where(Campaign.id == campaign_id)
        res = await self.db.execute(camp_stmt)
        campaign = res.scalar_one_or_none()
        if not campaign:
            return

        c_stmt = select(CampaignTarget.status, func.count(CampaignTarget.id)).where(
            CampaignTarget.campaign_id == campaign_id
        ).group_by(CampaignTarget.status)
        counts_res = await self.db.execute(c_stmt)
        counts_map = dict(counts_res.all())

        completed = counts_map.get("completed", 0)
        failed = counts_map.get("failed", 0)
        skipped = counts_map.get("skipped_opt_out", 0)
        cancelled = counts_map.get("cancelled", 0)
        total = sum(counts_map.values())

        campaign.completed_count = completed
        campaign.failed_count = failed
        campaign.skipped_count = skipped
        if total > 0:
            campaign.total_count = total

        # If all targets reached terminal state, complete campaign
        terminal_total = completed + failed + skipped + cancelled
        if terminal_total >= campaign.total_count and campaign.status in ("running", "scheduled"):
            campaign.status = "completed"
            campaign.ended_at = datetime.now(timezone.utc)
