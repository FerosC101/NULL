"""Visual exhibits, computed from raw records through the same scoped reader as the engine.

Each exhibit states what it could not read. A restricted source stays closed until an approved
check has read it, so a chart can't reach further than the person who approved the investigation.
"""

from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.observables import TOOLS, active_coverage, failure_profile
from app.analysis.records import EvidenceReader, SourceUnavailable
from app.models import DataSource, EvidenceItem, Investigation, ToolExecution
from app.services.datasets import describe, last_hours

# EDR telemetry arrives in 4-hour batches, so an hourly row would show gaps that aren't gaps.
CADENCE_HOURS = {"edr": 4}
SERIES_SOURCES = ("idp_auth", "edr", "directory", "saas_audit")
POINT_IN_TIME = ("inventory", "coverage")
EVIDENCE_FOR_ROW = {
    "idp_auth": "idp_auth_anomaly",
    "edr": "edr_high_severity",
    "directory": "sessions_outside_idp",
    "network": "collection_continuity",
}
CLASS_LABELS = {"workstation": "Workstations", "server": "Servers", "ot_gateway": "OT gateways"}
EGRESS_HOST_LIMIT = 2


def _bins(start: datetime, end: datetime, hours: int) -> list[tuple[datetime, datetime]]:
    bins = []
    current = start
    while current < end:
        bins.append((current, min(current + timedelta(hours=hours), end)))
        current += timedelta(hours=hours)
    return bins


