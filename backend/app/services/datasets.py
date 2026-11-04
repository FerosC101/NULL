"""The evidence sets a workspace can investigate: fixed demo snapshots and uploaded files."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.demo.generator import DATASETS, WINDOW_END, WINDOW_START
from app.models import Dataset

DEMO = "demo"
UPLOAD = "upload"

NOTICES = {
    (DEMO, "synthetic"): "Synthetic demonstration data for a fictional company. No real organization was examined.",
    (UPLOAD, "synthetic"): "Synthetic test data uploaded from files. No real organization was examined.",
    (UPLOAD, "real"): "Evidence uploaded from exported files. NULL did not collect it and cannot see what the "
    "exports left out.",
}


@dataclass(frozen=True)
class DatasetInfo:
    key: str
    label: str
    origin: str
    data_class: str
    window_start: datetime
    window_end: datetime
    allow_model: bool = True

    @property
    def notice(self) -> str:
        return NOTICES[(self.origin, self.data_class)]

    def out(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "origin": self.origin,
            "data_class": self.data_class,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "allow_model": self.allow_model,
        }


def _demo(key: str) -> DatasetInfo:
    return DatasetInfo(key, DATASETS[key]["label"], DEMO, "synthetic", WINDOW_START, WINDOW_END)


def _upload(row: Dataset) -> DatasetInfo:
    allow_model = row.data_class == "synthetic" or bool(row.summary.get("allow_model"))
    return DatasetInfo(row.key, row.label, UPLOAD, row.data_class, row.window_start, row.window_end, allow_model)


def describe(db: Session, key: str, workspace_id: str | None = None) -> DatasetInfo | None:
    """One dataset the workspace can read. Drafts aren't readable, and neither is another workspace's upload."""
    if key in DATASETS:
        return _demo(key)
    row = db.get(Dataset, key)
    if row is None or row.status != "ready" or (workspace_id and row.workspace_id != workspace_id):
        return None
    return _upload(row)


def available(db: Session, workspace_id: str) -> list[DatasetInfo]:
    uploads = db.scalars(
        select(Dataset)
        .where(Dataset.workspace_id == workspace_id, Dataset.status == "ready")
        .order_by(Dataset.created_at.desc())
    )
    return [_upload(row) for row in uploads] + [_demo(key) for key in DATASETS]


def active(db: Session, workspace) -> DatasetInfo:
    key = (workspace.settings or {}).get("active_dataset", "A")
    return describe(db, key, workspace.id) or _demo("A")


def last_hours(info: DatasetInfo, hours: int) -> tuple[datetime, datetime]:
    """The latest whole hours of a dataset, cut short if it doesn't hold that many."""
    return max(info.window_end - timedelta(hours=hours), info.window_start), info.window_end
