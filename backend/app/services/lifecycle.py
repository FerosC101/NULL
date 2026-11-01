"""Where an investigation stands: seven stages, the finding that matters most, and what happens next.

Everything here is read from stored state. Nothing is estimated, and a stage only reports what its
rows show.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Assumption,
    EvidenceItem,
    Finding,
    Hypothesis,
    Investigation,
    RecommendedCheck,
    Remediation,
    Report,
    TimelineEvent,
    VerificationRun,
)

STAGES = [
    ("claim", "Claim"),
    ("evidence", "Evidence"),
    ("explanations", "Explanations"),
    ("tests", "Tests"),
    ("findings", "Findings"),
    ("actions", "Actions"),
    ("verification", "Verification"),
]
RUNNING = ("queued", "analyzing", "running_checks")
SEVERITY = ("critical", "high", "medium", "low")
GAP_KINDS = ("evidence_gap", "incomplete_observation")


def _count(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


@dataclass
class Rows:
    hypotheses: list[Hypothesis]
    findings: list[Finding]
    checks: list[RecommendedCheck]
    remediations: list[Remediation]
    assumptions: list[Assumption]
    evidence: list[EvidenceItem]


def load(db: Session, investigation: Investigation) -> Rows:
    def rows(model, *order):
        return list(db.scalars(select(model).where(model.investigation_id == investigation.id).order_by(*order)))

    return Rows(
        hypotheses=rows(Hypothesis, Hypothesis.label),
        findings=rows(Finding, Finding.key),
        checks=rows(RecommendedCheck, RecommendedCheck.position),
        remediations=rows(Remediation, Remediation.ref),
        assumptions=rows(Assumption, Assumption.key),
        evidence=rows(EvidenceItem, EvidenceItem.ref),
    )


def _stage_claim(investigation: Investigation) -> tuple[str, str]:
    if investigation.compiled_claim:
        return "completed", investigation.scope.get("window_label", "")
    return ("in_progress", "Compiling") if investigation.status in RUNNING else ("not_started", "")


def _stage_evidence(investigation: Investigation, r: Rows) -> tuple[str, str]:
    primary = [e for e in r.evidence if e.data.get("primary")]
    if not primary:
        return ("in_progress", "Collecting") if investigation.status in RUNNING else ("not_started", "No evidence")
    unreadable = len((investigation.ledger or {}).get("_unavailable", {}))
    gaps = sum(1 for f in r.findings if f.kind in GAP_KINDS)
    summary = _count(len(primary), "observation")
    if unreadable:
        return "needs_attention", f"{summary}, {_count(unreadable, 'unreadable source')}"
    if gaps:
        return "needs_attention", f"{summary}, {_count(gaps, 'gap')}"
    return "completed", summary


def _stage_explanations(investigation: Investigation, r: Rows) -> tuple[str, str]:
    if not r.hypotheses:
        if investigation.status in RUNNING:
            return "in_progress", "Constructing"
        return "not_started", "Not applicable to this claim"
    survivors = [h for h in r.hypotheses if h.compatibility != "incompatible"]
    if len(survivors) > 1:
        return "needs_attention", f"{len(survivors)} of {len(r.hypotheses)} still possible"
    return "completed", f"{len(survivors)} of {len(r.hypotheses)} still possible"


def _stage_tests(investigation: Investigation, r: Rows) -> tuple[str, str]:
    if not r.checks:
        if investigation.status in RUNNING:
            return "not_started", ""
        return ("completed", "None needed") if r.hypotheses else ("not_started", "Not applicable to this claim")
    by_status: dict[str, int] = {}
    for check in r.checks:
        by_status[check.status] = by_status.get(check.status, 0) + 1
    if by_status.get("proposed") and investigation.status == "awaiting_approval":
        return "needs_attention", f"{by_status['proposed']} awaiting approval"
    if by_status.get("running") or by_status.get("approved"):
        return "in_progress", f"{by_status.get('running', 0) + by_status.get('approved', 0)} running"
    stopped = by_status.get("blocked", 0) + by_status.get("failed", 0)
    if stopped:
        return "blocked", f"{stopped} could not run"
    executed = by_status.get("completed", 0)
    if executed:
        return "completed", f"{executed} executed"
    return "completed", _count(by_status.get("rejected", 0), "test") + " rejected"


def _stage_findings(investigation: Investigation) -> tuple[str, str]:
    if investigation.status == "concluded":
        return "completed", investigation.assessment.capitalize()
    if investigation.status == "awaiting_approval":
        return "in_progress", f"Provisional: {investigation.assessment.capitalize()}"
    return ("in_progress", "Evaluating") if investigation.status in RUNNING else ("not_started", "")


def _live(r: Rows) -> list[Remediation]:
    return [x for x in r.remediations if x.approval_status != "rejected"]


def _stage_actions(investigation: Investigation, r: Rows) -> tuple[str, str]:
    live = _live(r)
    if not r.remediations:
        return ("completed", "None recommended") if investigation.status == "concluded" else ("not_started", "")
    if not live:
        return "completed", "All rejected"
    pending = sum(1 for x in live if x.approval_status == "pending")
    if pending:
        return "needs_attention", f"{pending} awaiting approval"
    waiting = sum(1 for x in live if x.execution_status != "executed")
    if waiting:
        return "in_progress", f"{waiting} approved, not executed"
    return "completed", f"{len(live)} executed"


def _stage_verification(r: Rows) -> tuple[str, str]:
    live = _live(r)
    executed = [x for x in live if x.execution_status == "executed"]
    if not executed:
        return "not_started", ""
    recurred = sum(1 for x in executed if x.verification_status == "recurred")
    failed = sum(1 for x in executed if x.verification_status == "failed")
    if recurred:
        return "needs_attention", f"{recurred} recurred"
    if failed:
        return "needs_attention", f"{failed} failed verification"
    verified = sum(1 for x in executed if x.verification_status == "verified")
    if verified == len(live):
        return "completed", f"{verified} verified"
    if verified < len(executed):
        return "in_progress", f"{len(executed) - verified} awaiting verification"
    return "in_progress", f"{verified} of {len(live)} verified"


def stages(investigation: Investigation, r: Rows) -> list[dict]:
    results = {
        "claim": _stage_claim(investigation),
        "evidence": _stage_evidence(investigation, r),
        "explanations": _stage_explanations(investigation, r),
        "tests": _stage_tests(investigation, r),
        "findings": _stage_findings(investigation),
        "actions": _stage_actions(investigation, r),
        "verification": _stage_verification(r),
    }
    out = [{"key": k, "label": label, "status": results[k][0], "summary": results[k][1]} for k, label in STAGES]
    if investigation.status == "failed":
        stopped = False
        for stage in out:
            if stopped:
                stage.update(status="not_started", summary="")
            elif stage["status"] != "completed":
                stage.update(status="blocked", summary="Stopped by an error")
                stopped = True
    return out


def key_finding(r: Rows) -> dict | None:
    """The most severe finding. Among equals, the one citing evidence against the claim comes first."""
    if not r.findings:
        return None
    against = {ref for h in r.hypotheses if h.claim_true for ref in h.contradicting}
    best = min(
        r.findings,
        key=lambda f: (SEVERITY.index(f.severity), not against & set(f.evidence_refs), f.key),
    )
    return {"title": best.title, "body": best.body, "severity": best.severity, "evidence_refs": best.evidence_refs}


def uncertainty(investigation: Investigation, r: Rows) -> str | None:
    ledger = investigation.ledger or {}
    unknown = ledger.get("unknown") or []
    if unknown:
        return f"Not yet observed: {unknown[0]}" + (f", and {len(unknown) - 1} more." if len(unknown) > 1 else ".")
    unverified = [a for a in r.assumptions if a.status == "unverified"]
    if unverified:
        return f"Unverified assumption: {unverified[0].text}"
    return investigation.limitations[0] if investigation.limitations else None


def next_action(investigation: Investigation, r: Rows) -> dict:
    """The single most useful thing a person can do now."""

    def action(label: str, detail: str, stage: str, kind: str = "open_stage") -> dict:
        return {"label": label, "detail": detail, "stage": stage, "kind": kind}

    if investigation.status == "failed":
        return action("Review what stopped this", investigation.error or "The investigation stopped.", "claim", "none")
    if investigation.status in RUNNING:
        return action("Analysis in progress", "NULL is working through the evidence.", "evidence", "none")
    proposed = [c for c in r.checks if c.status == "proposed"]
    if investigation.status == "awaiting_approval" and proposed:
        return action("Review recommended tests", proposed[0].title, "tests")
    live = _live(r)
    for state, label in (("recurred", "Investigate a recurrence"), ("failed", "Resolve a failed verification")):
        hit = next((x for x in live if x.verification_status == state), None)
        if hit:
            return action(label, f"{hit.ref}: {hit.action}", "verification")
    hit = next((x for x in live if x.verification_status == "awaiting"), None)
    if hit:
        return action("Run verification", f"{hit.ref}: {hit.action}", "verification")
    hit = next((x for x in live if x.approval_status == "approved" and x.execution_status != "executed"), None)
    if hit:
        return action("Execute an approved action", f"{hit.ref}: {hit.action}", "actions")
    pending = [x for x in live if x.approval_status == "pending"]
    if pending:
        first = min(pending, key=lambda x: SEVERITY.index(x.priority) if x.priority in SEVERITY else len(SEVERITY))
        detail = first.action if len(pending) == 1 else f"{first.action} {len(pending) - 1} more waiting."
        return action("Decide on corrective actions", detail, "actions")
    return action("Generate the report", "Nothing further is waiting on a person.", "findings", "report")


def describe(db: Session, investigation: Investigation) -> dict:
    r = load(db, investigation)
    return describe_rows(investigation, r)


def describe_rows(investigation: Investigation, r: Rows) -> dict:
    staged = stages(investigation, r)
    upcoming = next_action(investigation, r)
    return {
        "stages": staged,
        "current": upcoming["stage"],
        "completed": sum(1 for s in staged if s["status"] == "completed"),
        "key_finding": key_finding(r),
        "uncertainty": uncertainty(investigation, r),
        "next_action": upcoming,
    }


def _entry(at, kind: str, label: str, detail: str, tone: str) -> dict:
    return {"at": at, "kind": kind, "label": label, "detail": detail, "tone": tone, "planned": False}


def history(db: Session, investigation: Investigation, r: Rows, stage_labels: dict[str, str]) -> list[dict]:
    """Everything that happened, by its recorded time, followed by what is still planned."""
    done: list[dict] = []
    planned: list[dict] = []
    events = db.scalars(
        select(TimelineEvent).where(TimelineEvent.investigation_id == investigation.id).order_by(TimelineEvent.position)
    )

    def add(at, kind: str, label: str, detail: str = "", tone: str = "neutral") -> None:
        done.append(_entry(at, kind, label, detail, tone))

    for event in events:
        label = stage_labels.get(event.stage, event.stage)
        if event.status in ("done", "failed") and event.finished_at:
            add(event.finished_at, "stage", label, event.detail, "bad" if event.status == "failed" else "neutral")
        elif event.status in ("pending", "running"):
            planned.append({**_entry(None, "stage", label, event.detail, "neutral"), "planned": True})
    for check in r.checks:
        if check.decided_at:
            verb = "Rejected" if check.status == "rejected" else "Approved"
            add(check.decided_at, "decision", f"{verb}: {check.title}", tone="bad" if verb == "Rejected" else "neutral")
    for remediation in r.remediations:
        if remediation.executed_at:
            add(remediation.executed_at, "action", f"Executed {remediation.ref}", remediation.action)
        runs = db.scalars(
            select(VerificationRun)
            .where(VerificationRun.remediation_id == remediation.id)
            .order_by(VerificationRun.created_at)
        )
        for run in runs:
            outcome = "passed" if run.passed else ("recurrence detected" if run.recurrence else "failed")
            tone = "ok" if run.passed else "bad"
            add(run.created_at, "verification", f"Verification {outcome}: {remediation.ref}", run.summary, tone)
    for report in db.scalars(select(Report).where(Report.investigation_id == investigation.id)):
        add(report.created_at, "report", f"Report {report.ref} generated", f"Version {report.version}")
    done.sort(key=lambda item: item["at"])
    return done + planned
