"""Competing realities and the investigations that can separate them.

A reality is a set of predictions over observables. `p_positive` is a declared judgement of how
likely a positive result is if that reality holds. It drives information value only and never
decides a conclusion. Those judgements are shown to the user alongside the value they produce.
"""

from dataclasses import dataclass, field

from app.analysis.claims import ABSENCE_ACCESS, COVERAGE_COMPLETE, MFA_ENFORCED


@dataclass
class Prediction:
    observable: str
    expects: str  # zero | positive | any
    hard: bool
    p_positive: float
    reason: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Reality:
    label: str
    title: str
    statement: str
    claim_true: bool
    assumptions: list[str]
    predictions: list[Prediction]
    origin: str = "deterministic"


@dataclass
class AssumptionSpec:
    key: str
    text: str
    # observable -> status for each state. Omitted states leave the assumption unverified.
    tests: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass
class CheckSpec:
    tool: str
    title: str
    procedure: str
    rationale: str
    permissions: list[str]
    impact: str


P = Prediction

ACCESS_REALITIES = [
    Reality(
        "A",
        "No intrusion",
        "No unauthorized access occurred. Available records reflect actual activity.",
        True,
        [
            "Hosts without a reporting agent saw no unauthorized activity.",
            "Records from each source are complete for the window.",
        ],
        [
            P("edr_high_severity", "zero", True, 0.02, "Nothing malicious ran on monitored hosts."),
            P("idp_auth_anomaly", "zero", False, 0.05, "No credential attack against the identity provider."),
            P("uncovered_host_activity", "any", False, 0.6, "Unmonitored hosts may be active for ordinary reasons."),
            P("unexplained_sessions_uncovered", "zero", True, 0.03, "Every logon traces to a session or a change."),
            P("unexplained_sessions_monitored", "zero", True, 0.03, "Every logon traces to a session or a change."),
            P("egress_anomaly_uncovered", "zero", False, 0.08, "Data volumes stay within each host's baseline."),
        ],
    ),
    Reality(
        "B",
        "Undetected intrusion on an unmonitored endpoint",
        "An unauthorized actor reached an endpoint outside monitoring coverage. Existing logs cannot establish the "
        "absence of an incident.",
        False,
        [
            "At least one in-scope host has no reporting agent.",
            "The actor avoided the identity provider or used a valid credential.",
        ],
        [
            P("edr_high_severity", "any", False, 0.05, "The actor stays on a host EDR cannot see."),
            P("idp_auth_anomaly", "any", False, 0.15, "A valid credential raises no failed sign-ins."),
            P("uncovered_host_activity", "positive", True, 0.98, "The endpoint reached must have been active."),
            P("unexplained_sessions_uncovered", "positive", True, 0.85, "Independent logs would record the logon."),
            P("unexplained_sessions_monitored", "any", False, 0.1, "Movement to monitored hosts is optional."),
            P("egress_anomaly_uncovered", "positive", False, 0.6, "Access often comes with data movement."),
        ],
    ),
    Reality(
        "C",
        "Detection failure on a monitored endpoint",
        "An unauthorized actor reached a monitored host and the agent raised no alert.",
        False,
        [
            "The EDR agent failed to detect the activity it could see.",
            "Absence of a high-severity alert does not imply absence of activity.",
        ],
        [
            P("edr_high_severity", "any", False, 0.05, "The reality is defined by the alert not firing."),
            P("idp_auth_anomaly", "any", False, 0.15, "A valid credential raises no failed sign-ins."),
            P("unexplained_sessions_uncovered", "any", False, 0.1, "The session sits on a monitored host."),
            P("unexplained_sessions_monitored", "positive", True, 0.85, "Independent logs would record the logon."),
            P("egress_anomaly_uncovered", "any", False, 0.1, "Unmonitored hosts aren't involved."),
        ],
    ),
]

ACCESS_ASSUMPTIONS = [
    AssumptionSpec(
        "coverage_complete",
        "Monitoring covered every in-scope asset during the window.",
        {
            "enrollment_gap": {"positive": "violated"},
            "active_monitoring_gap": {"positive": "violated", "zero": "held"},
        },
    ),
    AssumptionSpec(
        "records_complete",
        "Records from each source are complete for the window.",
        {"collection_continuity": {"positive": "violated", "zero": "held"}},
    ),
    AssumptionSpec(
        "idp_is_chokepoint",
        "All authentication passes through the identity provider.",
        {"sessions_outside_idp": {"positive": "violated", "zero": "held"}},
    ),
    AssumptionSpec("edr_alerts_reliably", "An EDR agent that sees malicious activity raises an alert."),
]

