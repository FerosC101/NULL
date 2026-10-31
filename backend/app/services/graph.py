"""Materializes each investigation's evidence graph into graph_nodes and graph_edges."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    Assumption,
    DataSource,
    EvidenceItem,
    GraphEdge,
    GraphNode,
    Hypothesis,
    Investigation,
    Remediation,
)

# Which assumption each remediation addresses.
REMEDIATION_RESOLVES = {
    "enroll_unmonitored": "coverage_complete",
    "restore_sensor": "records_complete",
    "extend_independent_logging": "records_complete",
    "contain_credential": "idp_is_chokepoint",
    "enforce_mfa": "idp_is_chokepoint",
}


def rebuild_graph(db: Session, investigation: Investigation) -> None:
    db.execute(delete(GraphEdge).where(GraphEdge.investigation_id == investigation.id))
    db.execute(delete(GraphNode).where(GraphNode.investigation_id == investigation.id))
    db.flush()
    workspace_id = investigation.workspace_id
    seen_edges: set[tuple[str, str, str]] = set()

    def node(node_id: str, kind: str, label: str, shared: bool = False, **data) -> str:
        if shared:
            if db.get(GraphNode, node_id) is None:
                db.add(
                    GraphNode(
                        id=node_id, workspace_id=workspace_id, investigation_id=None, kind=kind, label=label, data=data
                    )
                )
                db.flush()
        else:
            db.add(
                GraphNode(
                    id=node_id,
                    workspace_id=workspace_id,
                    investigation_id=investigation.id,
                    kind=kind,
                    label=label,
                    data={**data, "investigation_ref": investigation.ref},
                )
            )
        return node_id

    def edge(source: str, target: str, relation: str, explanation: str = "") -> None:
        if (source, target, relation) in seen_edges:
            return
        seen_edges.add((source, target, relation))
        db.add(
            GraphEdge(
                investigation_id=investigation.id,
                source_id=source,
                target_id=target,
                relation=relation,
                explanation=explanation,
            )
        )

    prefix = investigation.id
    inv_node = node(
        f"inv:{prefix}",
        "investigation",
        f"{investigation.ref} {investigation.name}",
        status=investigation.status,
        assessment=investigation.assessment,
    )
    claim_node = node(f"claim:{prefix}", "claim", investigation.claim_text, assessment=investigation.assessment)
    db.flush()
    edge(inv_node, claim_node, "challenges", "This investigation tests the claim.")

    sources = {s.key: s for s in db.scalars(select(DataSource).where(DataSource.workspace_id == workspace_id))}
    assumptions = {
        a.key: a for a in db.scalars(select(Assumption).where(Assumption.investigation_id == investigation.id))
    }
    evidence = [
        e
        for e in db.scalars(select(EvidenceItem).where(EvidenceItem.investigation_id == investigation.id))
        if e.data.get("primary")
    ]
    by_ref = {e.ref: e for e in evidence}
    for item in evidence:
        node(
            f"ev:{prefix}:{item.ref}",
            "evidence",
            f"{item.ref} {item.observation}",
            ref=item.ref,
            state=item.data.get("state"),
            reliability=item.reliability,
        )
    for assumption in assumptions.values():
        node(
            f"as:{prefix}:{assumption.key}",
            "assumption",
            assumption.text,
            status=assumption.status,
            basis=assumption.basis,
        )
    hypotheses = db.scalars(select(Hypothesis).where(Hypothesis.investigation_id == investigation.id)).all()
    for hypothesis in hypotheses:
        node(
            f"hy:{prefix}:{hypothesis.label}",
            "hypothesis",
            f"Reality {hypothesis.label}: {hypothesis.title}",
            compatibility=hypothesis.compatibility,
            origin=hypothesis.origin,
        )
    db.flush()

    for item in evidence:
        for key in item.provenance.get("sources", []):
            source = sources.get(key)
            if source:
                source_node = node(f"src:{workspace_id[:8]}:{key}", "source", source.name, shared=True, key=key)
                edge(
                    f"ev:{prefix}:{item.ref}",
                    source_node,
                    "derived_from",
                    f"{item.provenance.get('tool')} read this source.",
                )
    for assumption in assumptions.values():
        edge(claim_node, f"as:{prefix}:{assumption.key}", "depends_on", "The claim needs this to hold.")
    for hypothesis in hypotheses:
        target = f"hy:{prefix}:{hypothesis.label}"
        if hypothesis.claim_true:
            edge(target, claim_node, "supports", "If this reality holds, the claim is true.")
        else:
            edge(target, claim_node, "challenges", "If this reality holds, the claim is false.")
        for ref in hypothesis.supporting:
            if ref in by_ref:
                edge(f"ev:{prefix}:{ref}", target, "supports", "The observation matches this reality's prediction.")
        for ref in hypothesis.contradicting:
            if ref in by_ref:
                edge(f"ev:{prefix}:{ref}", target, "contradicts", "The observation violates this reality's prediction.")
    observable_refs = {e.observable: e.ref for e in evidence}
    tested_by = {
        "coverage_complete": ["enrollment_gap", "active_monitoring_gap"],
        "records_complete": ["collection_continuity"],
        "idp_is_chokepoint": ["sessions_outside_idp"],
        "enrolled_means_reporting": ["active_monitoring_gap"],
    }
    for key, assumption in assumptions.items():
        for observable in tested_by.get(key, []):
            ref = observable_refs.get(observable)
            if ref and assumption.status in ("held", "violated"):
                relation = "supports" if assumption.status == "held" else "contradicts"
                edge(f"ev:{prefix}:{ref}", f"as:{prefix}:{key}", relation, assumption.basis)
    remediations = db.scalars(select(Remediation).where(Remediation.investigation_id == investigation.id)).all()
    for remediation in remediations:
        rem_node = node(
            f"rm:{remediation.id}",
            "remediation",
            f"{remediation.ref} {remediation.action}",
            ref=remediation.ref,
            verification=remediation.verification_status,
        )
        db.flush()
        target = REMEDIATION_RESOLVES.get(remediation.key)
        if target and target in assumptions:
            edge(rem_node, f"as:{prefix}:{target}", "resolves", remediation.verification_criteria)
        else:
            edge(rem_node, claim_node, "resolves", remediation.verification_criteria)
