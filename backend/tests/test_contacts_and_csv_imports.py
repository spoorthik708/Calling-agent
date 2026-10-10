"""Tests for Contacts Management, E.164 Phone Normalization, CSV Import Workflows,
Tenant Isolation, and Campaign Opt-Out Suppression.
"""

from datetime import datetime, timezone
import io
import uuid
import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent, AgentStatus
from app.contacts.models import Contact, ContactList, ContactListMembership
from app.contacts.utils import normalize_phone_number, parse_contacts_csv
from app.core.security import create_access_token, get_password_hash
from app.models import Tenant, User
from app.telephony.models import Campaign


def create_auth_headers(user: User) -> dict:
    token = create_access_token(subject=user.id, tenant_id=user.tenant_id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def contacts_setup(db_session: AsyncSession):
    tenant_a = Tenant(
        id=uuid.uuid4(),
        name="Company Alpha Contacts",
        slug=f"alpha-contacts-{uuid.uuid4().hex[:6]}",
        status="active",
        is_active=True,
    )
    tenant_b = Tenant(
        id=uuid.uuid4(),
        name="Company Beta Contacts",
        slug=f"beta-contacts-{uuid.uuid4().hex[:6]}",
        status="active",
        is_active=True,
    )
    db_session.add_all([tenant_a, tenant_b])

    user_a = User(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        email=f"usera_{uuid.uuid4().hex[:6]}@alpha.com",
        hashed_password=get_password_hash("password123"),
        role="owner",
        status="active",
        is_active=True,
    )
    user_b = User(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        email=f"userb_{uuid.uuid4().hex[:6]}@beta.com",
        hashed_password=get_password_hash("password123"),
        role="owner",
        status="active",
        is_active=True,
    )
    db_session.add_all([user_a, user_b])

    agent_a = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        name="Alpha Voice Agent",
        system_prompt="You are a phone agent.",
        status=AgentStatus.ACTIVE.value,
        llm_provider="mock",
        llm_model="mock-model",
    )
    db_session.add(agent_a)
    await db_session.commit()

    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "user_a": user_a,
        "user_b": user_b,
        "agent_a": agent_a,
    }


class TestPhoneNormalizationAndCSVUtils:
    def test_phone_normalization(self):
        assert normalize_phone_number("+15550199821") == "+15550199821"
        assert normalize_phone_number("+919876543210") == "+919876543210"
        assert normalize_phone_number("5550199821") == "+15550199821"
        assert normalize_phone_number("+1 (555) 019-9821") == "+15550199821"
        assert normalize_phone_number("abc") is None
        assert normalize_phone_number("123") is None
        assert normalize_phone_number("") is None
        assert normalize_phone_number(None) is None

    def test_csv_parser_valid_and_invalid_rows(self):
        csv_data = (
            "Name,Phone,Email,Tags\n"
            "Alice Smith,+15550101,alice@example.com,\"VIP, Lead\"\n"
            "Bob Jones,123,bob@example.com,Customer\n"
            "Charlie Brown,+15550101,charlie@example.com,New\n"  # Duplicate phone in file
            "David Miller,+15550102,david@example.com,Prospect\n"
        ).encode("utf-8")

        accepted, rejected, stats = parse_contacts_csv(csv_data)

        assert stats["total_rows"] == 4
        assert stats["accepted_count"] == 2
        assert stats["rejected_count"] == 2
        assert stats["duplicate_count"] == 1

        assert accepted[0]["name"] == "Alice Smith"
        assert accepted[0]["phone_number"] == "+15550101"
        assert accepted[0]["tags"] == ["VIP", "Lead"]

        assert accepted[1]["name"] == "David Miller"
        assert accepted[1]["phone_number"] == "+15550102"

        # Verify rejection reasons
        assert "Invalid" in rejected[0]["reason"]
        assert "Duplicate" in rejected[1]["reason"]


@pytest.mark.asyncio
class TestContactsAPIAndTenantIsolation:
    async def test_create_and_get_contact(
        self, async_client: AsyncClient, contacts_setup
    ):
        user_a = contacts_setup["user_a"]
        headers = create_auth_headers(user_a)
        payload = {
            "name": "Jane Doe",
            "phone_number": "+15559990001",
            "email": "jane@example.com",
            "tags": ["Lead", "HighPriority"],
        }

        res = await async_client.post("/api/v1/contacts", json=payload, headers=headers)
        assert res.status_code == status.HTTP_201_CREATED
        data = res.json()
        assert data["name"] == "Jane Doe"
        assert data["phone_number"] == "+15559990001"
        assert data["consent_status"] == "opted_in"
        contact_id = data["id"]

        # Get contact
        res_get = await async_client.get(f"/api/v1/contacts/{contact_id}", headers=headers)
        assert res_get.status_code == status.HTTP_200_OK
        assert res_get.json()["id"] == contact_id

    async def test_contact_tenant_isolation(
        self, async_client: AsyncClient, contacts_setup
    ):
        user_a = contacts_setup["user_a"]
        user_b = contacts_setup["user_b"]

        headers_a = create_auth_headers(user_a)
        headers_b = create_auth_headers(user_b)

        # Create contact in Tenant A
        res_a = await async_client.post(
            "/api/v1/contacts",
            json={"name": "Tenant A Contact", "phone_number": "+15551112222"},
            headers=headers_a,
        )
        assert res_a.status_code == status.HTTP_201_CREATED
        contact_a_id = res_a.json()["id"]

        # Tenant B tries to access Tenant A's contact -> 404
        res_b_get = await async_client.get(f"/api/v1/contacts/{contact_a_id}", headers=headers_b)
        assert res_b_get.status_code == status.HTTP_404_NOT_FOUND

        # Tenant B creates same phone number in Tenant B -> Should succeed (tenant scoped unique constraint)
        res_b_create = await async_client.post(
            "/api/v1/contacts",
            json={"name": "Tenant B Contact", "phone_number": "+15551112222"},
            headers=headers_b,
        )
        assert res_b_create.status_code == status.HTTP_201_CREATED

    async def test_duplicate_contact_conflict_in_same_tenant(
        self, async_client: AsyncClient, contacts_setup
    ):
        user_a = contacts_setup["user_a"]
        headers = create_auth_headers(user_a)
        payload = {"name": "User One", "phone_number": "+15553334444"}

        res1 = await async_client.post("/api/v1/contacts", json=payload, headers=headers)
        assert res1.status_code == status.HTTP_201_CREATED

        # Duplicate phone in same tenant -> HTTP 409
        res2 = await async_client.post("/api/v1/contacts", json=payload, headers=headers)
        assert res2.status_code == status.HTTP_409_CONFLICT

    async def test_opt_out_and_suppression(
        self, async_client: AsyncClient, contacts_setup
    ):
        user_a = contacts_setup["user_a"]
        headers = create_auth_headers(user_a)
        res_c = await async_client.post(
            "/api/v1/contacts",
            json={"name": "Opt Out Target", "phone_number": "+15557778888"},
            headers=headers,
        )
        contact_id = res_c.json()["id"]

        # Opt-Out
        res_opt = await async_client.post(f"/api/v1/contacts/{contact_id}/opt-out", headers=headers)
        assert res_opt.status_code == status.HTTP_200_OK
        data = res_opt.json()
        assert data["consent_status"] == "opted_out"
        assert data["opted_out_at"] is not None


