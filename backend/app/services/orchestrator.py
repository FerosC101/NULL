"""Runs an investigation over shared state: compile, observe, reason, validate, recommend."""

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.claims import UNSUPPORTED, compile_claim
from app.analysis.narrative import build_findings, build_ledger, build_limitations, build_rationale
from app.analysis.observables import TOOLS, ObservableResult
from app.analysis.records import EvidenceReader, SourceUnavailable
from app.analysis.templates import TEMPLATES, AssumptionSpec, CheckSpec, Reality
from app.analysis.validation import (
    HypothesisView,
    assess,
    distinguishing_labels,
    evaluate_hypothesis,
    expected_information_gain,
)
from app.db import SessionLocal
from app.models import (
    Assumption,
    DataSource,
    EvidenceItem,
    EvidenceRecord,
    Finding,
    Hypothesis,
    Investigation,
    RecommendedCheck,
    TimelineEvent,
    ToolExecution,
    Workspace,
    utcnow,
)
from app.reasoning.base import Blackboard, ReasoningFailure
from app.reasoning.deterministic import DeterministicProvider
from app.reasoning.factory import ProviderChoice, choose_provider
from app.services.graph import rebuild_graph
from app.services.remediation import sync_remediations

log = logging.getLogger("null.orchestrator")

STAGES = [
    ("claim_submitted", "Claim submitted"),
    ("evidence_connected", "Evidence connected"),
    ("evidence_analyzed", "Evidence analyzed"),
    ("explanations_constructed", "Competing explanations constructed"),
    ("investigation_recommended", "Additional investigation recommended"),
    ("verification_executed", "Verification executed"),
    ("conclusion_updated", "Conclusion updated"),
]
SKIP_STAGES = ("investigation_recommended", "verification_executed")


def window_of(investigation: Investigation) -> tuple[datetime, datetime]:
    return (
        datetime.fromisoformat(investigation.scope["window_start"]),
        datetime.fromisoformat(investigation.scope["window_end"]),
    )


def create_timeline(db: Session, investigation: Investigation) -> None:
    for position, (stage, _) in enumerate(STAGES):
        db.add(TimelineEvent(investigation_id=investigation.id, stage=stage, status="pending", position=position))


