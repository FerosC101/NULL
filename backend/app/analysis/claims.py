"""Claim compiler: natural language to a structured claim NULL can test.

A claim that can't be mapped to observables stays unsupported rather than being guessed at.
That outcome is UNVERIFIED, which says plainly that NULL has no way to test it.
"""

import re
from dataclasses import asdict, dataclass, field


@dataclass
class CompiledClaim:
    kind: str
    subject: str
    predicate: str
    quantifier: str
    required_observations: list[str] = field(default_factory=list)
    interpretation: str = ""
    compiler: str = "deterministic"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


ABSENCE_ACCESS = "absence_of_access"
COVERAGE_COMPLETE = "coverage_completeness"
MFA_ENFORCED = "mfa_enforcement"
UNSUPPORTED = "unsupported"

_ACCESS = re.compile(r"\b(unauthori[sz]ed|intrusion|breach|compromis|malicious|attacker|illegitimate)", re.I)
_ACCESS_NOUN = re.compile(r"\b(access|login|log-?in|logon|sign-?in|intrusion|breach|compromis|activity|entry)", re.I)
_MFA = re.compile(r"\b(mfa|multi-?factor|2fa|two-?factor)\b", re.I)
_COVERAGE = re.compile(r"\b(coverage|monitored|monitoring|edr|agent)", re.I)
_COVERAGE_SCOPE = re.compile(r"\b(all|every|complete|full|fully|100)\b", re.I)


def compile_claim(text: str) -> CompiledClaim:
    claim = " ".join(text.split())
    if _MFA.search(claim):
        return CompiledClaim(
            kind=MFA_ENFORCED,
            subject="successful sign-ins",
            predicate="completed a multi-factor step",
            quantifier="all",
            required_observations=["mfa_unenforced_logins"],
            interpretation="Every successful sign-in in scope included a multi-factor step.",
        )
    if _ACCESS.search(claim) and _ACCESS_NOUN.search(claim):
        notes = []
        if claim.endswith("?"):
            notes.append("Read as the claim the question seeks to confirm.")
        return CompiledClaim(
            kind=ABSENCE_ACCESS,
            subject="in-scope assets",
            predicate="experienced unauthorized access",
            quantifier="none",
            required_observations=[
                "edr_high_severity",
                "unexplained_sessions_uncovered",
                "unexplained_sessions_monitored",
            ],
            interpretation="No in-scope asset experienced unauthorized access during the window. This is a universal "
            "negative: it can be established only where the evidence could have shown the opposite.",
            notes=notes,
        )
    if _COVERAGE.search(claim) and _COVERAGE_SCOPE.search(claim):
        return CompiledClaim(
            kind=COVERAGE_COMPLETE,
            subject="in-scope hosts",
            predicate="had a reporting monitoring agent",
            quantifier="all",
            required_observations=["active_monitoring_gap"],
            interpretation="Every in-scope host had a monitoring agent that actually reported during the window.",
        )
    return CompiledClaim(
        kind=UNSUPPORTED,
        subject="",
        predicate="",
        quantifier="",
        interpretation="NULL can't yet map this claim to observations in the connected evidence. Supported claim types "
        "are absence of unauthorized access, monitoring completeness, and MFA enforcement.",
    )