@pytest.mark.asyncio
class TestCSVImportWorkflow:
    async def test_csv_import_preview_and_confirm(
        self, async_client: AsyncClient, contacts_setup
    ):
        user_a = contacts_setup["user_a"]
        headers = create_auth_headers(user_a)

        csv_content = (
            "Name,Phone,Email,Tags\n"
            "Import Contact 1,+15556667701,c1@example.com,Tag1\n"
            "Import Contact 2,+15556667702,c2@example.com,Tag2\n"
            "Invalid Contact,bad_phone,invalid@example.com,Tag3\n"
        ).encode("utf-8")

        # 1. Preview
        files = {"file": ("contacts.csv", csv_content, "text/csv")}
        res_prev = await async_client.post("/api/v1/contacts/import/preview", files=files, headers=headers)
        assert res_prev.status_code == status.HTTP_200_OK
        p_data = res_prev.json()
        assert p_data["total_rows"] == 3
        assert p_data["accepted_count"] == 2
        assert p_data["rejected_count"] == 1

        # 2. Confirm Import
        confirm_payload = {
            "list_name": "Autumn Leads List",
            "contacts": [
                {"name": "Import Contact 1", "phone_number": "+15556667701", "email": "c1@example.com", "tags": ["Tag1"]},
                {"name": "Import Contact 2", "phone_number": "+15556667702", "email": "c2@example.com", "tags": ["Tag2"]},
            ],
            "skip_existing": False,
        }

        res_conf = await async_client.post("/api/v1/contacts/import/confirm", json=confirm_payload, headers=headers)
        assert res_conf.status_code == status.HTTP_200_OK
        c_data = res_conf.json()
        assert c_data["created_count"] == 2
        assert c_data["list_id"] is not None


@pytest.mark.asyncio
class TestCampaignContactListIntegration:
    async def test_campaign_creation_with_contact_list_and_opt_out_suppression(
        self, async_client: AsyncClient, contacts_setup
    ):
        user_a = contacts_setup["user_a"]
        agent_a = contacts_setup["agent_a"]
        headers = create_auth_headers(user_a)

        # 1. Create 3 contacts: 2 opted_in, 1 opted_out
        res_c1 = await async_client.post("/api/v1/contacts", json={"name": "Opt In 1", "phone_number": "+15558880001"}, headers=headers)
        res_c2 = await async_client.post("/api/v1/contacts", json={"name": "Opt In 2", "phone_number": "+15558880002"}, headers=headers)
        res_c3 = await async_client.post("/api/v1/contacts", json={"name": "Opt Out Target", "phone_number": "+15558880003"}, headers=headers)

        c3_id = res_c3.json()["id"]
        await async_client.post(f"/api/v1/contacts/{c3_id}/opt-out", headers=headers)

        # 2. Import into Contact List
        res_conf = await async_client.post(
            "/api/v1/contacts/import/confirm",
            json={
                "list_name": "Campaign Target List",
                "contacts": [
                    {"name": "Opt In 1", "phone_number": "+15558880001"},
                    {"name": "Opt In 2", "phone_number": "+15558880002"},
                    {"name": "Opt Out Target", "phone_number": "+15558880003"},
                ],
            },
            headers=headers,
        )
        list_id = res_conf.json()["list_id"]

        # 3. Create Campaign using contact_list_id
        camp_payload = {
            "name": "Campaign From Contact List",
            "agent_id": str(agent_a.id),
            "from_phone": "+18005550199",
            "contact_list_id": list_id,
        }

        res_camp = await async_client.post("/api/v1/telephony/campaigns", json=camp_payload, headers=headers)
        assert res_camp.status_code == status.HTTP_201_CREATED
        camp_data = res_camp.json()

        # The campaign must automatically exclude the opted-out contact (+15558880003)!
        assert camp_data["total_count"] == 2
        assert "+15558880001" in camp_data["target_phones"]
        assert "+15558880002" in camp_data["target_phones"]
        assert "+15558880003" not in camp_data["target_phones"]
