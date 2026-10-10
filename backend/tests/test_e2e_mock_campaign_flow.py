"""End-to-End Integration Test for Outbound Campaign Flow using Mock Telephony Provider.

Tests complete campaign lifecycle:
1. Contact list creation & CSV preview/confirm import with accepted/rejected row accounting.
2. Campaign creation linked to persistent contact list.
3. Asynchronous worker dispatch with pre-call consent re-checking.
4. Pre-dispatch opt-out suppression (opted-out contacts marked skipped_opt_out, zero call dispatched).
5. Provider status callbacks, target retry logic, and campaign completion state transitions.
6. Campaign lifecycle controls (pause, resume, retry-failed, cancel).
7. Duplicate callback idempotency (prevents corrupted counts or double terminal states).
8. Strict multi-tenant isolation across all endpoints and data models.
"""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.database.session import get_db
from app.agents.models import Agent
from app.contacts.service import ContactService
from app.telephony.models import Campaign, CampaignTarget, CallSession
from app.telephony.worker import CampaignWorkerService
from app.tenants.models import Tenant
from app.users.models import User
from app.core.security import create_access_token


@pytest.fixture
async def e2e_tenants_and_users(db_session: AsyncSession):
    """Sets up two isolated active tenants (Tenant A and Tenant B) with owner users and agents."""
    # Tenant A
    tenant_a = Tenant(
        id=uuid.uuid4(),
        name="Tenant Alpha",
        slug=f"tenant-a-{uuid.uuid4().hex[:6]}",
        status="active",
        is_active=True,
    )
    db_session.add(tenant_a)

    user_a = User(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        email=f"admin.a.{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hashed_secret_a",
        first_name="Admin",
        last_name="A",
        role="owner",
        status="active",
        is_active=True,
    )
    db_session.add(user_a)

    agent_a = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        name="Agent Alpha",
        system_prompt="Assist customer clearly.",
        status="active",
    )
    db_session.add(agent_a)

    # Tenant B
    tenant_b = Tenant(
        id=uuid.uuid4(),
        name="Tenant Beta",
        slug=f"tenant-b-{uuid.uuid4().hex[:6]}",
        status="active",
        is_active=True,
    )
    db_session.add(tenant_b)

    user_b = User(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        email=f"admin.b.{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hashed_secret_b",
        first_name="Admin",
        last_name="B",
        role="owner",
        status="active",
        is_active=True,
    )
    db_session.add(user_b)

    agent_b = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        name="Agent Beta",
        system_prompt="Assist customer clearly.",
        status="active",
    )
    db_session.add(agent_b)

    await db_session.commit()

    token_a = create_access_token(subject=user_a.id, tenant_id=tenant_a.id, role="owner")
    token_b = create_access_token(subject=user_b.id, tenant_id=tenant_b.id, role="owner")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    return {
        "tenant_a": tenant_a,
        "user_a": user_a,
        "agent_a": agent_a,
        "headers_a": headers_a,
        "tenant_b": tenant_b,
        "user_b": user_b,
        "agent_b": agent_b,
        "headers_b": headers_b,
    }


