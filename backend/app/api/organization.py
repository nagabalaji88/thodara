import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    TENANT_WIDE_ROLES,
    AuthContext,
    require_csrf,
    require_permission,
)
from app.api.masterdata import STALE, audit, commit_or_conflict
from app.db.session import get_db
from app.models.identity import Site, TenantMembership, User
from app.models.masterdata import MembershipSite
from app.models.organization import DOCUMENT_TYPES, DocumentSequence, SiteCalendar, SiteHoliday
from app.schemas.masterdata import (
    CalendarDay,
    CalendarOut,
    CalendarUpdate,
    HolidayCreate,
    HolidayOut,
    MemberOut,
    SequenceOut,
    SequenceUpdate,
    SiteAccessUpdate,
    SiteCreate,
    SiteOut,
)
from app.services.calendar import WorkCalendar
from app.services.numbering import ensure_sequences, format_number

router = APIRouter(prefix="/organization", tags=["organization"])


@router.get("/sites", response_model=list[SiteOut])
async def list_sites(
    context: AuthContext = Depends(require_permission("workspace:read")),
    db: AsyncSession = Depends(get_db),
):
    query = select(Site).where(Site.tenant_id == context.tenant.id)
    if context.site_ids is not None:
        query = query.where(Site.id.in_(context.site_ids))
    return (await db.scalars(query.order_by(Site.name))).all()


@router.post(
    "/sites", response_model=SiteOut, status_code=201, dependencies=[Depends(require_csrf)]
)
async def create_site(
    payload: SiteCreate,
    request: Request,
    context: AuthContext = Depends(require_permission("sites:manage")),
    db: AsyncSession = Depends(get_db),
):
    site = Site(
        tenant_id=context.tenant.id,
        name=payload.name,
        normalized_name=payload.name.casefold(),
        city=payload.city,
        time_zone=payload.time_zone,
    )
    db.add(site)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A site with this name already exists") from exc
    audit(
        db,
        context,
        request,
        "organization.site.created",
        {"site_id": str(site.id), "name": site.name, "time_zone": site.time_zone},
    )
    await db.commit()
    await db.refresh(site)
    return site


async def _site_ids_by_membership(
    db: AsyncSession, tenant_id: uuid.UUID
) -> dict[uuid.UUID, list[uuid.UUID]]:
    rows = await db.execute(
        select(MembershipSite.membership_id, MembershipSite.site_id).where(
            MembershipSite.tenant_id == tenant_id
        )
    )
    grouped: dict[uuid.UUID, list[uuid.UUID]] = {}
    for membership_id, site_id in rows:
        grouped.setdefault(membership_id, []).append(site_id)
    return grouped


def _member_out(
    membership: TenantMembership, user: User, site_ids: list[uuid.UUID]
) -> MemberOut:
    tenant_wide = membership.role in TENANT_WIDE_ROLES
    return MemberOut(
        membership_id=membership.id,
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=membership.role,
        status=membership.status,
        site_scope="all" if tenant_wide else membership.site_scope,
        site_ids=[] if tenant_wide or membership.site_scope == "all" else sorted(site_ids),
    )


@router.get("/members", response_model=list[MemberOut])
async def list_members(
    context: AuthContext = Depends(require_permission("users:manage")),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(TenantMembership, User)
        .join(User, User.id == TenantMembership.user_id)
        .where(TenantMembership.tenant_id == context.tenant.id)
        .order_by(User.display_name)
    )
    site_ids = await _site_ids_by_membership(db, context.tenant.id)
    return [_member_out(m, u, site_ids.get(m.id, [])) for m, u in rows]


