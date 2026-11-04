"""Generates the Tallowmere Foods synthetic dataset as CSV exports.

Everything here is fictional. Run from the repository root with the backend's Python:

    backend/.venv/bin/python docs/datasets/tallowmere-synthetic/generate.py

The same seeds produce the same files. External addresses use documentation ranges (RFC 5737)
and the private-use ASN range, and the email domain is reserved.
"""

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent
WINDOW_END = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
WINDOW_START = WINDOW_END - timedelta(hours=24)
BASELINE_START = WINDOW_START - timedelta(days=3)
PHT = 8

SEEDS = {"E": 5101, "F": 5209, "G": 5303, "H": 5407}

# prefix, asset class, team, hosts, criticality, activity profile
HOST_GROUPS = [
    ("HQ-FIN", "workstation", "Finance", 24, "high", "office"),
    ("HQ-SLS", "workstation", "Sales", 46, "medium", "office"),
    ("HQ-OPS", "workstation", "Operations", 38, "medium", "office"),
    ("HQ-ITS", "workstation", "IT", 12, "high", "office"),
    ("WH-OPS", "workstation", "Warehouse", 40, "medium", "warehouse"),
    ("ERP-SRV", "server", "Platform", 6, "critical", "server"),
    ("DB-SRV", "server", "Platform", 6, "critical", "server"),
    ("APP-SRV", "server", "Platform", 16, "high", "server"),
    ("FILE-SRV", "server", "Platform", 4, "high", "server"),
    ("CC-GW", "ot_gateway", "Cold chain", 18, "high", "gateway"),
]
# prefix, accounts, activity profile, usual applications, host prefix for logons
TEAMS = [
    ("fin", 24, "office", ["erp", "payroll-portal", "mail"], "HQ-FIN"),
    ("sls", 46, "office", ["crm", "mail", "vpn-portal"], "HQ-SLS"),
    ("ops", 28, "office", ["wms", "erp", "mail"], "HQ-OPS"),
    ("its", 12, "office", ["vpn-portal", "mail", "erp"], "HQ-ITS"),
    ("wh", 150, "warehouse", ["wms", "mail"], "WH-OPS"),
]
SERVICE_ACCOUNTS = ["svc-backup", "svc-erp-sync", "svc-edi", "svc-monitor"]
SITE_GEO = {"Cebu": "PH-07", "Manila": "PH-00", "Davao": "PH-11"}
RULES = [
    "adware.bundle",
    "script.unsigned",
    "policy.usb",
    "pup.toolbar",
    "macro.office",
]

ACTOR_SOURCE_IP = "203.0.113.77"
ACTOR_ASN = "AS64512"
ACTOR_START = WINDOW_START + timedelta(hours=9, minutes=14)
THEFT_HOURS = (9, 13)
THEFT_FACTOR = 150
CHANGE_FACTOR = 30


@dataclass
class Scenario:
    name: str
    truth: str
    reality: str
    unauthorized_access: bool
    never_enrolled: list[str] = field(default_factory=list)
    stale_agents: list[str] = field(default_factory=list)
    no_independent_logs: list[str] = field(default_factory=list)
    intruder: str | None = None
    intrusion_host: str | None = None
    edr_gap_host: str | None = None
    sensor_gap_subnet: str | None = None
    mfa_gap_app: str | None = None
    change: dict | None = None


