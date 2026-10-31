from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.observables import OBSERVABLE_LABELS
from app.config import get_settings
from app.demo.generator import DATASETS
from app.models import (
    Assumption,
    DataSource,
    EvidenceItem,
    EvidenceRecord,
    Finding,
    Hypothesis,
    Investigation,
    RecommendedCheck,
    Remediation,
    Report,
    TimelineEvent,
    ToolExecution,
    User,
    VerificationRun,
)
from app.security import ROLE_PERMISSIONS
from app.services.orchestrator import STAGES

STAGE_LABELS = dict(STAGES)


def user_out(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "title": user.title,
        "role": user.role,
        "is_active": user.is_active,
        "permissions": sorted(ROLE_PERMISSIONS.get(user.role, set())),
    }


def investigation_summary(investigation: Investigation) -> dict:
    return {
        "id": investigation.id,
        "ref": investigation.ref,
        "name": investigation.name,
        "claim": investigation.claim_text,
        "status": investigation.status,
        "assessment": investigation.assessment,
        "dataset": investigation.dataset,
        "dataset_label": DATASETS.get(investigation.dataset, {}).get("label", investigation.dataset),
        "source_keys": investigation.source_keys,
        "assignee": investigation.assignee.name,
        "created_at": investigation.created_at,
        "updated_at": investigation.updated_at,
    }


def evidence_out(item: EvidenceItem) -> dict:
    return {
        "ref": item.ref,
        "source_key": item.source_key,
        "observable": item.observable,
        "observable_label": OBSERVABLE_LABELS.get(item.observable, item.observable),
        "observation": item.observation,
        "observed_at": item.observed_at,
        "reliability": item.reliability,
        "reliability_basis": item.reliability_basis,
        "relevance": item.relevance,
        "provenance": item.provenance,
        "primary": item.data.get("primary", False),
        "state": item.data.get("state"),
        "value": item.data.get("value"),
    }


def hypothesis_out(h: Hypothesis) -> dict:
    results = h.prediction_results or [{**p, "outcome": "untested"} for p in h.predictions]
    return {
        "label": h.label,
        "title": h.title,
        "statement": h.statement,
        "claim_true": h.claim_true,
        "origin": h.origin,
        "assumptions": h.assumptions,
        "compatibility": h.compatibility,
        "supporting": h.supporting,
        "contradicting": h.contradicting,
        "challenge": h.challenge,
        "predictions": [{**r, "label": OBSERVABLE_LABELS.get(r["observable"], r["observable"])} for r in results],
    }


def check_out(c: RecommendedCheck, users: dict[str, User]) -> dict:
    decider = users.get(c.decided_by_id or "")
    return {
        "id": c.id,
        "tool": c.tool,
        "title": c.title,
        "procedure": c.procedure,
        "rationale": c.rationale,
        "distinguishes": c.distinguishes,
        "information_gain_bits": c.information_gain_bits,
        "permissions": c.permissions,
        "operational_impact": c.operational_impact,
        "requires_sources": c.requires_sources,
        "status": c.status,
        "error": c.error,
        "decided_by": decider.name if decider else None,
        "decided_at": c.decided_at,
    }


def remediation_out(r: Remediation, runs: list[VerificationRun] | None = None) -> dict:
    return {
        "id": r.id,
        "ref": r.ref,
        "key": r.key,
        "investigation_id": r.investigation_id,
        "finding": r.finding,
        "root_cause": r.root_cause,
        "action": r.action,
        "priority": r.priority,
        "risk_addressed": r.risk_addressed,
        "owner": {"id": r.owner.id, "name": r.owner.name},
        "approval_status": r.approval_status,
        "execution_status": r.execution_status,
        "verification_status": r.verification_status,
        "verification_criteria": r.verification_criteria,
        "verification_procedure": r.verification_procedure,
        "attempts": r.attempts,
        "decision_note": r.decision_note,
        "can_simulate_recurrence": r.key != "restore_sensor",
        "runs": [
            {
                "id": v.id,
                "passed": v.passed,
                "recurrence": v.recurrence,
                "summary": v.summary,
                "evidence": v.evidence,
                "created_at": v.created_at,
            }
            for v in (runs or [])
        ],
    }


