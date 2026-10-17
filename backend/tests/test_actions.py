"""Slice F7: recovery actions with owners, due times, approvals and outcomes."""

# ruff: noqa: F811  (pytest fixtures are imported and then used as parameters)

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import AddMember, csrf_headers, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select
from test_orders import API, act, data, post  # noqa: F401
from test_risk import calendar, order_risk, scene, supplier_says  # noqa: F401

from app.main import app
from app.models import AuditEvent


def soon(hours: int = 24) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def body(owner: uuid.UUID, **overrides) -> dict:
    values = {
        "submission_key": str(uuid.uuid4()),
        "kind": "chase_update",
        "title": "Get a fresh update from Hosur Coaters",
        "owner_id": str(owner),
        "due_at": soon(),
    }
    values.update(overrides)
    return values


@pytest.fixture
async def team(client: AsyncClient, scene: dict, add_member: AddMember, workspace_records):
    site = workspace_records["site_id"]
    ids = {
        "buyer": await add_member("buyer@example.com", "procurement", site_ids=[site]),
        "approver": await add_member("approver@example.com", "approver", site_ids=[site]),
        "viewer": await add_member("viewer@example.com", "read_only", site_ids=[site]),
        "owner": workspace_records["user_id"],
    }
    await calendar(client, scene["site"])
    return {**scene, **ids, "line": scene["late"]["lines"][0]["id"]}


async def test_risk_suggests_actions_that_stay_drafts(client: AsyncClient, team: dict) -> None:
    await supplier_says(client, team, "50", "30", "20", revised=None)

    risk = await order_risk(client, team["late"])

    kinds = {(s["kind"], s["requires_approval"]) for s in risk["suggestions"]}
    assert {("rework", True), ("alternate_supplier", True), ("collect", False)} <= kinds
    collect = next(s for s in risk["suggestions"] if s["kind"] == "collect")
    assert collect["title"] == "Collect the 50 PCS completed at Hosur Coaters"
    assert collect["batch_id"] == team["batch"]["id"]
    listed = (await client.get(f"{API}/actions")).json()
    assert listed["total"] == 0  # suggestions create nothing on their own


async def test_an_action_has_an_owner_a_due_time_and_the_risk_it_answers(
    client: AsyncClient, team: dict
) -> None:
    await supplier_says(client, team, "50", "30", "20")
    payload = body(team["buyer"], line_id=team["line"], batch_id=team["batch"]["id"])
    created = await post(client, "/actions", payload)
    again = await client.post(f"{API}/actions", headers=csrf_headers(client), json=payload)

    assert again.status_code == 200 and again.json()["id"] == created["id"]
    assert (created["status"], created["requires_approval"], created["owner_label"]) == (
        "open",
        False,
        "buyer <buyer@example.com>",
    )
    assert created["line"]["order_number"] == team["late"]["number"]
    assert created["batch"]["number"] == "OB-00001"
    assert created["risk_before"]["headline"] == "quantity_shortage"
    assert [e["kind"] for e in created["events"]] == ["created"]

    await sign_in_as(client, "buyer@example.com")
    mine = (await client.get(f"{API}/actions", params={"mine": True})).json()
    assert (mine["total"], mine["counts"]["mine"], mine["counts"]["overdue"]) == (1, 1, 0)


@pytest.mark.parametrize(
    "overrides, expect, detail",
    [
        ({"line_id": None, "batch_id": None}, 422, "order line or a batch"),
        ({"due_at": "2020-01-01T09:00:00+05:30"}, 422, "future"),
        ({"due_at": "2099-01-01T09:00:00+05:30"}, 422, "within a year"),
        ({"owner": "viewer"}, 422, "can own actions"),
        ({"title": "x"}, 422, None),
        ({"kind": "teleport"}, 422, None),
    ],
)
async def test_actions_need_a_subject_a_real_owner_and_a_sensible_due_time(
    client: AsyncClient, team: dict, overrides: dict, expect: int, detail: str | None
) -> None:
    owner = team[overrides.pop("owner", "buyer")]
    values = {"line_id": team["line"], **overrides}
    response = await client.post(
        f"{API}/actions", headers=csrf_headers(client), json=body(owner, **values)
    )
    assert response.status_code == expect, response.text
    if detail:
        assert detail in response.json()["detail"]


async def test_the_batch_must_serve_the_line_and_the_line_must_be_open(
    client: AsyncClient, team: dict, data: dict
) -> None:
    other = await post(
        client,
        "/outsourcing/batches",
        {
            "site_id": team["site"],
            "supplier_id": team["batch"]["supplier_id"],
            "item_id": team["casting"],
            "operation": "Powder coating",
            "quantity": "5",
            "expected_return_date": team["batch"]["expected_return_date"],
        },
    )
    unrelated = await post(
        client,
        "/actions",
        body(team["buyer"], line_id=team["line"], batch_id=other["id"]),
        expect=422,
    )
    assert "does not serve" in unrelated["detail"]
    draft = await post(
        client,
        "/orders",
        {
            "site_id": team["site"],
            "customer_id": data["acme"],
            "lines": [{"item_id": data["pump"], "quantity": "1", "requested_date": "2026-12-01"}],
        },
    )
    await post(client, "/actions", body(team["buyer"], line_id=draft["lines"][0]["id"]), expect=409)


