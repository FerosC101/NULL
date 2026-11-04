from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.analysis.claims import compile_claim
from app.api.deps import get_investigation, get_workspace
from app.api.serializers import investigation_card, investigation_detail, raw_records
from app.db import get_db
from app.demo.seed import next_ref
from app.models import DataSource, EvidenceItem, GroundTruth, Investigation, RecommendedCheck, User, utcnow
from app.security import audit, require
from app.services import exhibits
from app.services.datasets import DatasetInfo, active, available, describe, last_hours
from app.services.orchestrator import analyze, create_timeline, execute_checks, in_background

router = APIRouter(prefix="/investigations", tags=["investigations"])

WINDOW_HOURS = {6: "Last 6 hours", 12: "Last 12 hours", 24: "Last 24 hours"}
ASSET_CLASSES = {"workstation": "Workstations", "server": "Servers", "ot_gateway": "OT gateways"}


class ClaimBody(BaseModel):
    claim: str = Field(min_length=8, max_length=1000)


class InvestigationBody(ClaimBody):
    name: str = Field(min_length=2, max_length=200)
    objective: str = Field(default="", max_length=2000)
    dataset: str
    window_hours: int = 24
    window_start: datetime | None = None
    window_end: datetime | None = None
    asset_classes: list[str] = []
    source_keys: list[str] = Field(min_length=1, max_length=20)

    @field_validator("window_hours")
    @classmethod
    def known_window(cls, value: int) -> int:
        if value not in WINDOW_HOURS:
            raise ValueError("Unsupported window")
        return value

    @field_validator("asset_classes")
    @classmethod
    def known_assets(cls, value: list[str]) -> list[str]:
        if any(v not in ASSET_CLASSES for v in value):
            raise ValueError("Unknown asset class")
        return value


class ApprovalBody(BaseModel):
    check_ids: list[str] = Field(min_length=1, max_length=10)
    acknowledged: bool


class RejectBody(BaseModel):
    check_ids: list[str] = Field(min_length=1, max_length=10)
    reason: str = Field(default="", max_length=500)


def _resolve_window(dataset: DatasetInfo, body: InvestigationBody) -> tuple[datetime, datetime, str]:
    """The period under examination. It has to sit inside the records, on whole hours, for the hourly tests."""
    if body.window_start is None and body.window_end is None:
        start, end = last_hours(dataset, body.window_hours)
        if end - start == timedelta(hours=body.window_hours):
            return start, end, f"{WINDOW_HOURS[body.window_hours]} of the snapshot"
        hours = int((end - start).total_seconds() // 3600)
        return start, end, f"All {hours} hour{'' if hours == 1 else 's'} of the dataset"
    start, end = body.window_start, body.window_end
    if start is None or end is None or start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(422, "Give both a start and an end, with a time zone")
    if start >= end:
        raise HTTPException(422, "The period must end after it starts")
    if start.minute or start.second or end.minute or end.second:
        raise HTTPException(422, "The period must start and end on the hour")
    if start < dataset.window_start or end > dataset.window_end:
        raise HTTPException(422, "The period must fall inside the dataset")
    return start, end, "Custom period"


@router.get("/options")
def options(db: Session = Depends(get_db), user: User = Depends(require("investigations.read"))):
    sources = db.scalars(select(DataSource).where(DataSource.workspace_id == user.workspace_id)).all()
    return {
        "active_dataset": active(db, get_workspace(db, user)).key,
        "datasets": [d.out() for d in available(db, user.workspace_id)],
        "windows": [{"hours": h, "label": f"{label} of the snapshot"} for h, label in WINDOW_HOURS.items()],
        "asset_classes": [{"key": k, "label": v} for k, v in ASSET_CLASSES.items()],
        "sources": [
            {"key": s.key, "name": s.name, "status": s.status, "mode": s.mode, "restricted": s.restricted}
            for s in sources
        ],
        "assignees": [
            {"id": u.id, "name": u.name}
            for u in db.scalars(select(User).where(User.workspace_id == user.workspace_id, User.is_active))
            if u.role != "viewer"
        ],
    }


@router.post("/compile")
def compile_preview(body: ClaimBody, user: User = Depends(require("investigations.read"))):
    return compile_claim(body.claim).to_dict()


@router.get("")
def list_investigations(
    q: str = Query(default="", max_length=200),
    status: str = "",
    assessment: str = "",
    since: datetime | None = None,
    until: datetime | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require("investigations.read")),
):
    query = (
        select(Investigation)
        .options(joinedload(Investigation.assignee))
        .where(Investigation.workspace_id == user.workspace_id)
    )
    if q:
        like = f"%{q}%"
        query = query.where(
            or_(Investigation.name.ilike(like), Investigation.claim_text.ilike(like), Investigation.ref.ilike(like))
        )
    if status:
        query = query.where(Investigation.status == status)
    if assessment:
        query = query.where(Investigation.assessment == assessment)
    if since:
        query = query.where(Investigation.created_at >= since)
    if until:
        query = query.where(Investigation.created_at <= until)
    rows = db.scalars(query.order_by(Investigation.updated_at.desc())).all()
    return [investigation_card(db, i) for i in rows]


