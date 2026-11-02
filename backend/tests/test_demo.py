"""Slice D1: the fictional demo company and demo hosting rules (ADR-0016)."""

import pytest
from conftest import ORIGIN
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import DEV_TWO_STEP_KEY, Settings
from app.demo import DemoError, seed
from app.main import app, origin_allowed
from app.models import AuditEvent, OutsourcedBatch, Tenant, User

API = "/api/v1"


async def test_the_demo_tells_the_whole_story(client: AsyncClient) -> None:
    accounts = await seed(app, reset=False)
    assert [a[2] for a in accounts][:2] == ["owner", "administrator"]
    assert all(a[0].endswith("@srimant.example.com") for a in accounts)
    assert len({a[3] for a in accounts}) == len(accounts)  # a password each

    with pytest.raises(DemoError, match="--reset"):
        await seed(app, reset=False)  # never overwrites a database silently

    email, _, _, password = accounts[2]  # the production manager
    signed = await client.post(
        f"{API}/auth/login", json={"email": email, "password": password}, headers={"Origin": ORIGIN}
    )
    assert signed.status_code == 200 and signed.json()["two_step"]["stage"] == "full"
    orders = (await client.get(f"{API}/orders?limit=50")).json()["items"]
    assert len(orders) == 4
    risk = (await client.get(f"{API}/risk/board")).json()
    assert risk  # the board has something to show
    batches = (await client.get(f"{API}/outsourcing/batches?limit=50")).json()["items"]
    coating = next(b for b in batches if b["operation"] == "Powder coating")
    detail = (await client.get(f"{API}/outsourcing/batches/{coating['id']}")).json()
    q = detail["quantities"]
    assert (q["sent"], q["received"], q["accepted"], q["held"]) == ("200", "100", "95", "5")
    assert detail["latest_update"]["completed_qty"] == "120"

    async with app.state.session_factory() as db:
        events = list(await db.scalars(select(AuditEvent.action)))
        assert "outsourcing.batch_sent" in events  # created through the API, so audited

    again = await seed(app, reset=True)
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count(Tenant.id))) == 1
        assert await db.scalar(select(func.count(User.id))) == len(again)
        assert await db.scalar(select(func.count(OutsourcedBatch.id))) == 3
    assert {a[3] for a in again}.isdisjoint({a[3] for a in accounts})  # new passwords


def test_same_host_origin_is_accepted_and_others_are_not() -> None:
    assert origin_allowed(
        "https://calm-river-1234.trycloudflare.com", "calm-river-1234.trycloudflare.com"
    )
    assert not origin_allowed("https://evil.example", "calm-river-1234.trycloudflare.com")
    assert not origin_allowed("https://calm-river-1234.trycloudflare.com", None)
    assert not origin_allowed("null", "null")
    assert origin_allowed("http://localhost:5173", "anything")  # listed origin


async def test_meta_says_whether_this_is_a_demo(client: AsyncClient) -> None:
    response = await client.get(f"{API}/meta")
    assert response.json() == {"demo": False}


def test_a_demo_on_the_internet_needs_secure_cookies_and_its_own_key() -> None:
    with pytest.raises(ValueError, match="secure session cookies"):
        Settings(app_env="demo", two_step_key="A" * 43 + "=")
    with pytest.raises(ValueError, match="THODARA_TWO_STEP_KEY"):
        Settings(app_env="demo", session_cookie_secure=True, two_step_key=DEV_TWO_STEP_KEY)
    demo = Settings(
        app_env="demo",
        session_cookie_secure=True,
        two_step_key="A" * 43 + "=",
        allowed_hosts=["*.trycloudflare.com", "localhost"],
    )
    assert demo.app_env == "demo"


async def test_the_api_rejects_a_post_from_another_site(client: AsyncClient) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as other:
        response = await other.post(
            f"{API}/auth/login",
            json={"email": "x@example.com", "password": "nope"},
            headers={"Origin": "https://evil.example"},
        )
    assert response.status_code == 403


async def test_an_always_on_demo_keeps_the_passwords_handed_out(client: AsyncClient) -> None:
    from app.demo import read_kept_passwords

    first = await seed(app, reset=False)
    lines = [f"{email} {password}" for email, _, _, password in first]
    lines += ["stranger@example.com Demo-not-a-demo-person", "meena@srimant.example.com short"]
    kept = read_kept_passwords(lines)
    assert set(kept) == {a[0] for a in first}  # strangers and short passwords are ignored
    del kept["vijay@srimant.example.com"]
    again = await seed(app, reset=True, keep=kept)
    before = {a[0]: a[3] for a in first}
    after = {a[0]: a[3] for a in again}
    assert all(after[e] == before[e] for e in kept)
    assert after["vijay@srimant.example.com"] != before["vijay@srimant.example.com"]
