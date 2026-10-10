"""Slice F4: what suppliers report, kept apart from receipts and quality."""

import uuid
from datetime import datetime, timedelta

import pytest
from conftest import AddMember, csrf_headers, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select
from test_dependencies import flow, put  # noqa: F401  (fixtures)
from test_orders import API, act, data, post  # noqa: F401
from test_outsourcing import batch_body, planned, second_order  # noqa: F401

from app.main import app
from app.models import AuditEvent, SupplierUpdate

SENT = "2026-10-01"


def at(days_after_sent: int, hour: int = 11) -> str:
    sent = datetime.fromisoformat(f"{SENT}T{hour:02d}:00:00+05:30")
    return (sent + timedelta(days=days_after_sent)).isoformat()


@pytest.fixture
async def sent(client: AsyncClient, planned: dict[str, str]) -> dict:  # noqa: F811
    """The acceptance scenario: 200 castings for coating, serving two customer orders."""
    other = await second_order(client, planned)
    batch = await post(
        client,
        "/outsourcing/batches",
        batch_body(
            planned,
            allocations=[
                {"component_id": planned["component"], "quantity": "40"},
                {"component_id": other["lines"][0]["components"][0]["id"], "quantity": "60"},
            ],
        ),
    )
    batch = await act(
        client,
        f"/outsourcing/batches/{batch['id']}/send",
        {"version": batch["version"], "sent_date": SENT, "challan_reference": "DC-1182"},
    )
    return {"batch": batch, "ids": planned, "other_order": other["id"]}


def report(batch: dict, completed: str, rejected: str, pending: str, **extra) -> dict:
    body = {
        "version": batch["version"],
        "submission_key": str(uuid.uuid4()),
        "completed_qty": completed,
        "rejected_qty": rejected,
        "pending_qty": pending,
        "contact_method": "phone",
        "contact_name": "Murugan (supervisor)",
        "reported_at": at(3),
    }
    body.update(extra)
    return body


def updates_path(batch: dict) -> str:
    return f"/outsourcing/batches/{batch['id']}/updates"


async def test_supplier_report_is_labelled_and_kept_apart_from_receipts(
    client: AsyncClient, sent: dict
) -> None:
    batch = sent["batch"]
    result = await post(
        client,
        updates_path(batch),
        report(
            batch,
            "120",
            "20",
            "60",
            revised_return_date="2026-11-06",
            blocker="Coating line down for two days; 20 castings have porosity",
        ),
    )

    assert result["quantities"] == {
        "sent": "200",
        "reported_completed": "120",
        "reported_rejected": "20",
        "reported_pending": "60",
        "received": "0",
        "accepted": "0",
    }
    latest = result["latest_update"]
    assert (latest["source"], latest["confirmation_state"], latest["contact_method"]) == (
        "manufacturer_entered",
        "supplier_confirmation_pending",
        "phone",
    )
    assert latest["contact_name"] == "Murugan (supervisor)"
    assert latest["recorded_by_label"] == "A. Owner <owner@example.com>"
    assert result["expected_return_date"] == "2026-11-02"  # the plan is not overwritten
    assert latest["revised_return_date"] == "2026-11-06"

    # Both dependent orders see what the supplier said, with its date and source.
    for order_id in (sent["ids"]["order"], sent["other_order"]):
        order = (await client.get(f"{API}/orders/{order_id}")).json()
        [allocation] = order["lines"][0]["components"][0]["allocations"]
        assert (
            allocation["reported_completed"],
            allocation["reported_rejected"],
            allocation["reported_pending"],
        ) == ("120", "20", "60")
        assert allocation["revised_return_date"] == "2026-11-06"
        assert allocation["blocker"].startswith("Coating line down")
        # A promised date is never changed by a supplier report.
        assert order["lines"][0]["promise_history"][-1]["reason_code"] == "initial"

    listed = (await client.get(f"{API}/outsourcing/batches")).json()["items"][0]
    assert (listed["reported_completed"], listed["revised_return_date"]) == ("120", "2026-11-06")
    async with app.state.session_factory() as db:
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "outsourcing.supplier_update_recorded")
        )
    assert (event.details["source"], event.details["completed"], event.details["pending"]) == (
        "manufacturer_entered",
        "120",
        "60",
    )


@pytest.mark.parametrize(
    "quantities, extra, detail",
    [
        (("120", "20", "50"), {}, "add up to the 200 PCS sent; these add up to 190"),
        (("120.5", "20", "59.5"), {}, "decimal place"),
        (("120", "20", "60"), {"reported_at": at(3650)}, "future"),
        (("120", "20", "60"), {"reported_at": at(-1)}, "before the batch was sent"),
        (("120", "20", "60"), {"revised_return_date": "2026-09-30"}, "before the batch was sent"),
        (("120", "20", "60"), {"correction_reason": "Typo"}, "needs the update it corrects"),
    ],
)
async def test_reports_must_reconcile_to_the_batch(
    client: AsyncClient, sent: dict, quantities: tuple, extra: dict, detail: str
) -> None:
    response = await client.post(
        f"{API}{updates_path(sent['batch'])}",
        headers=csrf_headers(client),
        json=report(sent["batch"], *quantities, **extra),
    )
    assert response.status_code == 422
    assert detail in response.json()["detail"]


