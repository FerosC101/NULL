from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_investigation, get_remediation, get_workspace
from app.api.serializers import remediation_out
from app.db import get_db
from app.models import Investigation, Remediation, User, VerificationRun, utcnow
from app.security import audit, require
from app.services.assurance import preventive_scan, unverified_assumptions
from app.services.graph import rebuild_graph
from app.services.remediation import execute_simulated, run_verification, simulate_recurrence

router = APIRouter(prefix="/assurance", tags=["assurance"])


class DecisionBody(BaseModel):
    note: str = Field(default="", max_length=1000)


class ModifyBody(BaseModel):
    action: str | None = Field(default=None, min_length=4, max_length=2000)
    priority: str | None = Field(default=None, pattern="^(critical|high|medium|low)$")
    owner_id: str | None = None


class ExecuteBody(BaseModel):
    confirmed: bool


def runs_for(db: Session, remediation_ids: list[str]) -> dict[str, list[VerificationRun]]:
    grouped: dict[str, list[VerificationRun]] = {}
    for run in db.scalars(
        select(VerificationRun)
        .where(VerificationRun.remediation_id.in_(remediation_ids))
        .order_by(VerificationRun.created_at.desc())
    ):
        grouped.setdefault(run.remediation_id, []).append(run)
    return grouped


@router.get("")
def assurance(db: Session = Depends(get_db), user: User = Depends(require("investigations.read"))):
    workspace = get_workspace(db, user)
    dataset = (workspace.settings or {}).get("active_dataset", "A")
    rows = db.scalars(
        select(Remediation)
        .options(joinedload(Remediation.owner))
        .where(Remediation.workspace_id == user.workspace_id)
        .order_by(Remediation.ref)
    ).all()
    runs = runs_for(db, [r.id for r in rows])
    refs = dict(
        db.execute(
            select(Investigation.id, Investigation.ref).where(Investigation.workspace_id == user.workspace_id)
        ).all()
    )
    remediations = [
        {**remediation_out(r, runs.get(r.id, [])), "investigation_ref": refs.get(r.investigation_id)} for r in rows
    ]
    return {
        "preventive": {
            **preventive_scan(db, user.workspace_id, dataset),
            "unverified_assumptions": unverified_assumptions(db, user.workspace_id),
        },
        "remediations": remediations,
    }


def _touch_graph(db: Session, remediation: Remediation) -> None:
    rebuild_graph(db, db.get(Investigation, remediation.investigation_id))


def _out(db: Session, remediation: Remediation) -> dict:
    runs = runs_for(db, [remediation.id])
    return remediation_out(remediation, runs.get(remediation.id, []))


@router.post("/remediations/{remediation_id}/approve")
def approve(
    remediation_id: str,
    body: DecisionBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("remediations.approve")),
):
    remediation = get_remediation(db, user, remediation_id)
    if remediation.approval_status == "approved":
        raise HTTPException(409, "This action is already approved")
    remediation.approval_status = "approved"
    remediation.decided_by_id = user.id
    remediation.decision_note = body.note
    audit(db, user, user.workspace_id, "remediation.approved", remediation.ref, {"note": body.note}, request)
    db.commit()
    return _out(db, remediation)


@router.post("/remediations/{remediation_id}/reject")
def reject(
    remediation_id: str,
    body: DecisionBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("remediations.approve")),
):
    remediation = get_remediation(db, user, remediation_id)
    if remediation.execution_status == "executed":
        raise HTTPException(409, "This action has already been executed")
    remediation.approval_status = "rejected"
    remediation.decided_by_id = user.id
    remediation.decision_note = body.note
    audit(db, user, user.workspace_id, "remediation.rejected", remediation.ref, {"note": body.note}, request)
    db.commit()
    return _out(db, remediation)


@router.patch("/remediations/{remediation_id}")
def modify(
    remediation_id: str,
    body: ModifyBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("remediations.write")),
):
    remediation = get_remediation(db, user, remediation_id)
    if remediation.execution_status == "executed":
        raise HTTPException(409, "An executed action can't be modified")
    changes = body.model_dump(exclude_none=True)
    if "owner_id" in changes:
        owner = db.get(User, changes["owner_id"])
        if owner is None or owner.workspace_id != user.workspace_id:
            raise HTTPException(422, "Unknown owner")
    for field, value in changes.items():
        setattr(remediation, field, value)
    # Changing what an approval covered voids that approval.
    if "action" in changes and remediation.approval_status == "approved":
        remediation.approval_status = "pending"
    audit(db, user, user.workspace_id, "remediation.modified", remediation.ref, changes, request)
    db.commit()
    db.refresh(remediation)
    return _out(db, remediation)


@router.post("/remediations/{remediation_id}/execute")
def execute(
    remediation_id: str,
    body: ExecuteBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("remediations.execute")),
):
    if not body.confirmed:
        raise HTTPException(422, "Execution must be confirmed")
    remediation = get_remediation(db, user, remediation_id)
    if remediation.approval_status != "approved":
        raise HTTPException(409, "This action has not been approved")
    if remediation.verification_status == "verified":
        raise HTTPException(409, "This action is already verified")
    investigation = get_investigation(db, user, remediation.investigation_id)
    message = execute_simulated(db, remediation, investigation.dataset)
    remediation.execution_status = "executed"
    remediation.executed_at = utcnow()
    remediation.verification_status = "awaiting"
    audit(
        db,
        user,
        user.workspace_id,
        "remediation.executed",
        remediation.ref,
        {"message": message, "integration": "simulated"},
        request,
    )
    db.commit()
    return {**_out(db, remediation), "message": message}


@router.post("/remediations/{remediation_id}/verify")
def verify(
    remediation_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("remediations.write")),
):
    remediation = get_remediation(db, user, remediation_id)
    investigation = get_investigation(db, user, remediation.investigation_id)
    try:
        run = run_verification(db, remediation, investigation.dataset, user)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit(
        db,
        user,
        user.workspace_id,
        "remediation.verified",
        remediation.ref,
        {"passed": run.passed, "summary": run.summary},
        request,
    )
    _touch_graph(db, remediation)
    db.commit()
    return _out(db, remediation)


@router.post("/remediations/{remediation_id}/simulate-recurrence")
def recurrence(
    remediation_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("remediations.execute")),
):
    remediation = get_remediation(db, user, remediation_id)
    if remediation.verification_status != "verified":
        raise HTTPException(409, "Only a verified action can recur")
    investigation = get_investigation(db, user, remediation.investigation_id)
    try:
        message = simulate_recurrence(db, remediation, investigation.dataset)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit(db, user, user.workspace_id, "demo.recurrence_simulated", remediation.ref, {"message": message}, request)
    db.commit()
    return {"message": message}
