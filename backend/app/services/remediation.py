"""Corrective actions. An action is resolved only by evidence that it worked."""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.demo.generator import WINDOW_END
from app.models import EvidenceRecord, Finding, Investigation, Remediation, User, VerificationRun


def _next_ref(db: Session) -> str:
    return f"RM-{(db.scalar(select(func.count(Remediation.id))) or 0) + 1:04d}"


def _blueprints(findings: dict[str, Finding]) -> list[dict]:
    plans: list[dict] = []
    gap = findings.get("active_monitoring_gap")
    if gap:
        hosts = gap.data["uncovered"]
        plans.append(
            dict(
                key="enroll_unmonitored",
                finding=gap.title,
                root_cause="Assets joined the inventory without a required agent, and nothing alerts when an enrolled "
                "agent stops reporting.",
                action=f"Enroll or repair the EDR agent on {len(hosts)} hosts: {', '.join(hosts)}.",
                priority="critical",
                risk_addressed="Activity on these hosts is invisible to endpoint monitoring.",
                verification_criteria="Every listed host has a coverage record with a heartbeat later than the "
                "execution time.",
                verification_procedure="verify_monitoring_coverage",
                params={"hosts": hosts},
            )
        )
    session = findings.get("unexplained_session")
    if session:
        row = session.data["session"]
        plans.append(
            dict(
                key="contain_credential",
                finding=session.title,
                root_cause=f"The {row['user']} credential authenticated outside the identity provider, so it isn't "
                "protected by MFA or sign-in policy.",
                action=f"Rotate the {row['user']} credential, end its active sessions, and block it from VPN.",
                priority="critical",
                risk_addressed="An unexplained actor may still hold a working credential.",
                verification_criteria=f"A rotation event exists for {row['user']} and no logon by that account "
                "follows it.",
                verification_procedure="verify_credential_rotated",
                params={"account": row["user"], "host": row["hostname"]},
            )
        )
    reach = findings.get("independent_reach")
    if reach:
        hosts = reach.data["unreached"]
        plans.append(
            dict(
                key="extend_independent_logging",
                finding=reach.title,
                root_cause="These hosts sit outside log forwarding, and they also have no reporting EDR agent.",
                action=f"Turn on log forwarding for {', '.join(hosts)}.",
                priority="high",
                risk_addressed="No evidence source can observe activity on these hosts.",
                verification_criteria="Each listed host has a log-coverage record showing forwarding is on.",
                verification_procedure="verify_independent_reach",
                params={"hosts": hosts},
            )
        )
    collection = findings.get("collection_gap")
    if collection:
        subnets = [g["subnet"] for g in collection.data["gaps"]]
        plans.append(
            dict(
                key="restore_sensor",
                finding=collection.title,
                root_cause="A network sensor stopped sending records and nothing raised an alert.",
                action=f"Restore the network sensor for {', '.join(subnets)} and alert on missing hours.",
                priority="medium",
                risk_addressed="Blind periods in network evidence.",
                verification_criteria="Each listed subnet has network records for 3 consecutive hours after execution.",
                verification_procedure="verify_collection_continuity",
                params={"subnets": subnets},
            )
        )
    mfa = findings.get("mfa_gap")
    if mfa:
        apps = list(mfa.data["by_app"])
        plans.append(
            dict(
                key="enforce_mfa",
                finding=mfa.title,
                root_cause=f"{', '.join(apps)} sits outside the conditional-access policy that requires MFA.",
                action=f"Bring {', '.join(apps)} under the MFA policy.",
                priority="high",
                risk_addressed="A stolen password alone is enough to sign in.",
                verification_criteria="Every successful sign-in to the listed applications after execution has MFA.",
                verification_procedure="verify_mfa_enforced",
                params={"apps": apps},
            )
        )
    return plans


def sync_remediations(db: Session, investigation: Investigation) -> None:
    db.flush()
    findings = {f.key: f for f in db.scalars(select(Finding).where(Finding.investigation_id == investigation.id))}
    existing = set(db.scalars(select(Remediation.key).where(Remediation.investigation_id == investigation.id)))
    for plan in _blueprints(findings):
        if plan["key"] in existing:
            continue
        db.add(
            Remediation(
                workspace_id=investigation.workspace_id,
                investigation_id=investigation.id,
                ref=_next_ref(db),
                owner_id=investigation.assignee_id,
                **plan,
            )
        )
        db.flush()


# --- Simulated integration ---------------------------------------------------------------


def simulated_time(remediation: Remediation) -> datetime:
    """Demo clock. Post-remediation records sit after the fixed snapshot."""
    return WINDOW_END + timedelta(hours=remediation.attempts)


def _emit(db: Session, dataset: str, source: str, ts: datetime, entity: str, payload: dict) -> None:
    db.add(
        EvidenceRecord(
            dataset=dataset, source_key=source, ts=ts, entity=entity, payload={**payload, "simulated_change": True}
        )
    )


