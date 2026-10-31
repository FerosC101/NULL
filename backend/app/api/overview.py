from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_workspace
from app.api.serializers import investigation_summary
from app.db import get_db
from app.models import Finding, Investigation, RecommendedCheck, Remediation, User
from app.security import require
from app.services.assurance import preventive_scan

router = APIRouter(prefix="/overview", tags=["overview"])

OPEN_STATES = ("queued", "analyzing", "awaiting_approval", "running_checks")
SETTLED = ("SUPPORTED", "CONTRADICTED")


@router.get("")
def overview(db: Session = Depends(get_db), user: User = Depends(require("investigations.read"))):
    workspace = get_workspace(db, user)
    dataset = (workspace.settings or {}).get("active_dataset", "A")
    investigations = db.scalars(
        select(Investigation)
        .options(joinedload(Investigation.assignee))
        .where(Investigation.workspace_id == user.workspace_id)
        .order_by(Investigation.updated_at.desc())
    ).all()
    ids = [i.id for i in investigations]
    by_id = {i.id: i for i in investigations}
    findings = db.scalars(select(Finding).where(Finding.investigation_id.in_(ids))).all()
    remediations = db.scalars(select(Remediation).where(Remediation.workspace_id == user.workspace_id)).all()
    pending_checks = db.scalars(
        select(RecommendedCheck).where(
            RecommendedCheck.investigation_id.in_(ids), RecommendedCheck.status == "proposed"
        )
    ).all()
    scan = preventive_scan(db, user.workspace_id, dataset)

    verified = [r for r in remediations if r.verification_status == "verified"]
    open_actions = [r for r in remediations if r.verification_status != "verified" and r.approval_status != "rejected"]
    critical = [f for f in findings if f.severity == "critical"]

    status_counts: dict[str, int] = {}
    for investigation in investigations:
        status_counts[investigation.status] = status_counts.get(investigation.status, 0) + 1

    attention: list[dict] = []
    for investigation_id in {c.investigation_id for c in pending_checks}:
        investigation = by_id[investigation_id]
        if investigation.status == "awaiting_approval":
            attention.append(
                {
                    "kind": "approval",
                    "severity": "high",
                    "title": f"{investigation.name} is waiting for approval",
                    "detail": f"{investigation.assessment.title()} until a recommended check runs.",
                    "href": f"/investigations/{investigation.id}#recommended",
                }
            )
    for finding in critical:
        investigation = by_id[finding.investigation_id]
        attention.append(
            {
                "kind": "finding",
                "severity": "critical",
                "title": finding.title,
                "detail": investigation.name,
                "href": f"/investigations/{investigation.id}#discovered",
            }
        )
    for source in scan["disconnected_sources"]:
        attention.append(
            {
                "kind": "source",
                "severity": "high",
                "title": f"{source['name']} is disconnected",
                "detail": "No investigation can read this source.",
                "href": "/sources",
            }
        )
    for remediation in remediations:
        if remediation.verification_status in ("awaiting", "failed", "recurred"):
            label = {
                "awaiting": "is awaiting verification",
                "failed": "failed verification",
                "recurred": "has recurred",
            }[remediation.verification_status]
            attention.append(
                {
                    "kind": "remediation",
                    "severity": "high",
                    "title": f"{remediation.ref} {label}",
                    "detail": remediation.action,
                    "href": "/assurance#mitigation",
                }
            )
    order = {"critical": 0, "high": 1, "medium": 2}
    attention.sort(key=lambda a: order.get(a["severity"], 3))

    return {
        "metrics": {
            "active_investigations": sum(1 for i in investigations if i.status in OPEN_STATES),
            "unresolved_claims": sum(1 for i in investigations if i.assessment not in SETTLED),
            "critical_gaps": len(critical),
            "open_actions": len(open_actions),
            "verified_remediations": len(verified),
        },
        "assurance": {
            "dataset": dataset,
            "coverage": scan["coverage"],
            "collection_weaknesses": scan["collection_weaknesses"],
            "disconnected_sources": scan["disconnected_sources"],
            "status_counts": status_counts,
            "remediation": {
                "pending": sum(1 for r in remediations if r.approval_status == "pending"),
                "approved": sum(
                    1 for r in remediations if r.approval_status == "approved" and r.execution_status != "executed"
                ),
                "executed": sum(
                    1 for r in remediations if r.execution_status == "executed" and r.verification_status != "verified"
                ),
                "verified": len(verified),
                "total": len(remediations),
            },
        },
        "recent": [{**investigation_summary(i), "conclusion": i.assessment_rationale} for i in investigations[:6]],
        "attention": attention[:8],
    }
