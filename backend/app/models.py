"""Persistent state. Records of what was observed are kept apart from what NULL inferred."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

Json = JSONB().with_variant(JSON(), "sqlite")


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid4().hex


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    settings: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataSource(Base):
    __tablename__ = "data_sources"
    __table_args__ = (UniqueConstraint("workspace_id", "key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    key: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(20), default="simulated")  # simulated | live
    status: Mapped[str] = mapped_column(String(20), default="disconnected")
    restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions: Mapped[list[str]] = mapped_column(Json, default=list)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvidenceRecord(Base):
    """A raw record as ingested. Never edited after load."""

    __tablename__ = "evidence_records"
    __table_args__ = (Index("ix_records_lookup", "dataset", "source_key", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset: Mapped[str] = mapped_column(String(20))
    source_key: Mapped[str] = mapped_column(String(40))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entity: Mapped[str] = mapped_column(String(120), default="")
    payload: Mapped[dict[str, Any]] = mapped_column(Json)


class GroundTruth(Base):
    """Answer key for synthetic snapshots. The analysis engine has no access to this table."""

    __tablename__ = "dataset_ground_truth"

    dataset: Mapped[str] = mapped_column(String(20), primary_key=True)
    truth: Mapped[dict[str, Any]] = mapped_column(Json)


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    ref: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    claim_text: Mapped[str] = mapped_column(Text)
    objective: Mapped[str] = mapped_column(Text, default="")
    dataset: Mapped[str] = mapped_column(String(20))
    scope: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    compiled_claim: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    source_keys: Mapped[list[str]] = mapped_column(Json, default=list)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    assessment: Mapped[str] = mapped_column(String(30), default="UNVERIFIED")
    assessment_rationale: Mapped[str] = mapped_column(Text, default="")
    limitations: Mapped[list[str]] = mapped_column(Json, default=list)
    ledger: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    observables: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    reasoning_mode: Mapped[str] = mapped_column(String(30), default="deterministic")
    reasoning_note: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    assignee_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    assignee: Mapped[User] = relationship(foreign_keys=[assignee_id])


class TimelineEvent(Base):
    __tablename__ = "timeline_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))  # pending | running | done | failed | skipped
    detail: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    position: Mapped[int] = mapped_column(Integer)


class ToolExecution(Base):
    __tablename__ = "tool_executions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    tool: Mapped[str] = mapped_column(String(60))
    role: Mapped[str] = mapped_column(String(30))  # system | Explorer | Worldbuilder | Challenger
    status: Mapped[str] = mapped_column(String(20), default="running")
    input: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    records_read: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvidenceItem(Base):
    """An observation derived from raw records by a named tool, with provenance."""

    __tablename__ = "evidence_items"
    __table_args__ = (UniqueConstraint("investigation_id", "ref"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(String(20))
    source_key: Mapped[str] = mapped_column(String(40))
    observable: Mapped[str] = mapped_column(String(60))
    observation: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reliability: Mapped[str] = mapped_column(String(20))
    reliability_basis: Mapped[str] = mapped_column(Text, default="")
    relevance: Mapped[str] = mapped_column(String(20))
    provenance: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    data: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(4))
    title: Mapped[str] = mapped_column(String(200))
    statement: Mapped[str] = mapped_column(Text)
    claim_true: Mapped[bool] = mapped_column(Boolean, default=False)
    origin: Mapped[str] = mapped_column(String(30))  # deterministic | model
    assumptions: Mapped[list[str]] = mapped_column(Json, default=list)
    predictions: Mapped[list[dict[str, Any]]] = mapped_column(Json, default=list)
    prediction_results: Mapped[list[dict[str, Any]]] = mapped_column(Json, default=list)
    supporting: Mapped[list[str]] = mapped_column(Json, default=list)
    contradicting: Mapped[list[str]] = mapped_column(Json, default=list)
    compatibility: Mapped[str] = mapped_column(String(30), default="untested")
    challenge: Mapped[str] = mapped_column(Text, default="")


class Assumption(Base):
    __tablename__ = "assumptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(60))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="unverified")  # unverified | held | violated
    basis: Mapped[str] = mapped_column(Text, default="")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(
        String(30)
    )  # evidence_gap | unsupported_assumption | incomplete_observation | measurement_bias
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20))
    evidence_refs: Mapped[list[str]] = mapped_column(Json, default=list)
    data: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)


class RecommendedCheck(Base):
    __tablename__ = "recommended_checks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    tool: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(200))
    procedure: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    distinguishes: Mapped[list[str]] = mapped_column(Json, default=list)
    information_gain_bits: Mapped[float] = mapped_column(Float, default=0.0)
    permissions: Mapped[list[str]] = mapped_column(Json, default=list)
    operational_impact: Mapped[str] = mapped_column(Text, default="")
    requires_sources: Mapped[list[str]] = mapped_column(Json, default=list)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    decided_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)


class Remediation(Base):
    __tablename__ = "remediations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(String(20), unique=True)
    key: Mapped[str] = mapped_column(String(60))
    finding: Mapped[str] = mapped_column(Text)
    root_cause: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20))
    risk_addressed: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    approval_status: Mapped[str] = mapped_column(String(20), default="pending")
    execution_status: Mapped[str] = mapped_column(String(20), default="not_started")
    verification_status: Mapped[str] = mapped_column(String(20), default="not_verified")
    verification_criteria: Mapped[str] = mapped_column(Text)
    verification_procedure: Mapped[str] = mapped_column(String(60))
    params: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped[User] = relationship(foreign_keys=[owner_id])


class VerificationRun(Base):
    __tablename__ = "verification_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    remediation_id: Mapped[str] = mapped_column(ForeignKey("remediations.id", ondelete="CASCADE"), index=True)
    procedure: Mapped[str] = mapped_column(String(60))
    passed: Mapped[bool] = mapped_column(Boolean)
    recurrence: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    run_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GraphNode(Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (Index("ix_graph_nodes_investigation", "investigation_id"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    investigation_id: Mapped[str | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)


class GraphEdge(Base):
    __tablename__ = "graph_edges"
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "relation"),
        Index("ix_graph_edges_investigation", "investigation_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    investigation_id: Mapped[str | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=True
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.id", ondelete="CASCADE"))
    target_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.id", ondelete="CASCADE"))
    relation: Mapped[str] = mapped_column(String(20))
    explanation: Mapped[str] = mapped_column(Text, default="")


class Report(Base):
    """An immutable snapshot of an investigation at the moment it was generated."""

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(String(20), unique=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(Json)
    sha256: Mapped[str] = mapped_column(String(64))
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_workspace_time", "workspace_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(80))
    target: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
    ip: Mapped[str] = mapped_column(String(60), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
