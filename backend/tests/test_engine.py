"""Conclusions are scored against the hidden answer key, which the engine cannot read."""

import ast
from pathlib import Path

import pytest
from sqlalchemy import select

from app.analysis.claims import ABSENCE_ACCESS, COVERAGE_COMPLETE, MFA_ENFORCED, UNSUPPORTED, compile_claim
from app.analysis.validation import (
    HypothesisView,
    assess,
    evaluate_hypothesis,
    expected_information_gain,
)
from app.demo.generator import DATASETS, generate
from app.demo.seed import approve_all, new_investigation
from app.models import DataSource, EvidenceItem, Finding, Hypothesis, RecommendedCheck
from app.services.orchestrator import analyze, execute_checks

CLAIM = "Can we confirm that no unauthorized access occurred during the last 24 hours?"


def run_full(db, workspace, user, dataset, claim=CLAIM, sources=None):
    investigation = new_investigation(db, workspace, user, "Test", claim, dataset, "", sources)
    analyze(db, investigation.id)
    db.refresh(investigation)
    return investigation


def hypothesis(db, investigation, label):
    return db.scalar(
        select(Hypothesis).where(Hypothesis.investigation_id == investigation.id, Hypothesis.label == label)
    )


@pytest.mark.parametrize("dataset", list(DATASETS))
def test_initial_evidence_cannot_settle_the_claim(db, workspace, admin, dataset):
    investigation = run_full(db, workspace, admin, dataset)
    assert investigation.assessment == "UNDERDETERMINED"
    assert investigation.status == "awaiting_approval"


@pytest.mark.parametrize("dataset", list(DATASETS))
def test_conclusion_matches_ground_truth(db, workspace, admin, truth, dataset):
    investigation = run_full(db, workspace, admin, dataset)
    approve_all(db, investigation, admin)
    db.refresh(investigation)
    expected = truth[dataset]
    assert investigation.assessment == expected["expected_assessment"]
    assert investigation.status == "concluded"
    if expected["unauthorized_access"]:
        assert hypothesis(db, investigation, expected["reality"]).compatibility == "corroborated"
        assert hypothesis(db, investigation, "A").compatibility == "incompatible"


def test_decoy_session_with_approved_change_is_not_called_unexplained(db, workspace, admin):
    investigation = run_full(db, workspace, admin, "B")
    approve_all(db, investigation, admin)
    db.refresh(investigation)
    outside = investigation.observables["sessions_outside_idp"]
    assert len(outside["details"]["explained"]) == 1
    assert outside["details"]["unexplained"] == []


def test_decoy_egress_inside_change_window_is_discounted(db, workspace, admin):
    investigation = run_full(db, workspace, admin, "B")
    approve_all(db, investigation, admin)
    db.refresh(investigation)
    egress = investigation.observables["egress_anomaly_uncovered"]
    assert egress["state"] == "zero"
    assert egress["details"]["explained_by_change"] == ["ENG-WS-0031"]


def test_true_positive_egress_is_found(db, workspace, admin):
    investigation = run_full(db, workspace, admin, "A")
    approve_all(db, investigation, admin)
    db.refresh(investigation)
    assert investigation.observables["egress_anomaly_uncovered"]["details"]["flagged"] == ["FIN-WS-0014"]


def test_stale_agents_are_invisible_to_enrollment_count(db, workspace, admin):
    investigation = run_full(db, workspace, admin, "A")
    assert investigation.observables["enrollment_gap"]["value"] == 4
    approve_all(db, investigation, admin)
    db.refresh(investigation)
    assert investigation.observables["active_monitoring_gap"]["value"] == 7


def test_aggregate_egress_misses_the_intrusion(db, workspace, admin):
    investigation = run_full(db, workspace, admin, "A")
    assert investigation.observables["network_volume"]["state"] == "zero"


def test_partial_approval_leaves_the_claim_underdetermined(db, workspace, admin):
    investigation = run_full(db, workspace, admin, "A")
    row = db.scalar(
        select(RecommendedCheck).where(
            RecommendedCheck.investigation_id == investigation.id,
            RecommendedCheck.tool == "reconcile_inventory_coverage",
        )
    )
    row.status = "approved"
    db.commit()
    execute_checks(db, investigation.id, [row.id])
    db.refresh(investigation)
    assert investigation.assessment == "UNDERDETERMINED"
    assert investigation.status == "awaiting_approval"


