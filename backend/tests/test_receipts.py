"""Slice F5: what came back from the supplier, and what quality accepted."""

# ruff: noqa: F811  (pytest fixtures are imported and then used as parameters)

import uuid

import pytest
from conftest import AddMember, csrf_headers, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select
from test_dependencies import flow, put  # noqa: F401  (fixtures)
from test_orders import API, act, data, post  # noqa: F401
from test_outsourcing import batch_body, planned  # noqa: F401
from test_supplier_updates import report, sent  # noqa: F401

from app.main import app
from app.models import AuditEvent, BatchReceipt


def receipt_body(batch: dict, quantity: str, **extra) -> dict:
    body = {
        "version": batch["version"],
        "submission_key": str(uuid.uuid4()),
        "received_qty": quantity,
        "receipt_date": "2026-10-08",
        "document_reference": "IN-4471",
    }
    body.update(extra)
    return body


def inspection_body(receipt: dict, accepted: str, rejected="0", held="0", rework="0", **extra):
    body = {
        "version": receipt["version"],
        "accepted_qty": accepted,
        "rejected_qty": rejected,
        "held_qty": held,
        "rework_qty": rework,
    }
    body.update(extra)
    return body


def receipts_path(batch: dict) -> str:
    return f"/outsourcing/batches/{batch['id']}/receipts"


@pytest.fixture
async def received(client: AsyncClient, sent: dict) -> dict:
    """The supplier reported 120/20/60; stores then received the 120."""
    batch = sent["batch"]
    batch = await post(
        client, f"/outsourcing/batches/{batch['id']}/updates", report(batch, "120", "20", "60")
    )
    batch = await post(client, receipts_path(batch), receipt_body(batch, "120"))
    return {**sent, "batch": batch, "receipt": batch["receipts"][0]}


async def test_only_inspected_and_accepted_material_becomes_usable(
    client: AsyncClient, received: dict
) -> None:
    batch, receipt = received["batch"], received["receipt"]
    assert (receipt["status"], receipt["received_qty"]) == ("awaiting_inspection", "120")
    q = batch["quantities"]
    assert (q["received"], q["awaiting_inspection"], q["accepted"], q["still_at_supplier"]) == (
        "120",
        "120",
        "0",
        "80",
    )
    assert [m["kind"] for m in batch["movements"]] == ["sent_to_supplier", "received_from_supplier"]
    assert q["sent"] == "200"  # receipts never count as sent

    inspected = await act(
        client,
        f"{receipts_path(batch)}/{receipt['id']}/inspection",
        inspection_body(receipt, "110", held="10", note="10 need a porosity check"),
    )
    q = inspected["quantities"]
    assert (q["awaiting_inspection"], q["accepted"], q["held"]) == ("0", "110", "10")

    receipt = inspected["receipts"][0]
    released = await act(
        client,
        f"{receipts_path(batch)}/{receipt['id']}/release",
        {
            "version": receipt["version"],
            "accepted_qty": "6",
            "rejected_qty": "0",
            "rework_qty": "4",
            "reason": "Pressure test passed on 6; 4 need re-coating",
        },
    )
    q = released["quantities"]
    assert (q["accepted"], q["held"], q["rework"], q["rejected_at_inspection"]) == (
        "116",
        "0",
        "4",
        "0",
    )
    decisions = released["receipts"][0]["decisions"]
    assert [(d["kind"], d["accepted_qty"], d["held_qty"]) for d in decisions] == [
        ("inspection", "110", "10"),
        ("hold_release", "6", "0"),
    ]
    # Supplier-reported figures stay as reported, next to what was received and accepted.
    assert (q["reported_completed"], q["received"]) == ("120", "120")

    order = (await client.get(f"{API}/orders/{received['ids']['order']}")).json()
    [allocation] = order["lines"][0]["components"][0]["allocations"]
    assert (allocation["received_qty"], allocation["accepted_qty"], allocation["held_qty"]) == (
        "120",
        "116",
        "0",
    )
    async with app.state.session_factory() as db:
        actions = [
            e.action
            for e in await db.scalars(select(AuditEvent).order_by(AuditEvent.created_at))
            if e.action.startswith(("quality.", "outsourcing.receipt"))
        ]
    assert actions == [
        "outsourcing.receipt_recorded",
        "quality.inspection_recorded",
        "quality.hold_released",
    ]


@pytest.mark.parametrize(
    "quantity, extra, detail",
    [
        ("201", {}, "Only 200 PCS"),
        ("1.5", {}, "decimal place"),
        ("10", {"receipt_date": "2099-01-01"}, "future"),
        ("10", {"receipt_date": "2026-09-30"}, "before the batch was sent"),
    ],
)
async def test_receipts_cannot_exceed_what_is_at_the_supplier(
    client: AsyncClient,
    sent: dict,
    quantity: str,
    extra: dict,
    detail: str,
) -> None:
    response = await client.post(
        f"{API}{receipts_path(sent['batch'])}",
        headers=csrf_headers(client),
        json=receipt_body(sent["batch"], quantity, **extra),
    )
    assert response.status_code == 422
    assert detail in response.json()["detail"]


