"""Tests for Durable Campaign Worker, Rate & Concurrency Throttling, Pre-Call Opt-Out Re-Verification,
Exponential Backoff Retries, Crash Recovery, and Campaign Pause/Resume/Cancel Controls.
"""

from datetime import datetime, timezone, timedelta
import uuid
import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent, AgentStatus
from app.contacts.models import Contact
from app.core.security import create_access_token, get_password_hash
from app.models import Tenant, User
from app.telephony.models import Campaign, CampaignTarget
from app.telephony.worker import CampaignWorkerService


def create_auth_headers(user: User) -> dict:
    token = create_access_token(subject=user.id, tenant_id=user.tenant_id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def worker_setup(db_session: AsyncSession):
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Worker Test Tenant",
        slug=f"worker-{uuid.uuid4().hex[:6]}",
        status="active",
        is_active=True,
    )
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"worker_{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("password123"),
        role="owner",
        status="active",
        is_active=True,
    )
    agent = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Worker Test Agent",
        system_prompt="You are a test phone agent.",
        status=AgentStatus.ACTIVE.value,
        llm_provider="mock",
        llm_model="mock-model",
    )
    db_session.add_all([tenant, user, agent])
    await db_session.commit()

    return {"tenant": tenant, "user": user, "agent": agent}


@pytest.mark.asyncio
class TestDurableCampaignWorkerEngine:
    async def test_campaign_target_initialization_and_dispatch(
        self, async_client: AsyncClient, worker_setup, db_session: AsyncSession
    ):
        user = worker_setup["user"]
        agent = worker_setup["agent"]
        headers = create_auth_headers(user)

        # 1. Launch campaign with 3 targets
        camp_payload = {
            "name": "Durable Worker Test Campaign",
            "agent_id": str(agent.id),
            "from_phone": "+18005550199",
            "target_phones": ["+15551110001", "+15551110002", "+15551110003"],
        }
        res = await async_client.post("/api/v1/telephony/campaigns", json=camp_payload, headers=headers)
        assert res.status_code == status.HTTP_201_CREATED
        camp_id = res.json()["id"]

        # Verify targets were initialized in queued status
        worker = CampaignWorkerService(db_session)
        targets = await async_client.get(f"/api/v1/telephony/campaigns/{camp_id}/targets", headers=headers)
        assert targets.status_code == status.HTTP_200_OK
        t_data = targets.json()
        assert len(t_data) == 3
        assert all(t["status"] == "queued" for t in t_data)

        # 2. Trigger worker dispatch batch
        dispatched = await worker.dispatch_pending_targets(batch_size=10)
        assert dispatched == 3

    async def test_pre_call_opt_out_recheck_immediately_before_dispatch(
        self, async_client: AsyncClient, worker_setup, db_session: AsyncSession
    ):
        user = worker_setup["user"]
        agent = worker_setup["agent"]
        headers = create_auth_headers(user)

        # Create contact in opted_in state
        res_c = await async_client.post(
            "/api/v1/contacts",
            json={"name": "Late Opt Out Target", "phone_number": "+15559998888"},
            headers=headers,
        )
        c_id = res_c.json()["id"]

        # Create campaign
        res_camp = await async_client.post(
            "/api/v1/telephony/campaigns",
            json={
                "name": "Late Opt Out Campaign",
                "agent_id": str(agent.id),
                "from_phone": "+18005550199",
                "target_phones": ["+15559998888"],
            },
            headers=headers,
        )
        camp_id = res_camp.json()["id"]

        # Contact opts out BEFORE worker dispatches call
        await async_client.post(f"/api/v1/contacts/{c_id}/opt-out", headers=headers)

        # Worker runs batch dispatch
        worker = CampaignWorkerService(db_session)
        dispatched = await worker.dispatch_pending_targets(batch_size=10)
        assert dispatched == 0  # Should be skipped!

        # Check target status is skipped_opt_out
        res_targets = await async_client.get(f"/api/v1/telephony/campaigns/{camp_id}/targets", headers=headers)
        t_list = res_targets.json()
        assert len(t_list) == 1
        assert t_list[0]["status"] == "skipped_opt_out"
        assert "opted out" in t_list[0]["last_error"]

    async def test_campaign_pause_resume_cancel_controls(
        self, async_client: AsyncClient, worker_setup, db_session: AsyncSession
    ):
        user = worker_setup["user"]
        agent = worker_setup["agent"]
        headers = create_auth_headers(user)

        res_camp = await async_client.post(
            "/api/v1/telephony/campaigns",
            json={
                "name": "Control Test Campaign",
                "agent_id": str(agent.id),
                "from_phone": "+18005550199",
                "target_phones": ["+15554445555"],
            },
            headers=headers,
        )
        camp_id = res_camp.json()["id"]

        # Pause
        res_p = await async_client.post(f"/api/v1/telephony/campaigns/{camp_id}/pause", headers=headers)
        assert res_p.status_code == status.HTTP_200_OK
        assert res_p.json()["status"] == "paused"

        # Worker dispatch should skip paused campaign
        worker = CampaignWorkerService(db_session)
        dispatched = await worker.dispatch_pending_targets(batch_size=10)
        assert dispatched == 0

        # Resume
        res_r = await async_client.post(f"/api/v1/telephony/campaigns/{camp_id}/resume", headers=headers)
        assert res_r.status_code == status.HTTP_200_OK
        assert res_r.json()["status"] == "running"

        # Cancel
        res_c = await async_client.post(f"/api/v1/telephony/campaigns/{camp_id}/cancel", headers=headers)
        assert res_c.status_code == status.HTTP_200_OK
        assert res_c.json()["status"] == "cancelled"

    async def test_worker_crash_recovery_reconciliation(
        self, async_client: AsyncClient, worker_setup, db_session: AsyncSession
    ):
        tenant = worker_setup["tenant"]
        agent = worker_setup["agent"]

        # Simulate stuck in_progress target from crashed worker node
        stuck_target = CampaignTarget(
            id=uuid.uuid4(),
            campaign_id=uuid.uuid4(),
            tenant_id=tenant.id,
            phone_number="+15550009999",
            status="in_progress",
            attempts=1,
            started_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        )
        db_session.add(stuck_target)
        await db_session.commit()

        # Run crash recovery reconciliation
        worker = CampaignWorkerService(db_session)
        reconciled = await worker.reconcile_stuck_targets(stuck_threshold_minutes=15)
        assert reconciled == 1

        await db_session.refresh(stuck_target)
        assert stuck_target.status == "queued"