@router.put(
    "/members/{membership_id}/site-access",
    response_model=MemberOut,
    dependencies=[Depends(require_csrf)],
)
async def update_site_access(
    membership_id: uuid.UUID,
    payload: SiteAccessUpdate,
    request: Request,
    context: AuthContext = Depends(require_permission("users:manage")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(TenantMembership, User)
            .join(User, User.id == TenantMembership.user_id)
            .where(
                TenantMembership.tenant_id == context.tenant.id,
                TenantMembership.id == membership_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Member not found")
    membership, user = row
    if membership.role in TENANT_WIDE_ROLES:
        raise HTTPException(
            status_code=409, detail="Owners and administrators always have access to every site"
        )
    requested = set(payload.site_ids) if payload.site_scope == "selected" else set()
    if payload.site_scope == "all" and payload.site_ids:
        raise HTTPException(status_code=422, detail="Leave site_ids empty when granting all sites")
    if requested:
        found = set(
            (
                await db.scalars(
                    select(Site.id).where(
                        Site.tenant_id == context.tenant.id, Site.id.in_(requested)
                    )
                )
            ).all()
        )
        if found != requested:
            raise HTTPException(status_code=422, detail="One or more sites were not found")

    before_ids = (await _site_ids_by_membership(db, context.tenant.id)).get(membership.id, [])
    before = {"site_scope": membership.site_scope, "site_ids": sorted(map(str, before_ids))}
    await db.execute(
        delete(MembershipSite).where(
            MembershipSite.tenant_id == context.tenant.id,
            MembershipSite.membership_id == membership.id,
        )
    )
    membership.site_scope = payload.site_scope
    db.add_all(
        MembershipSite(tenant_id=context.tenant.id, membership_id=membership.id, site_id=site_id)
        for site_id in requested
    )
    after = {"site_scope": payload.site_scope, "site_ids": sorted(map(str, requested))}
    if before != after:
        audit(
            db,
            context,
            request,
            "organization.member.site_access_changed",
            {"membership_id": str(membership.id), "user_id": str(user.id),
             "before": before, "after": after},
        )
    await db.commit()
    return _member_out(membership, user, sorted(requested))


# Working calendars


async def _accessible_site(db: AsyncSession, context: AuthContext, site_id: uuid.UUID) -> Site:
    site = await db.scalar(
        select(Site).where(Site.tenant_id == context.tenant.id, Site.id == site_id)
    )
    if site is None or not context.can_access_site(site.id):
        raise HTTPException(status_code=404, detail="Site not found")
    return site


async def load_work_calendar(db: AsyncSession, site: Site) -> WorkCalendar | None:
    """The site's calendar for date arithmetic, or None when it has not been configured."""
    calendar = await db.scalar(select(SiteCalendar).where(SiteCalendar.site_id == site.id))
    if calendar is None:
        return None
    holidays = await db.scalars(
        select(SiteHoliday.holiday_date).where(SiteHoliday.site_id == site.id)
    )
    return WorkCalendar(
        working_days=frozenset(int(day) for day in calendar.working_days),
        shift_start=calendar.shift_start,
        shift_end=calendar.shift_end,
        holidays=frozenset(holidays.all()),
        time_zone=ZoneInfo(site.time_zone),
    )


async def _calendar_out(db: AsyncSession, site: Site) -> CalendarOut:
    calendar = await db.scalar(select(SiteCalendar).where(SiteCalendar.site_id == site.id))
    holidays = (
        await db.scalars(
            select(SiteHoliday)
            .where(SiteHoliday.site_id == site.id)
            .order_by(SiteHoliday.holiday_date)
        )
    ).all()
    upcoming: list[CalendarDay] = []
    work = await load_work_calendar(db, site)
    if work is not None:
        names = {holiday.holiday_date: holiday.name for holiday in holidays}
        today = datetime.now(ZoneInfo(site.time_zone)).date()
        for offset in range(14):
            day = today + timedelta(days=offset)
            reason = None
            if day in names:
                reason = names[day]
            elif day.isoweekday() not in work.working_days:
                reason = "Weekly off"
            upcoming.append(CalendarDay(day=day, working=reason is None, reason=reason))
    return CalendarOut(
        site_id=site.id,
        configured=calendar is not None,
        working_days=[int(day) for day in calendar.working_days] if calendar else None,
        shift_start=calendar.shift_start if calendar else None,
        shift_end=calendar.shift_end if calendar else None,
        minutes_per_day=work.minutes_per_day if work else None,
        version=calendar.version if calendar else None,
        holidays=[HolidayOut.model_validate(holiday) for holiday in holidays],
        upcoming=upcoming,
    )


@router.get("/sites/{site_id}/calendar", response_model=CalendarOut)
async def get_calendar(
    site_id: uuid.UUID,
    context: AuthContext = Depends(require_permission("workspace:read")),
    db: AsyncSession = Depends(get_db),
):
    return await _calendar_out(db, await _accessible_site(db, context, site_id))


@router.put(
    "/sites/{site_id}/calendar",
    response_model=CalendarOut,
    dependencies=[Depends(require_csrf)],
)
async def save_calendar(
    site_id: uuid.UUID,
    payload: CalendarUpdate,
    request: Request,
    context: AuthContext = Depends(require_permission("sites:manage")),
    db: AsyncSession = Depends(get_db),
):
    site = await _accessible_site(db, context, site_id)
    if payload.shift_end <= payload.shift_start:
        raise HTTPException(status_code=422, detail="The shift must end after it starts")
    days = "".join(str(day) for day in payload.working_days)
    calendar = await db.scalar(select(SiteCalendar).where(SiteCalendar.site_id == site.id))
    before = None
    if calendar is None:
        if payload.version is not None:
            raise HTTPException(status_code=409, detail=STALE)
        calendar = SiteCalendar(tenant_id=context.tenant.id, site_id=site.id)
        db.add(calendar)
    else:
        if payload.version != calendar.version:
            raise HTTPException(status_code=409, detail=STALE)
        before = {
            "working_days": calendar.working_days,
            "shift_start": calendar.shift_start.isoformat("minutes"),
            "shift_end": calendar.shift_end.isoformat("minutes"),
        }
    calendar.working_days = days
    calendar.shift_start = payload.shift_start
    calendar.shift_end = payload.shift_end
    calendar.updated_by = context.user.id
    after = {
        "working_days": days,
        "shift_start": payload.shift_start.isoformat("minutes"),
        "shift_end": payload.shift_end.isoformat("minutes"),
    }
    if before != after:
        audit(
            db,
            context,
            request,
            "organization.calendar.saved",
            {"site_id": str(site.id), "before": before, "after": after},
        )
    await commit_or_conflict(db, STALE)
    return await _calendar_out(db, site)


@router.post(
    "/sites/{site_id}/holidays",
    response_model=HolidayOut,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
async def add_holiday(
    site_id: uuid.UUID,
    payload: HolidayCreate,
    request: Request,
    context: AuthContext = Depends(require_permission("sites:manage")),
    db: AsyncSession = Depends(get_db),
):
    site = await _accessible_site(db, context, site_id)
    holiday = SiteHoliday(
        tenant_id=context.tenant.id,
        site_id=site.id,
        holiday_date=payload.holiday_date,
        name=payload.name,
    )
    db.add(holiday)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="That date is already a holiday at this site"
        ) from exc
    audit(
        db,
        context,
        request,
        "organization.holiday.added",
        {"site_id": str(site.id), "date": payload.holiday_date.isoformat(), "name": payload.name},
    )
    await db.commit()
    return holiday


@router.delete(
    "/sites/{site_id}/holidays/{holiday_id}",
    status_code=204,
    dependencies=[Depends(require_csrf)],
)
async def remove_holiday(
    site_id: uuid.UUID,
    holiday_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(require_permission("sites:manage")),
    db: AsyncSession = Depends(get_db),
):
    site = await _accessible_site(db, context, site_id)
    holiday = await db.scalar(
        select(SiteHoliday).where(SiteHoliday.id == holiday_id, SiteHoliday.site_id == site.id)
    )
    if holiday is None:
        raise HTTPException(status_code=404, detail="Holiday not found")
    audit(
        db,
        context,
        request,
        "organization.holiday.removed",
        {
            "site_id": str(site.id),
            "date": holiday.holiday_date.isoformat(),
            "name": holiday.name,
        },
    )
    await db.delete(holiday)
    await db.commit()
    return Response(status_code=204)


# Document numbering


def _sequence_out(sequence: DocumentSequence) -> SequenceOut:
    return SequenceOut(
        document_type=sequence.document_type,
        prefix=sequence.prefix,
        next_number=sequence.next_number,
        padding=sequence.padding,
        version=sequence.version,
        preview=format_number(sequence.prefix, sequence.next_number, sequence.padding),
    )


@router.get("/numbering", response_model=list[SequenceOut])
async def list_numbering(
    context: AuthContext = Depends(require_permission("workspace:read")),
    db: AsyncSession = Depends(get_db),
):
    await ensure_sequences(db, context.tenant.id)
    await db.commit()
    rows = await db.scalars(
        select(DocumentSequence).where(DocumentSequence.tenant_id == context.tenant.id)
    )
    order = {name: index for index, name in enumerate(DOCUMENT_TYPES)}
    return [_sequence_out(row) for row in sorted(rows, key=lambda r: order[r.document_type])]


@router.put(
    "/numbering/{document_type}",
    response_model=SequenceOut,
    dependencies=[Depends(require_csrf)],
)
async def update_numbering(
    document_type: str,
    payload: SequenceUpdate,
    request: Request,
    context: AuthContext = Depends(require_permission("tenant:configure")),
    db: AsyncSession = Depends(get_db),
):
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=404, detail="Unknown document type")
    await ensure_sequences(db, context.tenant.id)
    sequence = await db.scalar(
        select(DocumentSequence)
        .where(
            DocumentSequence.tenant_id == context.tenant.id,
            DocumentSequence.document_type == document_type,
        )
        .with_for_update()
    )
    if payload.version != sequence.version:
        raise HTTPException(status_code=409, detail=STALE)
    if payload.next_number < sequence.next_number:
        raise HTTPException(
            status_code=409,
            detail="The next number cannot go backwards; earlier numbers may already be in use",
        )
    before = {
        "prefix": sequence.prefix,
        "padding": sequence.padding,
        "next_number": sequence.next_number,
    }
    sequence.prefix = payload.prefix
    sequence.padding = payload.padding
    sequence.next_number = payload.next_number
    after = {
        "prefix": payload.prefix,
        "padding": payload.padding,
        "next_number": payload.next_number,
    }
    if before != after:
        audit(
            db,
            context,
            request,
            "organization.numbering.updated",
            {"document_type": document_type, "before": before, "after": after},
        )
    await db.commit()
    await db.refresh(sequence)
    return _sequence_out(sequence)
