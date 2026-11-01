from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_investigation, get_report
from app.api.serializers import report_summary
from app.db import get_db
from app.models import Report, User
from app.security import audit, require
from app.services.report_pdf import render_pdf
from app.services.reports import SECTION_TITLES, create_report, evidence_csv, normalize_snapshot, version_history

router = APIRouter(prefix="/reports", tags=["reports"])


class ReportBody(BaseModel):
    investigation_id: str


@router.get("")
def list_reports(db: Session = Depends(get_db), user: User = Depends(require("investigations.read"))):
    rows = db.scalars(
        select(Report).where(Report.workspace_id == user.workspace_id).order_by(Report.created_at.desc())
    ).all()
    return [report_summary(r) for r in rows]


@router.post("", status_code=201)
def generate(
    body: ReportBody, request: Request, db: Session = Depends(get_db), user: User = Depends(require("reports.write"))
):
    investigation = get_investigation(db, user, body.investigation_id)
    report = create_report(db, investigation, user)
    audit(db, user, user.workspace_id, "report.generated", report.ref, request=request)
    db.commit()
    return report_summary(report)


@router.get("/{report_id}")
def read_report(report_id: str, db: Session = Depends(get_db), user: User = Depends(require("investigations.read"))):
    report = get_report(db, user, report_id)
    return {
        **report_summary(report),
        "snapshot": normalize_snapshot(report.snapshot),
        "sections": SECTION_TITLES,
        "versions": version_history(db, report),
    }


@router.get("/{report_id}/export.pdf")
def export_pdf(
    report_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("investigations.read")),
):
    report = get_report(db, user, report_id)
    audit(db, user, user.workspace_id, "report.exported", report.ref, {"format": "pdf"}, request)
    db.commit()
    return Response(
        render_pdf(report),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report.ref}.pdf"'},
    )


@router.get("/{report_id}/evidence.csv")
def export_csv(
    report_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("investigations.read")),
):
    report = get_report(db, user, report_id)
    audit(db, user, user.workspace_id, "report.exported", report.ref, {"format": "csv"}, request)
    db.commit()
    return Response(
        evidence_csv(report),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{report.ref}-evidence.csv"'},
    )