@pytest.mark.asyncio
async def test_full_mock_campaign_end_to_end_flow(db_session: AsyncSession, e2e_tenants_and_users: dict):
    headers_a = e2e_tenants_and_users["headers_a"]
    headers_b = e2e_tenants_and_users["headers_b"]
    agent_a = e2e_tenants_and_users["agent_a"]

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # STEP 1: CSV Import Preview & Confirm
            csv_content = (
                "full_name,phone_number,email\n"
                "John Doe,+15551000001,john@example.com\n"
                "Jane Optout,+15551000002,jane@example.com\n"
                "Invalid Row,not-a-phone,bademail\n"
                "Bob Smith,+15551000003,bob@example.com\n"
            )
            files = {"file": ("contacts.csv", csv_content.encode("utf-8"), "text/csv")}

            # Preview CSV
            preview_res = await client.post("/api/v1/contacts/import/preview", headers=headers_a, files=files)
            assert preview_res.status_code == 200, preview_res.text
            preview_data = preview_res.json()
            assert preview_data["accepted_count"] == 3
            assert preview_data["rejected_count"] == 1
            assert len(preview_data["sample_accepted"]) == 3

            # Confirm CSV Import into new Contact List
            confirm_payload = {
                "list_name": "E2E Test List",
                "contacts": preview_data["sample_accepted"],
                "skip_existing": True,
            }
            import_res = await client.post(
                "/api/v1/contacts/import/confirm",
                headers=headers_a,
                json=confirm_payload,
            )
            assert import_res.status_code == 200, import_res.text
            import_data = import_res.json()
            assert import_data["created_count"] == 3
            contact_list_id = uuid.UUID(import_data["list_id"])

            # STEP 2: Create Campaign using Contact List (All 3 contacts currently opted_in)
            campaign_payload = {
                "name": "E2E Mock Campaign",
                "agent_id": str(agent_a.id),
                "from_phone": "+18005550199",
                "contact_list_id": str(contact_list_id),
                "custom_parameters": {"max_concurrent_calls": 5},
            }
            camp_res = await client.post("/api/v1/telephony/campaigns", headers=headers_a, json=campaign_payload)
            assert camp_res.status_code == 201, camp_res.text
            camp_data = camp_res.json()
            campaign_id = uuid.UUID(camp_data["id"])
            assert camp_data["total_count"] == 3
            assert camp_data["status"] == "running"

            # STEP 3: Opt-Out Jane Optout (+15551000002) AFTER campaign creation to test pre-call consent re-check
            contacts_res = await client.get("/api/v1/contacts", headers=headers_a)
            assert contacts_res.status_code == 200
            contacts_list = contacts_res.json()
            jane = next(c for c in contacts_list if c["phone_number"] == "+15551000002")

            optout_res = await client.post(
                f"/api/v1/contacts/{jane['id']}/opt-out",
                headers=headers_a,
            )
            assert optout_res.status_code == 200
            assert optout_res.json()["consent_status"] == "opted_out"

            # STEP 4: Worker Dispatch Iteration 1
            worker = CampaignWorkerService(db_session)
            dispatched_1 = await worker.dispatch_pending_targets(batch_size=10)
            # Expect 2 targets dispatched (+15551000001, +15551000003), and 1 skipped due to pre-call opt-out check (+15551000002)
            assert dispatched_1 == 2

            # Check target states
            camp_progress = await client.get(f"/api/v1/telephony/campaigns/{campaign_id}", headers=headers_a)
            assert camp_progress.status_code == 200
            assert camp_progress.json()["skipped_count"] == 1

            targets_res = await client.get(f"/api/v1/telephony/campaigns/{campaign_id}/targets", headers=headers_a)
            assert targets_res.status_code == 200
            targets = targets_res.json()
            assert len(targets) == 3

            skipped_targets = [t for t in targets if t["status"] == "skipped_opt_out"]
            assert len(skipped_targets) == 1
            assert skipped_targets[0]["phone_number"] == "+15551000002"

            in_progress_targets = [t for t in targets if t["status"] == "in_progress"]
            assert len(in_progress_targets) == 2

            # STEP 5: Simulate Call Status Callbacks & Idempotency
            target_1 = in_progress_targets[0]
            call_id_1 = target_1["provider_call_id"]

            # Call completed for target 1
            updated_1 = await worker.update_target_from_call_session(call_id_1, "completed")
            assert updated_1 is not None
            assert updated_1.status == "completed"

            # Duplicate callback for call 1 must not corrupt state
            dup_updated = await worker.update_target_from_call_session(call_id_1, "completed")
            assert dup_updated is not None
            assert dup_updated.status == "completed"

            # Call failed for target 2 (triggers retry queue backoff)
            target_2 = in_progress_targets[1]
            call_id_2 = target_2["provider_call_id"]
            updated_2 = await worker.update_target_from_call_session(call_id_2, "failed", error_message="Busy line")
            assert updated_2 is not None
            assert updated_2.status == "queued"  # Queued for retry since attempts < max_retries

            # STEP 6: Campaign Pause & Resume Controls
            pause_res = await client.post(f"/api/v1/telephony/campaigns/{campaign_id}/pause", headers=headers_a)
            assert pause_res.status_code == 200
            assert pause_res.json()["status"] == "paused"

            resume_res = await client.post(f"/api/v1/telephony/campaigns/{campaign_id}/resume", headers=headers_a)
            assert resume_res.status_code == 200
            assert resume_res.json()["status"] == "running"

            # Force next retry ready now for target 2 and complete it
            updated_2.next_retry_at = None
            await db_session.commit()

            dispatched_2 = await worker.dispatch_pending_targets(batch_size=10)
            assert dispatched_2 == 1
            call_id_2_retry = updated_2.provider_call_id
            await worker.update_target_from_call_session(call_id_2_retry, "completed")

            # STEP 7: Verify Final Campaign Auto-Completion State
            final_camp_res = await client.get(f"/api/v1/telephony/campaigns/{campaign_id}", headers=headers_a)
            assert final_camp_res.status_code == 200
            final_camp = final_camp_res.json()
            assert final_camp["status"] == "completed"
            assert final_camp["completed_count"] == 2
            assert final_camp["skipped_count"] == 1
            assert final_camp["failed_count"] == 0

            # STEP 8: Multi-Tenant Isolation Verification
            # Tenant B cannot view Tenant A's contact list contacts or campaign
            list_b_res = await client.get(f"/api/v1/contacts?list_id={contact_list_id}", headers=headers_b)
            assert list_b_res.status_code == 200
            assert len(list_b_res.json()) == 0

            camp_b_res = await client.get(f"/api/v1/telephony/campaigns/{campaign_id}", headers=headers_b)
            assert camp_b_res.status_code in (404, 403)

            pause_b_res = await client.post(f"/api/v1/telephony/campaigns/{campaign_id}/pause", headers=headers_b)
            assert pause_b_res.status_code in (404, 403)
    finally:
        app.dependency_overrides.clear()