SCENARIOS = {
    "E": Scenario(
        "Payment data theft",
        "A stolen svc-edi credential opened a VPN session, logged on to a finance workstation whose EDR agent had "
        "stopped reporting, and moved data out for 4 hours.",
        "B",
        True,
        stale_agents=["FILE-SRV-0003", "HQ-FIN-0014"],
        intruder="svc-edi",
        intrusion_host="HQ-FIN-0014",
        sensor_gap_subnet="WH-MNL",
        mfa_gap_app="payroll-portal",
        change={
            "ticket": "CHG-2210",
            "start_hour": 3,
            "logon_host": "FILE-SRV-0003",
            "hosts": ["FILE-SRV-0003"],
            "egress_host": "FILE-SRV-0003",
            "summary": "Month-end ERP report archive transfer",
        },
    ),
    "F": Scenario(
        "Clean month-end",
        "No intrusion occurred. Finance worked late and traffic rose, every host reported, and independent records "
        "account for every session.",
        "A",
        False,
    ),
    "G": Scenario(
        "Cold-room blind spot",
        "No intrusion occurred, but two cold-chain gateways had neither EDR nor independent logging, so the evidence "
        "cannot establish the claim for them. The unmatched session and the egress spike trace to an approved change.",
        "A",
        False,
        never_enrolled=["CC-GW-0002", "CC-GW-0007"],
        stale_agents=["HQ-OPS-0031"],
        no_independent_logs=["CC-GW-0002", "CC-GW-0007"],
        change={
            "ticket": "CHG-2214",
            "start_hour": 9,
            "logon_host": "CC-GW-0004",
            "hosts": ["CC-GW-0004", "HQ-OPS-0031"],
            "egress_host": "HQ-OPS-0031",
            "summary": "Cold-room gateway firmware update by vendor and log archive transfer",
        },
    ),
    "H": Scenario(
        "Silent ERP intrusion",
        "Monitoring coverage was complete, yet a stolen svc-erp-sync credential reached a monitored ERP server and "
        "raised no EDR alert. Only the independent records expose the session.",
        "C",
        True,
        intruder="svc-erp-sync",
        intrusion_host="ERP-SRV-0002",
        edr_gap_host="ERP-SRV-0002",
    ),
}

# Each snapshot is run against the same four claims.
EXPECTED = {
    "No unauthorized access occurred during the month-end close.": {
        "E": "CONTRADICTED",
        "F": "SUPPORTED",
        "G": "PARTIALLY IDENTIFIED",
        "H": "CONTRADICTED",
    },
    "All hosts were monitored throughout the window.": {
        "E": "CONTRADICTED",
        "F": "SUPPORTED",
        "G": "CONTRADICTED",
        "H": "SUPPORTED",
    },
    "MFA was enforced on every sign-in.": {
        "E": "CONTRADICTED",
        "F": "SUPPORTED",
        "G": "SUPPORTED",
        "H": "SUPPORTED",
    },
    "All supplier invoices were approved before payment.": dict.fromkeys(
        SEEDS, "UNVERIFIED"
    ),
}


def stamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def site_of(prefix: str, index: int) -> str:
    if prefix == "WH-OPS":
        return "Cebu" if index <= 14 else "Manila" if index <= 30 else "Davao"
    if prefix == "CC-GW":
        return "Cebu" if index <= 8 else "Manila" if index <= 14 else "Davao"
    return "Cebu"


def build_hosts() -> list[dict]:
    hosts = []
    for prefix, asset_class, team, count, criticality, profile in HOST_GROUPS:
        for index in range(1, count + 1):
            site = site_of(prefix, index)
            subnet = (
                {"Cebu": "WH-CEB", "Manila": "WH-MNL", "Davao": "WH-DVO"}[site]
                if prefix == "WH-OPS"
                else prefix
            )
            hosts.append(
                {
                    "hostname": f"{prefix}-{index:04d}",
                    "prefix": prefix,
                    "asset_class": asset_class,
                    "team": team,
                    "site": site,
                    "criticality": criticality,
                    "profile": profile,
                    "subnet": subnet,
                }
            )
    return hosts


def activity(profile: str, hour_utc: int) -> float:
    local = (hour_utc + PHT) % 24
    office = 0.12 + 0.88 * np.exp(-((local - 13.5) ** 2) / 20)
    if profile == "office":
        return float(office)
    if profile == "warehouse":
        distance = min(abs(local - 2), 24 - abs(local - 2))
        return float(0.15 + 0.85 * np.exp(-(distance**2) / 24))
    if profile == "server":
        return float(0.55 + 0.45 * office)
    return 1.0


def in_finance_close(ts: datetime) -> bool:
    """Finance works late from 18:00 to 23:00 PHT on the Thursday of month-end."""
    return WINDOW_START + timedelta(hours=1) <= ts < WINDOW_START + timedelta(hours=6)


