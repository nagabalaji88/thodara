import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.main import app
from app.models import Site, Tenant, TenantMembership, User

ORIGIN = "http://localhost:5173"
TEST_PASSWORD = "a-secure-test-password"
# Set to a disposable PostgreSQL database URL to run the suite against PostgreSQL.
# Every table in that database is dropped after each test.
POSTGRES_TEST_URL = os.environ.get("THODARA_TEST_DATABASE_URL")


def _create_test_engine():
    if POSTGRES_TEST_URL:
        return create_async_engine(POSTGRES_TEST_URL, poolclass=NullPool)
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

    return engine


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    engine = _create_test_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app.state.session_factory = factory
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url=ORIGIN) as test_client:
            yield test_client
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


def csrf_headers(client: AsyncClient) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": client.cookies["thodara_csrf"]}


async def sign_in_as(client: AsyncClient, email: str, password: str = TEST_PASSWORD) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200, response.text


AddMember = Callable[..., Awaitable[uuid.UUID]]


@pytest_asyncio.fixture
async def add_member(workspace_records: dict[str, object]) -> AddMember:
    async def _add(
        email: str,
        role: str,
        tenant_id: uuid.UUID | None = None,
        home_site_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        async with app.state.session_factory() as db:
            user = User(
                email=email,
                email_normalized=email.casefold(),
                display_name=email.split("@")[0],
                password_hash=hash_password(TEST_PASSWORD),
                email_verified_at=datetime.now(UTC),
            )
            db.add(user)
            await db.flush()
            db.add(
                TenantMembership(
                    tenant_id=tenant_id or workspace_records["tenant_id"],
                    user_id=user.id,
                    home_site_id=home_site_id,
                    role=role,
                )
            )
            await db.commit()
            return user.id

    return _add


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
            "site_id": site.id,
            "other_site_id": other_site.id,
            "user_id": user.id,
        }
