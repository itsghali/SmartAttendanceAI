import logging
import re
import uuid

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.rate_limit import get_redis_client
from app.core.seed import seed_rbac
from app.main import app  # noqa: F401 pulls in app.routes -> app.models, populating Base.metadata
from app.models.role import Role
from app.models.user import User


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed_rbac(session)
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis_client] = lambda: fake_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await fake_redis.aclose()


@pytest.fixture
def unique_email():
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


def extract_otp(caplog: pytest.LogCaptureFixture) -> str:
    """Returns the most recently logged OTP code. Tests that trigger more than
    one OTP email before extracting (e.g. onboarding an employee, then
    registering a second user) would otherwise get a stale earlier code if
    this scanned oldest-first."""
    for record in reversed(caplog.records):
        match = re.search(r"verification code is (\d{6})", record.message)
        if match:
            return match.group(1)
    raise AssertionError("no OTP code found in captured logs")


async def register_and_verify(client, caplog, email: str, password: str = "Password123") -> None:
    # Self-registration auto-verifies now (no email step) — name/signature kept
    # as-is since every caller across the test suite passes `caplog` and awaits
    # this helper; `caplog` is simply unused here now.
    resp = await client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": "Test User"},
    )
    assert resp.status_code == 201, resp.text


async def promote_to_role(db_session, email: str, role_name: str) -> None:
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    role = (
        await db_session.execute(select(Role).where(Role.name == role_name))
    ).scalar_one()
    user.role_id = role.id
    await db_session.flush()


async def login(client, email: str, password: str = "Password123") -> str:
    resp = await client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]
