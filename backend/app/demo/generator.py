"""Seeded synthetic cybersecurity telemetry for a fictional company, Cobalt Freight.

Each snapshot shares ordinary background activity and differs in what actually happened.
The truth for each snapshot is returned separately and stored where the analysis engine
cannot read it, so conclusions can be scored against an answer key.

External addresses use documentation ranges (RFC 5737) and the private-use ASN range.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np

WINDOW_END = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
WINDOW_START = WINDOW_END - timedelta(hours=24)
BASELINE_START = WINDOW_START - timedelta(days=3)

DATASETS: dict[str, dict] = {
    "A": {"label": "Snapshot A", "seed": 1147},
    "B": {"label": "Snapshot B", "seed": 2291},
    "C": {"label": "Snapshot C", "seed": 3373},
    "D": {"label": "Snapshot D", "seed": 4409},
}

HOST_GROUPS = [
    ("FIN-WS", "workstation", "Finance", 30, "high"),
    ("ENG-WS", "workstation", "Engineering", 52, "medium"),
    ("OPS-WS", "workstation", "Operations", 44, "medium"),
    ("APP-SRV", "server", "Platform", 22, "high"),
    ("DB-SRV", "server", "Platform", 10, "critical"),
    ("LAB-SRV", "server", "Research", 12, "low"),
    ("OT-GW", "ot_gateway", "Facilities", 10, "high"),
]
PEOPLE = 96
SERVICE_ACCOUNTS = ["svc-backup", "svc-deploy", "svc-monitor", "svc-etl"]
APPS = ["erp", "mail", "hr-portal", "git", "vpn-portal", "wiki"]
GEOS = ["US-IL", "US-TX", "US-WA", "CA-ON"]

ACTOR_ACCOUNT = "svc-backup"
ACTOR_SOURCE_IP = "203.0.113.77"
ACTOR_ASN = "AS64512"


@dataclass
class Scenario:
    never_enrolled: list[str] = field(default_factory=list)
    stale_agents: list[str] = field(default_factory=list)
    powered_off: list[str] = field(default_factory=list)
    no_independent_logs: list[str] = field(default_factory=list)
    intrusion_host: str | None = None
    edr_telemetry_gap_host: str | None = None
    decoy_change_host: str | None = None
    decoy_egress_host: str | None = None
    sensor_gap_prefix: str | None = None
    mfa_bypass_app: str | None = None
    truth: dict = field(default_factory=dict)


def _scenario(dataset: str) -> Scenario:
    gap = dict(
        never_enrolled=["LAB-SRV-0004", "LAB-SRV-0009", "OT-GW-0002", "OT-GW-0007"],
        stale_agents=["ENG-WS-0031", "FIN-WS-0014", "OPS-WS-0022"],
        powered_off=["LAB-SRV-0009", "OPS-WS-0022"],
    )
    if dataset == "A":
        return Scenario(
            **gap,
            intrusion_host="FIN-WS-0014",
            decoy_change_host="LAB-SRV-0004",
            sensor_gap_prefix="ENG-WS",
            mfa_bypass_app="erp",
            truth={
                "unauthorized_access": True,
                "reality": "B",
                "expected_assessment": "CONTRADICTED",
                "narrative": "A stolen service-account credential opened a VPN session and logged on to an "
                "endpoint whose EDR agent had stopped reporting, then moved data out over the following hours.",
                "host": "FIN-WS-0014",
                "account": ACTOR_ACCOUNT,
            },
        )
    if dataset == "B":
        return Scenario(
            **gap,
            no_independent_logs=["OT-GW-0002", "OT-GW-0007"],
            decoy_change_host="LAB-SRV-0004",
            decoy_egress_host="ENG-WS-0031",
            sensor_gap_prefix="OPS-WS",
            truth={
                "unauthorized_access": False,
                "reality": "A",
                "expected_assessment": "PARTIALLY IDENTIFIED",
                "narrative": "No intrusion occurred, but two gateways had neither EDR nor independent logging, so "
                "the evidence cannot establish the claim for those assets. The one unmatched session and the one "
                "egress spike both trace to an approved change.",
                "host": None,
                "account": None,
            },
        )
    if dataset == "C":
        return Scenario(
            truth={
                "unauthorized_access": False,
                "reality": "A",
                "expected_assessment": "SUPPORTED",
                "narrative": "No intrusion occurred. Every in-scope host was actively monitored and independent "
                "records account for every session.",
                "host": None,
                "account": None,
            },
        )
    return Scenario(
        intrusion_host="APP-SRV-0008",
        edr_telemetry_gap_host="APP-SRV-0008",
        truth={
            "unauthorized_access": True,
            "reality": "C",
            "expected_assessment": "CONTRADICTED",
            "narrative": "Monitoring coverage was complete, yet an actor reached a monitored server and raised no "
            "EDR alert. Only the independent records expose the session.",
            "host": "APP-SRV-0008",
            "account": ACTOR_ACCOUNT,
        },
    )


def _hosts() -> list[dict]:
    hosts = []
    for prefix, asset_class, team, count, criticality in HOST_GROUPS:
        for index in range(1, count + 1):
            hosts.append(
                {
                    "hostname": f"{prefix}-{index:04d}",
                    "asset_class": asset_class,
                    "team": team,
                    "criticality": criticality,
                    "subnet": prefix,
                }
            )
    return hosts


def _diurnal(hour: int) -> float:
    return 0.35 + 0.65 * np.exp(-((hour - 15) ** 2) / 18)


def generate(dataset: str) -> tuple[list[tuple], dict]:
    """Return (rows, truth). A row is (dataset, source_key, ts, entity, payload_json)."""
    scenario = _scenario(dataset)
    rng = np.random.default_rng(DATASETS[dataset]["seed"])
    hosts = _hosts()
    rows: list[tuple] = []

    def emit(source: str, ts: datetime, entity: str, payload: dict) -> None:
        rows.append((dataset, source, ts, entity, json.dumps(payload)))

    _inventory(hosts, emit)
    _coverage(hosts, scenario, rng, emit)
    sessions = _identity(scenario, rng, emit)
    _edr(hosts, scenario, rng, emit)
    _network(hosts, scenario, rng, emit)
    _directory(hosts, scenario, rng, sessions, emit)
    return rows, scenario.truth


def _inventory(hosts, emit) -> None:
    for host in hosts:
        emit("inventory", WINDOW_END - timedelta(hours=1), host["hostname"], {**host, "in_scope": True})


def _coverage(hosts, scenario: Scenario, rng, emit) -> None:
    snapshot = WINDOW_END - timedelta(minutes=10)
    for host in hosts:
        name = host["hostname"]
        if name in scenario.never_enrolled:
            continue
        stale = name in scenario.stale_agents
        heartbeat = (
            WINDOW_START - timedelta(days=int(rng.integers(2, 12)), minutes=int(rng.integers(0, 600)))
            if stale
            else snapshot - timedelta(minutes=int(rng.integers(1, 12)))
        )
        emit(
            "coverage",
            snapshot,
            name,
            {
                "hostname": name,
                "agent_state": "enrolled",
                "agent_version": "7.4.2" if rng.random() > 0.2 else "7.3.9",
                "last_heartbeat": heartbeat.isoformat(),
            },
        )


def _identity(scenario: Scenario, rng, emit) -> list[dict]:
    """Identity-provider sign-ins. Returns successful sessions so directory logons can reference them."""
    sessions = []
    counter = 0
    current = BASELINE_START
    while current < WINDOW_END:
        expected = 140 * _diurnal(current.hour)
        for _ in range(rng.poisson(expected)):
            counter += 1
            ts = current + timedelta(seconds=int(rng.integers(0, 3600)))
            user = f"user{int(rng.integers(1, PEOPLE + 1)):03d}"
            success = rng.random() > 0.035
            app = str(rng.choice(APPS))
            mfa = True
            if scenario.mfa_bypass_app == app and rng.random() < 0.09:
                mfa = False
            session_id = f"idp-{dataset_tag(scenario)}-{counter:06d}"
            payload = {
                "user": user,
                "result": "success" if success else "failure",
                "app": app,
                "mfa": mfa,
                "src_ip": f"198.51.100.{int(rng.integers(2, 250))}",
                "geo": str(rng.choice(GEOS, p=[0.55, 0.2, 0.15, 0.1])),
                "session_id": session_id,
            }
            emit("idp_auth", ts, user, payload)
            if success and ts >= WINDOW_START:
                sessions.append({"session_id": session_id, "user": user, "ts": ts})
        current += timedelta(hours=1)
    return sessions


def dataset_tag(scenario: Scenario) -> str:
    return str(scenario.truth.get("expected_assessment", "x"))[:1].lower()


def _edr(hosts, scenario: Scenario, rng, emit) -> None:
    uncovered = set(scenario.never_enrolled) | set(scenario.stale_agents)
    rules = ["adware.bundle", "script.unsigned", "policy.usb", "pup.toolbar", "macro.office"]
    for host in hosts:
        name = host["hostname"]
        if name in uncovered:
            continue
        for bucket in range(6):
            ts = WINDOW_START + timedelta(hours=4 * bucket, minutes=int(rng.integers(0, 30)))
            if name == scenario.edr_telemetry_gap_host and bucket in (1, 2):
                continue
            emit("edr", ts, name, {"hostname": name, "event": "telemetry_batch", "events": int(rng.integers(120, 900))})
        if rng.random() < 0.28:
            ts = WINDOW_START + timedelta(minutes=int(rng.integers(0, 24 * 60)))
            emit(
                "edr",
                ts,
                name,
                {
                    "hostname": name,
                    "event": "detection",
                    "severity": str(rng.choice(["info", "low", "medium"], p=[0.5, 0.4, 0.1])),
                    "rule": str(rng.choice(rules)),
                    "disposition": "auto_closed",
                },
            )


def _network(hosts, scenario: Scenario, rng, emit) -> None:
    hours = int((WINDOW_END - BASELINE_START).total_seconds() // 3600)
    gap_start = WINDOW_START + timedelta(hours=7)
    gap_end = gap_start + timedelta(hours=2)
    for host in hosts:
        name = host["hostname"]
        off = name in scenario.powered_off
        base = float(rng.lognormal(mean=17.0, sigma=0.6))
        noise = rng.normal(0, 0.28, size=hours)
        for index in range(hours):
            ts = BASELINE_START + timedelta(hours=index)
            if off and ts >= WINDOW_START:
                continue
            if scenario.sensor_gap_prefix and name.startswith(scenario.sensor_gap_prefix) and gap_start <= ts < gap_end:
                continue
            bytes_out = base * _diurnal(ts.hour) * float(np.exp(noise[index]))
            elapsed = (ts - WINDOW_START).total_seconds() / 3600
            if name == scenario.intrusion_host and 17 <= elapsed < 21:
                bytes_out *= 42
            if name == scenario.decoy_egress_host and 9 <= elapsed < 12:
                bytes_out *= 30
            emit(
                "network",
                ts,
                name,
                {
                    "hostname": name,
                    "subnet": host["subnet"],
                    "bytes_out": int(bytes_out),
                    "flows": int(rng.poisson(40 * _diurnal(ts.hour))),
                },
            )


def _directory(hosts, scenario: Scenario, rng, sessions, emit) -> None:
    """Domain-controller logons and VPN sessions, recorded independently of the identity provider."""
    in_window = list(sessions)
    rng.shuffle(in_window)
    reachable = [h["hostname"] for h in hosts if h["hostname"] not in scenario.no_independent_logs]
    for host in hosts:
        name = host["hostname"]
        emit(
            "directory",
            WINDOW_END - timedelta(hours=2),
            name,
            {"kind": "log_coverage", "hostname": name, "forwarding": name not in scenario.no_independent_logs},
        )
    for session in in_window[:900]:
        host = str(rng.choice(reachable))
        if host in scenario.powered_off:
            continue
        emit(
            "directory",
            session["ts"] + timedelta(seconds=int(rng.integers(5, 90))),
            session["user"],
            {
                "kind": "dc_logon",
                "user": session["user"],
                "hostname": host,
                "logon_type": "interactive",
                "src_ip": "10.20.0." + str(int(rng.integers(2, 250))),
                "idp_session_id": session["session_id"],
                "change_ref": None,
            },
        )
    if scenario.decoy_change_host:
        ticket = "CHG-48213"
        start = WINDOW_START + timedelta(hours=9)
        emit(
            "directory",
            start - timedelta(hours=20),
            ticket,
            {
                "kind": "change_record",
                "change_ref": ticket,
                "hostnames": [
                    scenario.decoy_change_host,
                    *([scenario.decoy_egress_host] if scenario.decoy_egress_host else []),
                ],
                "window_start": start.isoformat(),
                "window_end": (start + timedelta(hours=3)).isoformat(),
                "approved_by": "change-board",
                "summary": "Firmware maintenance and log archive transfer",
            },
        )
        emit(
            "directory",
            start + timedelta(minutes=12),
            "adm-patch",
            {
                "kind": "dc_logon",
                "user": "adm-patch",
                "hostname": scenario.decoy_change_host,
                "logon_type": "remote_interactive",
                "src_ip": "10.20.9.14",
                "idp_session_id": None,
                "change_ref": ticket,
            },
        )
    if scenario.intrusion_host:
        start = WINDOW_START + timedelta(hours=17, minutes=14)
        emit(
            "directory",
            start,
            ACTOR_ACCOUNT,
            {
                "kind": "vpn_session",
                "user": ACTOR_ACCOUNT,
                "src_ip": ACTOR_SOURCE_IP,
                "src_asn": ACTOR_ASN,
                "assigned_ip": "10.8.0.41",
                "idp_session_id": None,
                "change_ref": None,
            },
        )
        emit(
            "directory",
            start + timedelta(minutes=5),
            ACTOR_ACCOUNT,
            {
                "kind": "dc_logon",
                "user": ACTOR_ACCOUNT,
                "hostname": scenario.intrusion_host,
                "logon_type": "remote_interactive",
                "src_ip": "10.8.0.41",
                "idp_session_id": None,
                "change_ref": None,
            },
        )
