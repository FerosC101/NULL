"""Preventive assurance: weaknesses in the evidence environment, measured from current records."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.observables import active_coverage, collection_continuity
from app.analysis.records import EvidenceReader, SourceUnavailable
from app.demo.generator import WINDOW_END, WINDOW_START
from app.models import Assumption, DataSource, Investigation

CURRENT_AGENT = "7.4.2"


def preventive_scan(db: Session, workspace_id: str, dataset: str) -> dict:
    sources = db.scalars(select(DataSource).where(DataSource.workspace_id == workspace_id)).all()
    connected = {s.key for s in sources if s.status == "connected"}
    disconnected = [{"key": s.key, "name": s.name} for s in sources if s.status != "connected"]
    reader = EvidenceReader(db, workspace_id, dataset, connected, None)
    result: dict = {
        "dataset": dataset,
        "disconnected_sources": disconnected,
        "coverage": None,
        "collection_weaknesses": [],
        "emerging_risks": [],
        "unavailable": [],
    }
    try:
        coverage_frame = reader.frame("coverage")
        latest_ts = coverage_frame["ts"].max().to_pydatetime() if len(coverage_frame) else WINDOW_END
        state = active_coverage(reader, max(latest_ts, WINDOW_END))
        inventory = state["frame"]
        rows = []
        for asset_class, group in inventory.groupby("asset_class"):
            hosts = set(group["hostname"])
            uncovered = sorted(hosts & set(state["uncovered"]))
            rows.append(
                {
                    "asset_class": asset_class,
                    "hosts": len(hosts),
                    "reporting": len(hosts) - len(uncovered),
                    "uncovered": uncovered,
                }
            )
        total = len(state["hosts"])
        result["coverage"] = {
            "hosts": total,
            "reporting": total - len(state["uncovered"]),
            "never_enrolled": state["never_enrolled"],
            "stale": state["stale"],
            "by_class": sorted(rows, key=lambda r: r["asset_class"]),
        }
        latest = coverage_frame.sort_values("ts").groupby("hostname").tail(1)
        outdated = latest[latest["agent_version"] != CURRENT_AGENT]
        if len(outdated):
            result["emerging_risks"].append(
                {
                    "title": "Agents behind the current version",
                    "body": f"{len(outdated)} of {len(latest)} agents run a version older than {CURRENT_AGENT}.",
                    "severity": "low",
                }
            )
    except SourceUnavailable as exc:
        result["unavailable"].append({"key": exc.source_key, "reason": exc.reason})
    try:
        continuity = collection_continuity(reader, WINDOW_START, WINDOW_END)
        for gap in continuity.details["gaps"]:
            result["collection_weaknesses"].append(
                {"subnet": gap["subnet"], "missing_hours": len(gap["hours"]), "first": gap["hours"][0]}
            )
    except SourceUnavailable as exc:
        result["unavailable"].append({"key": exc.source_key, "reason": exc.reason})
    return result


def unverified_assumptions(db: Session, workspace_id: str) -> list[dict]:
    rows = db.execute(
        select(Assumption, Investigation)
        .join(Investigation, Assumption.investigation_id == Investigation.id)
        .where(Investigation.workspace_id == workspace_id, Assumption.status.in_(["unverified", "violated"]))
        .order_by(Investigation.ref)
    ).all()
    return [
        {
            "text": a.text,
            "status": a.status,
            "basis": a.basis,
            "investigation_id": i.id,
            "investigation_ref": i.ref,
        }
        for a, i in rows
    ]