async def test_consequential_actions_need_someone_else_to_approve(
    client: AsyncClient, team: dict
) -> None:
    await sign_in_as(client, "buyer@example.com")
    proposed = await post(
        client,
        "/actions",
        body(
            team["buyer"],
            kind="alternate_supplier",
            title="Evaluate Pune Platers for 30 castings",
            line_id=team["line"],
        ),
    )
    assert (proposed["status"], proposed["requires_approval"]) == ("awaiting_approval", True)
    path = f"/actions/{proposed['id']}"
    await act(client, f"{path}/approve", {"version": proposed["version"]}, expect=403)
    early = await act(
        client,
        f"{path}/complete",
        {"version": proposed["version"], "outcome": "resolved", "note": "Done already"},
        expect=409,
    )
    assert "waiting for approval" in early["detail"]

    await sign_in_as(client, "owner@example.com")
    approved = await act(client, f"{path}/approve", {"version": proposed["version"], "note": "OK"})
    assert approved["status"] == "open" and approved["approved_at"]
    await act(client, f"{path}/approve", {"version": approved["version"]}, expect=409)

    await sign_in_as(client, "approver@example.com")
    second = await post(
        client, "/actions", body(team["buyer"], kind="rework", line_id=team["line"]), expect=403
    )
    assert second["detail"] == "Permission denied"


async def test_proposals_can_be_rejected_with_a_reason(client: AsyncClient, team: dict) -> None:
    proposed = await post(
        client,
        "/actions",
        body(team["buyer"], kind="promise_review", title="Move the promise", line_id=team["line"]),
    )
    await sign_in_as(client, "approver@example.com")
    rejected = await act(
        client,
        f"/actions/{proposed['id']}/reject",
        {"version": proposed["version"], "reason": "Customer will not accept a later date"},
    )
    assert (rejected["status"], rejected["events"][-1]["note"]) == (
        "rejected",
        "Customer will not accept a later date",
    )
    assert rejected["closed_at"] is not None


async def test_owner_acknowledges_and_supplier_acknowledgement_is_labelled(
    client: AsyncClient, team: dict
) -> None:
    created = await post(
        client, "/actions", body(team["buyer"], line_id=team["line"], batch_id=team["batch"]["id"])
    )
    path = f"/actions/{created['id']}"
    not_owner = await act(client, f"{path}/acknowledge", {"version": created["version"]}, 403)
    assert "owner" in not_owner["detail"]

    await sign_in_as(client, "buyer@example.com")
    seen = await act(client, f"{path}/acknowledge", {"version": created["version"]})
    assert seen["acknowledged_at"] is not None
    await act(client, f"{path}/acknowledge", {"version": seen["version"]}, expect=409)
    acked = await act(
        client,
        f"{path}/supplier-acknowledgement",
        {
            "version": seen["version"],
            "contact_method": "whatsapp",
            "contact_name": "Murugan",
            "acknowledged_at": datetime.now(UTC).isoformat(),
            "note": "Will send 50 on Friday's truck",
        },
    )
    event = acked["events"][-1]
    assert (event["kind"], event["details"]["source"], event["details"]["contact_name"]) == (
        "supplier_acknowledged",
        "manufacturer_entered",
        "Murugan",
    )

    line_only = await post(client, "/actions", body(team["buyer"], line_id=team["line"]))
    await act(
        client,
        f"/actions/{line_only['id']}/supplier-acknowledgement",
        {
            "version": line_only["version"],
            "contact_method": "phone",
            "acknowledged_at": datetime.now(UTC).isoformat(),
        },
        expect=422,
    )


async def test_reassigning_needs_a_reason_and_an_owner_with_site_access(
    client: AsyncClient, team: dict, add_member: AddMember
) -> None:
    hosur = await post(client, "/organization/sites", {"name": "Hosur Plant"})
    far = await add_member("far@example.com", "procurement", site_ids=[uuid.UUID(hosur["id"])])
    created = await post(client, "/actions", body(team["buyer"], line_id=team["line"]))
    path = f"/actions/{created['id']}/reassign"

    nope = await act(
        client,
        path,
        {"version": created["version"], "owner_id": str(far), "reason": "Covering for Ravi"},
        expect=422,
    )
    assert "no access to this site" in nope["detail"]
    moved = await act(
        client,
        path,
        {
            "version": created["version"],
            "owner_id": str(team["owner"]),
            "due_at": soon(48),
            "reason": "Buyer is on leave",
        },
    )
    event = moved["events"][-1]
    assert event["details"]["before"]["owner"] == "buyer <buyer@example.com>"
    assert event["details"]["after"]["owner"] == "A. Owner <owner@example.com>"
    assignees = (
        await client.get(f"{API}/actions/assignees", params={"site_id": team["site"]})
    ).json()
    assert {a["display_name"] for a in assignees} == {"A. Owner", "buyer"}


