import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, get_password_hash
from app.models import Tenant, User
from app.tools.models import ToolDefinition, ToolType


@pytest.fixture
async def tool_test_setup(db_session: AsyncSession):
    tenant_a = Tenant(
        id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        name="Tenant Tool Alpha",
        slug="tenant-tool-alpha",
        status="active",
        is_active=True,
    )
    tenant_b = Tenant(
        id=uuid.UUID("22222222-3333-4444-5555-666666666666"),
        name="Tenant Tool Beta",
        slug="tenant-tool-beta",
        status="active",
        is_active=True,
    )
    db_session.add_all([tenant_a, tenant_b])

    owner_a = User(
        id=uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"),
        tenant_id=tenant_a.id,
        email="owner_a@alpha.com",
        hashed_password=get_password_hash("Password123!"),
        role="owner",
        status="active",
        is_active=True,
    )
    admin_a = User(
        id=uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002"),
        tenant_id=tenant_a.id,
        email="admin_a@alpha.com",
        hashed_password=get_password_hash("Password123!"),
        role="admin",
        status="active",
        is_active=True,
    )
    member_a = User(
        id=uuid.UUID("aaaaaaaa-0000-0000-0000-000000000003"),
        tenant_id=tenant_a.id,
        email="member_a@alpha.com",
        hashed_password=get_password_hash("Password123!"),
        role="member",
        status="active",
        is_active=True,
    )
    owner_b = User(
        id=uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001"),
        tenant_id=tenant_b.id,
        email="owner_b@beta.com",
        hashed_password=get_password_hash("Password123!"),
        role="owner",
        status="active",
        is_active=True,
    )
    db_session.add_all([owner_a, admin_a, member_a, owner_b])
    await db_session.commit()

    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "owner_a": owner_a,
        "admin_a": admin_a,
        "member_a": member_a,
        "owner_b": owner_b,
    }


