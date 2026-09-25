import argparse
import asyncio
import getpass
import re
from datetime import UTC, datetime

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionFactory, engine
from app.models.identity import Site, Tenant, TenantMembership, User


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="thodara-api")
    subparsers = parser.add_subparsers(dest="command", required=True)
    owner_parser = subparsers.add_parser("provision-owner", help="Create a local development owner")
    owner_parser.add_argument("--email", required=True)
    owner_parser.add_argument("--name", required=True)
    owner_parser.add_argument("--tenant", required=True)
    owner_parser.add_argument("--site", required=True)
    args = parser.parse_args()
    if args.command == "provision-owner":
        asyncio.run(provision_owner(args))


if __name__ == "__main__":
    main()