class Run:
    """One pass of work over an investigation, with its own database session."""

    def __init__(self, db: Session, investigation: Investigation, choice: ProviderChoice):
        self.db = db
        self.investigation = investigation
        self.choice = choice
        self.provider = choice.provider
        start, end = window_of(investigation)
        self.start, self.end = start, end
        self.allowed = set(investigation.source_keys)
        self.observables: dict[str, dict] = dict(investigation.observables or {})
        self.unavailable: dict[str, str] = dict((investigation.ledger or {}).get("_unavailable", {}))

    # --- recording ---

    def stage(self, stage: str, status: str, detail: str = "") -> None:
        event = self.db.scalar(
            select(TimelineEvent).where(
                TimelineEvent.investigation_id == self.investigation.id, TimelineEvent.stage == stage
            )
        )
        now = utcnow()
        if status == "running":
            event.started_at = event.started_at or now
            event.finished_at = None
        else:
            event.started_at = event.started_at or now
            event.finished_at = now
        event.status = status
        if detail:
            event.detail = detail
        self.investigation.updated_at = now
        self.db.commit()

    def record_tool(self, tool: str, role: str, payload: dict, fn) -> Any:
        execution = ToolExecution(investigation_id=self.investigation.id, tool=tool, role=role, input=payload)
        self.db.add(execution)
        self.db.commit()
        try:
            output, summary, records = fn()
        except Exception as exc:
            execution.status = "failed"
            execution.error = str(exc)[:1000]
            execution.finished_at = utcnow()
            self.db.commit()
            raise
        execution.status = "succeeded"
        execution.output = summary
        execution.records_read = records
        execution.finished_at = utcnow()
        self.db.commit()
        return output, execution

    # --- observation ---

    def reader(self) -> EvidenceReader:
        return EvidenceReader(
            self.db,
            self.investigation.workspace_id,
            self.investigation.dataset,
            self.allowed,
            self.end,
            self.investigation.scope.get("asset_classes"),
        )

    def run_tool(self, name: str, role: str = "system") -> list[ObservableResult] | None:
        tool = TOOLS[name]
        reader = self.reader()

        def execute():
            result = tool.run(reader, self.start, self.end)
            results = result if isinstance(result, list) else [result]
            summary = {r.key: {"state": r.state, "value": r.value, "summary": r.summary} for r in results}
            return results, summary, reader.records_read

        try:
            results, execution = self.record_tool(
                name,
                role,
                {"window": [self.start.isoformat(), self.end.isoformat()], "sources": list(tool.sources)},
                execute,
            )
        except SourceUnavailable as exc:
            self.unavailable[exc.source_key] = exc.reason
            for key in tool.observables:
                self.observables.setdefault(key, {"key": key, "state": "unavailable", "summary": exc.reason})
            return None
        for source_key in tool.sources:
            self.unavailable.pop(source_key, None)
        for result in results:
            self.observables[result.key] = result.to_dict()
            self.add_evidence(result, execution)
        return results

    def add_evidence(self, result: ObservableResult, execution: ToolExecution) -> None:
        self._insert_evidence(
            result,
            execution,
            result.summary,
            self.end,
            result.record_ids,
            primary=True,
            data={"primary": True, "state": result.state, "value": result.value, "details": result.details},
        )
        sessions = result.details.get("sessions", []) + result.details.get("vpn_sessions", [])
        for row in sessions:
            what = "VPN session" if row["kind"] == "vpn_session" else "Logon"
            where = f" on {row['hostname']}" if row.get("hostname") else ""
            asn = f" ({row['src_asn']})" if row.get("src_asn") else ""
            self._insert_evidence(
                result,
                execution,
                f"{what} by {row['user']}{where} from {row['src_ip']}{asn}, no identity-provider session.",
                datetime.fromisoformat(row["ts"]),
                [row["record_id"]],
                primary=False,
                data={"primary": False, "record": row},
            )

    def _insert_evidence(self, result, execution, observation, observed_at, record_ids, primary, data) -> None:
        count = len(
            self.db.scalars(select(EvidenceItem.id).where(EvidenceItem.investigation_id == self.investigation.id)).all()
        )
        rows = (
            self.db.scalars(
                select(EvidenceRecord.payload).where(EvidenceRecord.id.in_(record_ids)).order_by(EvidenceRecord.id)
            ).all()
            if record_ids
            else []
        )
        digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
        self.db.add(
            EvidenceItem(
                investigation_id=self.investigation.id,
                ref=f"EV-{count + 1:04d}",
                source_key=result.source_keys[0],
                observable=result.key,
                observation=observation,
                observed_at=observed_at,
                reliability=result.reliability,
                reliability_basis=result.reliability_basis,
                relevance=result.relevance,
                provenance={
                    "tool": execution.tool,
                    "execution_id": execution.id,
                    "method": result.method,
                    "sources": result.source_keys,
                    "dataset": self.investigation.dataset,
                    "record_ids": record_ids,
                    "sha256": digest,
                },
                data=data,
            )
        )
        self.db.commit()

    def evidence_rows(self) -> list[EvidenceItem]:
        return list(
            self.db.scalars(
                select(EvidenceItem)
                .where(EvidenceItem.investigation_id == self.investigation.id)
                .order_by(EvidenceItem.ref)
            )
        )

    # --- board and role tools ---

    def board(self) -> Blackboard:
        hypotheses = self.db.scalars(
            select(Hypothesis).where(Hypothesis.investigation_id == self.investigation.id).order_by(Hypothesis.label)
        ).all()
        return Blackboard(
            claim_text=self.investigation.claim_text,
            compiled=self.investigation.compiled_claim,
            scope=self.investigation.scope,
            observables=self.observables,
            evidence=[
                {
                    "ref": e.ref,
                    "observation": e.observation,
                    "relevance": e.relevance,
                    "observable": e.observable,
                    "primary": e.data.get("primary", False),
                }
                for e in self.evidence_rows()
            ],
            realities=[
                {
                    "label": h.label,
                    "title": h.title,
                    "statement": h.statement,
                    "compatibility": h.compatibility,
                    "results": h.prediction_results,
                    "assumptions": h.assumptions,
                }
                for h in hypotheses
            ],
            checks=self.check_dicts(),
            available_tools=self.template()["automatic"] if self.template() else [],
        )

    def check_dicts(self) -> list[dict]:
        rows = self.db.scalars(
            select(RecommendedCheck)
            .where(RecommendedCheck.investigation_id == self.investigation.id)
            .order_by(RecommendedCheck.position)
        ).all()
        return [
            {"tool": c.tool, "title": c.title, "status": c.status, "information_gain_bits": c.information_gain_bits}
            for c in rows
        ]

    def template(self) -> dict | None:
        return TEMPLATES.get(self.investigation.compiled_claim.get("kind"))

    def definitions(self, role: str) -> list[dict]:
        def fn(name: str, description: str, properties: dict | None = None) -> dict:
            return {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties or {},
                        "required": list(properties or {}),
                    },
                },
            }

        tools = [
            fn("list_observations", "List every observation made so far, with state and summary."),
            fn(
                "get_evidence",
                "Read one evidence item and its provenance by EV- reference.",
                {"ref": {"type": "string"}},
            ),
            fn("list_realities", "List competing realities with predictions and current compatibility."),
            fn("information_value", "Compute the information value in bits of each check still available."),
        ]
        if role == "Explorer":
            tools.append(
                fn(
                    "run_analysis",
                    "Run one read-only analysis already permitted for this investigation.",
                    {"tool": {"type": "string", "enum": self.template()["automatic"]}},
                )
            )
        return tools

    def call(self, role: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a model tool call. Each call is recorded in the tool execution history."""

        def execute() -> tuple[dict, dict, int]:
            if name == "list_observations":
                output = {
                    k: {"state": v["state"], "summary": v.get("summary", "")} for k, v in self.observables.items()
                }
            elif name == "get_evidence":
                row = next((e for e in self.evidence_rows() if e.ref == arguments.get("ref")), None)
                output = (
                    {
                        "ref": row.ref,
                        "observation": row.observation,
                        "reliability": row.reliability,
                        "provenance": row.provenance,
                    }
                    if row
                    else {"error": "unknown evidence reference"}
                )
            elif name == "list_realities":
                output = {"realities": self.board().realities}
            elif name == "information_value":
                output = {"checks": self.information_values()}
            elif name == "run_analysis":
                requested = arguments.get("tool")
                if requested not in self.template()["automatic"]:
                    output = {"error": "this analysis requires approval and cannot be run by a reasoning role"}
                else:
                    results = self.run_tool(requested, role) or []
                    output = {r.key: {"state": r.state, "summary": r.summary} for r in results}
            else:
                output = {"error": f"unknown tool {name}"}
            return output, {"keys": list(output)[:10]}, 0

        output, _ = self.record_tool(f"role.{name}", role, arguments, execute)
        return output

    def role(self, name: str, tool: str, fn) -> Any:
        """Run a reasoning role. A model failure is recorded and rule-based roles take over."""

        def execute():
            output = fn(self.provider)
            return output, {"provider": self.provider.name, "result": _preview(output)}, 0

        try:
            output, _ = self.record_tool(tool, name, {"provider": self.provider.name}, execute)
            return output
        except ReasoningFailure as exc:
            self.fall_back(str(exc))
            output, _ = self.record_tool(
                tool,
                name,
                {"provider": "deterministic", "reason": "fallback"},
                lambda: ((value := fn(self.provider)), {"provider": "deterministic", "result": _preview(value)}, 0),
            )
            return output

    def fall_back(self, reason: str) -> None:
        log.warning("Reasoning fell back to rule-based roles: %s", reason)
        self.provider = DeterministicProvider()
        self.investigation.reasoning_mode = "deterministic"
        self.investigation.reasoning_note = (
            f"The Meta model failed during this run ({reason}). Rule-based roles finished it."
        )
        self.db.commit()

    # --- reasoning and validation ---

    def seed_realities(self, extra: list[Reality]) -> None:
        template = self.template()
        realities = list(template["realities"]) + extra
        existing = {
            h.title
            for h in self.db.scalars(select(Hypothesis).where(Hypothesis.investigation_id == self.investigation.id))
        }
        count = len(existing)
        for reality in realities:
            if reality.title in existing:
                continue
            count += 1
            label = reality.label if reality.label != "?" else chr(ord("A") + count - 1)
            self.db.add(
                Hypothesis(
                    investigation_id=self.investigation.id,
                    label=label,
                    title=reality.title,
                    statement=reality.statement,
                    claim_true=reality.claim_true,
                    origin=reality.origin,
                    assumptions=reality.assumptions,
                    predictions=[p.to_dict() for p in reality.predictions],
                )
            )
        for spec in template["assumptions"]:
            exists = self.db.scalar(
                select(Assumption).where(
                    Assumption.investigation_id == self.investigation.id, Assumption.key == spec.key
                )
            )
            if not exists:
                self.db.add(Assumption(investigation_id=self.investigation.id, key=spec.key, text=spec.text))
        self.db.commit()

    def evaluate(self) -> None:
        investigation = self.investigation
        hypotheses = self.db.scalars(
            select(Hypothesis).where(Hypothesis.investigation_id == investigation.id).order_by(Hypothesis.label)
        ).all()
        refs = {e.observable: e.ref for e in self.evidence_rows() if e.data.get("primary")}
        decisions = {}
        for hypothesis in hypotheses:
            view = HypothesisView(hypothesis.label, hypothesis.claim_true, hypothesis.predictions)
            status, results = evaluate_hypothesis(view, self.observables)
            hypothesis.compatibility = status
            hypothesis.prediction_results = results
            hypothesis.supporting = sorted(
                {refs[r["observable"]] for r in results if r["outcome"] == "matched" and r["observable"] in refs}
            )
            hypothesis.contradicting = sorted(
                {refs[r["observable"]] for r in results if r["outcome"] == "violated" and r["observable"] in refs}
            )
            decisions[hypothesis.label] = (hypothesis.claim_true, status, results)

        self.update_assumptions()
        made = any(o["state"] != "unavailable" for o in self.observables.values())
        assessment = assess(decisions, made)
        investigation.assessment = assessment
        realities = [
            {"label": h.label, "title": h.title, "compatibility": h.compatibility, "results": h.prediction_results}
            for h in hypotheses
        ]
        investigation.assessment_rationale = build_rationale(
            assessment, realities, investigation.compiled_claim["kind"]
        )
        self.update_findings(refs)
        self.db.commit()

    def update_assumptions(self) -> None:
        specs: dict[str, AssumptionSpec] = {s.key: s for s in self.template()["assumptions"]}
        rows = self.db.scalars(select(Assumption).where(Assumption.investigation_id == self.investigation.id)).all()
        for row in rows:
            spec = specs.get(row.key)
            if not spec:
                continue
            verdicts = []
            for observable, by_state in spec.tests.items():
                item = self.observables.get(observable)
                if item and item["state"] in by_state:
                    verdicts.append((by_state[item["state"]], item.get("summary", "")))
            violated = [v for v in verdicts if v[0] == "violated"]
            if violated:
                row.status, row.basis = "violated", violated[0][1]
            elif verdicts:
                row.status, row.basis = verdicts[-1]

    def update_findings(self, refs: dict[str, str]) -> None:
        wanted = build_findings(self.observables, refs, self.unavailable)
        keys = {f["key"] for f in wanted}
        existing = {
            f.key: f for f in self.db.scalars(select(Finding).where(Finding.investigation_id == self.investigation.id))
        }
        for key, row in existing.items():
            if key not in keys:
                self.db.delete(row)
        for item in wanted:
            row = existing.get(item["key"])
            if row:
                for field, value in item.items():
                    setattr(row, field, value)
            else:
                self.db.add(Finding(investigation_id=self.investigation.id, **item))

    def survivors(self) -> dict[str, list[dict]]:
        rows = self.db.scalars(
            select(Hypothesis).where(
                Hypothesis.investigation_id == self.investigation.id, Hypothesis.compatibility != "incompatible"
            )
        ).all()
        return {h.label: h.predictions for h in rows}

    def information_values(self) -> list[dict]:
        survivors = self.survivors()
        values = []
        for spec in self.template()["checks"]:
            observables = list(TOOLS[spec.tool].observables)
            pending = [o for o in observables if self.observables.get(o, {}).get("state") in (None, "unavailable")]
            values.append(
                {
                    "tool": spec.tool,
                    "bits": _bits(survivors, pending),
                    "distinguishes": distinguishing_labels(survivors, pending),
                }
            )
        return values

    def propose_checks(self) -> int:
        """Rank remaining checks by information value. Returns the number still open."""
        specs: list[CheckSpec] = self.template()["checks"]
        existing = {
            c.tool: c
            for c in self.db.scalars(
                select(RecommendedCheck).where(RecommendedCheck.investigation_id == self.investigation.id)
            )
        }
        values = {v["tool"]: v for v in self.information_values()}
        open_rows = []
        for spec in specs:
            row = existing.get(spec.tool)
            value = values[spec.tool]
            if row is None:
                row = RecommendedCheck(
                    investigation_id=self.investigation.id,
                    tool=spec.tool,
                    title=spec.title,
                    procedure=spec.procedure,
                    rationale=spec.rationale,
                    permissions=spec.permissions,
                    operational_impact=spec.impact,
                    requires_sources=list(TOOLS[spec.tool].sources),
                    status="proposed",
                )
                self.db.add(row)
            if row.status in ("proposed", "failed", "blocked"):
                row.information_gain_bits = value["bits"]
                row.distinguishes = value["distinguishes"]
                if value["bits"] <= 0 and row.status == "proposed":
                    row.status = "not_needed"
                else:
                    open_rows.append(row)
        for position, row in enumerate(sorted(open_rows, key=lambda r: -r.information_gain_bits)):
            row.position = position
        self.db.commit()
        return len(open_rows)

    def finish(self) -> None:
        self.db.flush()
        self.investigation.updated_at = utcnow()
        self.persist_ledger()
        sync_remediations(self.db, self.investigation)
        rebuild_graph(self.db, self.investigation)
        self.db.commit()

    def persist_ledger(self) -> None:
        investigation = self.investigation
        hypotheses = self.db.scalars(
            select(Hypothesis).where(Hypothesis.investigation_id == investigation.id).order_by(Hypothesis.label)
        ).all()
        assumptions = [
            {"text": a.text, "status": a.status}
            for a in self.db.scalars(select(Assumption).where(Assumption.investigation_id == investigation.id))
        ]
        realities = [
            {"label": h.label, "title": h.title, "compatibility": h.compatibility, "results": h.prediction_results}
            for h in hypotheses
        ]
        ledger = build_ledger(self.observables, realities, assumptions, self.check_dicts())
        ledger["_unavailable"] = self.unavailable
        investigation.ledger = ledger
        investigation.observables = self.observables
        investigation.limitations = build_limitations(self.observables, assumptions, self.unavailable)


def _bits(survivors: dict[str, list[dict]], observables: list[str]) -> float:
    if not observables:
        return 0.0
    likelihoods = {}
    for label, predictions in survivors.items():
        by_key = {p["observable"]: p["p_positive"] for p in predictions}
        likelihoods[label] = [by_key.get(o, 0.5) for o in observables]
    return expected_information_gain(likelihoods)


def _preview(value: Any) -> Any:
    if isinstance(value, list):
        return [_preview(v) for v in value[:8]]
    if isinstance(value, Reality):
        return {"title": value.title, "origin": value.origin}
    if isinstance(value, dict):
        return {k: _preview(v) for k, v in list(value.items())[:8]}
    return value if isinstance(value, (str, int, float, bool, type(None))) else str(value)


def _open(db: Session, investigation_id: str) -> tuple[Investigation, ProviderChoice]:
    investigation = db.get(Investigation, investigation_id)
    workspace = db.get(Workspace, investigation.workspace_id)
    return investigation, choose_provider((workspace.settings or {}).get("ai", {}))


def analyze(db: Session, investigation_id: str) -> None:
    """First pass: everything that needs no approval."""
    investigation, choice = _open(db, investigation_id)
    run = Run(db, investigation, choice)
    investigation.reasoning_mode = choice.mode
    investigation.reasoning_note = choice.note
    investigation.status = "analyzing"
    db.commit()

    run.stage("claim_submitted", "running")

    def do_compile():
        fallback = compile_claim(investigation.claim_text)
        try:
            compiled = run.provider.compile_claim(investigation.claim_text, fallback)
        except ReasoningFailure as exc:
            run.fall_back(str(exc))
            compiled = fallback
        return compiled, compiled.to_dict(), 0

    compiled, _ = run.record_tool("compile_claim", "system", {"claim": investigation.claim_text}, do_compile)
    investigation.compiled_claim = compiled.to_dict()
    run.stage("claim_submitted", "done", compiled.interpretation)

    run.stage("evidence_connected", "running")
    connected = {
        s.key
        for s in db.scalars(select(DataSource).where(DataSource.workspace_id == investigation.workspace_id))
        if s.status == "connected"
    }
    selected = set(investigation.source_keys)
    unreachable = sorted(selected - connected)
    for key in unreachable:
        run.unavailable[key] = "source is not connected"
    readable = len(selected & connected)
    run.stage(
        "evidence_connected",
        "done",
        f"{readable} of {len(selected)} selected sources are readable."
        + (f" Not connected: {', '.join(unreachable)}." if unreachable else ""),
    )

    template = run.template()
    if compiled.kind == UNSUPPORTED or template is None:
        for stage in ("evidence_analyzed", "explanations_constructed", *SKIP_STAGES):
            run.stage(stage, "skipped", "Claim could not be mapped to observations.")
        investigation.assessment = "UNVERIFIED"
        investigation.assessment_rationale = build_rationale("UNVERIFIED", [], UNSUPPORTED)
        investigation.status = "concluded"
        run.stage("conclusion_updated", "done", "UNVERIFIED")
        run.finish()
        return

    run.stage("evidence_analyzed", "running")
    for name in template["automatic"]:
        run.run_tool(name)
    made = sum(1 for o in run.observables.values() if o["state"] != "unavailable")
    run.stage("evidence_analyzed", "done", f"{made} observations made from {len(run.evidence_rows())} evidence items.")

    run.stage("explanations_constructed", "running")
    run.seed_realities([])
    run.evaluate()
    tools = run
    board = run.board()
    board.explorer_notes = run.role("Explorer", "role.explore", lambda p: p.explore(board, tools))
    investigation.ledger = {**(investigation.ledger or {}), "_explorer": board.explorer_notes}
    run.seed_realities(run.role("Worldbuilder", "role.worldbuild", lambda p: p.worldbuild(run.board(), tools)))
    run.evaluate()
    challenge(run)
    count = len(db.scalars(select(Hypothesis.id).where(Hypothesis.investigation_id == investigation.id)).all())
    run.stage("explanations_constructed", "done", f"{count} competing realities constructed and tested.")
    advance(run)


def challenge(run: Run) -> None:
    critiques = run.role("Challenger", "role.challenge", lambda p: p.challenge(run.board(), run))
    for hypothesis in run.db.scalars(select(Hypothesis).where(Hypothesis.investigation_id == run.investigation.id)):
        hypothesis.challenge = critiques.get(hypothesis.label, hypothesis.challenge)
    run.db.commit()


def advance(run: Run) -> None:
    """Move to awaiting approval if a check can still help; otherwise conclude."""
    investigation = run.investigation
    explorer = (investigation.ledger or {}).get("_explorer", [])
    open_checks = run.propose_checks() if investigation.assessment not in ("CONTRADICTED", "SUPPORTED") else 0
    if open_checks:
        run.stage("investigation_recommended", "done", f"{open_checks} checks ranked by information value.")
        investigation.status = "awaiting_approval"
        run.stage("conclusion_updated", "pending", f"Provisional: {investigation.assessment}")
    else:
        recommended = db_status(run, "investigation_recommended")
        if recommended == "pending":
            run.stage("investigation_recommended", "skipped", "No further check would change the assessment.")
        if db_status(run, "verification_executed") == "pending":
            run.stage("verification_executed", "skipped", "No verification was required.")
        investigation.status = "concluded"
        for row in run.db.scalars(
            select(RecommendedCheck).where(
                RecommendedCheck.investigation_id == investigation.id, RecommendedCheck.status == "proposed"
            )
        ):
            row.status = "not_needed"
        run.stage("conclusion_updated", "done", investigation.assessment)
    run.finish()
    investigation.ledger = {**investigation.ledger, "_explorer": explorer}
    run.db.commit()


def db_status(run: Run, stage: str) -> str:
    return run.db.scalar(
        select(TimelineEvent.status).where(
            TimelineEvent.investigation_id == run.investigation.id, TimelineEvent.stage == stage
        )
    )


def execute_checks(db: Session, investigation_id: str, check_ids: list[str]) -> None:
    """Second pass: run only the checks a person approved, then update the conclusion."""
    investigation, choice = _open(db, investigation_id)
    run = Run(db, investigation, choice)
    investigation.status = "running_checks"
    db.commit()
    run.stage("verification_executed", "running")
    rows = db.scalars(
        select(RecommendedCheck)
        .where(RecommendedCheck.id.in_(check_ids), RecommendedCheck.status == "approved")
        .order_by(RecommendedCheck.position)
    ).all()
    completed, failed = 0, 0
    for row in rows:
        row.status = "running"
        db.commit()
        missing_before = set(run.unavailable)
        results = run.run_tool(row.tool)
        if results is None:
            new = {k: v for k, v in run.unavailable.items() if k not in missing_before} or run.unavailable
            row.status = "blocked"
            row.error = "; ".join(f"{k}: {v}" for k, v in new.items())
            failed += 1
        else:
            row.status = "completed"
            row.error = ""
            completed += 1
        db.commit()
    run.evaluate()
    challenge(run)
    run.stage(
        "verification_executed",
        "failed" if failed and not completed else "done",
        f"{completed} checks completed" + (f", {failed} could not run." if failed else "."),
    )
    advance(run)


def in_background(job, investigation_id: str, *args) -> None:
    """Background entry point. A crash is written to the investigation instead of being lost."""
    with SessionLocal() as db:
        try:
            job(db, investigation_id, *args)
        except Exception as exc:
            log.exception("Investigation job failed")
            db.rollback()
            investigation = db.get(Investigation, investigation_id)
            investigation.status = "failed"
            investigation.error = str(exc)[:1000]
            investigation.updated_at = utcnow()
            for event in db.scalars(
                select(TimelineEvent).where(
                    TimelineEvent.investigation_id == investigation_id, TimelineEvent.status == "running"
                )
            ):
                event.status = "failed"
                event.finished_at = utcnow()
            db.commit()


def mark_interrupted() -> None:
    """Runs at startup. Work that was in flight when the server stopped did not finish."""
    with SessionLocal() as db:
        for investigation in db.scalars(
            select(Investigation).where(Investigation.status.in_(["queued", "analyzing", "running_checks"]))
        ):
            investigation.status = "failed"
            investigation.error = "The server restarted while this investigation was running."
        db.commit()
