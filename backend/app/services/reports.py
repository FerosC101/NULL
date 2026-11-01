"""Reports are frozen snapshots. Each statement is labelled observed, hypothesis, or conclusion."""

import csv
import hashlib
import io
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.observables import OBSERVABLE_LABELS, TOOLS
from app.demo.generator import DATASETS
from app.models import (
    Assumption,
    DataSource,
    EvidenceItem,
    Finding,
    Hypothesis,
    Investigation,
    RecommendedCheck,
    Remediation,
    Report,
    ToolExecution,
    User,
    VerificationRun,
)
from app.services import exhibits, lifecycle
from app.services.orchestrator import STAGES

SCHEMA = 2
SECTION_TITLES = [
    "Executive summary",
    "Investigation scope",
    "Evidence overview",
    "Competing explanations",
    "Investigation and test results",
    "Findings and conclusion",
    "Corrective and preventive actions",
    "Verification and assurance",
    "Appendix",
]
METHODOLOGY = (
    "NULL compiles the claim into a testable statement, then constructs competing explanations that each declare what "
    "they predict for named observables. Observables are answered from raw records by deterministic tools, and each "
    "result keeps its method, record IDs and a SHA-256 hash of those records. A validator compares predictions with "
    "observations and assigns the assessment. A language model may propose explanations, but it cannot set a "
    "conclusion or a statistic. Further checks are ranked by expected information gain in bits, using a uniform prior "
    "and declared likelihoods, which ranks checks and is not a probability of intrusion. Nothing beyond the first "
    "pass runs without human approval."
)


def _test_results(check: RecommendedCheck, hypotheses: list[Hypothesis], evidence: list[EvidenceItem]) -> list[dict]:
    """For each observable a test produces: what each reality expected, and what was actually seen."""
    observed = {e.observable: e for e in evidence if e.data.get("primary")}
    results = []
    for observable in TOOLS[check.tool].observables if check.tool in TOOLS else ():
        expected = {}
        for hypothesis in hypotheses:
            prediction = next(
                (p for p in hypothesis.prediction_results or hypothesis.predictions if p["observable"] == observable),
                None,
            )
            expected[hypothesis.label] = prediction["expects"] if prediction else "any"
        item = observed.get(observable)
        results.append(
            {
                "observable": observable,
                "label": OBSERVABLE_LABELS.get(observable, observable),
                "expected": expected,
                "actual": (
                    {
                        "ref": item.ref,
                        "state": item.data.get("state"),
                        "value": item.data.get("value"),
                        "observation": item.observation,
                    }
                    if item
                    else None
                ),
            }
        )
    return results