async def test_partial_receipts_add_up_and_repeat_submissions_count_once(
    client: AsyncClient, received: dict
) -> None:
    batch = received["batch"]
    body = receipt_body(batch, "60")
    second = await post(client, receipts_path(batch), body)
    again = await client.post(
        f"{API}{receipts_path(batch)}", headers=csrf_headers(client), json=body
    )
    assert again.status_code == 200
    assert second["quantities"]["received"] == "180"
    over = await post(client, receipts_path(batch), receipt_body(second, "21"), expect=422)
    assert "Only 20 PCS" in over["detail"]
    await post(client, receipts_path(batch), receipt_body(batch, "5"), expect=409)  # stale
    async with app.state.session_factory() as db:
        assert len((await db.scalars(select(BatchReceipt))).all()) == 2


async def test_receipts_only_for_batches_at_the_supplier(
    client: AsyncClient,
    planned: dict[str, str],
) -> None:
    batch = await post(client, "/outsourcing/batches", batch_body(planned))
    await post(client, receipts_path(batch), receipt_body(batch, "10"), expect=409)


async def test_inspection_must_account_for_everything_received(
    client: AsyncClient, received: dict
) -> None:
    batch, receipt = received["batch"], received["receipt"]
    path = f"{receipts_path(batch)}/{receipt['id']}/inspection"
    short = await act(client, path, inspection_body(receipt, "100", rejected="10"), expect=422)
    assert "add up to the 120 PCS received; these add up to 110" in short["detail"]
    silent = await act(client, path, inspection_body(receipt, "100", rejected="20"), expect=422)
    assert "Say why" in silent["detail"]
    await act(client, path, inspection_body({"version": 99}, "120"), expect=409)

    done = await act(client, path, inspection_body(receipt, "120"))
    again = await act(client, path, inspection_body(done["receipts"][0], "120"), expect=409)
    assert "already inspected" in again["detail"]
    nothing_held = await act(
        client,
        f"{receipts_path(batch)}/{receipt['id']}/release",
        {
            "version": done["receipts"][0]["version"],
            "accepted_qty": "1",
            "rejected_qty": "0",
            "rework_qty": "0",
            "reason": "No hold",
        },
        expect=409,
    )
    assert "Nothing" in nothing_held["detail"]


async def test_hold_release_is_bounded_and_needs_a_reason(
    client: AsyncClient, received: dict
) -> None:
    batch, receipt = received["batch"], received["receipt"]
    inspected = await act(
        client,
        f"{receipts_path(batch)}/{receipt['id']}/inspection",
        inspection_body(receipt, "100", held="20", note="Dimension check pending"),
    )
    receipt = inspected["receipts"][0]
    path = f"{receipts_path(batch)}/{receipt['id']}/release"
    base = {"version": receipt["version"], "rejected_qty": "0", "rework_qty": "0"}
    await act(client, path, {**base, "accepted_qty": "21", "reason": "Too many"}, expect=422)
    await act(client, path, {**base, "accepted_qty": "0", "reason": "Nothing"}, expect=422)
    await act(client, path, {**base, "accepted_qty": "5", "reason": ""}, expect=422)
    partial = await act(client, path, {**base, "accepted_qty": "5", "reason": "Measured OK"})
    assert (partial["quantities"]["accepted"], partial["quantities"]["held"]) == ("105", "15")


async def test_stores_receive_and_quality_decides(
    client: AsyncClient,
    sent: dict,
    add_member: AddMember,
    workspace_records: dict[str, object],
) -> None:
    site = workspace_records["site_id"]
    hosur = await post(client, "/organization/sites", {"name": "Hosur Plant"})
    for email, role, sites in [
        ("stores@example.com", "stores", [site]),
        ("qc@example.com", "quality", [site]),
        ("coordinator@example.com", "production_coordinator", [site]),
        ("hosur-qc@example.com", "quality", [uuid.UUID(hosur["id"])]),
    ]:
        await add_member(email, role, site_ids=sites)
    batch = sent["batch"]

    for email in ("qc@example.com", "coordinator@example.com"):
        await sign_in_as(client, email)
        await post(client, receipts_path(batch), receipt_body(batch, "120"), expect=403)
    await sign_in_as(client, "stores@example.com")
    batch = await post(client, receipts_path(batch), receipt_body(batch, "120"))
    receipt = batch["receipts"][0]
    assert receipt["received_by_label"] == "stores <stores@example.com>"
    inspect = f"{receipts_path(batch)}/{receipt['id']}/inspection"
    await act(client, inspect, inspection_body(receipt, "120"), expect=403)

    await sign_in_as(client, "hosur-qc@example.com")
    await act(client, inspect, inspection_body(receipt, "120"), expect=404)
    await sign_in_as(client, "qc@example.com")
    done = await act(client, inspect, inspection_body(receipt, "120"))
    assert done["receipts"][0]["decisions"][0]["decided_by_label"] == "qc <qc@example.com>"
