import argparse
import asyncio
import getpass
import re
import uuid
from datetime import UTC, datetime

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionFactory, engine
from app.models.identity import AuditEvent, Site, Tenant, TenantMembership, User
from app.services import two_step


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


async def provision_owner(args: argparse.Namespace) -> None:
    settings = get_settings()
    if settings.app_env != "development":
        raise SystemExit("The development owner command is disabled outside development")
    try:
        email = validate_email(args.email, check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise SystemExit(f"Invalid email: {exc}") from exc
    email_normalized = email.casefold()
    display_name = normalize_name(args.name)
    tenant_name = normalize_name(args.tenant)
    site_name = normalize_name(args.site)
    password = getpass.getpass("Initial password (minimum 14 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    if len(password) < 14:
        raise SystemExit("Use a password of at least 14 characters")

    async with SessionFactory() as db:
        existing = await db.execute(
            select(User.id).where(User.email_normalized == email_normalized)
        )
        if existing.scalar_one_or_none() is not None:
            raise SystemExit("This email is already registered")
        tenant = Tenant(display_name=tenant_name)
        db.add(tenant)
        await db.flush()
        site = Site(
            tenant_id=tenant.id,
            name=site_name,
            normalized_name=site_name.casefold(),
            time_zone="Asia/Kolkata",
        )
        user = User(
            email=email,
            email_normalized=email_normalized,
            display_name=display_name,
            password_hash=hash_password(password),
            email_verified_at=datetime.now(UTC),
        )
        db.add_all([site, user])
        await db.flush()
        db.add(
            TenantMembership(
                tenant_id=tenant.id,
                user_id=user.id,
                home_site_id=site.id,
                role="owner",
            )
        )
        await db.commit()
        print(f"Created development owner {email} for workspace {tenant_name}.")
        print("The initial site uses Asia/Kolkata; review it in workspace setup.")
    await engine.dispose()


async def reset_two_step(args: argparse.Namespace) -> None:
    """Support-only recovery when a company has no other administrator (ADR-0015).

    Needs direct server access. The reason is required and kept in the audit trail.
    """
    reason = normalize_name(args.reason)
    if len(reason) < 10:
        raise SystemExit("Give a reason of at least 10 characters (for example the ticket number)")
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email_normalized == args.email.casefold()))
        if user is None:
            raise SystemExit("No account with this email")
        now = datetime.now(UTC)
        was_enabled, sessions_ended = await two_step.reset(db, user, now)
        tenant_ids = (
            await db.scalars(
                select(TenantMembership.tenant_id).where(TenantMembership.user_id == user.id)
            )
        ).all()
        for tenant_id in tenant_ids or [None]:
            db.add(
                AuditEvent(
                    tenant_id=tenant_id,
                    actor_user_id=None,
                    actor_type="system",
                    actor_label="Thodara support (command line)",
                    source_channel="cli",
                    action="support.two_step_reset",
                    request_id=str(uuid.uuid4()),
                    details={
                        "user_id": str(user.id),
                        "was_enabled": was_enabled,
                        "sessions_ended": sessions_ended,
                        "reason": reason,
                    },
                )
            )
        await db.commit()
        print(f"Two-step sign-in reset for {user.email}; {sessions_ended} session(s) ended.")
        print("They must set it up again at their next sign-in.")
    await engine.dispose()


async def seed_demo(args: argparse.Namespace) -> None:
    """Replace everything with the fictional demo company (ADR-0016)."""
    settings = get_settings()
    if settings.app_env not in {"development", "demo"}:
        raise SystemExit("The demo can only be loaded in a development or demo environment")
    from app.demo import DemoError, seed
    from app.main import app

    try:
        accounts = await seed(app, reset=args.reset)
    except DemoError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        await engine.dispose()
    print(f"Demo loaded: {COMPANY_NOTE}")
    print("Sign in with these accounts (fictional people; new passwords on every reset):")
    for email, name, role, password in accounts:
        print(f"  {role:<20} {email:<32} {password}   ({name})")


COMPANY_NOTE = "Srimant Auto Parts (DEMO), fictional data only."


def main() -> None:
    parser = argparse.ArgumentParser(prog="thodara-api")
    subparsers = parser.add_subparsers(dest="command", required=True)
    owner_parser = subparsers.add_parser("provision-owner", help="Create a local development owner")
    owner_parser.add_argument("--email", required=True)
    owner_parser.add_argument("--name", required=True)
    owner_parser.add_argument("--tenant", required=True)
    owner_parser.add_argument("--site", required=True)
    reset_parser = subparsers.add_parser(
        "reset-two-step", help="Support: reset someone's two-step sign-in"
    )
    reset_parser.add_argument("--email", required=True)
    reset_parser.add_argument("--reason", required=True)
    demo_parser = subparsers.add_parser(
        "seed-demo", help="Load the fictional demo company (development and demo only)"
    )
    demo_parser.add_argument(
        "--reset", action="store_true", help="Delete everything in this database first"
    )
    args = parser.parse_args()
    if args.command == "provision-owner":
        asyncio.run(provision_owner(args))
    elif args.command == "seed-demo":
        asyncio.run(seed_demo(args))
    elif args.command == "reset-two-step":
        asyncio.run(reset_two_step(args))


if __name__ == "__main__":
    main()