def execute_simulated(db: Session, remediation: Remediation, dataset: str) -> str:
    """Apply a change through the demo integration by writing the records a real system would produce.

    On its first attempt, enrollment leaves one host unreported, so verification has something
    real to catch. No external system is touched.
    """
    remediation.attempts += 1
    ts = simulated_time(remediation)
    params = remediation.params
    if remediation.key == "enroll_unmonitored":
        hosts = list(params["hosts"])
        withheld = hosts[-1] if remediation.attempts == 1 else None
        for host in hosts:
            if host == withheld:
                continue
            _emit(
                db,
                dataset,
                "coverage",
                ts,
                host,
                {
                    "hostname": host,
                    "agent_state": "enrolled",
                    "agent_version": "7.4.2",
                    "last_heartbeat": ts.isoformat(),
                },
            )
        reported = len(hosts) - (1 if withheld else 0)
        return f"Simulated agent deployment sent to {len(hosts)} hosts. {reported} responded."
    if remediation.key == "contain_credential":
        _emit(
            db,
            dataset,
            "directory",
            ts,
            params["account"],
            {
                "kind": "credential_event",
                "user": params["account"],
                "event": "rotated",
            },
        )
        return f"Simulated rotation of {params['account']}."
    if remediation.key == "extend_independent_logging":
        for host in params["hosts"]:
            _emit(db, dataset, "directory", ts, host, {"kind": "log_coverage", "hostname": host, "forwarding": True})
        return f"Simulated log forwarding enabled on {len(params['hosts'])} hosts."
    if remediation.key == "restore_sensor":
        for subnet in params["subnets"]:
            for hour in range(3):
                _emit(
                    db,
                    dataset,
                    "network",
                    ts + timedelta(hours=hour),
                    f"{subnet}-sensor",
                    {
                        "hostname": f"{subnet}-sensor",
                        "subnet": subnet,
                        "bytes_out": 0,
                        "flows": 0,
                        "kind": "sensor_probe",
                    },
                )
        return f"Simulated sensor restart for {', '.join(params['subnets'])}."
    if remediation.key == "enforce_mfa":
        for app in params["apps"]:
            for index in range(12):
                _emit(
                    db,
                    dataset,
                    "idp_auth",
                    ts + timedelta(minutes=5 * index),
                    f"user{index:03d}",
                    {
                        "user": f"user{index:03d}",
                        "result": "success",
                        "app": app,
                        "mfa": True,
                        "src_ip": "198.51.100.9",
                        "geo": "US-IL",
                        "session_id": f"post-{app}-{index}",
                    },
                )
        return f"Simulated policy update for {', '.join(params['apps'])}."
    raise ValueError(f"No simulated integration for {remediation.key}")


def simulate_recurrence(db: Session, remediation: Remediation, dataset: str) -> str:
    """Demo control: bring a resolved weakness back so continuous verification can catch it."""
    latest = db.scalar(select(func.max(EvidenceRecord.ts)).where(EvidenceRecord.dataset == dataset)) or WINDOW_END
    ts = latest + timedelta(hours=1)
    params = remediation.params
    if remediation.key == "enroll_unmonitored":
        host = params["hosts"][0]
        _emit(
            db,
            dataset,
            "coverage",
            ts,
            host,
            {
                "hostname": host,
                "agent_state": "enrolled",
                "agent_version": "7.4.2",
                "last_heartbeat": (ts - timedelta(days=3)).isoformat(),
            },
        )
        return f"Simulated: the agent on {host} stopped reporting."
    if remediation.key == "contain_credential":
        _emit(
            db,
            dataset,
            "directory",
            ts,
            params["account"],
            {
                "kind": "dc_logon",
                "user": params["account"],
                "hostname": params["host"],
                "logon_type": "remote_interactive",
                "src_ip": "10.8.0.41",
                "idp_session_id": None,
                "change_ref": None,
            },
        )
        return f"Simulated: {params['account']} logged on again."
    if remediation.key == "extend_independent_logging":
        host = params["hosts"][0]
        _emit(db, dataset, "directory", ts, host, {"kind": "log_coverage", "hostname": host, "forwarding": False})
        return f"Simulated: log forwarding stopped on {host}."
    if remediation.key == "enforce_mfa":
        app = params["apps"][0]
        _emit(
            db,
            dataset,
            "idp_auth",
            ts,
            "user001",
            {
                "user": "user001",
                "result": "success",
                "app": app,
                "mfa": False,
                "src_ip": "198.51.100.9",
                "geo": "US-IL",
                "session_id": f"post-{app}-recur",
            },
        )
        return f"Simulated: a sign-in to {app} completed without MFA."
    raise ValueError("This action has no recurrence simulation")


# --- Verification ------------------------------------------------------------------------


