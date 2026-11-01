"""Deterministic observables: named questions answered from raw records.

Every result carries its state, the records it rests on, and a reliability basis. A language
model can name these observables in a prediction but cannot compute or overrule them.

States: positive, zero, partial (the answer holds for only part of the scope), unavailable.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from app.analysis.records import EvidenceReader, SourceUnavailable

ALPHA = 0.01
STALE_AFTER = timedelta(hours=24)
NETWORK_SHIFT_LIMIT = 0.25


@dataclass
class ObservableResult:
    key: str
    state: str
    value: float
    summary: str
    source_keys: list[str]
    method: str
    reliability: str
    reliability_basis: str
    relevance: str
    record_ids: list[int] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _count(items: list, noun: str) -> str:
    return f"{len(items)} {noun}{'' if len(items) == 1 else 's'}"


def _text(value) -> str | None:
    """Sparse JSON columns come back from pandas as NaN, which is not valid JSON."""
    return value if isinstance(value, str) else None


def _ids(frame: pd.DataFrame, limit: int = 25) -> list[int]:
    return [int(i) for i in frame["record_id"].head(limit)] if "record_id" in frame else []


def _window(frame: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
    return frame[(frame["ts"] >= start) & (frame["ts"] <= end)]


def active_coverage(reader: EvidenceReader, end: datetime) -> dict:
    """Host-level comparison of inventory with agents that actually reported."""
    inventory = reader.frame("inventory")
    coverage = reader.frame("coverage")
    hosts = set(inventory[inventory["in_scope"]]["hostname"])
    latest = coverage.sort_values("ts").groupby("hostname").tail(1)
    heartbeat = pd.to_datetime(latest["last_heartbeat"], utc=True, format="ISO8601")
    reporting = set(latest[(end - heartbeat) <= STALE_AFTER]["hostname"])
    enrolled = set(latest["hostname"])
    return {
        "hosts": hosts,
        "enrolled": enrolled,
        "never_enrolled": sorted(hosts - enrolled),
        "stale": sorted((hosts & enrolled) - reporting),
        "uncovered": sorted(hosts - reporting),
        "frame": inventory,
    }


def edr_high_severity(reader: EvidenceReader, start, end) -> ObservableResult:
    frame = _window(reader.frame("edr"), start, end)
    detections = frame[frame["event"] == "detection"] if "event" in frame else frame.iloc[0:0]
    high = detections[detections["severity"].isin(["high", "critical"])] if len(detections) else detections
    count = len(high)
    return ObservableResult(
        key="edr_high_severity",
        state="positive" if count else "zero",
        value=count,
        summary=f"{count} high or critical EDR detections in the window; {len(detections)} detections of any severity, "
        "all auto-closed."
        if not count
        else f"{count} high or critical EDR detections in the window.",
        source_keys=["edr"],
        method="Filter EDR detection events to severity high or critical within the scope window.",
        reliability="moderate",
        reliability_basis="Vendor console output. It can only describe hosts with a reporting agent.",
        relevance="high",
        record_ids=_ids(high if count else detections),
        details={"all_detections": len(detections)},
    )


def failure_profile(frame: pd.DataFrame, start, end) -> dict:
    """Hourly failed sign-ins against the same hour-of-day baseline, with the hours that exceed it."""
    failures = frame[frame["result"] == "failure"]
    baseline = failures[failures["ts"] < start]
    current = _window(failures, start, end)
    baseline_hours = max((start - frame["ts"].min()).total_seconds() / 3600, 1)
    rate_by_hour = baseline.groupby(baseline["ts"].dt.hour).size() / (baseline_hours / 24)
    counts = current.groupby(current["ts"].dt.floor("h")).size()
    tested = pd.date_range(start, end, freq="h", inclusive="left")
    rates = [max(float(rate_by_hour.get(hour.hour, 0.5)), 0.5) for hour in tested]
    observed = [int(counts.get(hour, 0)) for hour in tested]
    pvalues = [float(stats.poisson.sf(c - 1, r)) for c, r in zip(observed, rates, strict=True)]
    rejected = multipletests(pvalues, alpha=ALPHA, method="fdr_bh")[0]
    return {"hours": tested, "observed": observed, "expected": rates, "rejected": rejected, "current": current}


def idp_auth_anomaly(reader: EvidenceReader, start, end) -> ObservableResult:
    profile = failure_profile(reader.frame("idp_auth"), start, end)
    tested, current = profile["hours"], profile["current"]
    flagged = [tested[i].isoformat() for i, r in enumerate(profile["rejected"]) if r]
    return ObservableResult(
        key="idp_auth_anomaly",
        state="positive" if flagged else "zero",
        value=len(flagged),
        summary=f"{len(flagged)} of {len(tested)} hours exceed the failed sign-in baseline at FDR {ALPHA}; "
        f"{len(current)} failures in the window.",
        source_keys=["idp_auth"],
        method="Poisson tail test of hourly failed sign-ins against the same hour-of-day baseline, "
        "Benjamini-Hochberg corrected across hours.",
        reliability="high",
        reliability_basis="Identity provider records with complete hourly continuity in the window.",
        relevance="medium",
        record_ids=_ids(current),
        details={"flagged_hours": flagged, "failures": len(current), "hours_tested": len(tested)},
    )


def enrollment_gap(reader: EvidenceReader, start, end) -> ObservableResult:
    state = active_coverage(reader, end)
    gap = len(state["hosts"]) - len(state["hosts"] & state["enrolled"])
    return ObservableResult(
        key="enrollment_gap",
        state="positive" if gap else "zero",
        value=gap,
        summary=f"{len(state['hosts'] & state['enrolled'])} of {len(state['hosts'])} inventoried hosts have an "
        "enrolled EDR agent."
        + (f" {gap} hosts have none." if gap else " Enrollment does not show whether those agents reported."),
        source_keys=["inventory", "coverage"],
        method="Count in-scope inventory hosts with an enrollment record. Host-level reporting is not checked here.",
        reliability="moderate",
        reliability_basis="Enrollment shows that an agent was installed, not that it was reporting.",
        relevance="high",
        record_ids=_ids(state["frame"]),
        details={"hosts": len(state["hosts"]), "enrolled": len(state["hosts"] & state["enrolled"])},
    )


def network_volume(reader: EvidenceReader, start, end) -> ObservableResult:
    frame = reader.frame("network")
    current = _window(frame, start, end)
    # Baseline periods align with the window, so each covers the same hours of the day.
    period = end - start
    totals = []
    period_end = start
    while period_end - period >= frame["ts"].min():
        rows = frame[(frame["ts"] >= period_end - period) & (frame["ts"] < period_end)]
        totals.append(float(rows["bytes_out"].sum()))
        period_end -= period
    baseline = float(np.mean(totals)) if totals else 0.0
    total = float(current["bytes_out"].sum())
    change = (total - baseline) / baseline if baseline else 0.0
    return ObservableResult(
        key="network_volume",
        state="positive" if abs(change) > NETWORK_SHIFT_LIMIT else "zero",
        value=round(change * 100, 1),
        summary=f"Total egress is {change * 100:+.1f}% against the mean of {len(totals)} equal baseline periods.",
        source_keys=["network"],
        method=f"Compare total egress in the window with aligned baseline periods. A shift beyond "
        f"{NETWORK_SHIFT_LIMIT:.0%} counts as positive.",
        reliability="low",
        reliability_basis="An organization-wide total can hide a change on a single host.",
        relevance="low",
        record_ids=_ids(current),
        details={"window_bytes": total, "baseline_mean_bytes": baseline, "baseline_periods": len(totals)},
    )


def collection_continuity(reader: EvidenceReader, start, end) -> ObservableResult:
    frame = _window(reader.frame("network"), start, end)
    hours = pd.date_range(start, end, freq="h", inclusive="left")
    by_subnet = frame.groupby([frame["ts"].dt.floor("h"), "subnet"]).size().unstack(fill_value=0)
    by_subnet = by_subnet.reindex(hours, fill_value=0)
    gaps = []
    for subnet in by_subnet.columns:
        missing = by_subnet.index[by_subnet[subnet] == 0]
        if len(missing):
            gaps.append({"subnet": subnet, "hours": [t.isoformat() for t in missing]})
    missing_hours = sum(len(g["hours"]) for g in gaps)
    return ObservableResult(
        key="collection_continuity",
        state="positive" if gaps else "zero",
        value=missing_hours,
        summary=(
            f"{missing_hours} subnet-hours are missing from network records: "
            + ", ".join(f"{g['subnet']} ({len(g['hours'])}h)" for g in gaps)
            + "."
            if gaps
            else "Network records are continuous across every subnet in the window."
        ),
        source_keys=["network"],
        method="Count records per subnet per hour and report hours with no records at all.",
        reliability="high",
        reliability_basis="Direct count of stored records.",
        relevance="medium",
        record_ids=_ids(frame.head(5)),
        details={"gaps": gaps},
    )


def reconcile_gap(reader: EvidenceReader, start, end) -> list[ObservableResult]:
    state = active_coverage(reader, end)
    uncovered = state["uncovered"]
    network = _window(reader.frame("network"), start, end)
    active = sorted(set(uncovered) & set(network["hostname"]))
    gap = ObservableResult(
        key="active_monitoring_gap",
        state="positive" if uncovered else "zero",
        value=len(uncovered),
        summary=f"{len(uncovered)} of {len(state['hosts'])} in-scope hosts had no reporting EDR agent: "
        f"{len(state['never_enrolled'])} never enrolled, {len(state['stale'])} enrolled with a heartbeat older "
        f"than {int(STALE_AFTER.total_seconds() // 3600)} hours.",
        source_keys=["inventory", "coverage"],
        method="Join inventory to the latest coverage record per host and require a heartbeat within 24 hours "
        "of the window end.",
        reliability="high",
        reliability_basis="Host-level join across two independently maintained systems.",
        relevance="critical",
        record_ids=_ids(state["frame"][state["frame"]["hostname"].isin(uncovered)]),
        details={
            "uncovered": uncovered,
            "never_enrolled": state["never_enrolled"],
            "stale": state["stale"],
            "hosts": len(state["hosts"]),
        },
    )
    activity = ObservableResult(
        key="uncovered_host_activity",
        state="positive" if active else "zero",
        value=len(active),
        summary=(
            f"{len(active)} of the {len(uncovered)} unmonitored hosts sent network traffic during the window."
            + (f" Active: {', '.join(active)}." if active else "")
            if uncovered
            else "Every in-scope host has a reporting agent, so no unmonitored host could be active."
        ),
        source_keys=["inventory", "coverage", "network"],
        method="Intersect unmonitored hosts with hosts present in network records in the window.",
        reliability="high",
        reliability_basis="Network records are collected independently of the EDR agent.",
        relevance="high",
        record_ids=_ids(network[network["hostname"].isin(active)]),
        details={"active": active, "silent": sorted(set(uncovered) - set(active))},
    )
    return [gap, activity]


def inspect_independent_auth(reader: EvidenceReader, start, end) -> list[ObservableResult]:
    state = active_coverage(reader, end)
    uncovered = set(state["uncovered"])
    directory = reader.frame("directory")
    idp = reader.frame("idp_auth")
    known_sessions = set(idp["session_id"])

    log_coverage = directory[directory["kind"] == "log_coverage"]
    forwarding = set(log_coverage[log_coverage["forwarding"].astype(bool)]["hostname"])
    unreached = sorted(uncovered - forwarding)
    unreached_all = sorted(state["hosts"] - forwarding)

    changes = directory[directory["kind"] == "change_record"]
    valid_refs = {}
    for row in changes.itertuples():
        valid_refs[row.change_ref] = {
            "hostnames": set(row.hostnames),
            "start": pd.Timestamp(row.window_start),
            "end": pd.Timestamp(row.window_end),
        }

    logons = _window(directory[directory["kind"].isin(["dc_logon", "vpn_session"])], start, end)
    without_idp = logons[~logons["idp_session_id"].isin(known_sessions)]

    def covered_by_change(row) -> bool:
        change = valid_refs.get(row.get("change_ref"))
        return bool(
            change and row.get("hostname") in change["hostnames"] and change["start"] <= row["ts"] <= change["end"]
        )

    explained, unexplained = [], []
    for row in without_idp.to_dict("records"):
        (explained if covered_by_change(row) else unexplained).append(row)

    def describe(row: dict) -> dict:
        return {
            "record_id": int(row["record_id"]),
            "ts": row["ts"].isoformat(),
            "kind": row["kind"],
            "user": row["user"],
            "hostname": _text(row.get("hostname")),
            "src_ip": _text(row.get("src_ip")),
            "src_asn": _text(row.get("src_asn")),
            "change_ref": _text(row.get("change_ref")),
        }

    unexplained_logons = [r for r in unexplained if isinstance(r.get("hostname"), str)]
    on_uncovered = [describe(r) for r in unexplained_logons if r["hostname"] in uncovered]
    on_monitored = [describe(r) for r in unexplained_logons if r["hostname"] not in uncovered]
    vpn_only = [describe(r) for r in unexplained if not isinstance(r.get("hostname"), str)]
    ids = [int(r["record_id"]) for r in unexplained] or _ids(logons)
    shared = dict(
        source_keys=["directory", "idp_auth", "coverage", "inventory"],
        method="Anti-join domain-controller and VPN records against identity-provider sessions, excluding records "
        "that fall inside an approved change for the same host.",
        reliability="high",
        reliability_basis="Recorded by domain controllers and the VPN concentrator, outside the identity provider "
        "and the EDR agent.",
        relevance="critical",
        record_ids=ids[:25],
    )
    # Silence from a host with no independent logging says nothing, so a zero becomes partial here.
    if on_uncovered:
        uncovered_state = "positive"
    elif unreached:
        uncovered_state = "partial"
    else:
        uncovered_state = "zero"
    return [
        ObservableResult(
            key="unexplained_sessions_uncovered",
            state=uncovered_state,
            value=len(on_uncovered),
            summary=(
                f"{_count(on_uncovered, 'logon')} on unmonitored hosts without an identity-provider session or an "
                f"approved change: {on_uncovered[0]['user']} on {on_uncovered[0]['hostname']}."
                if on_uncovered
                else f"No unexplained logons on unmonitored hosts, but {len(unreached)} of those hosts forward no "
                f"independent logs: {', '.join(unreached)}."
                if unreached
                else "No unexplained logons on unmonitored hosts, and independent logs reach every host."
            ),
            details={"sessions": on_uncovered, "vpn_sessions": vpn_only, "unreached": unreached},
            **shared,
        ),
        ObservableResult(
            key="unexplained_sessions_monitored",
            state="positive" if on_monitored else ("partial" if len(unreached_all) > len(unreached) else "zero"),
            value=len(on_monitored),
            summary=(
                f"{_count(on_monitored, 'logon')} on monitored hosts without an identity-provider session or an "
                f"approved change: {on_monitored[0]['user']} on {on_monitored[0]['hostname']}."
                if on_monitored
                else "No unexplained logons on monitored hosts."
            ),
            details={"sessions": on_monitored},
            **shared,
        ),
        ObservableResult(
            key="sessions_outside_idp",
            state="positive" if len(without_idp) else "zero",
            value=len(without_idp),
            summary=f"{len(without_idp)} directory or VPN records have no identity-provider session; "
            f"{len(explained)} match an approved change.",
            details={
                "explained": [describe(r) for r in explained],
                "unexplained": [describe(r) for r in unexplained],
                "logons_examined": len(logons),
            },
            **shared,
        ),
    ]


def host_egress_test(reader: EvidenceReader, start, end) -> ObservableResult:
    state = active_coverage(reader, end)
    uncovered = state["uncovered"]
    network = reader.frame("network")
    frame = network[network["hostname"].isin(uncovered)].copy()
    frame["log_bytes"] = np.log1p(frame["bytes_out"].astype(float))
    hosts, pvalues, stats_by_host = [], [], {}
    for host, rows in frame.groupby("hostname"):
        baseline = rows[rows["ts"] < start]
        current = rows[(rows["ts"] >= start) & (rows["ts"] <= end)]
        if len(baseline) < 24 or current.empty:
            continue
        # Compare against this host's own hour-of-day profile so ordinary daily cycles don't register.
        profile = baseline.groupby(baseline["ts"].dt.hour)["log_bytes"].mean()
        residuals = baseline["log_bytes"] - baseline["ts"].dt.hour.map(profile)
        sigma = float(residuals.std(ddof=1)) or 1.0
        excess = current["log_bytes"] - current["ts"].dt.hour.map(profile).fillna(float(profile.mean()))
        z = float(excess.max() / sigma)
        hosts.append(host)
        # Bonferroni across the host's hours gives a valid p-value for the max statistic.
        pvalues.append(min(float(stats.norm.sf(z)) * len(current), 1.0))
        peak = current.loc[excess.idxmax()]
        stats_by_host[host] = {
            "max_z": round(z, 2),
            "peak_ts": peak["ts"].isoformat(),
            "peak_bytes": int(peak["bytes_out"]),
            "baseline_median_bytes": int(baseline["bytes_out"].median()),
        }
    flagged: list[str] = []
    if pvalues:
        rejected = multipletests(pvalues, alpha=ALPHA, method="fdr_bh")[0]
        flagged = [h for h, r in zip(hosts, rejected, strict=True) if r]
    explained, changes_read = _egress_change_overlaps(reader, flagged, stats_by_host)
    remaining = [h for h in flagged if h not in explained]
    tested = len(hosts)
    if not tested:
        result_state = "zero"
    else:
        result_state = "positive" if remaining else "zero"
    summary = (
        f"{len(remaining)} of {tested} tested unmonitored hosts show unexplained egress above their own baseline"
        if tested
        else "No unmonitored hosts had enough records to test"
    )
    if remaining:
        top = stats_by_host[remaining[0]]
        summary += (
            f": {remaining[0]} moved {top['peak_bytes'] / 1e9:.1f} GB in its most anomalous hour against a "
            f"{top['baseline_median_bytes'] / 1e6:.0f} MB median"
        )
    summary += "."
    if explained:
        summary += f" {', '.join(explained)} also spiked inside an approved change window."
    if flagged and not changes_read:
        summary += " Change records were unavailable, so these spikes were not compared with approved changes."
    return ObservableResult(
        key="egress_anomaly_uncovered",
        state=result_state,
        value=len(remaining),
        summary=summary,
        source_keys=["network", "coverage", "inventory", "directory"],
        method="Test each unmonitored host's peak hourly log-egress against its own hour-of-day baseline, Bonferroni "
        "within host and Benjamini-Hochberg across hosts, then remove peaks inside approved change windows.",
        reliability="moderate",
        reliability_basis="Volume anomalies are indirect. They show movement of data, not who caused it.",
        relevance="high",
        record_ids=_ids(frame[frame["hostname"].isin(remaining or flagged)].sort_values("bytes_out", ascending=False)),
        details={
            "tested": tested,
            "flagged": remaining,
            "explained_by_change": explained,
            "change_records_read": changes_read,
            "hosts": stats_by_host,
        },
    )


def _egress_change_overlaps(reader: EvidenceReader, flagged: list[str], stats_by_host: dict) -> tuple[list[str], bool]:
    """Return flagged hosts whose peak falls inside an approved change, and whether changes could be read."""
    if not flagged:
        return [], True
    try:
        directory = reader.frame("directory")
    except SourceUnavailable:
        return [], False
    changes = directory[directory["kind"] == "change_record"]
    explained = []
    for host in flagged:
        peak = pd.Timestamp(stats_by_host[host]["peak_ts"])
        for row in changes.itertuples():
            if host in row.hostnames and pd.Timestamp(row.window_start) <= peak <= pd.Timestamp(row.window_end):
                explained.append(host)
                break
    return explained, True


def mfa_enforcement(reader: EvidenceReader, start, end) -> ObservableResult:
    frame = _window(reader.frame("idp_auth"), start, end)
    successes = frame[frame["result"] == "success"]
    missing = successes[~successes["mfa"].astype(bool)]
    by_app = {str(k): int(v) for k, v in missing.groupby("app").size().items()}
    return ObservableResult(
        key="mfa_unenforced_logins",
        state="positive" if len(missing) else "zero",
        value=len(missing),
        summary=f"{len(missing)} of {len(successes)} successful sign-ins completed without MFA"
        + (f", in {', '.join(by_app)}." if by_app else "."),
        source_keys=["idp_auth"],
        method="Filter successful identity-provider sign-ins in the window to those without an MFA step.",
        reliability="high",
        reliability_basis="The identity provider records the MFA step on every sign-in.",
        relevance="critical",
        record_ids=_ids(missing if len(missing) else successes),
        details={"successes": len(successes), "by_app": by_app},
    )


Runner = Callable[[EvidenceReader, datetime, datetime], ObservableResult | list[ObservableResult]]


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    run: Runner
    sources: tuple[str, ...]
    observables: tuple[str, ...]


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool("scan_edr_detections", "Scan EDR detections", edr_high_severity, ("edr",), ("edr_high_severity",)),
        Tool("test_signin_anomalies", "Test sign-in anomalies", idp_auth_anomaly, ("idp_auth",), ("idp_auth_anomaly",)),
        Tool(
            "count_enrollment", "Count EDR enrollment", enrollment_gap, ("inventory", "coverage"), ("enrollment_gap",)
        ),
        Tool("measure_network_volume", "Measure total egress", network_volume, ("network",), ("network_volume",)),
        Tool(
            "check_collection_continuity",
            "Check collection continuity",
            collection_continuity,
            ("network",),
            ("collection_continuity",),
        ),
        Tool("audit_mfa", "Audit MFA enforcement", mfa_enforcement, ("idp_auth",), ("mfa_unenforced_logins",)),
        Tool(
            "reconcile_inventory_coverage",
            "Reconcile inventory with active coverage",
            reconcile_gap,
            ("inventory", "coverage", "network"),
            ("active_monitoring_gap", "uncovered_host_activity"),
        ),
        Tool(
            "inspect_independent_auth",
            "Inspect independent authentication records",
            inspect_independent_auth,
            ("directory", "idp_auth", "coverage", "inventory"),
            ("unexplained_sessions_uncovered", "unexplained_sessions_monitored", "sessions_outside_idp"),
        ),
        Tool(
            "test_host_egress",
            "Test egress on unmonitored hosts",
            host_egress_test,
            ("network", "coverage", "inventory"),
            ("egress_anomaly_uncovered",),
        ),
    ]
}

OBSERVABLE_LABELS = {
    "edr_high_severity": "High-severity EDR detections",
    "idp_auth_anomaly": "Sign-in failure anomaly",
    "enrollment_gap": "Hosts without an enrolled agent",
    "network_volume": "Organization-wide egress shift",
    "collection_continuity": "Gaps in collected records",
    "active_monitoring_gap": "Hosts without a reporting agent",
    "uncovered_host_activity": "Unmonitored hosts that were active",
    "unexplained_sessions_uncovered": "Unexplained logons on unmonitored hosts",
    "unexplained_sessions_monitored": "Unexplained logons on monitored hosts",
    "sessions_outside_idp": "Sessions outside the identity provider",
    "egress_anomaly_uncovered": "Egress anomaly on unmonitored hosts",
    "mfa_unenforced_logins": "Sign-ins without MFA",
}
