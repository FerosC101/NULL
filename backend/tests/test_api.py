import time

import pytest
from sqlalchemy import select

from app.models import Investigation, Remediation
from app.services.orchestrator import STAGES
from tests.conftest import login

CLAIM = "Can we confirm that no unauthorized access occurred during the last 24 hours?"
ALL = ["idp_auth", "edr", "network", "inventory", "coverage", "directory"]


def wait(client, investigation_id, statuses=("awaiting_approval", "concluded", "failed")):
    for _ in range(200):
        detail = client.get(f"/api/v1/investigations/{investigation_id}").json()
        if detail["status"] in statuses:
            return detail
        time.sleep(0.05)
    raise AssertionError("investigation did not settle")


def start(client, dataset="A", **overrides):
    body = {"name": "API run", "claim": CLAIM, "dataset": dataset, "window_hours": 24, "source_keys": ALL, **overrides}
    response = client.post("/api/v1/investigations", json=body)
    assert response.status_code == 201, response.text
    return wait(client, response.json()["id"])


def approve_all(client, detail):
    ids = [c["id"] for c in detail["checks"] if c["status"] == "proposed"]
    response = client.post(
        f"/api/v1/investigations/{detail['id']}/checks/approve", json={"check_ids": ids, "acknowledged": True}
    )
    assert response.status_code == 200, response.text
    return wait(client, detail["id"], ("concluded", "failed"))


def test_requires_authentication(client):
    client.cookies.clear()
    for path in ("overview", "investigations", "assurance", "reports", "sources", "settings", "network"):
        assert client.get(f"/api/v1/{path}").status_code == 401


def test_bad_password_is_rejected(client):
    response = client.post("/api/v1/auth/login", json={"email": "ada@cobalt.example", "password": "wrong"})
    assert response.status_code == 401


def test_session_cookie_is_httponly(client):
    response = client.post("/api/v1/auth/login", json={"email": "ada@cobalt.example", "password": "test-password"})
    assert "httponly" in response.headers["set-cookie"].lower()


def test_me_never_exposes_secrets(client):
    login(client)
    body = client.get("/api/v1/auth/me").text + client.get("/api/v1/settings").text
    assert "password_hash" not in body
    assert "test-secret-key" not in body


def test_full_lifecycle(client, db):
    login(client)
    detail = start(client)
    assert detail["assessment"] == "UNDERDETERMINED"
    assert [t["stage"] for t in detail["timeline"]] == [s for s, _ in STAGES]
    assert detail["timeline"][-1]["status"] == "pending"

    blocked = client.get(f"/api/v1/investigations/{detail['id']}/ground-truth")
    assert blocked.status_code == 409

    concluded = approve_all(client, detail)
    assert concluded["assessment"] == "CONTRADICTED"
    assert concluded["timeline"][-1]["status"] == "done"
    truth = client.get(f"/api/v1/investigations/{detail['id']}/ground-truth").json()
    assert truth["matches"] is True

    enroll = next(r for r in concluded["remediations"] if r["key"] == "enroll_unmonitored")
    rid = enroll["id"]
    assert client.post(f"/api/v1/assurance/remediations/{rid}/execute", json={"confirmed": True}).status_code == 409
    assert client.post(f"/api/v1/assurance/remediations/{rid}/verify").status_code == 409

    assert client.post(f"/api/v1/assurance/remediations/{rid}/approve", json={}).status_code == 200
    assert client.post(f"/api/v1/assurance/remediations/{rid}/execute", json={"confirmed": False}).status_code == 422
    executed = client.post(f"/api/v1/assurance/remediations/{rid}/execute", json={"confirmed": True}).json()
    assert executed["execution_status"] == "executed"
    assert executed["verification_status"] == "awaiting"

    # Executed but one host never reported, so the action must not resolve.
    first = client.post(f"/api/v1/assurance/remediations/{rid}/verify").json()
    assert first["verification_status"] == "failed"
    assert "Not reporting" in first["runs"][0]["summary"]

    client.post(f"/api/v1/assurance/remediations/{rid}/execute", json={"confirmed": True})
    second = client.post(f"/api/v1/assurance/remediations/{rid}/verify").json()
    assert second["verification_status"] == "verified"
    assert second["attempts"] == 2

    assert client.post(f"/api/v1/assurance/remediations/{rid}/simulate-recurrence").status_code == 200
    third = client.post(f"/api/v1/assurance/remediations/{rid}/verify").json()
    assert third["verification_status"] == "recurred"
    assert third["runs"][0]["recurrence"] is True


def test_each_remediation_type_verifies_on_evidence(client):
    login(client)
    concluded = approve_all(client, start(client, "B"))
    for remediation in concluded["remediations"]:
        rid = remediation["id"]
        client.post(f"/api/v1/assurance/remediations/{rid}/approve", json={})
        client.post(f"/api/v1/assurance/remediations/{rid}/execute", json={"confirmed": True})
        result = client.post(f"/api/v1/assurance/remediations/{rid}/verify").json()
        if result["verification_status"] != "verified":
            client.post(f"/api/v1/assurance/remediations/{rid}/execute", json={"confirmed": True})
            result = client.post(f"/api/v1/assurance/remediations/{rid}/verify").json()
        assert result["verification_status"] == "verified", result