@pytest.mark.asyncio
async def test_tool_definition_crud_lifecycle(async_client: AsyncClient, tool_test_setup):
    """Verifies complete CRUD operations for ToolDefinition."""
    owner_a = tool_test_setup["owner_a"]
    token = create_access_token(subject=owner_a.id, tenant_id=owner_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create Tool
    payload = {
        "name": "check_order_status",
        "display_name": "Check Order Status",
        "description": "Retrieves real-time fulfillment status of an order.",
        "tool_type": "internal",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
        "output_schema": {
            "type": "object",
            "properties": {"status": {"type": "string"}},
        },
        "configuration": {"endpoint_mode": "read_only"},
        "is_active": True,
    }

    create_resp = await async_client.post("/api/v1/tools", json=payload, headers=headers)
    assert create_resp.status_code == 201
    created_data = create_resp.json()
    assert created_data["name"] == "check_order_status"
    tool_id = created_data["id"]

    # 2. Get Tool by ID
    get_resp = await async_client.get(f"/api/v1/tools/{tool_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == tool_id

    # 3. List Tools
    list_resp = await async_client.get("/api/v1/tools", headers=headers)
    assert list_resp.status_code == 200
    tools = list_resp.json()
    assert len(tools) == 1
    assert tools[0]["name"] == "check_order_status"

    # 4. Update Tool
    update_payload = {
        "display_name": "Check Real-Time Order Status",
        "is_active": False,
    }
    update_resp = await async_client.patch(f"/api/v1/tools/{tool_id}", json=update_payload, headers=headers)
    assert update_resp.status_code == 200
    assert update_resp.json()["display_name"] == "Check Real-Time Order Status"
    assert update_resp.json()["is_active"] is False

    # 5. Delete Tool
    del_resp = await async_client.delete(f"/api/v1/tools/{tool_id}", headers=headers)
    assert del_resp.status_code == 204

    # Verify deleted
    get_deleted = await async_client.get(f"/api/v1/tools/{tool_id}", headers=headers)
    assert get_deleted.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_tool_name_rejected_within_tenant(async_client: AsyncClient, tool_test_setup):
    """Enforces uniqueness constraint on (tenant_id, name)."""
    owner_a = tool_test_setup["owner_a"]
    token = create_access_token(subject=owner_a.id, tenant_id=owner_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "name": "lookup_customer",
        "display_name": "Lookup Customer Profile",
        "description": "Customer profile lookup",
        "tool_type": "internal",
        "version": "1.0.0",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "configuration": {},
    }

    resp1 = await async_client.post("/api/v1/tools", json=payload, headers=headers)
    assert resp1.status_code == 201

    # Second creation with identical name in Tenant A must fail
    resp2 = await async_client.post("/api/v1/tools", json=payload, headers=headers)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_cross_tenant_tool_isolation(async_client: AsyncClient, tool_test_setup):
    """Guarantees Tenant A cannot view, modify, or delete Tenant B tools."""
    owner_a = tool_test_setup["owner_a"]
    owner_b = tool_test_setup["owner_b"]

    token_a = create_access_token(subject=owner_a.id, tenant_id=owner_a.tenant_id, role="owner")
    token_b = create_access_token(subject=owner_b.id, tenant_id=owner_b.tenant_id, role="owner")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Tenant B creates a tool
    b_payload = {
        "name": "tenant_b_tool",
        "display_name": "Tenant B Tool",
        "description": "Tenant B specific tool",
        "tool_type": "internal",
        "version": "1.0.0",
        "input_schema": {},
        "output_schema": {},
        "configuration": {},
    }
    resp_b = await async_client.post("/api/v1/tools", json=b_payload, headers=headers_b)
    assert resp_b.status_code == 201
    tool_b_id = resp_b.json()["id"]

    # Tenant A attempts to get Tenant B's tool
    get_cross = await async_client.get(f"/api/v1/tools/{tool_b_id}", headers=headers_a)
    assert get_cross.status_code == 404

    # Tenant A attempts to update Tenant B's tool
    patch_cross = await async_client.patch(
        f"/api/v1/tools/{tool_b_id}",
        json={"display_name": "Hacked Tool"},
        headers=headers_a,
    )
    assert patch_cross.status_code == 404

    # Tenant A attempts to delete Tenant B's tool
    del_cross = await async_client.delete(f"/api/v1/tools/{tool_b_id}", headers=headers_a)
    assert del_cross.status_code == 404

    # Tenant A lists tools -> Tenant B's tool must NOT appear
    list_a = await async_client.get("/api/v1/tools", headers=headers_a)
    assert list_a.status_code == 200
    assert len(list_a.json()) == 0


@pytest.mark.asyncio
async def test_tool_rbac_permissions(async_client: AsyncClient, tool_test_setup):
    """Enforces that OWNER and ADMIN can manage tools, while MEMBER is read-only."""
    admin_a = tool_test_setup["admin_a"]
    member_a = tool_test_setup["member_a"]

    token_admin = create_access_token(subject=admin_a.id, tenant_id=admin_a.tenant_id, role="admin")
    token_member = create_access_token(subject=member_a.id, tenant_id=member_a.tenant_id, role="member")
    headers_admin = {"Authorization": f"Bearer {token_admin}"}
    headers_member = {"Authorization": f"Bearer {token_member}"}

    payload = {
        "name": "admin_created_tool",
        "display_name": "Admin Tool",
        "description": "Created by Admin",
        "tool_type": "internal",
        "version": "1.0.0",
        "input_schema": {},
        "output_schema": {},
    }

    # 1. Admin can create tool
    admin_create = await async_client.post("/api/v1/tools", json=payload, headers=headers_admin)
    assert admin_create.status_code == 201
    tool_id = admin_create.json()["id"]

    # 2. Member can read tools
    member_read = await async_client.get(f"/api/v1/tools/{tool_id}", headers=headers_member)
    assert member_read.status_code == 200

    # 3. Member cannot create tools (403)
    member_create = await async_client.post(
        "/api/v1/tools",
        json={"name": "member_tool", "display_name": "Member Tool", "description": "desc"},
        headers=headers_member,
    )
    assert member_create.status_code == 403

    # 4. Member cannot update tools (403)
    member_update = await async_client.patch(
        f"/api/v1/tools/{tool_id}",
        json={"display_name": "Member Updated"},
        headers=headers_member,
    )
    assert member_update.status_code == 403

    # 5. Member cannot delete tools (403)
    member_delete = await async_client.delete(f"/api/v1/tools/{tool_id}", headers=headers_member)
    assert member_delete.status_code == 403


@pytest.mark.asyncio
async def test_tool_configuration_scrubs_plaintext_secrets(async_client: AsyncClient, tool_test_setup):
    """Ensures sensitive fields in tool configuration are scrubbed upon creation."""
    owner_a = tool_test_setup["owner_a"]
    token = create_access_token(subject=owner_a.id, tenant_id=owner_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "name": "sensitive_config_tool",
        "display_name": "Sensitive Config Tool",
        "description": "Attempts to send plaintext secrets in config",
        "tool_type": "internal",
        "version": "1.0.0",
        "input_schema": {},
        "output_schema": {},
        "configuration": {
            "api_key": "super-secret-key-12345",
            "db_password": "super-secret-password-xyz",
            "safe_mode": True,
        },
    }

    resp = await async_client.post("/api/v1/tools", json=payload, headers=headers)
    assert resp.status_code == 201
    config = resp.json()["configuration"]
    assert config["api_key"] == "[REDACTED]"
    assert config["db_password"] == "[REDACTED]"
    assert config["safe_mode"] is True
