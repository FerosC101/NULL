from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Investigation, Remediation, Report, User, Workspace


def get_investigation(db: Session, user: User, investigation_id: str) -> Investigation:
    investigation = db.get(Investigation, investigation_id)
    if investigation is None or investigation.workspace_id != user.workspace_id:
        raise HTTPException(404, "Investigation not found")
    return investigation


def get_remediation(db: Session, user: User, remediation_id: str) -> Remediation:
    remediation = db.get(Remediation, remediation_id)
    if remediation is None or remediation.workspace_id != user.workspace_id:
        raise HTTPException(404, "Remediation not found")
    return remediation


def get_report(db: Session, user: User, report_id: str) -> Report:
    report = db.get(Report, report_id)
    if report is None or report.workspace_id != user.workspace_id:
        raise HTTPException(404, "Report not found")
    return report


def get_workspace(db: Session, user: User) -> Workspace:
    return db.scalar(select(Workspace).where(Workspace.id == user.workspace_id))
