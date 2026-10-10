"""Migration safety tests.

Verifies that Alembic database migrations 0001 through 0010 apply cleanly in sequence,
that schema upgrade and downgrade operations run without errors, and that registered ORM models
match target metadata.
"""

import asyncio
import pytest
from alembic.config import Config
from alembic import command
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.models import Base

settings = get_settings()


@pytest.mark.asyncio
async def test_all_migrations_apply_cleanly(tmp_path):
    """Verifies that all migrations (0001 through 0010) upgrade to head on a clean database."""
    test_db_file = tmp_path / "test_migrations.db"
    db_url = f"sqlite+aiosqlite:///{test_db_file}"

    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", "migrations")
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    # Run upgrade head via Alembic in thread to avoid event loop conflicts
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

    # Verify key tables exist in upgraded database
    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    await engine.dispose()

    expected_tables = {
        "tenants",
        "users",
        "call_sessions",
        "telephony_campaigns",
        "telephony_campaign_targets",
        "contacts",
        "contact_lists",
        "contact_list_memberships",
    }
    for expected in expected_tables:
        assert expected in tables, f"Expected table {expected} missing after alembic upgrade head."


@pytest.mark.asyncio
async def test_migration_downgrade_and_reupgrade(tmp_path):
    """Verifies downgrade and re-upgrade capability for durable campaign worker migration 0010."""
    test_db_file = tmp_path / "test_downgrade.db"
    db_url = f"sqlite+aiosqlite:///{test_db_file}"

    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", "migrations")
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    # 1. Upgrade to head (0010)
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

    # 2. Downgrade 1 revision back to 0009
    await asyncio.to_thread(command.downgrade, alembic_cfg, "-1")

    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        tables_0009 = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    assert "telephony_campaign_targets" not in tables_0009

    # 3. Re-upgrade to 0010 (head)
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

    async with engine.connect() as conn:
        tables_0010 = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    await engine.dispose()

    assert "telephony_campaign_targets" in tables_0010


def test_orm_models_registered_in_base():
    """Ensures all domain models are properly bound to Base metadata."""
    metadata_tables = Base.metadata.tables.keys()

    required_tables = [
        "tenants",
        "users",
        "call_sessions",
        "telephony_campaigns",
        "telephony_campaign_targets",
        "contacts",
        "contact_lists",
        "contact_list_memberships",
    ]

    for table_name in required_tables:
        assert table_name in metadata_tables, f"Table {table_name} missing from Base metadata."