class Export:
    """Collects rows per file so each CSV can be written sorted by its first column."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.rows: dict[str, list[dict]] = {}

    def add(self, name: str, row: dict) -> None:
        self.rows.setdefault(name, []).append(row)

    def write(self) -> dict[str, int]:
        self.folder.mkdir(parents=True, exist_ok=True)
        counts = {}
        for name, rows in self.rows.items():
            first = next(iter(rows[0]))
            rows.sort(key=lambda row: row[first])
            with (self.folder / f"{name}.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            counts[name] = len(rows)
        return counts


def agents(hosts, scenario: Scenario, rng, export: Export) -> None:
    snapshot = WINDOW_END - timedelta(minutes=10)
    for host in hosts:
        name = host["hostname"]
        if name in scenario.never_enrolled:
            continue
        heartbeat = (
            WINDOW_START
            - timedelta(
                days=int(rng.integers(2, 12)), minutes=int(rng.integers(0, 600))
            )
            if name in scenario.stale_agents
            else snapshot - timedelta(minutes=int(rng.integers(1, 12)))
        )
        export.add(
            "endpoint_agents",
            {
                "Snapshot Time (UTC)": stamp(snapshot),
                "Hostname": name,
                "Agent State": "enrolled",
                "Agent Version": "7.4.2" if rng.random() > 0.2 else "7.3.9",
                "Last Heartbeat (UTC)": stamp(heartbeat),
            },
        )


def signins(letter: str, scenario: Scenario, rng, export: Export) -> list[dict]:
    """Returns successful in-window sessions so Windows and VPN records can reference them."""
    sessions, counter = [], 0
    current = BASELINE_START
    while current < WINDOW_END:
        for prefix, size, profile, apps, _ in TEAMS:
            rate = size * 0.95 * activity(profile, current.hour)
            if prefix == "fin" and in_finance_close(current):
                rate *= 2
            for _ in range(rng.poisson(rate)):
                counter += 1
                user = f"{prefix}-{int(rng.integers(1, size + 1)):04d}"
                sessions.append(
                    sign_in(
                        letter,
                        scenario,
                        rng,
                        export,
                        current,
                        user,
                        prefix,
                        apps,
                        counter,
                    )
                )
        for account in SERVICE_ACCOUNTS:
            counter += 1
            sessions.append(
                sign_in(
                    letter,
                    scenario,
                    rng,
                    export,
                    current,
                    account,
                    "svc",
                    ["erp"],
                    counter,
                )
            )
        current += timedelta(hours=1)
    return [s for s in sessions if s]


def sign_in(
    letter, scenario, rng, export, hour, user, prefix, apps, counter
) -> dict | None:
    ts = hour + timedelta(seconds=int(rng.integers(0, 3600)))
    success = prefix == "svc" or rng.random() > 0.035
    app = str(rng.choice(apps))
    mfa = not (scenario.mfa_gap_app == app and rng.random() < 0.09)
    geo = (
        "PH-07"
        if prefix != "wh"
        else str(rng.choice(list(SITE_GEO.values()), p=[0.4, 0.4, 0.2]))
    )
    if prefix == "sls" and rng.random() < 0.08:
        geo = "SG-01"
    session = f"idp-{letter.lower()}-{counter:06d}"
    export.add(
        "signin_logs",
        {
            "Date (UTC)": stamp(ts),
            "Request ID": session,
            "Username": f"{user}@tallowmere.example",
            "Application": app,
            "Status": "Success" if success else "Failure",
            "Authentication Requirement": "Multifactor authentication"
            if mfa
            else "Single-factor authentication",
            "IP Address": f"198.51.100.{int(rng.integers(2, 250))}",
            "Location": geo,
        },
    )
    if success and ts >= WINDOW_START and prefix != "svc":
        return {
            "session": session,
            "user": user,
            "ts": ts,
            "prefix": prefix,
            "app": app,
        }
    return None


def endpoint_events(hosts, scenario: Scenario, rng, export: Export) -> None:
    silent = set(scenario.never_enrolled) | set(scenario.stale_agents)
    for host in hosts:
        name = host["hostname"]
        if name in silent:
            continue
        for bucket in range(6):
            ts = WINDOW_START + timedelta(
                hours=4 * bucket, minutes=int(rng.integers(0, 30))
            )
            if name == scenario.edr_gap_host and bucket in (1, 2):
                continue
            export.add(
                "endpoint_events",
                {
                    "Timestamp (UTC)": stamp(ts),
                    "Hostname": name,
                    "Event Type": "telemetry_batch",
                    "Event Count": int(rng.integers(120, 900)),
                    "Severity": "",
                    "Rule": "",
                    "Disposition": "",
                },
            )
        if rng.random() < 0.28:
            export.add(
                "endpoint_events",
                {
                    "Timestamp (UTC)": stamp(
                        WINDOW_START + timedelta(minutes=int(rng.integers(0, 24 * 60)))
                    ),
                    "Hostname": name,
                    "Event Type": "detection",
                    "Event Count": "",
                    "Severity": str(
                        rng.choice(["info", "low", "medium"], p=[0.5, 0.4, 0.1])
                    ),
                    "Rule": str(rng.choice(RULES)),
                    "Disposition": "auto_closed",
                },
            )


def network_flows(hosts, scenario: Scenario, rng, export: Export) -> None:
    hours = int((WINDOW_END - BASELINE_START).total_seconds() // 3600)
    gap_start = WINDOW_START + timedelta(hours=7)
    gap_end = gap_start + timedelta(hours=2)
    change = scenario.change
    for host in hosts:
        name = host["hostname"]
        gateway = host["profile"] == "gateway"
        base = float(
            rng.lognormal(mean=15.2 if gateway else 17.0, sigma=0.3 if gateway else 0.6)
        )
        noise = rng.normal(0, 0.1 if gateway else 0.28, size=hours)
        for index in range(hours):
            ts = BASELINE_START + timedelta(hours=index)
            if (
                host["subnet"] == scenario.sensor_gap_subnet
                and gap_start <= ts < gap_end
            ):
                continue
            level = activity(host["profile"], ts.hour)
            sent = base * level * float(np.exp(noise[index]))
            elapsed = (ts - WINDOW_START).total_seconds() / 3600
            if in_finance_close(ts) and host["prefix"] in ("HQ-FIN", "ERP-SRV"):
                sent *= 2
            if (
                name == scenario.intrusion_host
                and THEFT_HOURS[0] <= elapsed < THEFT_HOURS[1]
            ):
                sent *= THEFT_FACTOR
            if (
                change
                and name == change["egress_host"]
                and 0 <= elapsed - change["start_hour"] < 3
            ):
                sent *= CHANGE_FACTOR
            export.add(
                "network_flows",
                {
                    "Hour Start (UTC)": stamp(ts),
                    "Hostname": name,
                    "Subnet": host["subnet"],
                    "Bytes Out": int(sent),
                    "Flow Count": int(rng.poisson(40 * level)),
                },
            )


def windows_logon(
    export: Export, ts, user, host, logon_type, source, session, change_ref
) -> None:
    export.add(
        "windows_logons",
        {
            "TimeCreated (UTC)": stamp(ts),
            "EventID": 4624,
            "Computer": host,
            "TargetUserName": user,
            "LogonType": logon_type,
            "IpAddress": source,
            "IdP Session ID": session or "",
            "Change Ref": change_ref or "",
        },
    )


def vpn_session(export: Export, ts, user, source, asn, assigned, session) -> None:
    export.add(
        "vpn_sessions",
        {
            "Start Time (UTC)": stamp(ts),
            "Username": user,
            "Source IP": source,
            "Source ASN": asn,
            "Assigned IP": assigned,
            "IdP Session ID": session or "",
            "Change Ref": "",
        },
    )


def independent_records(
    hosts, scenario: Scenario, rng, sessions, export: Export
) -> None:
    for host in hosts:
        export.add(
            "log_forwarding",
            {
                "Checked At (UTC)": stamp(WINDOW_END - timedelta(hours=2)),
                "Hostname": host["hostname"],
                "Forwarding": "No"
                if host["hostname"] in scenario.no_independent_logs
                else "Yes",
            },
        )
    reachable: dict[str, list[str]] = {}
    for host in hosts:
        if host["hostname"] not in scenario.no_independent_logs:
            reachable.setdefault(host["prefix"], []).append(host["hostname"])
    host_prefix = {prefix: target for prefix, _, _, _, target in TEAMS}
    shuffled = list(sessions)
    rng.shuffle(shuffled)
    for session in shuffled[:1050]:
        delay = timedelta(seconds=int(rng.integers(5, 90)))
        if session["app"] == "vpn-portal":
            vpn_session(
                export,
                session["ts"] + delay,
                session["user"],
                f"198.51.100.{int(rng.integers(2, 250))}",
                "AS64500",
                f"10.8.0.{int(rng.integers(50, 250))}",
                session["session"],
            )
            continue
        host = str(rng.choice(reachable[host_prefix[session["prefix"]]]))
        source = f"10.20.0.{int(rng.integers(2, 250))}"
        windows_logon(
            export,
            session["ts"] + delay,
            session["user"],
            host,
            2,
            source,
            session["session"],
            None,
        )
    change = scenario.change
    if change:
        start = WINDOW_START + timedelta(hours=change["start_hour"])
        export.add(
            "change_tickets",
            {
                "Logged At (UTC)": stamp(start - timedelta(hours=20)),
                "Ticket": change["ticket"],
                "Hosts": ";".join(change["hosts"]),
                "Window Start (UTC)": stamp(start),
                "Window End (UTC)": stamp(start + timedelta(hours=3)),
                "Approved By": "change-board",
                "Summary": change["summary"],
            },
        )
        when = start + timedelta(minutes=12)
        windows_logon(
            export,
            when,
            "adm-patch",
            change["logon_host"],
            10,
            "10.20.9.14",
            None,
            change["ticket"],
        )
    if scenario.intruder:
        vpn_session(
            export,
            ACTOR_START,
            scenario.intruder,
            ACTOR_SOURCE_IP,
            ACTOR_ASN,
            "10.8.0.41",
            None,
        )
        when = ACTOR_START + timedelta(minutes=5)
        windows_logon(
            export,
            when,
            scenario.intruder,
            scenario.intrusion_host,
            10,
            "10.8.0.41",
            None,
            None,
        )


def asset_register(hosts) -> int:
    export = Export(OUT)
    for host in hosts:
        export.add(
            "asset_register",
            {
                "Recorded At (UTC)": stamp(WINDOW_END - timedelta(hours=1)),
                "Hostname": host["hostname"],
                "Asset Class": host["asset_class"],
                "Team": host["team"],
                "Site": host["site"],
                "Criticality": host["criticality"],
                "Subnet": host["subnet"],
                "In Scope": "Yes",
            },
        )
    return export.write()["asset_register"]


def answer_key() -> None:
    export = Export(OUT / "answer-key")
    for letter, scenario in SCENARIOS.items():
        export.add(
            "scenarios",
            {
                "Snapshot": letter,
                "Name": scenario.name,
                "Unauthorized Access": "Yes" if scenario.unauthorized_access else "No",
                "Reality": scenario.reality,
                "Host": scenario.intrusion_host or "",
                "Account": scenario.intruder or "",
                "What Happened": scenario.truth,
            },
        )
    for claim, outcomes in EXPECTED.items():
        for letter, outcome in outcomes.items():
            export.add(
                "expected_outcomes",
                {"Snapshot": letter, "Claim": claim, "Expected Assessment": outcome},
            )
    export.write()


def main() -> None:
    hosts = build_hosts()
    print(f"asset_register: {asset_register(hosts)}")
    answer_key()
    for letter, scenario in SCENARIOS.items():
        rng = np.random.default_rng(SEEDS[letter])
        export = Export(OUT / f"snapshot-{letter}")
        agents(hosts, scenario, rng, export)
        sessions = signins(letter, scenario, rng, export)
        endpoint_events(hosts, scenario, rng, export)
        network_flows(hosts, scenario, rng, export)
        independent_records(hosts, scenario, rng, sessions, export)
        counts = export.write()
        print(f"snapshot-{letter}: {sum(counts.values()):,} rows {counts}")


if __name__ == "__main__":
    main()