ACCESS_CHECKS = [
    CheckSpec(
        "reconcile_inventory_coverage",
        "Reconcile inventory with active monitoring coverage",
        "Join the device inventory to the latest coverage record for each host, require a heartbeat within 24 hours, "
        "then identify unmonitored hosts that sent network traffic in the window.",
        "A console count shows enrolled agents, not reporting agents. Reality B needs an active host outside coverage, "
        "so this confirms or removes the place an undetected intrusion could live.",
        ["inventory:read", "coverage:read", "network:read"],
        "Read-only. No effect on monitored systems.",
    ),
    CheckSpec(
        "inspect_independent_auth",
        "Inspect independent authentication records",
        "Anti-join domain-controller and VPN records against identity-provider sessions, excluding logons inside an "
        "approved change on the same host.",
        "Domain controllers and the VPN record logons whether or not an EDR agent is present. This is the only "
        "evidence here that can observe activity on the hosts EDR cannot see.",
        ["directory:read (restricted)", "idp_auth:read", "coverage:read"],
        "Read-only. Reads restricted directory logs, so access is recorded in the audit log.",
    ),
    CheckSpec(
        "test_host_egress",
        "Test egress on unmonitored hosts",
        "Test each unmonitored host's peak hourly egress against its own hour-of-day baseline, then discount spikes "
        "inside approved change windows.",
        "The organization-wide total can hide a single host. A per-host test can reveal data movement that the "
        "aggregate averages away.",
        ["network:read", "coverage:read", "directory:read (change records)"],
        "Read-only. No effect on monitored systems.",
    ),
]

COVERAGE_REALITIES = [
    Reality(
        "A",
        "Coverage is complete",
        "Every in-scope host had a reporting agent during the window.",
        True,
        ["Inventory lists every in-scope host."],
        [
            P("enrollment_gap", "zero", True, 0.02, "Complete coverage requires every host to be enrolled."),
            P("active_monitoring_gap", "zero", True, 0.02, "Complete coverage requires every agent to report."),
        ],
    ),
    Reality(
        "B",
        "Coverage is incomplete",
        "At least one in-scope host had no reporting agent during the window.",
        False,
        ["Enrollment figures may overstate how many agents are reporting."],
        [
            P("enrollment_gap", "any", False, 0.5, "The gap may be unenrolled or merely silent agents."),
            P("active_monitoring_gap", "positive", True, 0.98, "At least one host would have no recent heartbeat."),
        ],
    ),
]

COVERAGE_ASSUMPTIONS = [
    AssumptionSpec(
        "enrolled_means_reporting",
        "An enrolled agent is an agent that reports.",
        {"active_monitoring_gap": {"zero": "held"}},
    ),
    AssumptionSpec("inventory_complete", "The device inventory lists every in-scope host."),
]

COVERAGE_CHECKS = [ACCESS_CHECKS[0]]

MFA_REALITIES = [
    Reality(
        "A",
        "MFA was enforced",
        "Every successful sign-in in scope included a multi-factor step.",
        True,
        ["The identity provider records MFA accurately."],
        [P("mfa_unenforced_logins", "zero", True, 0.02, "Enforcement leaves no successful sign-in without MFA.")],
    ),
    Reality(
        "B",
        "A path bypasses MFA",
        "At least one application or flow allowed a successful sign-in without a multi-factor step.",
        False,
        ["Legacy or exempted applications may sit outside the MFA policy."],
        [P("mfa_unenforced_logins", "positive", True, 0.9, "A bypass leaves successful sign-ins without MFA.")],
    ),
]

# Neither test can change the result on its own. They run only when a proposed explanation needs them.
MFA_CHECKS = [
    CheckSpec(
        "inspect_independent_auth",
        "Inspect independent authentication records",
        "Anti-join domain-controller and VPN records against identity-provider sessions, excluding logons inside an "
        "approved change on the same host.",
        "A session that never passed through the identity provider never met its MFA policy, and it can't appear in "
        "the sign-in logs. Only independent records can show it.",
        ["directory:read (restricted)", "idp_auth:read", "coverage:read"],
        "Read-only. Reads restricted directory logs, so access is recorded in the audit log.",
    ),
    CheckSpec(
        "check_collection_continuity",
        "Check collection continuity",
        "Count records per subnet per hour and report hours with no records at all.",
        "Gaps in collection could hide sign-ins, so a clean sign-in log needs complete collection behind it.",
        ["network:read"],
        "Read-only.",
    ),
]

MFA_ASSUMPTIONS = [
    AssumptionSpec(
        "idp_is_chokepoint",
        "All authentication passes through the identity provider.",
        {"sessions_outside_idp": {"positive": "violated", "zero": "held"}},
    ),
]

TEMPLATES = {
    ABSENCE_ACCESS: {
        "realities": ACCESS_REALITIES,
        "assumptions": ACCESS_ASSUMPTIONS,
        "automatic": [
            "scan_edr_detections",
            "test_signin_anomalies",
            "count_enrollment",
            "measure_network_volume",
            "check_collection_continuity",
        ],
        "checks": ACCESS_CHECKS,
    },
    COVERAGE_COMPLETE: {
        "realities": COVERAGE_REALITIES,
        "assumptions": COVERAGE_ASSUMPTIONS,
        "automatic": ["count_enrollment"],
        "checks": COVERAGE_CHECKS,
    },
    MFA_ENFORCED: {
        "realities": MFA_REALITIES,
        "assumptions": MFA_ASSUMPTIONS,
        "automatic": ["audit_mfa"],
        "checks": MFA_CHECKS,
    },
}