def _records(db: Session, dataset: str, source: str, after: datetime | None = None) -> list[EvidenceRecord]:
    query = select(EvidenceRecord).where(EvidenceRecord.dataset == dataset, EvidenceRecord.source_key == source)
    if after is not None:
        query = query.where(EvidenceRecord.ts >= after)
    return list(db.scalars(query.order_by(EvidenceRecord.ts)))


def verify_monitoring_coverage(db, remediation, dataset, executed):
    latest: dict[str, dict] = {}
    for record in _records(db, dataset, "coverage"):
        latest[record.payload["hostname"]] = record.payload
    missing = []
    for host in remediation.params["hosts"]:
        payload = latest.get(host)
        heartbeat = datetime.fromisoformat(payload["last_heartbeat"]) if payload else None
        if heartbeat is None or heartbeat < executed:
            missing.append(host)
    total = len(remediation.params["hosts"])
    return (
        not missing,
        f"{total - len(missing)} of {total} hosts have a heartbeat after execution."
        + (f" Not reporting: {', '.join(missing)}." if missing else ""),
        {"not_reporting": missing, "checked": total},
    )


def verify_credential_rotated(db, remediation, dataset, executed):
    account = remediation.params["account"]
    records = [r for r in _records(db, dataset, "directory") if r.payload.get("user") == account]
    rotations = [r for r in records if r.payload.get("kind") == "credential_event"]
    if not rotations:
        return False, f"No rotation event exists for {account}.", {"rotation": None}
    rotated_at = rotations[-1].ts
    later = [r for r in records if r.ts > rotated_at and r.payload.get("kind") in ("dc_logon", "vpn_session")]
    if later:
        return False, f"{len(later)} logons by {account} follow the rotation.", {"logons_after": len(later)}
    return True, f"{account} was rotated at {rotated_at.isoformat()} and no logon follows it.", {"logons_after": 0}


def verify_independent_reach(db, remediation, dataset, executed):
    latest = {}
    for record in _records(db, dataset, "directory"):
        if record.payload.get("kind") == "log_coverage":
            latest[record.payload["hostname"]] = record.payload["forwarding"]
    missing = [h for h in remediation.params["hosts"] if not latest.get(h)]
    total = len(remediation.params["hosts"])
    return (
        not missing,
        f"{total - len(missing)} of {total} hosts forward logs."
        + (f" Not forwarding: {', '.join(missing)}." if missing else ""),
        {"not_forwarding": missing},
    )


def verify_collection_continuity(db, remediation, dataset, executed):
    records = _records(db, dataset, "network", after=executed)
    failures = []
    for subnet in remediation.params["subnets"]:
        hours = {r.ts for r in records if r.payload.get("subnet") == subnet}
        if len(hours) < 3:
            failures.append(subnet)
    return (
        not failures,
        (
            "Every listed subnet has records for 3 consecutive hours."
            if not failures
            else f"Insufficient records from: {', '.join(failures)}."
        ),
        {"failing_subnets": failures},
    )


def verify_mfa_enforced(db, remediation, dataset, executed):
    records = [
        r
        for r in _records(db, dataset, "idp_auth", after=executed)
        if r.payload.get("app") in remediation.params["apps"] and r.payload.get("result") == "success"
    ]
    if not records:
        return False, "No sign-ins exist after execution, so enforcement can't be shown.", {"signins": 0}
    missing = [r for r in records if not r.payload.get("mfa")]
    return (
        not missing,
        f"{len(records) - len(missing)} of {len(records)} sign-ins after execution used MFA.",
        {
            "signins": len(records),
            "without_mfa": len(missing),
        },
    )


PROCEDURES = {
    "verify_monitoring_coverage": verify_monitoring_coverage,
    "verify_credential_rotated": verify_credential_rotated,
    "verify_independent_reach": verify_independent_reach,
    "verify_collection_continuity": verify_collection_continuity,
    "verify_mfa_enforced": verify_mfa_enforced,
}


def run_verification(db: Session, remediation: Remediation, dataset: str, user: User) -> VerificationRun:
    if remediation.execution_status != "executed":
        raise ValueError("The action has not been executed, so there is nothing to verify.")
    # The demo clock places this attempt's records just after the fixed snapshot.
    procedure = PROCEDURES[remediation.verification_procedure]
    passed, summary, evidence = procedure(db, remediation, dataset, simulated_time(remediation))
    previously_passed = remediation.verification_status == "verified"
    recurrence = previously_passed and not passed
    run = VerificationRun(
        remediation_id=remediation.id,
        procedure=remediation.verification_procedure,
        passed=passed,
        recurrence=recurrence,
        summary=summary,
        evidence=evidence,
        run_by_id=user.id,
    )
    db.add(run)
    if passed:
        remediation.verification_status = "verified"
    else:
        remediation.verification_status = "recurred" if recurrence else "failed"
    return run