async def test_closing_records_the_outcome_and_the_risk_afterwards(
    client: AsyncClient, team: dict
) -> None:
    await supplier_says(client, team, "50", "30", "20")
    created = await post(
        client, "/actions", body(team["buyer"], kind="collect", line_id=team["line"])
    )
    path = f"/actions/{created['id']}/complete"
    await act(
        client, path, {"version": created["version"], "outcome": "resolved", "note": "x"}, 422
    )
    await sign_in_as(client, "approver@example.com")
    await act(
        client,
        path,
        {"version": created["version"], "outcome": "resolved", "note": "Collected"},
        expect=403,
    )
    await sign_in_as(client, "buyer@example.com")
    done = await act(
        client,
        path,
        {
            "version": created["version"],
            "outcome": "partly_resolved",
            "note": "Collected 50; the 30 rejected still need a decision",
        },
    )

    assert (done["status"], done["outcome"]) == ("done", "partly_resolved")
    assert done["risk_before"]["headline"] == done["risk_after"]["headline"] == "quantity_shortage"
    await act(
        client,
        f"/actions/{created['id']}/cancel",
        {"version": done["version"], "reason": "Too late"},
        expect=409,
    )
    async with app.state.session_factory() as db:
        actions = [
            e.action
            for e in await db.scalars(select(AuditEvent).order_by(AuditEvent.created_at))
            if e.action.startswith("actions.")
        ]
    assert actions == ["actions.created", "actions.completed"]


async def test_actions_respect_permissions_and_scope(
    client: AsyncClient, team: dict, add_member: AddMember, workspace_records: dict
) -> None:
    created = await post(client, "/actions", body(team["buyer"], line_id=team["line"]))
    hosur = await post(client, "/organization/sites", {"name": "Hosur Plant"})
    await add_member("hosur@example.com", "procurement", site_ids=[uuid.UUID(hosur["id"])])
    await add_member(
        "rival@example.com",
        "owner",
        tenant_id=workspace_records["other_tenant_id"],
        home_site_id=workspace_records["other_site_id"],
    )
    await sign_in_as(client, "viewer@example.com")
    assert (await client.get(f"{API}/actions")).json()["total"] == 1
    await post(client, "/actions", body(team["buyer"], line_id=team["line"]), expect=403)
    for email in ("hosur@example.com", "rival@example.com"):
        await sign_in_as(client, email)
        assert (await client.get(f"{API}/actions")).json()["total"] == 0
        assert (await client.get(f"{API}/actions/{created['id']}")).status_code == 404
        await act(
            client,
            f"/actions/{created['id']}/cancel",
            {"version": created["version"], "reason": "Not mine"},
            expect=404,
        )


async def test_an_approver_cannot_approve_their_own_proposal(
    client: AsyncClient, team: dict
) -> None:
    # The owner holds approval rights, but not over their own proposal.
    proposed = await post(
        client, "/actions", body(team["buyer"], kind="rework", line_id=team["line"])
    )
    assert proposed["can_approve"] is False
    own = await act(
        client, f"/actions/{proposed['id']}/approve", {"version": proposed["version"]}, 403
    )
    assert own["detail"] == "You cannot approve an action you proposed"
    await sign_in_as(client, "approver@example.com")
    assert (await client.get(f"{API}/actions/{proposed['id']}")).json()["can_approve"] is True


async def test_colleagues_cannot_close_someone_elses_action(
    client: AsyncClient, team: dict, add_member: AddMember, workspace_records: dict
) -> None:
    await add_member(
        "coordinator@example.com", "production_coordinator", site_ids=[workspace_records["site_id"]]
    )
    created = await post(client, "/actions", body(team["buyer"], line_id=team["line"]))
    await sign_in_as(client, "coordinator@example.com")
    for verb, extra in (
        ("complete", {"outcome": "resolved", "note": "Not mine to close"}),
        ("cancel", {"reason": "Not mine to cancel"}),
    ):
        refused = await act(
            client,
            f"/actions/{created['id']}/{verb}",
            {"version": created["version"], **extra},
            expect=403,
        )
        assert "Only the owner or the person who raised it" in refused["detail"]


async def test_the_follow_up_shows_whether_risk_changed(client: AsyncClient, team: dict) -> None:
    before = await post(client, "/actions", body(team["buyer"], line_id=team["line"]))
    assert before["risk_before"]["headline"] == "on_track"
    # Then the supplier reports rejections that leave this line short.
    await supplier_says(client, team, "50", "30", "20")
    await sign_in_as(client, "buyer@example.com")
    done = await act(
        client,
        f"/actions/{before['id']}/complete",
        {"version": before["version"], "outcome": "not_resolved", "note": "Supplier rejected 30"},
    )
    assert done["risk_after"]["headline"] == "quantity_shortage"