@router.post("", status_code=201)
def create_investigation(
    body: InvestigationBody,
    background: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("investigations.write")),
):
    known = {s.key for s in db.scalars(select(DataSource).where(DataSource.workspace_id == user.workspace_id))}
    unknown = set(body.source_keys) - known
    if unknown:
        raise HTTPException(422, f"Unknown sources: {', '.join(sorted(unknown))}")
    dataset = describe(db, body.dataset, user.workspace_id)
    if dataset is None:
        raise HTTPException(422, "Unknown dataset")
    window_start, window_end, window_label = _resolve_window(dataset, body)
    labels = [ASSET_CLASSES[a] for a in body.asset_classes]
    investigation = Investigation(
        workspace_id=user.workspace_id,
        ref=next_ref(db),
        name=body.name.strip(),
        claim_text=body.claim.strip(),
        objective=body.objective.strip(),
        dataset=body.dataset,
        scope={
            "window_start": window_start.astimezone(UTC).isoformat(),
            "window_end": window_end.astimezone(UTC).isoformat(),
            "window_label": window_label,
            "assets_label": ", ".join(labels) or "All in-scope assets",
            "asset_classes": body.asset_classes,
        },
        source_keys=body.source_keys,
        created_by_id=user.id,
        assignee_id=user.id,
    )
    db.add(investigation)
    db.flush()
    create_timeline(db, investigation)
    audit(db, user, user.workspace_id, "investigation.created", investigation.ref, request=request)
    db.commit()
    background.add_task(in_background, analyze, investigation.id)
    return {"id": investigation.id, "ref": investigation.ref}


@router.get("/{investigation_id}")
def get_detail(
    investigation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require("investigations.read")),
):
    return investigation_detail(db, get_investigation(db, user, investigation_id))


@router.get("/{investigation_id}/exhibits")
def get_exhibits(
    investigation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require("investigations.read")),
):
    return exhibits.compute(db, get_investigation(db, user, investigation_id))


@router.get("/{investigation_id}/evidence/{ref}")
def get_evidence(
    investigation_id: str,
    ref: str,
    db: Session = Depends(get_db),
    user: User = Depends(require("investigations.read")),
):
    investigation = get_investigation(db, user, investigation_id)
    item = db.scalar(
        select(EvidenceItem).where(EvidenceItem.investigation_id == investigation.id, EvidenceItem.ref == ref)
    )
    if item is None:
        raise HTTPException(404, "Evidence not found")
    return {"records": raw_records(db, item.provenance.get("record_ids", []))}


def _open_checks(db: Session, investigation: Investigation, ids: list[str]) -> list[RecommendedCheck]:
    rows = db.scalars(
        select(RecommendedCheck).where(
            RecommendedCheck.id.in_(ids), RecommendedCheck.investigation_id == investigation.id
        )
    ).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more checks were not found")
    if any(r.status not in ("proposed", "blocked", "failed") for r in rows):
        raise HTTPException(409, "One or more checks have already been decided")
    return list(rows)


@router.post("/{investigation_id}/checks/approve")
def approve_checks(
    investigation_id: str,
    body: ApprovalBody,
    background: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("checks.approve")),
):
    if not body.acknowledged:
        raise HTTPException(422, "Approval must be acknowledged")
    investigation = get_investigation(db, user, investigation_id)
    if investigation.status != "awaiting_approval":
        raise HTTPException(409, f"Investigation is {investigation.status}, not awaiting approval")
    security = (get_workspace(db, user).settings or {}).get("security", {})
    if security.get("separate_approver") and investigation.created_by_id == user.id:
        raise HTTPException(403, "This workspace requires a different person to approve your investigation's checks")
    rows = _open_checks(db, investigation, body.check_ids)
    for row in rows:
        row.status = "approved"
        row.decided_by_id = user.id
        row.decided_at = utcnow()
    investigation.status = "running_checks"
    audit(db, user, user.workspace_id, "check.approved", investigation.ref, {"checks": [r.tool for r in rows]}, request)
    db.commit()
    background.add_task(in_background, execute_checks, investigation.id, [r.id for r in rows])
    return {"status": "running_checks"}


@router.post("/{investigation_id}/checks/reject")
def reject_checks(
    investigation_id: str,
    body: RejectBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("checks.approve")),
):
    investigation = get_investigation(db, user, investigation_id)
    if investigation.status != "awaiting_approval":
        raise HTTPException(409, f"Investigation is {investigation.status}, not awaiting approval")
    rows = _open_checks(db, investigation, body.check_ids)
    for row in rows:
        row.status = "rejected"
        row.decided_by_id = user.id
        row.decided_at = utcnow()
        row.error = body.reason
    audit(
        db,
        user,
        user.workspace_id,
        "check.rejected",
        investigation.ref,
        {"checks": [r.tool for r in rows], "reason": body.reason},
        request,
    )
    db.commit()
    from app.services.orchestrator import Run, _open, advance

    investigation, choice = _open(db, investigation_id)
    advance(Run(db, investigation, choice))
    return investigation_detail(db, investigation)


@router.get("/{investigation_id}/ground-truth")
def ground_truth(
    investigation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require("investigations.read")),
):
    """Answer key for the synthetic snapshot, shown only after an investigation concludes."""
    investigation = get_investigation(db, user, investigation_id)
    if investigation.status != "concluded":
        raise HTTPException(409, "The answer key is available only after the investigation concludes")
    truth = db.get(GroundTruth, investigation.dataset)
    if truth is None:
        raise HTTPException(404, "No answer key exists for this dataset")
    default_claim = investigation.compiled_claim.get("kind") == "absence_of_access"
    full_scope = not investigation.scope.get("asset_classes") and investigation.scope.get(
        "window_label", ""
    ).startswith("Last 24")
    comparable = default_claim and full_scope
    return {
        **truth.truth,
        "comparable": comparable,
        "matches": comparable and truth.truth["expected_assessment"] == investigation.assessment,
    }
