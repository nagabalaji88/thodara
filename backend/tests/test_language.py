"""Slice G4: each user's screen language is stored on the server (ADR-0012)."""

from conftest import csrf_headers, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import AuditEvent

API = "/api/v1"


async def test_a_user_chooses_tamil_and_it_follows_them(
    client: AsyncClient, workspace_records: dict
) -> None:
    anonymous = await client.put(f"{API}/auth/language", json={"language": "ta"})
    assert anonymous.status_code == 401

    await sign_in_as(client, "owner@example.com")
    session = (await client.get(f"{API}/auth/session")).json()
    assert session["user"]["language"] == "en"

    no_csrf = await client.put(f"{API}/auth/language", json={"language": "ta"})
    assert no_csrf.status_code == 403
    bad = await client.put(
        f"{API}/auth/language", headers=csrf_headers(client), json={"language": "hi"}
    )
    assert bad.status_code == 422

    for _ in range(2):  # choosing the same language twice records one change
        chosen = await client.put(
            f"{API}/auth/language", headers=csrf_headers(client), json={"language": "ta"}
        )
        assert chosen.status_code == 200
        assert chosen.json()["user"]["language"] == "ta"

    await sign_in_as(client, "owner@example.com")  # a new session keeps the choice
    assert (await client.get(f"{API}/auth/session")).json()["user"]["language"] == "ta"
    async with app.state.session_factory() as db:
        events = list(
            await db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.language_changed"))
        )
    assert [e.details for e in events] == [{"before": "en", "after": "ta"}]
