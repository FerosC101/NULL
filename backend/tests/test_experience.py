"""Lifecycle, exhibits and reports: everything shown must come from stored state or raw records."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.analysis.observables import collection_continuity
from app.analysis.records import EvidenceReader
from app.models import EvidenceRecord, GraphNode, Investigation, Report
from app.services import exhibits
from app.services.graph import rebuild_graph
from app.services.report_pdf import _when, render_pdf
from app.services.reports import SECTION_TITLES, normalize_snapshot
from tests.test_api import approve_all, login, start, wait


def stage(detail: dict, key: str) -> dict:
    return next(s for s in detail["lifecycle"]["stages"] if s["key"] == key)


def test_lifecycle_follows_the_investigation(client):
    login(client)
    detail = start(client)
    assert [s["key"] for s in detail["lifecycle"]["stages"]] == [
        "claim",
        "evidence",
        "explanations",
        "tests",
        "findings",
        "actions",
        "verification",
    ]
    assert stage(detail, "tests")["status"] == "needs_attention"
    assert stage(detail, "findings")["status"] == "in_progress"
    assert stage(detail, "verification")["status"] == "not_started"
    assert detail["lifecycle"]["next_action"]["label"] == "Review recommended tests"
    assert detail["lifecycle"]["current"] == "tests"

    concluded = approve_all(client, detail)
    assert stage(concluded, "tests")["status"] == "completed"
    assert stage(concluded, "findings")["status"] == "completed"
    assert stage(concluded, "explanations")["summary"] == "1 of 3 still possible"
    assert concluded["lifecycle"]["next_action"]["stage"] == "actions"


def test_key_finding_prefers_evidence_against_the_claim(client):
    login(client)
    concluded = approve_all(client, start(client))
    finding = concluded["lifecycle"]["key_finding"]
    assert finding["severity"] == "critical"
    assert finding["title"].startswith("Unexplained logon")


def test_verification_failure_needs_attention_not_completion(client):
    login(client)
    concluded = approve_all(client, start(client))
    rid = next(r for r in concluded["remediations"] if r["key"] == "enroll_unmonitored")["id"]
    client.post(f"/api/v1/assurance/remediations/{rid}/approve", json={})
    client.post(f"/api/v1/assurance/remediations/{rid}/execute", json={"confirmed": True})
    executed = client.get(f"/api/v1/investigations/{concluded['id']}").json()
    assert executed["lifecycle"]["next_action"]["label"] == "Run verification"
    client.post(f"/api/v1/assurance/remediations/{rid}/verify")
    failed = client.get(f"/api/v1/investigations/{concluded['id']}").json()
    assert stage(failed, "verification")["status"] == "needs_attention"
    assert failed["lifecycle"]["next_action"]["label"] == "Resolve a failed verification"
    assert any(e["kind"] == "verification" and e["tone"] == "bad" for e in failed["events"])


def test_events_are_chronological_and_planned_work_is_marked(client):
    login(client)
    detail = start(client)
    done = [e for e in detail["events"] if not e["planned"]]
    assert [e["at"] for e in done] == sorted(e["at"] for e in done)
    assert all(e["at"] is None for e in detail["events"] if e["planned"])
    assert any(e["planned"] for e in detail["events"])


def test_matrix_counts_match_raw_records(client, db):
    login(client)
    detail = start(client)
    matrix = client.get(f"/api/v1/investigations/{detail['id']}/exhibits").json()["coverage_matrix"]
    row = next(r for r in matrix["rows"] if r["key"] == "idp_auth")
    start_at = datetime.fromisoformat(matrix["window"]["start"])
    end_at = datetime.fromisoformat(matrix["window"]["end"])
    expected = db.scalar(
        select(func.count())
        .select_from(EvidenceRecord)
        .where(
            EvidenceRecord.dataset == "A",
            EvidenceRecord.source_key == "idp_auth",
            EvidenceRecord.ts >= start_at,
            EvidenceRecord.ts < end_at,
        )
    )
    assert row["records"] == expected
    assert sum(c["count"] for c in row["cells"]) == expected


def test_matrix_gaps_are_the_gaps_the_engine_found(client, db):
    login(client)
    detail = start(client)
    investigation = db.get(Investigation, detail["id"])
    start_at = datetime.fromisoformat(investigation.scope["window_start"])
    end_at = datetime.fromisoformat(investigation.scope["window_end"])
    reader = EvidenceReader(db, investigation.workspace_id, "A", set(investigation.source_keys), end_at)
    engine = {g["subnet"]: len(g["hours"]) for g in collection_continuity(reader, start_at, end_at).details["gaps"]}
    shown = exhibits.compute(db, investigation)["coverage_matrix"]["gaps"]
    assert {g["label"].removeprefix("Network: "): g["hours"] for g in shown} == engine
    assert engine


def test_edr_uses_its_batch_cadence_so_no_false_gaps_appear(client):
    login(client)
    detail = start(client)
    matrix = client.get(f"/api/v1/investigations/{detail['id']}/exhibits").json()["coverage_matrix"]
    edr = next(r for r in matrix["rows"] if r["key"] == "edr")
    assert edr["cadence_hours"] == 4
    assert len(edr["cells"]) == 6
    assert all(c["state"] == "records" for c in edr["cells"])


def test_restricted_source_stays_closed_until_a_check_reads_it(client):
    login(client)
    detail = start(client)
    before = client.get(f"/api/v1/investigations/{detail['id']}/exhibits").json()
    directory = next(r for r in before["coverage_matrix"]["rows"] if r["key"] == "directory")
    assert directory["state"] == "restricted"
    assert directory["cells"] == [] and directory["records"] is None
    assert all(u["independent_logs"] is None for u in before["host_coverage"]["unmonitored"])
    assert before["egress"] == []

    concluded = approve_all(client, detail)
    after = client.get(f"/api/v1/investigations/{concluded['id']}/exhibits").json()
    assert next(r for r in after["coverage_matrix"]["rows"] if r["key"] == "directory")["state"] == "readable"
    assert all(u["independent_logs"] is not None for u in after["host_coverage"]["unmonitored"])


def test_sources_page_never_opens_a_restricted_source(client):
    login(client)
    matrix = client.get("/api/v1/sources/coverage").json()
    assert next(r for r in matrix["rows"] if r["key"] == "directory")["state"] == "restricted"
    assert next(r for r in matrix["rows"] if r["key"] == "saas_audit")["state"] == "disconnected"


def test_egress_series_comes_from_the_flagged_host(client):
    login(client)
    concluded = approve_all(client, start(client))
    data = client.get(f"/api/v1/investigations/{concluded['id']}/exhibits").json()
    series = data["egress"][0]
    observed = max(p["bytes"] for p in series["points"] if p["bytes"] is not None)
    assert series["highest_bytes"] == observed
    assert series["anomaly_bytes"] <= observed
    assert series["points"][0]["typical"] is not None
    assert series["events"]


def test_exhibits_respect_the_snapshot_window_after_simulated_changes(client):
    login(client)
    concluded = approve_all(client, start(client))
    url = f"/api/v1/investigations/{concluded['id']}/exhibits"
    before = client.get(url).json()["host_coverage"]
    rid = next(r for r in concluded["remediations"] if r["key"] == "enroll_unmonitored")["id"]
    client.post(f"/api/v1/assurance/remediations/{rid}/approve", json={})
    client.post(f"/api/v1/assurance/remediations/{rid}/execute", json={"confirmed": True})
    assert client.get(url).json()["host_coverage"] == before


def test_viewer_can_read_exhibits_but_not_change_a_target_date(client):
    login(client)
    concluded = approve_all(client, start(client))
    rid = concluded["remediations"][0]["id"]
    login(client, "mina@cobalt.example")
    assert client.get(f"/api/v1/investigations/{concluded['id']}/exhibits").status_code == 200
    denied = client.patch(f"/api/v1/assurance/remediations/{rid}", json={"target_date": "2026-12-01"})
    assert denied.status_code == 403


def test_target_date_can_be_set_and_cleared(client):
    login(client)
    concluded = approve_all(client, start(client))
    rid = concluded["remediations"][0]["id"]
    url = f"/api/v1/assurance/remediations/{rid}"
    assert client.patch(url, json={"target_date": "2026-12-01"}).json()["target_date"] == "2026-12-01"
    assert client.patch(url, json={"target_date": None}).json()["target_date"] is None
    assert client.patch(url, json={"priority": None}).status_code == 200


def test_evidence_ids_follow_the_ranked_check_order(client):
    login(client)
    first = approve_all(client, start(client))
    second = approve_all(client, start(client))

    def order(detail):
        return [(e["ref"], e["observable"]) for e in detail["evidence"] if e["primary"]]

    assert order(first) == order(second)


def test_failed_verification_is_not_logged_as_verified(client):
    login(client)
    concluded = approve_all(client, start(client))
    rid = next(r for r in concluded["remediations"] if r["key"] == "enroll_unmonitored")["id"]
    client.post(f"/api/v1/assurance/remediations/{rid}/approve", json={})
    client.post(f"/api/v1/assurance/remediations/{rid}/execute", json={"confirmed": True})
    client.post(f"/api/v1/assurance/remediations/{rid}/verify")
    actions = [row["action"] for row in client.get("/api/v1/settings/audit").json()]
    assert actions[0] == "remediation.verification_failed"


def test_lists_carry_next_action_and_overview_answers_three_questions(client):
    login(client)
    concluded = approve_all(client, start(client))
    row = next(i for i in client.get("/api/v1/investigations").json() if i["id"] == concluded["id"])
    assert row["next_action"]["label"] == concluded["lifecycle"]["next_action"]["label"]
    assert len(row["stages"]) == 7
    overview = client.get("/api/v1/overview").json()
    assert {"attention", "active", "resolved", "concluded"} <= set(overview)
    assert any(i["id"] == concluded["id"] for i in overview["active"])


def test_regressions_lead_the_attention_list(client):
    login(client)
    concluded = approve_all(client, start(client))
    rid = next(r for r in concluded["remediations"] if r["key"] == "enroll_unmonitored")["id"]
    client.post(f"/api/v1/assurance/remediations/{rid}/approve", json={})
    client.post(f"/api/v1/assurance/remediations/{rid}/execute", json={"confirmed": True})
    client.post(f"/api/v1/assurance/remediations/{rid}/verify")
    # The database is shared across tests, so assert the ordering rather than one specific entry.
    kinds = [item["kind"] for item in client.get("/api/v1/overview").json()["attention"]]
    assert kinds[0] == "regression"
    assert "regression" not in kinds[kinds.index(next(k for k in kinds if k != "regression")) :]


def test_graph_links_tests_and_findings(client, db):
    login(client)
    concluded = approve_all(client, start(client))
    graph = client.get(f"/api/v1/network?investigation_id={concluded['id']}").json()
    kinds = {n["kind"] for n in graph["nodes"]}
    assert {"test", "finding"} <= kinds
    assert any(e["relation"] == "distinguishes" for e in graph["edges"])


def test_older_graphs_are_rebuilt_when_opened(client, db):
    login(client)
    concluded = approve_all(client, start(client))
    investigation = db.get(Investigation, concluded["id"])
    rebuild_graph(db, investigation)
    node = db.get(GraphNode, f"inv:{investigation.id}")
    node.data = {k: v for k, v in node.data.items() if k != "graph_version"}
    db.commit()
    client.get(f"/api/v1/network?investigation_id={concluded['id']}")
    db.expire_all()
    assert db.get(GraphNode, f"inv:{investigation.id}").data["graph_version"]


def test_reports_are_versioned_per_investigation(client):
    login(client)
    concluded = approve_all(client, start(client))
    body = {"investigation_id": concluded["id"]}
    first = client.post("/api/v1/reports", json=body).json()
    second = client.post("/api/v1/reports", json=body).json()
    assert (first["version"], second["version"]) == (1, 2)
    full = client.get(f"/api/v1/reports/{second['id']}").json()
    assert [v["version"] for v in full["versions"]] == [1, 2]


def test_report_freezes_exhibits_and_separates_executed_from_proposed(client):
    login(client)
    detail = start(client)
    report = client.post("/api/v1/reports", json={"investigation_id": detail["id"]}).json()
    frozen = client.get(f"/api/v1/reports/{report['id']}").json()["snapshot"]
    assert frozen["conclusion"]["provisional"] is True
    assert {p["status"] for p in frozen["procedures"]} == {"proposed"}
    assert frozen["observations"]["edr_high_severity"]["state"] == "zero"

    approve_all(client, detail)
    unchanged = client.get(f"/api/v1/reports/{report['id']}").json()["snapshot"]
    assert unchanged == frozen


def test_report_test_results_show_expected_and_actual(client):
    login(client)
    concluded = approve_all(client, start(client))
    report = client.post("/api/v1/reports", json={"investigation_id": concluded["id"]}).json()
    snapshot = client.get(f"/api/v1/reports/{report['id']}").json()["snapshot"]
    executed = next(p for p in snapshot["procedures"] if p["tool"] == "inspect_independent_auth")
    result = executed["results"][0]
    assert set(result["expected"]) == {"A", "B", "C"}
    assert result["actual"]["ref"].startswith("EV-")


def test_older_reports_still_render(client, db):
    login(client)
    concluded = approve_all(client, start(client))
    created = client.post("/api/v1/reports", json={"investigation_id": concluded["id"]}).json()
    report = db.get(Report, created["id"])
    legacy = {
        k: v
        for k, v in report.snapshot.items()
        if k not in ("schema", "lifecycle", "exhibits", "ledger", "methodology", "events", "observations")
    }
    legacy["executive_summary"] = {
        k: v
        for k, v in legacy["executive_summary"].items()
        if k not in ("objective", "key_finding", "uncertainty", "next_action")
    }
    keep = ("title", "status", "procedure", "information_gain_bits", "error")
    legacy["procedures"] = [{k: p[k] for k in keep} for p in legacy["procedures"]]
    legacy["realities"] = [
        {k: v for k, v in r.items() if k not in ("claim_true", "predictions")} for r in legacy["realities"]
    ]
    mitigation_keep = (
        "ref",
        "action",
        "priority",
        "risk",
        "owner",
        "approval",
        "execution",
        "verification",
        "criteria",
    )
    legacy["mitigations"] = [{k: m[k] for k in mitigation_keep} for m in legacy["mitigations"]]
    normalized = normalize_snapshot(legacy)
    assert normalized["schema"] == 1 and normalized["exhibits"] is None
    stand_in = SimpleNamespace(
        snapshot=legacy,
        ref=report.ref,
        version=1,
        sha256=report.sha256,
        created_at=report.created_at,
    )
    assert render_pdf(stand_in).startswith(b"%PDF")


def test_snapshot_sections_match_the_required_structure():
    assert len(SECTION_TITLES) == 9
    assert SECTION_TITLES[0] == "Executive summary" and SECTION_TITLES[-1] == "Appendix"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("2026-10-31T22:02:00+08:00", "2026-10-31 14:02 UTC"), ("2026-10-31T14:02:00+00:00", "2026-10-31 14:02 UTC")],
)
def test_report_times_are_converted_not_relabelled(value, expected):
    assert _when(value) == expected


def test_unsupported_claims_show_no_invented_stages(client):
    login(client)
    created = client.post(
        "/api/v1/investigations",
        json={
            "name": "Revenue",
            "claim": "Quarterly revenue grew by ten percent.",
            "dataset": "A",
            "source_keys": ["edr"],
        },
    ).json()
    detail = wait(client, created["id"])
    assert detail["assessment"] == "UNVERIFIED"
    assert stage(detail, "explanations")["status"] == "not_started"
    assert detail["lifecycle"]["key_finding"] is None or detail["findings"]
