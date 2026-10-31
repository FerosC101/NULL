"""Read access to raw evidence. Everything the engine knows passes through this module."""

from datetime import datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataSource, EvidenceRecord


class SourceUnavailable(Exception):
    def __init__(self, source_key: str, reason: str):
        super().__init__(f"{source_key}: {reason}")
        self.source_key = source_key
        self.reason = reason


class EvidenceReader:
    """Scoped reader. A source can be read only if it is selected and actually connected."""

    def __init__(
        self,
        db: Session,
        workspace_id: str,
        dataset: str,
        allowed: set[str],
        as_of: datetime | None,
        asset_classes: list[str] | None = None,
    ):
        self.db = db
        self.workspace_id = workspace_id
        self.dataset = dataset
        self.allowed = allowed
        self.as_of = as_of
        self.asset_classes = asset_classes or None
        self.records_read = 0
        self._cache: dict[str, pd.DataFrame] = {}

    def _assert_readable(self, source_key: str) -> None:
        if source_key not in self.allowed:
            raise SourceUnavailable(source_key, "not selected for this investigation")
        source = self.db.scalar(
            select(DataSource).where(DataSource.workspace_id == self.workspace_id, DataSource.key == source_key)
        )
        if source is None or source.status != "connected":
            raise SourceUnavailable(source_key, "source is not connected")

    def frame(self, source_key: str) -> pd.DataFrame:
        self._assert_readable(source_key)
        if source_key in self._cache:
            return self._cache[source_key]
        query = select(EvidenceRecord.id, EvidenceRecord.ts, EvidenceRecord.entity, EvidenceRecord.payload).where(
            EvidenceRecord.dataset == self.dataset, EvidenceRecord.source_key == source_key
        )
        if self.as_of is not None:
            query = query.where(EvidenceRecord.ts <= self.as_of)
        rows = self.db.execute(query.order_by(EvidenceRecord.ts)).all()
        frame = pd.DataFrame([{"record_id": r.id, "ts": r.ts, "entity": r.entity, **r.payload} for r in rows])
        if frame.empty:
            frame = pd.DataFrame(columns=["record_id", "ts", "entity"])
        frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
        frame = self._apply_asset_scope(source_key, frame)
        self.records_read += len(frame)
        self._cache[source_key] = frame
        return frame

    def _apply_asset_scope(self, source_key: str, frame: pd.DataFrame) -> pd.DataFrame:
        """Keep only records for hosts in the investigation's asset scope."""
        if not self.asset_classes or "hostname" not in frame:
            return frame
        if source_key == "inventory":
            return frame[frame["asset_class"].isin(self.asset_classes)]
        rows = self.db.scalars(
            select(EvidenceRecord.payload).where(
                EvidenceRecord.dataset == self.dataset, EvidenceRecord.source_key == "inventory"
            )
        ).all()
        hosts = {r["hostname"] for r in rows if r["asset_class"] in self.asset_classes}
        return frame[frame["hostname"].isna() | frame["hostname"].isin(hosts)]
