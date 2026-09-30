import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import AuditEvent, User


def actor_label(user: User) -> str:
    return f"{user.display_name} <{user.email}>"


def request_source(request: Request) -> str:
    # Browser requests carry an Origin header; other callers are treated as API clients.
    return "web" if request.headers.get("origin") else "api"


def record_event(
    db: AsyncSession,
    request: Request,
    action: str,
    *,
    tenant_id: uuid.UUID | None,
    actor: User | None,
    details: dict[str, Any],
) -> AuditEvent:
    event = AuditEvent(
        tenant_id=tenant_id,
        actor_user_id=actor.id if actor else None,
        actor_type="user" if actor else "anonymous",
        actor_label=actor_label(actor) if actor else None,
        source_channel=request_source(request),
        action=action,
        request_id=request.state.request_id,
        details=details,
    )
    db.add(event)
    return event
