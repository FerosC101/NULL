"""Findings, the knowledge ledger, and the assessment rationale, all derived from computed results."""

from datetime import datetime

from app.analysis.observables import OBSERVABLE_LABELS
from app.analysis.validation import (
    CONTRADICTED,
    PARTIALLY_IDENTIFIED,
    SUPPORTED,
    UNDERDETERMINED,
    UNVERIFIED,
)


def _count(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _when(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%b %d, %H:%M UTC")


def _obs(observables: dict, key: str) -> dict | None:
    item = observables.get(key)
    return item if item and item["state"] != "unavailable" else None


def build_findings(observables: dict, refs: dict[str, str], unavailable: dict[str, str]) -> list[dict]:
    """Return findings keyed for upsert. `refs` maps observable key to evidence ID."""
    findings: list[dict] = []

    def add(key, kind, title, body, severity, evidence, data=None):
        findings.append(
            dict(
                key=key,
                kind=kind,
                title=title,
                body=body,
                severity=severity,
                evidence_refs=[refs[e] for e in evidence if e in refs],
                data=data or {},
            )
        )

    edr = _obs(observables, "edr_high_severity")
    enrollment = _obs(observables, "enrollment_gap")
    gap = _obs(observables, "active_monitoring_gap")
    if edr and edr["state"] == "zero":
        reach = None
        if gap:
            total = gap["details"]["hosts"]
            reach = f"{total - int(gap['value'])} of {total} hosts"
        elif enrollment:
            reach = f"at most {enrollment['details']['enrolled']} of {enrollment['details']['hosts']} hosts"
        add(
            "edr_silence",
            "unsupported_assumption",
            "EDR silence is being read as absence",
            "No high-severity detections is a statement about the hosts EDR can see"
            + (f", which is {reach}. " if reach else ". ")
            + "It says nothing about hosts without a reporting agent.",
            "high",
            ["edr_high_severity"],
        )
    if gap and gap["state"] == "positive":
        details = gap["details"]
        add(
            "active_monitoring_gap",
            "evidence_gap",
            "Endpoint monitoring coverage is incomplete",
            f"{len(details['uncovered'])} of {details['hosts']} in-scope hosts had no reporting agent: "
            f"{', '.join(details['uncovered'])}.",
            "critical",
            ["active_monitoring_gap"],
            {"uncovered": details["uncovered"]},
        )
        if details["stale"]:
            add(
                "enrollment_overstates",
                "measurement_bias",
                "Enrollment figures overstate coverage",
                f"{len(details['stale'])} enrolled hosts stopped reporting: {', '.join(details['stale'])}. "
                "A console that counts enrollment still shows these hosts as covered.",
                "high",
                ["active_monitoring_gap"],
            )
    elif enrollment and enrollment["state"] == "positive" and not gap:
        add(
            "enrollment_gap",
            "evidence_gap",
            "Endpoint monitoring coverage is incomplete",
            f"Inventory lists {enrollment['details']['hosts']} hosts and only {enrollment['details']['enrolled']} are "
            "enrolled. Which hosts are affected, and how many enrolled agents actually report, is not yet known.",
            "critical",
            ["enrollment_gap"],
        )
    volume = _obs(observables, "network_volume")
    if volume and volume["state"] == "zero":
        add(
            "aggregate_network",
            "measurement_bias",
            "Total egress cannot reveal a single host",
            f"Organization-wide egress looks normal ({volume['summary'].lower()}) but a total can absorb one host "
            "moving a large volume.",
            "medium",
            ["network_volume"],
        )
    continuity = _obs(observables, "collection_continuity")
    if continuity and continuity["state"] == "positive":
        add(
            "collection_gap",
            "incomplete_observation",
            "Network records have gaps",
            continuity["summary"] + " Nothing can be observed for those subnets during those hours.",
            "medium",
            ["collection_continuity"],
            {"gaps": continuity["details"]["gaps"]},
        )
    sessions = _obs(observables, "unexplained_sessions_uncovered")
    monitored = _obs(observables, "unexplained_sessions_monitored")
    for item, key in ((sessions, "unexplained_sessions_uncovered"), (monitored, "unexplained_sessions_monitored")):
        if item and item["state"] == "positive":
            row = item["details"]["sessions"][0]
            add(
                "unexplained_session",
                "evidence_gap",
                f"Unexplained logon on {row['hostname']}",
                f"{row['user']} logged on to {row['hostname']} at {_when(row['ts'])} from {row['src_ip']} with no "
                "identity-provider session and no approved change.",
                "critical",
                [key],
                {"session": row, "vpn_sessions": (sessions or {}).get("details", {}).get("vpn_sessions", [])},
            )
    if sessions and sessions["state"] == "partial":
        unreached = sessions["details"]["unreached"]
        add(
            "independent_reach",
            "incomplete_observation",
            "Some unmonitored hosts have no independent logs",
            f"{', '.join(unreached)} have neither a reporting EDR agent nor forwarded logs. Nothing in the evidence "
            "could reveal activity on these hosts in either direction.",
            "critical",
            ["unexplained_sessions_uncovered"],
            {"unreached": unreached},
        )
    outside = _obs(observables, "sessions_outside_idp")
    if outside and outside["details"]["explained"]:
        add(
            "idp_bypass_permitted",
            "unsupported_assumption",
            "Not every logon passes through the identity provider",
            f"{_count(len(outside['details']['explained']), 'logon')} bypassed the identity provider under an approved "
            "change. This is legitimate, and it shows that identity-provider records alone are not a complete picture.",
            "medium",
            ["sessions_outside_idp"],
        )
    egress = _obs(observables, "egress_anomaly_uncovered")
    if egress and egress["state"] == "positive":
        add(
            "egress_anomaly",
            "evidence_gap",
            "Unexplained egress from an unmonitored host",
            egress["summary"],
            "high",
            ["egress_anomaly_uncovered"],
            {"hosts": egress["details"]["flagged"]},
        )
    mfa = _obs(observables, "mfa_unenforced_logins")
    if mfa and mfa["state"] == "positive":
        add(
            "mfa_gap",
            "evidence_gap",
            "Sign-ins completed without MFA",
            mfa["summary"],
            "high",
            ["mfa_unenforced_logins"],
            {"by_app": mfa["details"]["by_app"]},
        )
    for source_key, reason in unavailable.items():
        add(
            f"source_unavailable_{source_key}",
            "incomplete_observation",
            f"{source_key} could not be read",
            f"Reason: {reason}. Observations that depend on this source were not made.",
            "high",
            [],
        )
    return findings


def build_ledger(observables: dict, realities: list[dict], assumptions: list[dict], checks: list[dict]) -> dict:
    observed = [o["summary"] for o in observables.values() if o["state"] != "unavailable"]
    inferred = []
    for reality in realities:
        if reality["compatibility"] == "incompatible":
            inferred.append(f"Reality {reality['label']} ({reality['title']}) conflicts with the evidence.")
        elif reality["compatibility"] == "corroborated":
            inferred.append(
                f"Reality {reality['label']} ({reality['title']}) matches the evidence. It remains a hypothesis."
            )
    assumed = [a["text"] for a in assumptions if a["status"] == "unverified"]
    violated = [f"Violated: {a['text']}" for a in assumptions if a["status"] == "violated"]
    open_checks = [c for c in checks if c["status"] in ("proposed", "failed", "rejected")]
    unknown = []
    for reality in realities:
        for result in reality.get("results", []):
            if result["outcome"] in ("untested", "inconclusive") and result["hard"]:
                label = OBSERVABLE_LABELS.get(result["observable"], result["observable"])
                if label not in unknown:
                    unknown.append(label)
    would_change = [f"{c['title']} ({c['information_gain_bits']:.2f} bits)" for c in open_checks]
    return {
        "observed": observed,
        "inferred": inferred + violated,
        "assumed": assumed,
        "unknown": unknown,
        "would_change": would_change,
    }


def build_rationale(assessment: str, realities: list[dict], claim_kind: str) -> str:
    survivors = [r for r in realities if r["compatibility"] != "incompatible"]
    names = ", ".join(f"Reality {r['label']}" for r in survivors)
    if claim_kind == "unsupported":
        return "NULL has no observable mapping for this claim, so it was not tested."
    if assessment == UNVERIFIED:
        return "None of the selected sources produced an observation that bears on this claim."
    if assessment == CONTRADICTED:
        lead = next((r for r in realities if r["compatibility"] in ("corroborated", "consistent")), None)
        tail = f" The evidence fits Reality {lead['label']}, which remains a hypothesis." if lead else ""
        return "Observed evidence conflicts with what the claim requires." + tail
    if assessment == SUPPORTED:
        return (
            "Every alternative reality was tested and excluded, and each observation the claim requires was made. "
            "The conclusion holds within the stated scope and assumptions."
        )
    if assessment == PARTIALLY_IDENTIFIED:
        return (
            f"The evidence excludes some alternatives, but {names} still fit. The claim holds for part of the scope "
            "and can't be established for the rest."
        )
    if assessment == UNDERDETERMINED:
        return f"The evidence so far is compatible with {names}. Nothing observed yet separates them."
    return ""


def build_limitations(observables: dict, assumptions: list[dict], unavailable: dict[str, str]) -> list[str]:
    limits = [f"{key} could not be read: {reason}." for key, reason in unavailable.items()]
    limits += [f"Unverified assumption: {a['text']}" for a in assumptions if a["status"] == "unverified"]
    continuity = _obs(observables, "collection_continuity")
    if continuity and continuity["state"] == "positive":
        limits.append(continuity["summary"])
    sessions = _obs(observables, "unexplained_sessions_uncovered")
    if sessions and sessions["state"] == "partial":
        limits.append(f"No visibility at all into: {', '.join(sessions['details']['unreached'])}.")
    limits.append("Scope is limited to the stated window and to assets listed in the device inventory.")
    return limits
