import asyncio

import pytest
from conftest import POSTGRES_TEST_URL, AddMember, csrf_headers, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import AuditEvent, Site
from app.services.numbering import allocate_number

ORG = "/api/v1/organization"
MON_SAT = {"working_days": [1, 2, 3, 4, 5, 6], "shift_start": "09:00", "shift_end": "18:00"}


@pytest.fixture
async def owner(client: AsyncClient, workspace_records: dict[str, object]) -> AsyncClient:
    await sign_in_as(client, "owner@example.com")
    return client


def cal_url(records: dict[str, object], site_key: str = "site_id") -> str:
    return f"{ORG}/sites/{records[site_key]}/calendar"


async def actions() -> list[str]:
    async with app.state.session_factory() as db:
        return list((await db.scalars(select(AuditEvent.action))).all())


# Calendars


async def test_calendar_starts_unconfigured(
    owner: AsyncClient, workspace_records: dict[str, object]
) -> None:
    body = (await owner.get(cal_url(workspace_records))).json()
    assert body["configured"] is False
    assert body["working_days"] is None
    assert body["upcoming"] == []


async def test_save_calendar_and_see_upcoming_days(
    owner: AsyncClient, workspace_records: dict[str, object]
) -> None:
    saved = await owner.put(cal_url(workspace_records), headers=csrf_headers(owner), json=MON_SAT)

    assert saved.status_code == 200
    body = saved.json()
    assert (body["configured"], body["minutes_per_day"], body["version"]) == (True, 540, 1)
    assert len(body["upcoming"]) == 14
    offs = [d for d in body["upcoming"] if not d["working"]]
    assert len(offs) == 2 and all(d["reason"] == "Weekly off" for d in offs)
    assert "organization.calendar.saved" in await actions()


