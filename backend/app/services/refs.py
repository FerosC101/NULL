"""Human-readable references. Allocation is serialized so two simultaneous requests can't take the same number."""

import zlib

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def next_ref(db: Session, model, prefix: str) -> str:
    # The lock is released when the transaction ends, by which time the new row is visible to the next caller.
    db.execute(select(func.pg_advisory_xact_lock(zlib.crc32(prefix.encode()))))
    return f"{prefix}-{(db.scalar(select(func.count(model.id))) or 0) + 1:04d}"