async def test_bad_values_are_rejected_by_validation(client: AsyncClient, sent: dict) -> None:
    for body in (
        report(sent["batch"], "-1", "20", "181"),
        report(sent["batch"], "120", "20", "60", contact_method="carrier pigeon"),
        report(sent["batch"], "120", "20", "60", reported_at="2026-10-08T11:00:00"),
    ):
        await post(client, updates_path(sent["batch"]), body, expect=422)


async def test_updates_only_for_batches_at_the_supplier(
    client: AsyncClient,
    planned: dict[str, str],  # noqa: F811
) -> None:
    batch = await post(client, "/outsourcing/batches", batch_body(planned))
    detail = await post(client, updates_path(batch), report(batch, "0", "0", "200"), expect=409)
    assert "at the supplier" in detail["detail"]


async def test_lower_figures_need_a_correction_with_a_reason(
    client: AsyncClient, sent: dict
) -> None:
    batch = sent["batch"]
    first = await post(client, updates_path(batch), report(batch, "120", "20", "60"))
    later = await post(
        client, updates_path(batch), report(first, "160", "20", "20", reported_at=at(5))
    )
    older = await post(
        client,
        updates_path(batch),
        report(later, "170", "20", "10", reported_at=at(4)),
        expect=422,
    )
    assert "newer supplier update" in older["detail"]
    lower = await post(
        client,
        updates_path(batch),
        report(later, "100", "20", "80", reported_at=at(6)),
        expect=422,
    )
    assert "earlier reported 160 PCS completed" in lower["detail"]

    first_id = first["latest_update"]["id"]
    latest_id = later["latest_update"]["id"]
    not_latest = await post(
        client,
        updates_path(batch),
        report(later, "100", "20", "80", corrects_id=first_id, correction_reason="Wrong count"),
        expect=409,
    )
    assert "latest" in not_latest["detail"]
    await post(
        client,
        updates_path(batch),
        report(later, "100", "20", "80", reported_at=at(5), corrects_id=latest_id),
        expect=422,
    )
    corrected = await post(
        client,
        updates_path(batch),
        report(
            later,
            "100",
            "20",
            "80",
            reported_at=at(5),
            corrects_id=latest_id,
            correction_reason="Supervisor read out yesterday's count; actual is 100",
        ),
    )

    assert corrected["quantities"]["reported_completed"] == "100"
    assert [(u["completed_qty"], u["superseded"]) for u in corrected["updates"]] == [
        ("100", False),
        ("160", True),
        ("120", False),
    ]
    assert corrected["latest_update"]["corrects_id"] == latest_id
    async with app.state.session_factory() as db:
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "outsourcing.supplier_update_corrected")
        )
        stored = (await db.scalars(select(SupplierUpdate))).all()
    assert event.details["correction_reason"].startswith("Supervisor read out")
    assert len(stored) == 3  # history is kept, never edited


async def test_a_repeated_submission_is_recorded_once(client: AsyncClient, sent: dict) -> None:
    batch = sent["batch"]
    body = report(batch, "120", "20", "60")
    first = await client.post(
        f"{API}{updates_path(batch)}", headers=csrf_headers(client), json=body
    )
    again = await client.post(
        f"{API}{updates_path(batch)}", headers=csrf_headers(client), json=body
    )

    assert (first.status_code, again.status_code) == (201, 200)
    assert len(again.json()["updates"]) == 1
    stale = await post(client, updates_path(batch), report(batch, "130", "20", "50"), expect=409)
    assert "changed by someone else" in stale["detail"]

    other = await post(client, "/outsourcing/batches", batch_body(sent["ids"], quantity="10"))
    other = await act(
        client,
        f"/outsourcing/batches/{other['id']}/send",
        {"version": other["version"], "sent_date": SENT},
    )
    reused = await post(
        client,
        updates_path(other),
        report(other, "10", "0", "0", submission_key=body["submission_key"]),
        expect=409,
    )
    assert "already used" in reused["detail"]


async def test_who_may_record_supplier_updates(
    client: AsyncClient,
    sent: dict,
    add_member: AddMember,
    workspace_records: dict[str, object],
) -> None:
    site = workspace_records["site_id"]
    hosur = await post(client, "/organization/sites", {"name": "Hosur Plant"})
    for email, role, sites in [
        ("coordinator@example.com", "production_coordinator", [site]),
        ("stores@example.com", "stores", [site]),
        ("hosur@example.com", "production_coordinator", [uuid.UUID(hosur["id"])]),
    ]:
        await add_member(email, role, site_ids=sites)
    await add_member(
        "rival@example.com",
        "owner",
        tenant_id=workspace_records["other_tenant_id"],
        home_site_id=workspace_records["other_site_id"],
    )
    batch = sent["batch"]

    await sign_in_as(client, "stores@example.com")
    await post(client, updates_path(batch), report(batch, "120", "20", "60"), expect=403)
    for email in ("hosur@example.com", "rival@example.com"):
        await sign_in_as(client, email)
        await post(client, updates_path(batch), report(batch, "120", "20", "60"), expect=404)

    await sign_in_as(client, "coordinator@example.com")
    recorded = await post(client, updates_path(batch), report(batch, "120", "20", "60"))
    assert recorded["latest_update"]["recorded_by_label"] == "coordinator <coordinator@example.com>"
