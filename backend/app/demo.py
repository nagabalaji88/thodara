"""Fictional demo company for presentations (ADR-0016). Never for real data.

The records are created through the application's own API, so they pass the same rules,
permissions and audit trail as anything a person enters. People are added directly because
invitations do not exist yet (decision D3).
"""

import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI
from sqlalchemy import delete, func, select

from app.core.security import hash_password
from app.db.base import Base
from app.models.identity import Site, Tenant, TenantMembership, User
from app.models.masterdata import MembershipSite

COMPANY = "Srimant Auto Parts (DEMO)"
SITE = "Bangalore Manufacturing"
DOMAIN = "srimant.example.com"  # example.com never delivers mail
# Calls go through the app in-process; https so that secure cookies are sent back.
ORIGIN = "https://localhost"

# (email name, display name, role); the first is the presenter.
PEOPLE = [
    ("priya", "Priya Sharma", "owner"),
    ("arun", "Arun Iyer", "administrator"),
    ("meena", "Meena Krishnan", "production_manager"),
    ("ravi", "Ravi Kumar", "stores"),
    ("kavya", "Kavya Raman", "quality"),
    ("anita", "Anita Rao", "approver"),
    ("vijay", "Vijay Das", "read_only"),
]


class DemoError(RuntimeError):
    pass


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def day(offset: int) -> str:
    return (today() + timedelta(days=offset)).isoformat()


def hours_ago(hours: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


def new_password() -> str:
    return "Demo-" + secrets.token_urlsafe(12)


class Api:
    def __init__(self, app: FastAPI) -> None:
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        )

    async def call(self, method: str, path: str, body: dict | None = None) -> Any:
        headers = {}
        if method != "GET":
            headers["X-CSRF-Token"] = self.client.cookies.get("thodara_csrf", "")
        response = await self.client.request(method, f"/api/v1{path}", json=body, headers=headers)
        if response.status_code >= 400:
            raise DemoError(f"{method} {path}: {response.status_code} {response.text}")
        return response.json() if response.content else None

    async def sign_in(self, email: str, password: str) -> None:
        self.client.cookies.clear()
        session = await self.call("POST", "/auth/login", {"email": email, "password": password})
        if session["two_step"]["stage"] != "full":
            raise DemoError(f"{email} needs two-step sign-in; reset the demo first")

    async def close(self) -> None:
        await self.client.aclose()


async def wipe(app: FastAPI) -> None:
    """Delete every record. Only for the demo database."""
    async with app.state.session_factory() as db:
        for table in reversed(Base.metadata.sorted_tables):
            await db.execute(delete(table))
        await db.commit()


async def add_people(app: FastAPI) -> list[tuple[str, str, str, str]]:
    accounts = []
    async with app.state.session_factory() as db:
        tenant = Tenant(display_name=COMPANY)
        db.add(tenant)
        await db.flush()
        site = Site(
            tenant_id=tenant.id,
            name=SITE,
            normalized_name=SITE.casefold(),
            city="Bengaluru",
            time_zone="Asia/Kolkata",
        )
        db.add(site)
        await db.flush()
        for handle, name, role in PEOPLE:
            email = f"{handle}@{DOMAIN}"
            password = new_password()
            user = User(
                email=email,
                email_normalized=email,
                display_name=name,
                password_hash=hash_password(password),
                email_verified_at=datetime.now(UTC),
            )
            db.add(user)
            await db.flush()
            membership = TenantMembership(
                tenant_id=tenant.id,
                user_id=user.id,
                home_site_id=site.id,
                role=role,
                site_scope="selected",
            )
            db.add(membership)
            await db.flush()
            db.add(
                MembershipSite(tenant_id=tenant.id, membership_id=membership.id, site_id=site.id)
            )
            accounts.append((email, name, role, password))
        await db.commit()
    return accounts


