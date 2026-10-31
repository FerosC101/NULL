"""Reports are frozen snapshots. Each statement is labelled observed, hypothesis, or conclusion."""

import csv
import hashlib
import io
import json
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

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

SECTION_TITLES = [
    "Executive summary",
    "Original claim",
    "Investigation scope",
    "Evidence sources",
    "Evidence quality assessment",
    "Competing explanations",
    "Findings and limitations",
    "Executed verification procedures",
    "Final conclusion",
    "Recommended mitigations",
    "Remediation verification",
    "Evidence provenance",
]


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
            "counts": {
                "evidence": len(evidence),
                "realities": len(hypotheses),
                "surviving_realities": len(survivors),
                "critical_findings": critical,
                "remediations": len(remediations),
            },
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
    snapshot = build_snapshot(db, investigation)
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    report = Report(
        workspace_id=investigation.workspace_id,
        investigation_id=investigation.id,
        ref=f"RPT-{count + 1:04d}",
        snapshot=snapshot,
        sha256=digest,
        created_by_id=user.id,
    )
    db.add(report)
    return report


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


INK = colors.HexColor("#111111")
GRAY = colors.HexColor("#6B6B6B")
RULE = colors.HexColor("#D9D9D9")
BASE = dict(fontName="Helvetica", textColor=INK, alignment=TA_LEFT)
STYLES = {
    "title": ParagraphStyle("title", **{**BASE, "fontName": "Helvetica"}, fontSize=24, leading=30, spaceAfter=6),
    "meta": ParagraphStyle("meta", **{**BASE, "textColor": GRAY}, fontSize=9, leading=13),
    "h2": ParagraphStyle(
        "h2", **{**BASE, "fontName": "Helvetica-Bold"}, fontSize=12, leading=16, spaceBefore=16, spaceAfter=6
    ),
    "h3": ParagraphStyle(
        "h3", **{**BASE, "fontName": "Helvetica-Bold"}, fontSize=10, leading=14, spaceBefore=6, spaceAfter=2
    ),
    "body": ParagraphStyle("body", **BASE, fontSize=10, leading=15, spaceAfter=5),
    "label": ParagraphStyle(
        "label", **{**BASE, "fontName": "Courier", "textColor": GRAY}, fontSize=7.5, leading=10, spaceAfter=2
    ),
    "claim": ParagraphStyle("claim", **BASE, fontSize=15, leading=21, spaceAfter=6),
    "cell": ParagraphStyle("cell", **BASE, fontSize=8, leading=11),
    "mono": ParagraphStyle("mono", **{**BASE, "fontName": "Courier"}, fontSize=7, leading=10),
}


