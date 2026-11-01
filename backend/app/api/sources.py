from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import get_workspace
from app.api.serializers import source_out
from app.db import get_db
from app.demo.generator import DATASETS
from app.models import DataSource, EvidenceRecord, User, utcnow
from app.security import audit, require
from app.services.assurance import preventive_scan
from app.services.exhibits import workspace_matrix

router = APIRouter(prefix="/sources", tags=["sources"])


class SnapshotBody(BaseModel):
    dataset: str

    @field_validator("dataset")
    @classmethod
    def known(cls, value: str) -> str:
        if value not in DATASETS:
            raise ValueError("Unknown dataset")
        return value


def _stats(db: Session, dataset: str) -> dict:
    rows = db.execute(
        select(EvidenceRecord.source_key, func.count(), func.min(EvidenceRecord.ts), func.max(EvidenceRecord.ts))
        .where(EvidenceRecord.dataset == dataset)
        .group_by(EvidenceRecord.source_key)
    ).all()
    return {r[0]: r[1:] for r in rows}


@router.get("")
def list_sources(db: Session = Depends(get_db), user: User = Depends(require("investigations.read"))):
    workspace = get_workspace(db, user)
    dataset = (workspace.settings or {}).get("active_dataset", "A")
    stats = _stats(db, dataset)
    sources = db.scalars(select(DataSource).where(DataSource.workspace_id == user.workspace_id)).all()
    sources = sorted(sources, key=lambda s: (s.status != "connected", s.name))
    scan = preventive_scan(db, user.workspace_id, dataset)
    coverage_text: dict[str, str] = {}
    if scan["coverage"]:
        coverage = scan["coverage"]
        coverage_text["coverage"] = f"{coverage['reporting']} of {coverage['hosts']} hosts reporting"
        coverage_text["inventory"] = f"{coverage['hosts']} hosts listed"
    if scan["collection_weaknesses"]:
        missing = sum(w["missing_hours"] for w in scan["collection_weaknesses"])
        coverage_text["network"] = f"{missing} subnet-hours missing"
    out = []
    for source in sources:
        count, earliest, latest = stats.get(source.key, (0, None, None))
        out.append(source_out(source, count, earliest, latest, coverage_text.get(source.key)))
    return {
        "active_dataset": dataset,
        "datasets": [{"key": k, "label": v["label"]} for k, v in DATASETS.items()],
        "sources": out,
    }


@router.get("/coverage")
def source_coverage(db: Session = Depends(get_db), user: User = Depends(require("investigations.read"))):
    workspace = get_workspace(db, user)
    return workspace_matrix(db, user.workspace_id, (workspace.settings or {}).get("active_dataset", "A"))


@router.post("/snapshot")
def set_snapshot(
    body: SnapshotBody, request: Request, db: Session = Depends(get_db), user: User = Depends(require("sources.manage"))
):
    workspace = get_workspace(db, user)
    workspace.settings = {**(workspace.settings or {}), "active_dataset": body.dataset}
    flag_modified(workspace, "settings")
    audit(db, user, user.workspace_id, "source.snapshot_changed", body.dataset, request=request)
    db.commit()
    return {"active_dataset": body.dataset}


def _source(db: Session, user: User, key: str) -> DataSource:
    source = db.scalar(select(DataSource).where(DataSource.workspace_id == user.workspace_id, DataSource.key == key))
    if source is None:
        raise HTTPException(404, "Source not found")
    return source


@router.post("/{key}/sync")
def sync(key: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require("sources.manage"))):
    source = _source(db, user, key)
    if source.status != "connected":
        raise HTTPException(409, f"{source.name} is not connected")
    workspace = get_workspace(db, user)
    dataset = (workspace.settings or {}).get("active_dataset", "A")
    count = _stats(db, dataset).get(key, (0, None, None))[0]
    source.last_sync_at = utcnow()
    audit(db, user, user.workspace_id, "source.synced", key, {"records": count}, request)
    db.commit()
    return {"records": count, "last_sync_at": source.last_sync_at}


@router.post("/{key}/disconnect")
def disconnect(
    key: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require("sources.manage"))
):
    source = _source(db, user, key)
    source.status = "disconnected"
    audit(db, user, user.workspace_id, "source.disconnected", key, request=request)
    db.commit()
    return {"status": source.status}


@router.post("/{key}/connect")
def connect(key: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require("sources.manage"))):
    source = _source(db, user, key)
    workspace = get_workspace(db, user)
    dataset = (workspace.settings or {}).get("active_dataset", "A")
    if key not in _stats(db, dataset):
        raise HTTPException(409, f"{source.name} has no integration or demo records, so it can't be connected.")
    source.status = "connected"
    source.last_sync_at = utcnow()
    audit(db, user, user.workspace_id, "source.connected", key, request=request)
    db.commit()
    return {"status": source.status}
