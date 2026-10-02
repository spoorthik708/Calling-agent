import asyncio
import os
import uuid
from typing import AsyncGenerator
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set test environment before importing app modules
os.environ["ENVIRONMENT"] = "testing"
os.environ["DEBUG"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_yavura.db"
os.environ["SECRET_KEY"] = "test-secret-key-for-unit-testing-32-chars-min"
os.environ["DEFAULT_AI_PROVIDER"] = "mock"

from app.core.config import get_settings
from app.database.base import Base
from app.database.session import get_db
from app.main import app
from app.models import Tenant, User
from app.core.security import get_password_hash

# Test async engine using SQLite
test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    echo=False,
    future=True,
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def prepare_database():
    """Initializes clean database schema before each test."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yields a test database session."""
    async with TestingSessionLocal() as session:
        yield session


@pytest.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provides async HTTP client wired to FastAPI app with test db override."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
async def seed_tenants(db_session: AsyncSession):
    """Creates two isolated test tenants with corresponding users."""
    tenant_a = Tenant(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        name="Company Alpha",
        slug="company-alpha",
        is_active=True,
        tier="enterprise",
    )
    tenant_b = Tenant(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        name="Company Beta",
        slug="company-beta",
        is_active=True,
        tier="starter",
    )
    db_session.add_all([tenant_a, tenant_b])

    user_a = User(
        id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        tenant_id=tenant_a.id,
        email="admin@alpha.com",
        hashed_password=get_password_hash("password123"),
        role="admin",
        is_active=True,
    )
    user_b = User(
        id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        tenant_id=tenant_b.id,
        email="admin@beta.com",
        hashed_password=get_password_hash("password123"),
        role="admin",
        is_active=True,
    )
    db_session.add_all([user_a, user_b])
    await db_session.commit()

    return {"tenant_a": tenant_a, "tenant_b": tenant_b, "user_a": user_a, "user_b": user_b}