def investigation_detail(db: Session, investigation: Investigation) -> dict:
    iid = investigation.id

    def rows(model, *order):
        return db.scalars(select(model).where(model.investigation_id == iid).order_by(*order)).all()

    users = {u.id: u for u in db.scalars(select(User).where(User.workspace_id == investigation.workspace_id))}
    timeline = rows(TimelineEvent, TimelineEvent.position)
    remediations = rows(Remediation, Remediation.ref)
    ledger = {k: v for k, v in (investigation.ledger or {}).items() if not k.startswith("_")}
    return {
        **investigation_summary(investigation),
        "objective": investigation.objective,
        "scope": investigation.scope,
        "compiled_claim": investigation.compiled_claim,
        "assessment_rationale": investigation.assessment_rationale,
        "limitations": investigation.limitations,
        "ledger": ledger,
        "explorer_notes": (investigation.ledger or {}).get("_explorer", []),
        "reasoning_mode": investigation.reasoning_mode,
        "reasoning_note": investigation.reasoning_note,
        "error": investigation.error,
        "timeline": [
            {
                "stage": t.stage,
                "label": STAGE_LABELS.get(t.stage, t.stage),
                "status": t.status,
                "detail": t.detail,
                "started_at": t.started_at,
                "finished_at": t.finished_at,
            }
            for t in timeline
        ],
        "realities": [hypothesis_out(h) for h in rows(Hypothesis, Hypothesis.label)],
        "evidence": [evidence_out(e) for e in rows(EvidenceItem, EvidenceItem.ref)],
        "assumptions": [
            {"key": a.key, "text": a.text, "status": a.status, "basis": a.basis}
            for a in rows(Assumption, Assumption.key)
        ],
        "findings": [
            {
                "id": f.id,
                "key": f.key,
                "kind": f.kind,
                "title": f.title,
                "body": f.body,
                "severity": f.severity,
                "evidence_refs": f.evidence_refs,
            }
            for f in sorted(
                rows(Finding, Finding.key),
                key=lambda f: ("critical", "high", "medium", "low").index(f.severity),
            )
        ],
        "checks": [check_out(c, users) for c in rows(RecommendedCheck, RecommendedCheck.position)],
        "tool_executions": [
            {
                "id": t.id,
                "tool": t.tool,
                "role": t.role,
                "status": t.status,
                "records_read": t.records_read,
                "error": t.error,
                "started_at": t.started_at,
                "finished_at": t.finished_at,
            }
            for t in rows(ToolExecution, ToolExecution.started_at)
        ],
        "remediations": [remediation_out(r) for r in remediations],
    }


def raw_records(db: Session, record_ids: list[int]) -> list[dict]:
    rows = db.scalars(select(EvidenceRecord).where(EvidenceRecord.id.in_(record_ids[:25]))).all()
    return [
        {"id": r.id, "source_key": r.source_key, "ts": r.ts, "entity": r.entity, "payload": r.payload} for r in rows
    ]


def source_out(source: DataSource, records: int, earliest, latest, coverage: str | None) -> dict:
    return {
        "key": source.key,
        "name": source.name,
        "description": source.description,
        "mode": source.mode,
        "status": source.status,
        "restricted": source.restricted,
        "permissions": source.permissions,
        "last_sync_at": source.last_sync_at,
        "records": records,
        "earliest": earliest,
        "latest": latest,
        "coverage": coverage,
    }


def report_summary(report: Report) -> dict:
    return {
        "id": report.id,
        "ref": report.ref,
        "investigation_id": report.investigation_id,
        "name": report.snapshot["investigation"]["name"],
        "investigation_ref": report.snapshot["investigation"]["ref"],
        "assessment": report.snapshot["conclusion"]["assessment"],
        "provisional": report.snapshot["conclusion"]["provisional"],
        "sha256": report.sha256,
        "created_at": report.created_at,
    }


def ai_status(ai_settings: dict) -> dict:
    from app.reasoning.factory import model_blocker

    settings = get_settings()
    model = ai_settings.get("model_id") or settings.meta_model_id
    blocker = model_blocker(model)
    mode = ai_settings.get("reasoning_mode", "auto")
    return {
        "provider": "Meta Model API",
        "base_url": settings.meta_api_base,
        "key_configured": bool(settings.model_api_key),
        "model_id": model,
        "reasoning_mode": mode,
        "reasoning_effort": ai_settings.get("reasoning_effort") or settings.meta_reasoning_effort,
        "active": "deterministic" if (mode == "deterministic" or blocker) else "meta",
        "blocker": blocker,
    }