def _when(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M UTC")


def _p(text: Any, style: str = "body") -> Paragraph:
    return Paragraph(escape(str(text)), STYLES[style])


def _table(header: list[str], rows: list[list[Any]], widths: list[float]) -> Table:
    data = [[_p(h.upper(), "label") for h in header]] + [[_p(c, "cell") for c in row] for row in rows]
    table = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, INK),
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _mark(canvas: Canvas, x: float, y: float, radius: float) -> None:
    canvas.setFillColor(colors.black)
    canvas.circle(x, y, radius, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.circle(x, y, radius * 0.22, stroke=0, fill=1)


def _footer(ref: str, sha: str):
    def draw(canvas: Canvas, doc) -> None:
        canvas.saveState()
        width, _ = LETTER
        _mark(canvas, 0.9 * inch, 0.5 * inch, 6)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(GRAY)
        canvas.drawString(1.05 * inch, 0.47 * inch, f"NULL  {ref}  SHA-256 {sha[:16]}  Synthetic demonstration data")
        canvas.drawRightString(width - 0.8 * inch, 0.47 * inch, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def render_pdf(report: Report) -> bytes:
    s = report.snapshot
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=0.8 * inch,
        rightMargin=0.8 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.85 * inch,
        title=f"{report.ref} {s['investigation']['name']}",
        author="NULL",
    )
    flow: list = [
        _p(f"INVESTIGATION REPORT  {report.ref}", "label"),
        _p(s["investigation"]["name"], "title"),
        _p(
            f"{s['investigation']['ref']}  ·  Generated {report.created_at:%Y-%m-%d %H:%M} UTC  ·  "
            f"Investigator {s['investigation']['assignee']}",
            "meta",
        ),
        _p(s["demo_notice"], "meta"),
        Spacer(1, 8),
        HRFlowable(width="100%", thickness=0.75, color=INK),
    ]

    def section(index: int) -> None:
        flow.append(_p(f"{index + 1}. {SECTION_TITLES[index]}", "h2"))

    section(0)
    summary = s["executive_summary"]
    flow += [_p("ANALYTICAL CONCLUSION", "label"), _p(summary["assessment"], "claim"), _p(summary["rationale"])]
    counts = summary["counts"]
    flow.append(
        _p(
            f"{counts['evidence']} evidence items, {counts['realities']} competing realities "
            f"({counts['surviving_realities']} still compatible), {counts['critical_findings']} critical findings, "
            f"{counts['remediations']} recommended actions.",
            "meta",
        )
    )

    section(1)
    flow += [
        _p("CLAIM AS SUBMITTED", "label"),
        _p(s["claim"]["text"], "claim"),
        _p("INTERPRETATION", "label"),
        _p(s["claim"]["interpretation"]),
    ]

    section(2)
    scope = s["scope"]
    flow.append(
        _table(
            ["Field", "Value"],
            [
                ["Window", f"{_when(scope['window_start'])} to {_when(scope['window_end'])}"],
                ["Assets", scope["assets"]],
                ["Objective", scope["objective"] or "Not stated"],
                ["Dataset", f"{scope['dataset']} (synthetic)"],
            ],
            [1.3, 5.6],
        )
    )

    section(3)
    flow.append(
        _table(
            ["Source", "Mode", "Status"], [[x["name"], x["mode"], x["status"]] for x in s["sources"]], [3.9, 1.5, 1.5]
        )
    )

    section(4)
    flow.append(_p("OBSERVED FACTS", "label"))
    flow.append(
        _table(
            ["ID", "Observation", "Reliability", "Relevance"],
            [[e["ref"], e["observation"], e["reliability"], e["relevance"]] for e in s["evidence_quality"]["items"]],
            [0.7, 4.6, 0.8, 0.8],
        )
    )

    section(5)
    flow.append(_p("GENERATED HYPOTHESES. NONE OF THESE IS AN OBSERVED FACT.", "label"))
    for reality in s["realities"]:
        block = [
            _p(f"Reality {reality['label']}: {reality['title']}", "h3"),
            _p(reality["statement"]),
            _p(
                f"Compatibility: {reality['compatibility']}. Supporting: {', '.join(reality['supporting']) or 'none'}. "
                f"Contradicting: {', '.join(reality['contradicting']) or 'none'}. Origin: {reality['origin']}.",
                "meta",
            ),
        ]
        if reality["challenge"]:
            block.append(_p(f"Challenge: {reality['challenge']}", "meta"))
        flow.append(KeepTogether(block))

    section(6)
    flow.append(_p("ANALYTICAL FINDINGS", "label"))
    for finding in s["findings"]:
        flow.append(
            KeepTogether(
                [
                    _p(f"{finding['title']} ({finding['severity']})", "h3"),
                    _p(finding["body"]),
                    _p(f"Evidence: {', '.join(finding['evidence']) or 'none'}", "meta"),
                ]
            )
        )
    flow.append(_p("Limitations", "h3"))
    for limit in s["limitations"]:
        flow.append(_p(f"– {limit}"))

    section(7)
    executed = [p for p in s["procedures"] if p["status"] in ("completed", "blocked", "failed")]
    if executed:
        flow.append(
            _table(
                ["Procedure", "Status", "Value (bits)"],
                [[p["title"], p["status"], f"{p['information_gain_bits']:.2f}"] for p in executed],
                [4.6, 1.2, 1.1],
            )
        )
    else:
        flow.append(_p("No verification procedures had been executed when this report was generated."))

    section(8)
    conclusion = s["conclusion"]
    flow += [_p(conclusion["assessment"], "claim"), _p(conclusion["rationale"])]
    if conclusion["provisional"]:
        flow.append(
            _p("This assessment is provisional. The investigation was still open when this report was generated.")
        )

    section(9)
    if s["mitigations"]:
        flow.append(
            _table(
                ["ID", "Action", "Priority", "Owner", "Approval"],
                [[m["ref"], m["action"], m["priority"], m["owner"], m["approval"]] for m in s["mitigations"]],
                [0.7, 3.5, 0.7, 1.1, 0.9],
            )
        )
    else:
        flow.append(_p("No mitigations were recommended."))

    section(10)
    if s["verifications"]:
        flow.append(
            _table(
                ["Action", "Result", "Summary"],
                [
                    [
                        v["remediation"],
                        "Passed" if v["passed"] else ("Recurrence" if v["recurrence"] else "Failed"),
                        v["summary"],
                    ]
                    for v in s["verifications"]
                ],
                [0.8, 0.9, 5.2],
            )
        )
    else:
        flow.append(_p("No remediation had been verified when this report was generated."))

    flow.append(PageBreak())
    section(11)
    flow.append(
        _table(
            ["ID", "Tool", "Records", "SHA-256"],
            [[p["ref"], p["tool"], p["record_count"], (p["sha256"] or "")[:32]] for p in s["provenance"]["evidence"]],
            [0.7, 2.5, 0.7, 3.0],
        )
    )
    flow += [Spacer(1, 10), _p("Report snapshot SHA-256", "h3"), _p(report.sha256, "mono")]

    footer = _footer(report.ref, report.sha256)
    document.build(flow, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