async def test_holidays_show_up_and_can_be_removed(
    owner: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await owner.put(cal_url(workspace_records), headers=csrf_headers(owner), json=MON_SAT)
    upcoming = (await owner.get(cal_url(workspace_records))).json()["upcoming"]
    working_day = next(d["day"] for d in upcoming if d["working"])
    base = f"{ORG}/sites/{workspace_records['site_id']}/holidays"

    added = await owner.post(
        base, headers=csrf_headers(owner), json={"holiday_date": working_day, "name": "Ayudha Puja"}
    )
    duplicate = await owner.post(
        base, headers=csrf_headers(owner), json={"holiday_date": working_day, "name": "Again"}
    )
    after_add = (await owner.get(cal_url(workspace_records))).json()

    assert added.status_code == 201
    assert duplicate.status_code == 409
    day = next(d for d in after_add["upcoming"] if d["day"] == working_day)
    assert (day["working"], day["reason"]) == (False, "Ayudha Puja")

    removed = await owner.delete(f"{base}/{added.json()['id']}", headers=csrf_headers(owner))
    assert removed.status_code == 204
    assert (await owner.get(cal_url(workspace_records))).json()["holidays"] == []
    assert {"organization.holiday.added", "organization.holiday.removed"} <= set(await actions())


async def test_calendar_edits_need_the_current_version(
    owner: AsyncClient, workspace_records: dict[str, object]
) -> None:
    url = cal_url(workspace_records)
    first_with_version = await owner.put(
        url, headers=csrf_headers(owner), json={**MON_SAT, "version": 1}
    )
    await owner.put(url, headers=csrf_headers(owner), json=MON_SAT)
    missing_version = await owner.put(url, headers=csrf_headers(owner), json=MON_SAT)
    ok = await owner.put(
        url,
        headers=csrf_headers(owner),
        json={**MON_SAT, "working_days": [1, 2, 3, 4, 5], "version": 1},
    )
    stale = await owner.put(url, headers=csrf_headers(owner), json={**MON_SAT, "version": 1})

    assert first_with_version.status_code == 409
    assert missing_version.status_code == 409
    assert ok.status_code == 200 and ok.json()["working_days"] == [1, 2, 3, 4, 5]
    assert stale.status_code == 409
    async with app.state.session_factory() as db:
        events = (
            await db.scalars(
                select(AuditEvent).where(AuditEvent.action == "organization.calendar.saved")
            )
        ).all()
    assert events[-1].details["before"]["working_days"] == "123456"
    assert events[-1].details["after"]["working_days"] == "12345"


@pytest.mark.parametrize(
    "body",
    [
        {**MON_SAT, "shift_start": "18:00", "shift_end": "09:00"},
        {**MON_SAT, "working_days": []},
        {**MON_SAT, "working_days": [1, 8]},
        {**MON_SAT, "working_days": [1, 1]},
        {**MON_SAT, "shift_start": "09:00:30"},
    ],
)
async def test_invalid_calendars_are_rejected(
    owner: AsyncClient, workspace_records: dict[str, object], body: dict
) -> None:
    response = await owner.put(cal_url(workspace_records), headers=csrf_headers(owner), json=body)
    assert response.status_code == 422


async def test_calendar_permissions_and_scope(
    client: AsyncClient, workspace_records: dict[str, object], add_member: AddMember
) -> None:
    await add_member("stores@example.com", "stores", site_ids=[workspace_records["site_id"]])
    await sign_in_as(client, "stores@example.com")

    read = await client.get(cal_url(workspace_records))
    write = await client.put(cal_url(workspace_records), headers=csrf_headers(client), json=MON_SAT)
    foreign = await client.get(cal_url(workspace_records, "other_site_id"))

    assert read.status_code == 200
    assert write.status_code == 403
    assert foreign.status_code == 404


async def test_site_outside_users_scope_is_hidden(
    client: AsyncClient, workspace_records: dict[str, object], add_member: AddMember
) -> None:
    async with app.state.session_factory() as db:
        hosur = Site(
            tenant_id=workspace_records["tenant_id"], name="Hosur", normalized_name="hosur"
        )
        db.add(hosur)
        await db.commit()
        hosur_id = hosur.id
    await add_member("stores@example.com", "stores", site_ids=[workspace_records["site_id"]])
    await sign_in_as(client, "stores@example.com")

    assert (await client.get(f"{ORG}/sites/{hosur_id}/calendar")).status_code == 404


# Numbering


async def test_default_sequences_are_created_on_first_view(owner: AsyncClient) -> None:
    rows = (await owner.get(f"{ORG}/numbering")).json()
    assert [(r["document_type"], r["preview"]) for r in rows] == [
        ("sales_order", "SO-00001"),
        ("outsourced_batch", "OB-00001"),
        ("dispatch", "DN-00001"),
    ]


async def test_allocation_is_consecutive_and_rollback_returns_the_number(
    workspace_records: dict[str, object],
) -> None:
    tenant_id = workspace_records["tenant_id"]
    async with app.state.session_factory() as db:
        first = await allocate_number(db, tenant_id, "sales_order")
        await db.commit()
    async with app.state.session_factory() as db:
        abandoned = await allocate_number(db, tenant_id, "sales_order")
        await db.rollback()
    async with app.state.session_factory() as db:
        second = await allocate_number(db, tenant_id, "sales_order")
        batch = await allocate_number(db, tenant_id, "outsourced_batch")
        await db.commit()
    async with app.state.session_factory() as db:
        other = await allocate_number(db, workspace_records["other_tenant_id"], "sales_order")
        await db.commit()

    assert (first, abandoned, second) == ("SO-00001", "SO-00002", "SO-00002")
    assert batch == "OB-00001"
    assert other == "SO-00001"


async def test_update_numbering_rules(
    owner: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await owner.get(f"{ORG}/numbering")
    url = f"{ORG}/numbering/sales_order"
    changed = await owner.put(
        url,
        headers=csrf_headers(owner),
        json={"prefix": "so/26-", "padding": 4, "next_number": 120, "version": 1},
    )
    backwards = await owner.put(
        url,
        headers=csrf_headers(owner),
        json={"prefix": "SO-", "padding": 4, "next_number": 5, "version": 2},
    )
    stale = await owner.put(
        url,
        headers=csrf_headers(owner),
        json={"prefix": "SO-", "padding": 4, "next_number": 500, "version": 1},
    )
    bad_prefix = await owner.put(
        url,
        headers=csrf_headers(owner),
        json={"prefix": "SO 26", "padding": 4, "next_number": 500, "version": 2},
    )
    unknown = await owner.put(
        f"{ORG}/numbering/invoice",
        headers=csrf_headers(owner),
        json={"prefix": "IN-", "padding": 4, "next_number": 1, "version": 1},
    )

    assert changed.status_code == 200 and changed.json()["preview"] == "SO/26-0120"
    assert backwards.status_code == 409
    assert stale.status_code == 409
    assert bad_prefix.status_code == 422
    assert unknown.status_code == 404
    async with app.state.session_factory() as db:
        number = await allocate_number(db, workspace_records["tenant_id"], "sales_order")
    assert number == "SO/26-0120"
    assert "organization.numbering.updated" in await actions()


async def test_only_configurers_can_change_numbering(
    client: AsyncClient, workspace_records: dict[str, object], add_member: AddMember
) -> None:
    await add_member("buyer@example.com", "procurement", site_scope="all")
    await sign_in_as(client, "buyer@example.com")
    assert (await client.get(f"{ORG}/numbering")).status_code == 200
    response = await client.put(
        f"{ORG}/numbering/sales_order",
        headers=csrf_headers(client),
        json={"prefix": "X-", "padding": 4, "next_number": 9, "version": 1},
    )
    assert response.status_code == 403


@pytest.mark.skipif(not POSTGRES_TEST_URL, reason="Row locking needs PostgreSQL")
async def test_concurrent_allocations_never_duplicate(
    workspace_records: dict[str, object],
) -> None:
    tenant_id = workspace_records["tenant_id"]

    async def one() -> str:
        async with app.state.session_factory() as db:
            number = await allocate_number(db, tenant_id, "outsourced_batch")
            await asyncio.sleep(0.01)
            await db.commit()
            return number

    numbers = await asyncio.gather(*(one() for _ in range(20)))
    assert sorted(numbers) == [f"OB-{n:05d}" for n in range(1, 21)]