def test_rejecting_all_checks_concludes_without_pretending(client):
    login(client)
    detail = start(client)
    ids = [c["id"] for c in detail["checks"]]
    response = client.post(
        f"/api/v1/investigations/{detail['id']}/checks/reject", json={"check_ids": ids, "reason": "Out of scope"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["assessment"] == "UNDERDETERMINED"
    assert body["status"] == "concluded"


def test_approval_needs_acknowledgement(client):
    login(client)
    detail = start(client)
    response = client.post(
        f"/api/v1/investigations/{detail['id']}/checks/approve",
        json={"check_ids": [detail["checks"][0]["id"]], "acknowledged": False},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(("email", "code"), [("mina@cobalt.example", 403), ("priya@cobalt.example", 403)])
def test_rbac_blocks_check_approval(client, email, code):
    login(client)
    detail = start(client)
    login(client, email)
    response = client.post(
        f"/api/v1/investigations/{detail['id']}/checks/approve",
        json={"check_ids": [detail["checks"][0]["id"]], "acknowledged": True},
    )
    assert response.status_code == code


def test_viewer_cannot_create_or_change_sources(client):
    login(client, "mina@cobalt.example")
    assert (
        client.post(
            "/api/v1/investigations", json={"name": "x1", "claim": CLAIM, "dataset": "A", "source_keys": ALL}
        ).status_code
        == 403
    )
    assert client.post("/api/v1/sources/edr/disconnect").status_code == 403


def test_input_validation(client):
    login(client)
    bad = {"name": "x1", "claim": CLAIM, "dataset": "Z", "source_keys": ALL}
    assert client.post("/api/v1/investigations", json=bad).status_code == 422
    assert client.post("/api/v1/investigations", json={**bad, "dataset": "A", "window_hours": 7}).status_code == 422
    assert (
        client.post("/api/v1/investigations", json={**bad, "dataset": "A", "source_keys": ["hack"]}).status_code == 422
    )


def test_never_connected_source_cannot_be_marked_connected(client):
    login(client)
    response = client.post("/api/v1/sources/saas_audit/connect")
    assert response.status_code == 409


def test_sources_show_real_counts_and_mode(client):
    login(client)
    body = client.get("/api/v1/sources").json()
    by_key = {s["key"]: s for s in body["sources"]}
    assert by_key["inventory"]["records"] == 180
    assert by_key["saas_audit"]["records"] == 0
    assert by_key["saas_audit"]["status"] == "disconnected"
    assert all(s["mode"] == "simulated" for s in body["sources"])


def test_report_snapshot_and_exports(client):
    login(client)
    concluded = approve_all(client, start(client))
    report = client.post("/api/v1/reports", json={"investigation_id": concluded["id"]}).json()
    full = client.get(f"/api/v1/reports/{report['id']}").json()
    assert len(full["sections"]) == 12
    assert full["snapshot"]["conclusion"]["assessment"] == "CONTRADICTED"
    assert "Synthetic" in full["snapshot"]["demo_notice"]
    pdf = client.get(f"/api/v1/reports/{report['id']}/export.pdf")
    assert pdf.content.startswith(b"%PDF")
    csv = client.get(f"/api/v1/reports/{report['id']}/evidence.csv")
    assert csv.text.startswith("evidence_id,")


def test_csv_neutralizes_formula_injection():
    from types import SimpleNamespace

    from app.services.reports import evidence_csv

    report = SimpleNamespace(
        snapshot={
            "provenance": {"evidence": []},
            "evidence_quality": {
                "items": [
                    {
                        "ref": "EV-1",
                        "source": "x",
                        "observation": "=HYPERLINK(1)",
                        "observed_at": "t",
                        "reliability": "r",
                        "relevance": "r",
                    }
                ]
            },
        }
    )
    assert "'=HYPERLINK" in evidence_csv(report)


def test_graph_is_connected_and_typed(client):
    login(client)
    concluded = approve_all(client, start(client))
    graph = client.get("/api/v1/network", params={"investigation_id": concluded["id"]}).json()
    kinds = {n["kind"] for n in graph["nodes"]}
    relations = {e["relation"] for e in graph["edges"]}
    assert {"claim", "evidence", "source", "assumption", "hypothesis", "investigation", "remediation"} <= kinds
    assert {"supports", "contradicts", "derived_from", "depends_on", "challenges", "resolves"} <= relations
    ids = {n["id"] for n in graph["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in graph["edges"])


def test_overview_counts_come_from_the_database(client, db):
    login(client)
    start(client)
    body = client.get("/api/v1/overview").json()
    open_rows = db.scalars(select(Remediation).where(Remediation.verification_status != "verified")).all()
    rejected = [r for r in open_rows if r.approval_status == "rejected"]
    assert body["metrics"]["open_actions"] == len(open_rows) - len(rejected)
    unresolved = db.scalars(
        select(Investigation).where(Investigation.assessment.notin_(["SUPPORTED", "CONTRADICTED"]))
    ).all()
    assert body["metrics"]["unresolved_claims"] == len(unresolved)


def test_audit_log_records_sensitive_actions(client):
    login(client)
    approve_all(client, start(client))
    actions = {row["action"] for row in client.get("/api/v1/settings/audit").json()}
    assert {"auth.login", "investigation.created", "check.approved"} <= actions


def test_contributor_model_rejected_by_settings(client):
    login(client)
    response = client.patch(
        "/api/v1/settings/ai",
        json={"reasoning_mode": "auto", "model_id": "muse-spark-1.3-contributor", "reasoning_effort": "medium"},
    )
    assert response.status_code == 422


def test_ai_test_reports_missing_key_honestly(client):
    login(client)
    assert client.post("/api/v1/settings/ai/test").json()["ok"] is False


def test_failed_job_is_recorded(client, db):
    from app.services import orchestrator

    login(client)
    detail = start(client)

    def explode(*_):
        raise RuntimeError("worker crashed")

    orchestrator.in_background(explode, detail["id"])
    failed = client.get(f"/api/v1/investigations/{detail['id']}").json()
    assert failed["status"] == "failed"
    assert "worker crashed" in failed["error"]