def build_snapshot(db: Session, investigation: Investigation) -> dict[str, Any]:
    iid = investigation.id
    evidence = db.scalars(
        select(EvidenceItem).where(EvidenceItem.investigation_id == iid).order_by(EvidenceItem.ref)
    ).all()
    hypotheses = db.scalars(
        select(Hypothesis).where(Hypothesis.investigation_id == iid).order_by(Hypothesis.label)
    ).all()
    findings = db.scalars(select(Finding).where(Finding.investigation_id == iid)).all()
    assumptions = db.scalars(select(Assumption).where(Assumption.investigation_id == iid)).all()
    checks = db.scalars(select(RecommendedCheck).where(RecommendedCheck.investigation_id == iid)).all()
    remediations = db.scalars(
        select(Remediation).where(Remediation.investigation_id == iid).order_by(Remediation.ref)
    ).all()
    executions = db.scalars(
        select(ToolExecution).where(ToolExecution.investigation_id == iid).order_by(ToolExecution.started_at)
    ).all()
    sources = {
        s.key: s for s in db.scalars(select(DataSource).where(DataSource.workspace_id == investigation.workspace_id))
    }

    state = lifecycle.describe(db, investigation)
    loaded = lifecycle.load(db, investigation)
    frozen_events = [
        {**event, "at": event["at"].isoformat() if event["at"] else None}
        for event in lifecycle.history(db, investigation, loaded, dict(STAGES))
    ]
    decided = {u.id: u.name for u in db.scalars(select(User).where(User.workspace_id == investigation.workspace_id))}
    upcoming = state["next_action"]
    if upcoming["kind"] == "report":
        upcoming = {**upcoming, "label": "No action outstanding"}
    reliability: dict[str, int] = {}
    for item in evidence:
        reliability[item.reliability] = reliability.get(item.reliability, 0) + 1
    runs = []
    for remediation in remediations:
        for run in db.scalars(
            select(VerificationRun)
            .where(VerificationRun.remediation_id == remediation.id)
            .order_by(VerificationRun.created_at)
        ):
            runs.append(
                {
                    "remediation": remediation.ref,
                    "procedure": run.procedure,
                    "passed": run.passed,
                    "recurrence": run.recurrence,
                    "summary": run.summary,
                    "at": run.created_at.isoformat(),
                }
            )
    survivors = [h for h in hypotheses if h.compatibility != "incompatible"]
    critical = sum(1 for f in findings if f.severity == "critical")
    return {
        "schema": SCHEMA,
        "investigation": {
            "id": investigation.id,
            "ref": investigation.ref,
            "name": investigation.name,
            "status": investigation.status,
            "assignee": investigation.assignee.name,
            "reasoning_mode": investigation.reasoning_mode,
            "reasoning_note": investigation.reasoning_note,
        },
        "demo_notice": "Synthetic demonstration data for a fictional company. No real organization was examined.",
        "executive_summary": {
            "assessment": investigation.assessment,
            "rationale": investigation.assessment_rationale,
            "objective": investigation.objective,
            "key_finding": state["key_finding"],
            "uncertainty": state["uncertainty"],
            "next_action": upcoming,
            "counts": {
                "evidence": len(evidence),
                "realities": len(hypotheses),
                "surviving_realities": len(survivors),
                "critical_findings": critical,
                "remediations": len(remediations),
            },
        },
        "lifecycle": state["stages"],
        "exhibits": exhibits.compute(db, investigation),
        "ledger": {k: v for k, v in (investigation.ledger or {}).items() if not k.startswith("_")},
        "methodology": METHODOLOGY,
        "events": frozen_events,
        "observations": {
            e.observable: {
                "ref": e.ref,
                "state": e.data.get("state"),
                "value": e.data.get("value"),
                "observation": e.observation,
            }
            for e in evidence
            if e.data.get("primary")
        },
        "claim": {
            "text": investigation.claim_text,
            "interpretation": investigation.compiled_claim.get("interpretation", ""),
            "compiled": investigation.compiled_claim,
        },
        "scope": {
            "window_start": investigation.scope.get("window_start"),
            "window_end": investigation.scope.get("window_end"),
            "assets": investigation.scope.get("assets_label", "All in-scope assets"),
            "objective": investigation.objective,
            "dataset": DATASETS.get(investigation.dataset, {}).get("label", investigation.dataset),
        },
        "sources": [
            {
                "key": key,
                "name": sources[key].name if key in sources else key,
                "mode": sources[key].mode if key in sources else "unknown",
                "status": sources[key].status if key in sources else "unknown",
            }
            for key in investigation.source_keys
        ],
        "evidence_quality": {
            "by_reliability": reliability,
            "items": [
                {
                    "ref": e.ref,
                    "source": e.source_key,
                    "observation": e.observation,
                    "reliability": e.reliability,
                    "basis": e.reliability_basis,
                    "relevance": e.relevance,
                    "observed_at": e.observed_at.isoformat(),
                }
                for e in evidence
            ],
        },
        "realities": [
            {
                "label": h.label,
                "title": h.title,
                "statement": h.statement,
                "origin": h.origin,
                "compatibility": h.compatibility,
                "assumptions": h.assumptions,
                "supporting": h.supporting,
                "contradicting": h.contradicting,
                "challenge": h.challenge,
                "claim_true": h.claim_true,
                "predictions": [
                    {**p, "label": OBSERVABLE_LABELS.get(p["observable"], p["observable"])}
                    for p in (h.prediction_results or [{**p, "outcome": "untested"} for p in h.predictions])
                ],
            }
            for h in hypotheses
        ],
        "findings": [
            {"title": f.title, "body": f.body, "kind": f.kind, "severity": f.severity, "evidence": f.evidence_refs}
            for f in findings
        ],
        "assumptions": [{"text": a.text, "status": a.status, "basis": a.basis} for a in assumptions],
        "limitations": investigation.limitations,
        "procedures": [
            {
                "title": c.title,
                "status": c.status,
                "procedure": c.procedure,
                "information_gain_bits": c.information_gain_bits,
                "error": c.error,
                "tool": c.tool,
                "rationale": c.rationale,
                "distinguishes": c.distinguishes,
                "requires_sources": c.requires_sources,
                "decided_by": decided.get(c.decided_by_id or ""),
                "decided_at": c.decided_at.isoformat() if c.decided_at else None,
                "results": _test_results(c, list(hypotheses), list(evidence)),
            }
            for c in checks
        ],
        "conclusion": {
            "assessment": investigation.assessment,
            "rationale": investigation.assessment_rationale,
            "provisional": investigation.status != "concluded",
        },
        "mitigations": [
            {
                "ref": r.ref,
                "action": r.action,
                "priority": r.priority,
                "risk": r.risk_addressed,
                "owner": r.owner.name,
                "approval": r.approval_status,
                "execution": r.execution_status,
                "verification": r.verification_status,
                "criteria": r.verification_criteria,
                "finding": r.finding,
                "root_cause": r.root_cause,
                "target_date": r.target_date.isoformat() if r.target_date else None,
                "procedure": r.verification_procedure,
                "attempts": r.attempts,
            }
            for r in remediations
        ],
        "verifications": runs,
        "provenance": {
            "evidence": [
                {
                    "ref": e.ref,
                    "tool": e.provenance.get("tool"),
                    "method": e.provenance.get("method"),
                    "sources": e.provenance.get("sources"),
                    "record_ids": e.provenance.get("record_ids", [])[:10],
                    "record_count": len(e.provenance.get("record_ids", [])),
                    "sha256": e.provenance.get("sha256"),
                }
                for e in evidence
            ],
            "tool_executions": [
                {
                    "tool": t.tool,
                    "role": t.role,
                    "status": t.status,
                    "records_read": t.records_read,
                    "started_at": t.started_at.isoformat(),
                    "error": t.error,
                }
                for t in executions
            ],
        },
    }