def _cells(frame: pd.DataFrame, start: datetime, end: datetime, hours: int, zero_state: str) -> list[dict]:
    cells = []
    for lower, upper in _bins(start, end, hours):
        count = int(((frame["ts"] >= lower) & (frame["ts"] < upper)).sum())
        cells.append(
            {
                "start": lower.isoformat(),
                "hours": int((upper - lower).total_seconds() // 3600),
                "count": count,
                "state": "records" if count else zero_state,
            }
        )
    return cells


def _closed_row(source: DataSource | None, key: str, selected: set[str], restricted_open: set[str]) -> str | None:
    """Why a source can't appear in the grid, or None when it can."""
    if source is None or source.status != "connected":
        return "disconnected"
    if key not in selected:
        return "not_selected"
    if source.restricted and key not in restricted_open:
        return "restricted"
    return None


def coverage_matrix(
    db: Session,
    workspace_id: str,
    dataset: str,
    start: datetime,
    end: datetime,
    selected: set[str],
    restricted_open: set[str],
    asset_classes: list[str] | None = None,
    refs: dict[str, str] | None = None,
) -> dict:
    """Sources against hours: where records exist, where they stop, and what could not be read."""
    refs = refs or {}
    sources = {s.key: s for s in db.scalars(select(DataSource).where(DataSource.workspace_id == workspace_id))}
    reader = EvidenceReader(db, workspace_id, dataset, selected, end, asset_classes)
    rows: list[dict] = []

    def add_closed(key: str, label: str, state: str) -> None:
        rows.append(
            {
                "key": key,
                "label": label,
                "source_key": key,
                "state": state,
                "cadence_hours": CADENCE_HOURS.get(key, 1),
                "records": None,
                "cells": [],
                "evidence_ref": None,
            }
        )

    for key in SERIES_SOURCES:
        source = sources.get(key)
        label = source.name if source else key
        closed = _closed_row(source, key, selected, restricted_open)
        if closed:
            add_closed(key, label, closed)
            continue
        try:
            frame = reader.frame(key)
        except SourceUnavailable:
            add_closed(key, label, "empty")
            continue
        frame = frame[(frame["ts"] >= start) & (frame["ts"] < end)]
        rows.append(
            {
                "key": key,
                "label": label,
                "source_key": key,
                "state": "readable",
                "cadence_hours": CADENCE_HOURS.get(key, 1),
                "records": len(frame),
                "cells": _cells(frame, start, end, CADENCE_HOURS.get(key, 1), "none"),
                "evidence_ref": refs.get(EVIDENCE_FOR_ROW.get(key, "")),
            }
        )

    network = sources.get("network")
    closed = _closed_row(network, "network", selected, restricted_open)
    frame = None
    if closed:
        add_closed("network", network.name if network else "network", closed)
    else:
        try:
            frame = reader.frame("network")
        except SourceUnavailable:
            add_closed("network", network.name, "empty")
    if frame is not None:
        windowed = frame[(frame["ts"] >= start) & (frame["ts"] < end)]
        # Subnets come from all records, so one silent for the whole window still gets a row.
        for subnet in sorted(frame["subnet"].dropna().unique()) if len(frame) else []:
            rows_for = windowed[windowed["subnet"] == subnet]
            rows.append(
                {
                    "key": f"network:{subnet}",
                    "label": f"Network: {subnet}",
                    "source_key": "network",
                    "state": "readable",
                    "cadence_hours": 1,
                    "records": len(rows_for),
                    "cells": _cells(rows_for, start, end, 1, "gap"),
                    "evidence_ref": refs.get("collection_continuity"),
                }
            )

    snapshots = []
    for key in POINT_IN_TIME:
        source = sources.get(key)
        closed = _closed_row(source, key, selected, restricted_open)
        entry = {"key": key, "label": source.name if source else key, "state": closed or "readable", "records": None}
        if not closed:
            try:
                frame = reader.frame(key)
                entry["records"] = len(frame)
                entry["taken_at"] = frame["ts"].max().isoformat() if len(frame) else None
            except SourceUnavailable:
                entry["state"] = "empty"
        snapshots.append(entry)

    gaps = [
        {"label": r["label"], "hours": sum(c["hours"] for c in r["cells"] if c["state"] == "gap")}
        for r in rows
        if any(c["state"] == "gap" for c in r["cells"])
    ]
    unreadable = [r["label"] for r in rows if r["state"] != "readable"]
    notes = [f"{g['label']} has no records for {g['hours']} of {len(_bins(start, end, 1))} hours." for g in gaps]
    if unreadable:
        notes.append(f"Not read: {', '.join(unreadable)}.")
    return {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "hours": [lower.isoformat() for lower, _ in _bins(start, end, 1)],
        "rows": rows,
        "snapshots": snapshots,
        "gaps": gaps,
        "unreadable": unreadable,
        "interpretation": " ".join(notes) or "Every readable source has records across the whole window.",
    }


def host_coverage(reader: EvidenceReader, start: datetime, end: datetime, directory_open: bool) -> dict:
    """What can see each host. Only the hosts EDR can't see are listed individually."""
    try:
        state = active_coverage(reader, end)
    except SourceUnavailable as exc:
        return {"unavailable": f"{exc.source_key}: {exc.reason}"}
    inventory = state["frame"]
    uncovered = set(state["uncovered"])
    try:
        network = reader.frame("network")
        seen: set | None = set(network[(network["ts"] >= start) & (network["ts"] <= end)]["hostname"])
    except SourceUnavailable:
        seen = None
    forwarding: dict | None = None
    if directory_open:
        try:
            directory = reader.frame("directory")
            logs = directory[directory["kind"] == "log_coverage"]
            forwarding = {row.hostname: bool(row.forwarding) for row in logs.itertuples()}
        except SourceUnavailable:
            forwarding = None
    classes = []
    for asset_class, group in inventory.groupby("asset_class"):
        hosts = set(group["hostname"])
        missing = sorted(hosts & uncovered)
        classes.append(
            {
                "asset_class": asset_class,
                "label": CLASS_LABELS.get(asset_class, str(asset_class)),
                "hosts": len(hosts),
                "reporting": len(hosts) - len(missing),
                "uncovered": missing,
            }
        )
    class_of = dict(zip(inventory["hostname"], inventory["asset_class"], strict=True))
    never = set(state["never_enrolled"])
    return {
        "hosts": len(state["hosts"]),
        "reporting": len(state["hosts"]) - len(uncovered),
        "by_class": sorted(classes, key=lambda c: c["asset_class"]),
        "unmonitored": [
            {
                "hostname": host,
                "asset_class": CLASS_LABELS.get(class_of.get(host), str(class_of.get(host))),
                "edr": "never_enrolled" if host in never else "stale",
                "network": None if seen is None else host in seen,
                "independent_logs": None if forwarding is None else forwarding.get(host, False),
            }
            for host in sorted(uncovered)
        ],
    }


def egress_series(reader: EvidenceReader, start: datetime, end: datetime, observables: dict) -> list[dict]:
    """Hourly egress for the hosts the egress test flagged, beside each host's own typical hour."""
    result = observables.get("egress_anomaly_uncovered")
    if not result:
        return []
    details = result.get("details", {})
    flagged = details.get("flagged", []) + details.get("explained_by_change", [])
    if not flagged:
        return []
    try:
        network = reader.frame("network")
    except SourceUnavailable:
        return []
    sessions = (observables.get("unexplained_sessions_uncovered") or {}).get("details", {}).get("sessions", [])
    series = []
    for host in flagged[:EGRESS_HOST_LIMIT]:
        rows = network[network["hostname"] == host]
        baseline = rows[rows["ts"] < start]
        typical = baseline.groupby(baseline["ts"].dt.hour)["bytes_out"].median()
        current = rows[(rows["ts"] >= start) & (rows["ts"] < end)].set_index("ts")["bytes_out"]
        points = []
        for lower, _ in _bins(start, end, 1):
            value = current.get(pd.Timestamp(lower))
            points.append(
                {
                    "ts": lower.isoformat(),
                    "bytes": None if value is None else int(value),
                    "typical": int(typical[lower.hour]) if lower.hour in typical.index else None,
                }
            )
        stats = details.get("hosts", {}).get(host, {})
        highest = max((p for p in points if p["bytes"] is not None), key=lambda p: p["bytes"], default=None)
        series.append(
            {
                "host": host,
                "explained_by_change": host in details.get("explained_by_change", []),
                # The test scores departure from the host's own hour, so its top hour isn't always the largest.
                "anomaly_ts": stats.get("peak_ts"),
                "anomaly_bytes": stats.get("peak_bytes"),
                "highest_ts": highest["ts"] if highest else None,
                "highest_bytes": highest["bytes"] if highest else None,
                "baseline_median_bytes": stats.get("baseline_median_bytes"),
                "max_z": stats.get("max_z"),
                "baseline_records": len(baseline),
                "points": points,
                "events": [
                    {"ts": s["ts"], "label": f"Unexplained logon by {s['user']}"}
                    for s in sessions
                    if s.get("hostname") == host
                ],
            }
        )
    return series


def signin_series(reader: EvidenceReader, start: datetime, end: datetime) -> dict | None:
    try:
        frame = reader.frame("idp_auth")
    except SourceUnavailable:
        return None
    profile = failure_profile(frame, start, end)
    points = [
        {"ts": hour.isoformat(), "failures": observed, "expected": round(expected, 1), "flagged": bool(rejected)}
        for hour, observed, expected, rejected in zip(
            profile["hours"], profile["observed"], profile["expected"], profile["rejected"], strict=True
        )
    ]
    return {"points": points, "flagged_hours": sum(1 for p in points if p["flagged"])}


def _restricted_open(db: Session, investigation: Investigation) -> set[str]:
    """Restricted sources an approved check has already read for this investigation."""
    tools = db.scalars(
        select(ToolExecution.tool).where(
            ToolExecution.investigation_id == investigation.id, ToolExecution.status == "succeeded"
        )
    ).all()
    return {key for name in tools if name in TOOLS for key in TOOLS[name].sources}


def compute(db: Session, investigation: Investigation) -> dict:
    start = datetime.fromisoformat(investigation.scope["window_start"])
    end = datetime.fromisoformat(investigation.scope["window_end"])
    selected = set(investigation.source_keys)
    opened = _restricted_open(db, investigation)
    asset_classes = investigation.scope.get("asset_classes")
    items = db.scalars(select(EvidenceItem).where(EvidenceItem.investigation_id == investigation.id)).all()
    refs = {e.observable: e.ref for e in items if e.data.get("primary")}
    reader = EvidenceReader(db, investigation.workspace_id, investigation.dataset, selected, end, asset_classes)
    observables = investigation.observables or {}
    return {
        "coverage_matrix": coverage_matrix(
            db,
            investigation.workspace_id,
            investigation.dataset,
            start,
            end,
            selected,
            opened,
            asset_classes,
            refs,
        ),
        "host_coverage": host_coverage(reader, start, end, "directory" in opened),
        "egress": egress_series(reader, start, end, observables),
        "signins": signin_series(reader, start, end),
        "refs": {
            "egress": refs.get("egress_anomaly_uncovered"),
            "signins": refs.get("idp_auth_anomaly"),
            "coverage": refs.get("active_monitoring_gap") or refs.get("enrollment_gap"),
        },
    }


def workspace_matrix(db: Session, workspace_id: str, dataset: str) -> dict:
    """Collection health for the Sources page. Restricted sources stay closed here."""
    sources = db.scalars(select(DataSource).where(DataSource.workspace_id == workspace_id))
    connected = {s.key for s in sources if s.status == "connected"}
    start, end = last_hours(describe(db, dataset, workspace_id), 24)
    return coverage_matrix(db, workspace_id, dataset, start, end, connected, set())
