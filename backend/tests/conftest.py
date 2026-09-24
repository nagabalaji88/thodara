from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.main import app
from app.models import Site, Tenant, TenantMembership, User


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app.state.session_factory = factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:5173") as test_client:
        yield test_client
    await engine.dispose()


@pytest_asyncio.fixture
async def workspace_records(client: AsyncClient) -> dict[str, object]:
    factory = app.state.session_factory
    async with factory() as db:
        tenant = Tenant(display_name="Acme Pumps")
        other_tenant = Tenant(display_name="Other Factory")
        db.add_all([tenant, other_tenant])
        await db.flush()
        site = Site(
            tenant_id=tenant.id,
            name="Main Plant",
            normalized_name="main plant",
            time_zone="Asia/Kolkata",
        )
        other_site = Site(
            tenant_id=other_tenant.id,
            name="Other Plant",
            normalized_name="other plant",
            time_zone="Asia/Kolkata",
        )
        user = User(
            email="owner@example.com",
            email_normalized="owner@example.com",
            display_name="A. Owner",
            password_hash=hash_password("a-secure-test-password"),
            email_verified_at=datetime.now(UTC),
        )
        db.add_all([site, other_site, user])
        await db.flush()
        db.add(
            TenantMembership(
                tenant_id=tenant.id, user_id=user.id, home_site_id=site.id, role="owner"
            )
        )
        await db.commit()
        return {
            "tenant_id": tenant.id,
            "other_tenant_id": other_tenant.id,
            "user_id": user.id,
        }