def test_unapproved_checks_never_run(db, workspace, admin):
    investigation = run_full(db, workspace, admin, "A")
    row = db.scalar(
        select(RecommendedCheck).where(
            RecommendedCheck.investigation_id == investigation.id, RecommendedCheck.tool == "inspect_independent_auth"
        )
    )
    execute_checks(db, investigation.id, [row.id])
    db.refresh(investigation)
    assert "unexplained_sessions_uncovered" not in investigation.observables


def test_recommendations_rank_independent_records_first(db, workspace, admin):
    investigation = run_full(db, workspace, admin, "A")
    rows = db.scalars(
        select(RecommendedCheck)
        .where(RecommendedCheck.investigation_id == investigation.id)
        .order_by(RecommendedCheck.position)
    ).all()
    assert rows[0].tool == "inspect_independent_auth"
    assert all(r.information_gain_bits > 0 for r in rows)
    assert rows[0].information_gain_bits >= rows[1].information_gain_bits >= rows[2].information_gain_bits


def test_disconnected_source_blocks_a_check_and_does_not_pretend(db, workspace, admin):
    investigation = run_full(db, workspace, admin, "A")
    source = db.scalar(select(DataSource).where(DataSource.key == "directory"))
    source.status = "disconnected"
    db.commit()
    try:
        approve_all(db, investigation, admin)
        db.refresh(investigation)
        assert investigation.assessment == "UNDERDETERMINED"
        row = db.scalar(
            select(RecommendedCheck).where(
                RecommendedCheck.investigation_id == investigation.id,
                RecommendedCheck.tool == "inspect_independent_auth",
            )
        )
        assert row.status == "blocked"
        assert "not connected" in row.error
    finally:
        source.status = "connected"
        db.commit()


def test_reconnecting_a_source_clears_the_stale_limitation(db, workspace, admin):
    investigation = run_full(db, workspace, admin, "A")
    source = db.scalar(select(DataSource).where(DataSource.key == "directory"))
    source.status = "disconnected"
    db.commit()
    try:
        approve_all(db, investigation, admin)
    finally:
        source.status = "connected"
        db.commit()
    db.refresh(investigation)
    assert any("directory could not be read" in limit for limit in investigation.limitations)
    blocked = db.scalars(
        select(RecommendedCheck).where(
            RecommendedCheck.investigation_id == investigation.id, RecommendedCheck.status == "blocked"
        )
    ).all()
    for row in blocked:
        row.status = "approved"
    db.commit()
    execute_checks(db, investigation.id, [r.id for r in blocked])
    db.refresh(investigation)
    assert investigation.assessment == "CONTRADICTED"
    assert not any("could not be read" in limit for limit in investigation.limitations)


def test_no_usable_sources_is_unverified(db, workspace, admin):
    investigation = run_full(db, workspace, admin, "A", sources=["saas_audit"])
    assert investigation.assessment == "UNVERIFIED"


def test_unsupported_claim_is_unverified_not_guessed(db, workspace, admin):
    investigation = run_full(db, workspace, admin, "A", claim="Our quarterly revenue beat forecast.")
    assert investigation.assessment == "UNVERIFIED"
    assert investigation.status == "concluded"
    assert db.scalars(select(EvidenceItem).where(EvidenceItem.investigation_id == investigation.id)).first() is None


@pytest.mark.parametrize(
    ("dataset", "claim", "expected_first"),
    [
        ("A", "All endpoints were monitored during the window.", "CONTRADICTED"),
        ("C", "All endpoints were monitored during the window.", "UNDERDETERMINED"),
    ],
)
def test_coverage_claim(db, workspace, admin, dataset, claim, expected_first):
    investigation = run_full(db, workspace, admin, dataset, claim=claim)
    assert investigation.assessment == expected_first


def test_stale_only_coverage_claim_needs_host_level_check(db, workspace, admin):
    investigation = run_full(db, workspace, admin, "C", claim="All endpoints were monitored during the window.")
    approve_all(db, investigation, admin)
    db.refresh(investigation)
    assert investigation.assessment == "SUPPORTED"