async def build_story(api: Api, logins: dict[str, str]) -> None:
    """The first-release story: castings out for coating, a supplier update, a partial receipt."""
    owner = f"priya@{DOMAIN}"
    await api.sign_in(owner, logins[owner])
    site = (await api.call("GET", "/organization/sites"))[0]
    await api.call(
        "PUT",
        "/onboarding/workspace",
        {
            "company_name": COMPANY,
            "country_code": "IN",
            "base_currency": "INR",
            "site_name": SITE,
            "city": "Bengaluru",
            "time_zone": "Asia/Kolkata",
        },
    )
    await api.call(
        "PUT",
        f"/organization/sites/{site['id']}/calendar",
        {"working_days": [1, 2, 3, 4, 5, 6], "shift_start": "09:00", "shift_end": "18:00"},
    )
    pcs = await api.call(
        "POST",
        "/master-data/units",
        {"code": "PCS", "name": "Pieces", "dimension": "count", "decimal_places": 0},
    )

    async def item(code: str, name: str, kind: str) -> str:
        body = {"code": code, "name": name, "item_type": kind, "base_unit_id": pcs["id"]}
        return (await api.call("POST", "/master-data/items", body))["id"]

    pump = await item("PMP-5HP", "Monoblock pump 5 HP", "finished_good")
    motor = await item("MTR-3HP", "Induction motor 3 HP", "finished_good")
    casting = await item("HSG-CAST", "Pump housing casting", "component")
    shaft = await item("SHF-EN8", "Motor shaft EN8", "component")

    customers = {}
    for code, name, city in [
        ("KISAN", "Kisan Agro Equipments (DEMO)", "Coimbatore"),
        ("AQUA", "Aqua Irrigation Systems (DEMO)", "Hubballi"),
        ("SRIL", "Sri Lakshmi Pump Distributors (DEMO)", "Madurai"),
    ]:
        body = {"code": code, "name": name, "city": city}
        customers[code] = (await api.call("POST", "/master-data/customers", body))["id"]
    suppliers = {}
    for code, name, city in [
        ("HCOAT", "Hosur Coaters (DEMO)", "Hosur"),
        ("CBHT", "Coimbatore Heat Treaters (DEMO)", "Coimbatore"),
        ("AMBPL", "Ambattur Platers (DEMO)", "Chennai"),
    ]:
        body = {"code": code, "name": name, "city": city, "provides_job_work": True}
        suppliers[code] = (await api.call("POST", "/master-data/suppliers", body))["id"]

    async def order(
        customer: str,
        reference: str,
        item_id: str,
        qty: str,
        promised: int,
        component: str,
        operation: str,
    ) -> dict:
        created = await api.call(
            "POST",
            "/orders",
            {
                "site_id": site["id"],
                "customer_id": customers[customer],
                "customer_reference": reference,
                "lines": [
                    {
                        "item_id": item_id,
                        "quantity": qty,
                        "requested_date": day(promised),
                        "promised_date": day(promised),
                    }
                ],
            },
        )
        created = await api.call(
            "POST", f"/orders/{created['id']}/confirm", {"version": created["version"]}
        )
        line = created["lines"][0]
        return await api.call(
            "PUT",
            f"/orders/{created['id']}/lines/{line['id']}/dependencies",
            {
                "order_version": created["version"],
                "components": [
                    {"item_id": component, "qty_per_unit": "1", "outsourced_operation": operation}
                ],
                "operations": [
                    {"name": "Assembly", "kind": "in_house", "duration_minutes": 360},
                    {"name": "Testing", "kind": "in_house", "duration_minutes": 120},
                ],
            },
        )

    aqua = await order("AQUA", "AQ-552", pump, "80", 6, casting, "Powder coating")
    kisan = await order("KISAN", "KA-118", pump, "120", 10, casting, "Powder coating")
    sril = await order("SRIL", "SL-77", motor, "40", 14, shaft, "Heat treatment")
    await order("KISAN", "KA-121", pump, "60", 21, casting, "Powder coating")

    def component(o: dict) -> str:
        return o["lines"][0]["components"][0]["id"]

    async def batch(
        supplier: str,
        item_id: str,
        operation: str,
        qty: str,
        back: int,
        allocations: list[tuple[dict, str]],
        sent: int | None,
        challan: str,
    ) -> dict:
        created = await api.call(
            "POST",
            "/outsourcing/batches",
            {
                "site_id": site["id"],
                "supplier_id": suppliers[supplier],
                "item_id": item_id,
                "operation": operation,
                "quantity": qty,
                "expected_return_date": day(back),
                "allocations": [
                    {"component_id": component(o), "quantity": q} for o, q in allocations
                ],
            },
        )
        if sent is None:
            return created
        return await api.call(
            "POST",
            f"/outsourcing/batches/{created['id']}/send",
            {"version": created["version"], "sent_date": day(sent), "challan_reference": challan},
        )

    coating = await batch(
        "HCOAT", casting, "Powder coating", "200", 3, [(aqua, "80"), (kisan, "120")], -6, "DC-1182"
    )
    await batch("CBHT", shaft, "Heat treatment", "40", 5, [(sril, "40")], -4, "DC-1190")
    await batch("AMBPL", shaft, "Zinc plating", "60", 12, [], None, "")

    # The supplier says 120 done, 20 rejected, 60 still in process (staff-entered, by phone).
    coating = await api.call(
        "POST",
        f"/outsourcing/batches/{coating['id']}/updates",
        {
            "version": coating["version"],
            "submission_key": str(uuid.uuid4()),
            "completed_qty": "120",
            "rejected_qty": "20",
            "pending_qty": "60",
            "contact_method": "phone",
            "contact_name": "Murugan (supervisor)",
            "reported_at": hours_ago(5),
            "revised_return_date": day(5),
        },
    )
    # Stores receives 100; quality accepts 95 and holds 5.
    stores = f"ravi@{DOMAIN}"
    await api.sign_in(stores, logins[stores])
    coating = await api.call(
        "POST",
        f"/outsourcing/batches/{coating['id']}/receipts",
        {
            "version": coating["version"],
            "submission_key": str(uuid.uuid4()),
            "received_qty": "100",
            "receipt_date": day(-1),
            "document_reference": "IN-4471",
        },
    )
    quality = f"kavya@{DOMAIN}"
    await api.sign_in(quality, logins[quality])
    receipt = coating["receipts"][0]
    await api.call(
        "POST",
        f"/outsourcing/batches/{coating['id']}/receipts/{receipt['id']}/inspection",
        {
            "version": receipt["version"],
            "accepted_qty": "95",
            "rejected_qty": "0",
            "held_qty": "5",
            "rework_qty": "0",
            "note": "5 pieces held for a coating thickness check",
        },
    )
    api.client.cookies.clear()


async def seed(app: FastAPI, *, reset: bool) -> list[tuple[str, str, str, str]]:
    """Create the demo company. Returns (email, name, role, password) for each person."""
    async with app.state.session_factory() as db:
        existing = await db.scalar(select(func.count(Tenant.id)))
    if existing and not reset:
        raise DemoError("The database already has data; use --reset to replace it with the demo")
    await wipe(app)
    accounts = await add_people(app)
    api = Api(app)
    try:
        await build_story(api, {email: password for email, _, _, password in accounts})
    finally:
        await api.close()
    return accounts
