import uuid

from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import DOCUMENT_TYPES, DocumentSequence

DEFAULT_PREFIXES = {"sales_order": "SO-", "outsourced_batch": "OB-", "dispatch": "DN-"}
DEFAULT_PADDING = 5


def format_number(prefix: str, number: int, padding: int) -> str:
    return f"{prefix}{number:0{padding}d}"


async def ensure_sequences(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Create any missing sequences for the tenant; safe under concurrent calls."""
    dialect = db.get_bind().dialect.name
    insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
    rows = [
        {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "document_type": document_type,
            "prefix": DEFAULT_PREFIXES[document_type],
            "next_number": 1,
            "padding": DEFAULT_PADDING,
            "version": 1,
        }
        for document_type in DOCUMENT_TYPES
    ]
    await db.execute(
        insert(DocumentSequence)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["tenant_id", "document_type"])
    )


async def allocate_number(db: AsyncSession, tenant_id: uuid.UUID, document_type: str) -> str:
    """Reserve the next number inside the caller's transaction.

    The sequence row stays locked until the caller commits, and a rollback returns the number,
    so committed documents get consecutive numbers without duplicates.
    """
    if document_type not in DOCUMENT_TYPES:
        raise ValueError(f"Unknown document type {document_type}")
    await ensure_sequences(db, tenant_id)
    sequence = await db.scalar(
        select(DocumentSequence)
        .where(
            DocumentSequence.tenant_id == tenant_id,
            DocumentSequence.document_type == document_type,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    number = format_number(sequence.prefix, sequence.next_number, sequence.padding)
    sequence.next_number += 1
    await db.flush()
    return number