@pytest.mark.parametrize(("dataset", "expected"), [("A", "CONTRADICTED"), ("C", "SUPPORTED")])
def test_mfa_claim(db, workspace, admin, dataset, expected):
    investigation = run_full(db, workspace, admin, dataset, claim="MFA was enforced on all sign-ins.")
    assert investigation.assessment == expected
    assert investigation.status == "concluded"


def test_asset_scope_changes_the_answer(db, workspace, admin):
    investigation = new_investigation(db, workspace, admin, "Scoped", CLAIM, "A", "")
    investigation.scope = {**investigation.scope, "asset_classes": ["ot_gateway"]}
    db.commit()
    analyze(db, investigation.id)
    db.refresh(investigation)
    assert investigation.observables["enrollment_gap"]["details"]["hosts"] == 10
    approve_all(db, investigation, admin)
    db.refresh(investigation)
    # The intrusion hit a workstation, which is out of scope here.
    assert investigation.assessment == "SUPPORTED"
    assert investigation.observables["unexplained_sessions_uncovered"]["value"] == 0


def test_findings_cite_evidence(db, workspace, admin):
    investigation = run_full(db, workspace, admin, "A")
    approve_all(db, investigation, admin)
    findings = db.scalars(select(Finding).where(Finding.investigation_id == investigation.id)).all()
    assert findings and all(f.evidence_refs for f in findings)


def test_provenance_points_at_real_records(db, workspace, admin):
    from app.models import EvidenceRecord

    investigation = run_full(db, workspace, admin, "A")
    approve_all(db, investigation, admin)
    items = db.scalars(select(EvidenceItem).where(EvidenceItem.investigation_id == investigation.id)).all()
    logon = next(i for i in items if not i.data.get("primary") and "Logon" in i.observation)
    record = db.get(EvidenceRecord, logon.provenance["record_ids"][0])
    assert record.payload["hostname"] == "FIN-WS-0014"
    assert logon.provenance["sha256"]


def test_generator_is_reproducible():
    first, _ = generate("A")
    second, _ = generate("A")
    assert first == second


def test_analysis_code_cannot_reach_the_answer_key():
    root = Path(__file__).resolve().parents[1] / "app"
    for folder in ("analysis", "reasoning"):
        for path in (root / folder).glob("*.py"):
            tree = ast.parse(path.read_text())
            names = {n.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for n in node.names}
            assert "GroundTruth" not in names, path


def test_compiler_routes_claims():
    assert compile_claim(CLAIM).kind == ABSENCE_ACCESS
    assert compile_claim("All endpoints have an EDR agent").kind == COVERAGE_COMPLETE
    assert compile_claim("MFA is enforced").kind == MFA_ENFORCED
    assert compile_claim("The sky is blue").kind == UNSUPPORTED


def test_information_gain_bounds():
    assert expected_information_gain({"A": [0.5], "B": [0.5]}) == 0
    assert expected_information_gain({"A": [0.0], "B": [1.0]}) == 1
    assert expected_information_gain({"A": [0.7]}) == 0


def view(claim_true, *predictions):
    return HypothesisView(
        "X",
        claim_true,
        [{"observable": o, "expects": e, "hard": h, "p_positive": 0.5, "reason": ""} for o, e, h in predictions],
    )


def test_hard_violation_is_incompatible():
    status, _ = evaluate_hypothesis(view(True, ("x", "zero", True)), {"x": {"state": "positive"}})
    assert status == "incompatible"


def test_soft_violation_only_strains():
    status, _ = evaluate_hypothesis(view(False, ("x", "zero", False)), {"x": {"state": "positive"}})
    assert status == "strained"


def test_partial_observation_decides_nothing():
    status, results = evaluate_hypothesis(view(True, ("x", "zero", True)), {"x": {"state": "partial"}})
    assert status == "compatible"
    assert results[0]["outcome"] == "inconclusive"


def test_assess_without_observations_is_unverified():
    assert assess({"A": (True, "untested", [])}, any_observation=False) == "UNVERIFIED"


def test_supported_requires_all_hard_predictions_observed():
    untested = [{"hard": True, "outcome": "untested", "expects": "zero"}]
    decision = assess({"A": (True, "compatible", untested), "B": (False, "incompatible", [])}, True)
    assert decision != "SUPPORTED"