def create_report(db: Session, investigation: Investigation, user: User) -> Report:
    count = len(db.scalars(select(Report.id)).all())
    earlier = db.scalar(select(func.count()).select_from(Report).where(Report.investigation_id == investigation.id))
    snapshot = build_snapshot(db, investigation)
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    report = Report(
        workspace_id=investigation.workspace_id,
        investigation_id=investigation.id,
        ref=f"RPT-{count + 1:04d}",
        version=(earlier or 0) + 1,
        snapshot=snapshot,
        sha256=digest,
        created_by_id=user.id,
    )
    db.add(report)
    return report


def normalize_snapshot(snapshot: dict) -> dict:
    """Reports are immutable, so an older one is read through defaults. Nothing is recomputed or backfilled."""
    if snapshot.get("schema", 1) >= SCHEMA:
        return snapshot
    summary = snapshot["executive_summary"]
    return {
        "lifecycle": [],
        "exhibits": None,
        "ledger": {},
        "methodology": None,
        "events": [],
        "observations": {},
        **snapshot,
        "schema": 1,
        "executive_summary": {
            "objective": "",
            "key_finding": None,
            "uncertainty": None,
            "next_action": None,
            **summary,
        },
        "realities": [{"claim_true": False, "predictions": [], **r} for r in snapshot["realities"]],
        "procedures": [
            {
                "tool": "",
                "rationale": "",
                "distinguishes": [],
                "requires_sources": [],
                "decided_by": None,
                "decided_at": None,
                "results": [],
                **p,
            }
            for p in snapshot["procedures"]
        ],
        "mitigations": [
            {"finding": "", "root_cause": "", "target_date": None, "procedure": "", "attempts": 0, **m}
            for m in snapshot["mitigations"]
        ],
    }


def version_history(db: Session, report: Report) -> list[dict]:
    rows = db.scalars(
        select(Report).where(Report.investigation_id == report.investigation_id).order_by(Report.version)
    ).all()
    return [
        {
            "id": r.id,
            "ref": r.ref,
            "version": r.version,
            "assessment": r.snapshot["conclusion"]["assessment"],
            "evidence": r.snapshot["executive_summary"]["counts"]["evidence"],
            "sha256": r.sha256,
            "created_at": r.created_at,
        }
        for r in rows
    ]


def evidence_csv(report: Report) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["evidence_id", "source", "observation", "observed_at", "reliability", "relevance", "tool", "sha256"]
    )
    provenance = {p["ref"]: p for p in report.snapshot["provenance"]["evidence"]}
    for item in report.snapshot["evidence_quality"]["items"]:
        trace = provenance.get(item["ref"], {})
        row = [
            item["ref"],
            item["source"],
            item["observation"],
            item["observed_at"],
            item["reliability"],
            item["relevance"],
            trace.get("tool", ""),
            trace.get("sha256", ""),
        ]
        # Evidence text can start with a formula character, which spreadsheets would execute.
        writer.writerow(["'" + str(v) if str(v)[:1] in "=+-@" else v for v in row])
    return buffer.getvalue()
